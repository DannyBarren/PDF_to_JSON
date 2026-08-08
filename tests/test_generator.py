"""Tests for API-key sanitization and OpenAI error classification."""

from __future__ import annotations

import pytest

from pdf_to_json.generator import (
    GenerationError,
    OpenAIChatCompleter,
    clean_api_key,
    configured_api_key,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("sk-abc123", "sk-abc123"),
        ("  sk-abc123  ", "sk-abc123"),
        ('"sk-abc123"', "sk-abc123"),
        ("'sk-abc123'", "sk-abc123"),
        ("sk-abc123\n", "sk-abc123"),
        ("Bearer sk-abc123", "sk-abc123"),
        ("bearer  sk-abc123", "sk-abc123"),
        ("sk-abc\t123\n", "sk-abc123"),
    ],
)
def test_clean_api_key(raw, expected):
    assert clean_api_key(raw) == expected


def test_configured_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", '  "sk-live-xyz"\n')
    assert configured_api_key() == "sk-live-xyz"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert configured_api_key() == ""


def test_auth_error_becomes_clear_generation_error():
    class AuthenticationError(Exception):
        status_code = 401

    result = OpenAIChatCompleter._as_generation_error(AuthenticationError("nope"))
    assert isinstance(result, GenerationError)
    assert "401" in str(result)


def test_status_401_becomes_generation_error_even_if_unnamed():
    class WeirdError(Exception):
        status_code = 401

    result = OpenAIChatCompleter._as_generation_error(WeirdError("x"))
    assert isinstance(result, GenerationError)


def test_model_not_found_becomes_clear_error(monkeypatch):
    monkeypatch.setenv("PDF_TO_JSON_MODEL", "gpt-nonexistent")

    class NotFoundError(Exception):
        status_code = 404

    result = OpenAIChatCompleter._as_generation_error(NotFoundError("x"))
    assert isinstance(result, GenerationError)
    assert "gpt-nonexistent" in str(result)


def test_transient_error_is_passed_through_for_retry():
    class APITimeoutError(Exception):
        pass

    exc = APITimeoutError("temporary")
    result = OpenAIChatCompleter._as_generation_error(exc)
    # Not converted -> tenacity will retry it.
    assert result is exc
    assert not isinstance(result, GenerationError)
