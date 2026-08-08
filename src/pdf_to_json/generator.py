"""Intermediate content -> ReportTemplate via LLM reasoning.

The generator sends the extracted document to a frontier LLM using JSON response
mode and returns the parsed dict (NOT yet validated — the pipeline validates).

Design notes:
* The OpenAI dependency is isolated behind a small callable ``ChatCompleter``
  protocol so tests can inject a fake completer and run without an API key.
* ``tenacity`` provides bounded retries with exponential backoff.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from tenacity import (
    Retrying,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .extractor import ExtractedDocument
from .prompts import SYSTEM_PROMPT, build_user_prompt

__all__ = [
    "GenerationError",
    "GeneratorConfig",
    "TemplateGenerator",
    "ChatCompleter",
    "OpenAIChatCompleter",
    "clean_api_key",
    "configured_api_key",
]

DEFAULT_MODEL = "gpt-4o"


def clean_api_key(raw: str | None) -> str:
    """Sanitize an API key value read from the environment.

    Deployment dashboards and ``.env`` files frequently introduce subtle
    corruption: wrapping quotes, a stray ``Bearer `` prefix, or trailing
    whitespace / newlines. Any of these makes OpenAI reject the key with a
    ``401 invalid_api_key`` even though "the key was entered". We strip those
    here so the *actual* secret is sent.
    """
    if not raw:
        return ""
    key = raw.strip()
    # Strip a single pair of surrounding quotes if present.
    if len(key) >= 2 and key[0] == key[-1] and key[0] in {'"', "'"}:
        key = key[1:-1].strip()
    # Drop an accidental "Bearer " prefix.
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    # Remove any internal whitespace/newlines that never belong in a key.
    key = "".join(key.split())
    return key


def configured_api_key() -> str:
    """Return the sanitized OPENAI_API_KEY (empty string if unusable)."""
    return clean_api_key(os.getenv("OPENAI_API_KEY"))


class GenerationError(Exception):
    """Raised when the LLM stage fails to produce parseable JSON."""


class ChatCompleter(Protocol):
    """Minimal protocol for a chat completion backend.

    Implementations receive the system + user messages and must return the raw
    assistant message content as a string (expected to be a JSON object).
    """

    def complete(self, *, system: str, user: str) -> str:  # pragma: no cover
        ...


@dataclass
class GeneratorConfig:
    model: str = DEFAULT_MODEL
    temperature: float = 0.2
    timeout: float = 120.0
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> "GeneratorConfig":
        return cls(
            model=os.getenv("PDF_TO_JSON_MODEL", DEFAULT_MODEL),
            temperature=float(os.getenv("PDF_TO_JSON_TEMPERATURE", "0.2")),
            timeout=float(os.getenv("PDF_TO_JSON_TIMEOUT", "120")),
        )


class OpenAIChatCompleter:
    """Default ChatCompleter backed by the OpenAI Chat Completions API."""

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        self.config = config or GeneratorConfig.from_env()
        self._client_obj: Any | None = None

    def _client(self) -> Any:
        """Create (once) and return the OpenAI client.

        Configuration problems raised here (missing package / API key) are NOT
        retried — they cannot succeed on a second attempt.
        """
        if self._client_obj is not None:
            return self._client_obj

        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise GenerationError(
                "The 'openai' package is required for generation. "
                "Install it with `pip install openai`."
            ) from exc

        api_key = configured_api_key()
        if not api_key:
            raise GenerationError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add "
                "your key, or export OPENAI_API_KEY in your shell."
            )
        base_url = os.getenv("OPENAI_BASE_URL")
        # Pass the sanitized key explicitly rather than relying on the SDK reading
        # the raw environment value (which may contain quotes/whitespace).
        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": self.config.timeout}
        if base_url:
            kwargs["base_url"] = base_url
        self._client_obj = OpenAI(**kwargs)
        return self._client_obj

    def complete(self, *, system: str, user: str) -> str:
        # Resolve the client first so config errors surface immediately and are
        # never retried. Only the network call below is wrapped in retries.
        client = self._client()

        # Retry transient failures (network, timeout, rate limit, 5xx) but NOT
        # GenerationError, which we raise for non-retryable problems such as a
        # rejected API key.
        retryer = Retrying(
            reraise=True,
            stop=stop_after_attempt(max(1, self.config.max_retries)),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_not_exception_type(GenerationError),
        )

        content: str | None = None
        for attempt in retryer:
            with attempt:
                try:
                    response = client.chat.completions.create(
                        model=self.config.model,
                        temperature=self.config.temperature,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    )
                except Exception as exc:  # noqa: BLE001 - classify below
                    raise self._as_generation_error(exc)
                message_content = response.choices[0].message.content
                if not message_content:
                    raise GenerationError("LLM returned an empty response.")
                content = message_content
        assert content is not None  # for type-checkers; loop guarantees it
        return content

    @staticmethod
    def _as_generation_error(exc: Exception) -> Exception:
        """Turn known non-retryable OpenAI errors into clear GenerationErrors.

        Transient errors are returned unchanged so tenacity can retry them.
        """
        name = type(exc).__name__
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)

        if name in {"AuthenticationError", "PermissionDeniedError"} or status == 401:
            return GenerationError(
                "OpenAI rejected the API key (HTTP 401 invalid_api_key). The key "
                "value is being sent but is not accepted. Check that OPENAI_API_KEY "
                "is the full, current key with no surrounding quotes, spaces, or "
                "line breaks, that it has not been rotated/revoked, and that it "
                "belongs to the correct project/organization. After updating the "
                "key on your host (e.g. Render), redeploy so the new value is used."
            )
        if name == "NotFoundError" or status == 404:
            model = os.getenv("PDF_TO_JSON_MODEL", DEFAULT_MODEL)
            return GenerationError(
                f"The model '{model}' was not found or is not available to this "
                "API key. Set PDF_TO_JSON_MODEL to a model your account can access "
                "(e.g. gpt-4o or gpt-4o-mini)."
            )
        # Rate limits / connection / timeout / 5xx: let the caller retry.
        return exc


class TemplateGenerator:
    """Turns an :class:`ExtractedDocument` into a template dict via an LLM."""

    def __init__(self, completer: ChatCompleter | None = None) -> None:
        self._completer = completer or OpenAIChatCompleter()

    def generate(self, document: ExtractedDocument) -> dict[str, Any]:
        """Generate a (not-yet-validated) template dict from extracted content."""
        if not document.markdown.strip():
            raise GenerationError(
                "Extracted document is empty; cannot generate a template."
            )

        filename = os.path.basename(document.source_path) if document.source_path else None
        user_prompt = build_user_prompt(
            document.markdown,
            page_count=document.page_count,
            detected_headings=document.detected_headings,
            filename=filename,
        )

        raw = self._completer.complete(system=SYSTEM_PROMPT, user=user_prompt)
        data = _parse_json(raw)

        # Guarantee schema_version is present/correct regardless of the model.
        data.setdefault("schema_version", 3)
        return data


def _parse_json(raw: str) -> dict[str, Any]:
    """Parse the model output into a dict, tolerating stray markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        # Strip a leading ```json / ``` fence and trailing ```
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Last resort: extract the outermost {...} block.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise GenerationError(
                "LLM did not return valid JSON. First 200 chars:\n" + raw[:200]
            )
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise GenerationError(
                f"LLM returned malformed JSON: {exc}. First 200 chars:\n{raw[:200]}"
            ) from exc

    if not isinstance(data, dict):
        raise GenerationError("LLM JSON output was not a JSON object.")
    return data
