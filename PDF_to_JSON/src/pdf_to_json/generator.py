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
    retry,
    retry_if_exception_type,
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
]

DEFAULT_MODEL = "gpt-4o"


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

    def _client(self) -> Any:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise GenerationError(
                "The 'openai' package is required for generation. "
                "Install it with `pip install openai`."
            ) from exc

        if not os.getenv("OPENAI_API_KEY"):
            raise GenerationError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add "
                "your key, or export OPENAI_API_KEY in your shell."
            )
        base_url = os.getenv("OPENAI_BASE_URL")
        kwargs: dict[str, Any] = {"timeout": self.config.timeout}
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(Exception),
    )
    def complete(self, *, system: str, user: str) -> str:
        client = self._client()
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=self.config.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise GenerationError("LLM returned an empty response.")
        return content


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
