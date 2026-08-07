"""API tests using FastAPI's TestClient (no API key required)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from pdf_to_json.api import app
from pdf_to_json.pipeline import TranslationPipeline
from tests.conftest import make_valid_template

client = TestClient(app)


class _FakeCompleter:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or make_valid_template()

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(self.payload)


def test_root_lists_endpoints():
    r = client.get("/")
    assert r.status_code == 200
    assert "endpoints" in r.json()


def test_health_reports_config():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == 3
    assert "llm_configured" in body
    assert "model" in body


def test_schema_endpoint_returns_json_schema():
    r = client.get("/schema")
    assert r.status_code == 200
    body = r.json()
    assert body.get("title") == "ReportTemplate"
    assert "properties" in body


def test_translate_rejects_non_pdf():
    r = client.post("/translate", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400


def test_translate_rejects_empty():
    r = client.post("/translate", files={"file": ("x.pdf", b"", "application/pdf")})
    assert r.status_code == 400


def test_translate_success_with_fake_completer(monkeypatch, sample_pdf):
    def fake_factory() -> TranslationPipeline:
        return TranslationPipeline(completer=_FakeCompleter())

    monkeypatch.setattr("pdf_to_json.api.TranslationPipeline", fake_factory)

    pdf_bytes = sample_pdf.read_bytes()
    r = client.post(
        "/translate",
        files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == 3
    assert body["document_class"] == "inspection_report"


def test_translate_invalid_generation_returns_422(monkeypatch, sample_pdf):
    bad = make_valid_template()
    del bad["guidance"]

    def fake_factory() -> TranslationPipeline:
        return TranslationPipeline(completer=_FakeCompleter(payload=bad))

    monkeypatch.setattr("pdf_to_json.api.TranslationPipeline", fake_factory)

    pdf_bytes = sample_pdf.read_bytes()
    r = client.post(
        "/translate",
        files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 422
