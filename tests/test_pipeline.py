"""Pipeline + extractor tests that run without any API key (fake completer)."""

from __future__ import annotations

import json

import pytest

from pdf_to_json.extractor import ExtractedDocument, extract_pdf
from pdf_to_json.generator import GenerationError, TemplateGenerator
from pdf_to_json.pipeline import PipelineError, TranslationPipeline
from tests.conftest import make_valid_template


class FakeCompleter:
    """Returns a fixed JSON payload; records the prompts it received."""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload if payload is not None else make_valid_template()
        self.last_system: str | None = None
        self.last_user: str | None = None

    def complete(self, *, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
        return json.dumps(self.payload)


def test_extractor_reads_text_pdf(sample_pdf):
    document = extract_pdf(sample_pdf)
    assert document.page_count == 1
    assert document.char_count > 0
    assert "Roof Condition" in document.raw_text
    assert document.engine in {"pymupdf", "pdfplumber"}


def test_extractor_missing_file():
    from pdf_to_json.extractor import ExtractionError

    with pytest.raises(ExtractionError):
        extract_pdf("/no/such/file.pdf")


def test_generator_with_fake_completer():
    completer = FakeCompleter()
    generator = TemplateGenerator(completer=completer)
    doc = ExtractedDocument(
        source_path="x.pdf",
        page_count=1,
        markdown="# Roof\nSome content about the roof.",
        raw_text="Roof content",
    )
    data = generator.generate(doc)
    assert data["schema_version"] == 3
    assert completer.last_system is not None
    assert "SOURCE DOCUMENT" in (completer.last_user or "")


def test_pipeline_end_to_end_with_fake(sample_pdf):
    completer = FakeCompleter()
    pipeline = TranslationPipeline(completer=completer)
    result = pipeline.run(sample_pdf)
    assert result.template.document_class == "inspection_report"
    assert len(result.template.guidance.sections) == 3
    # The extracted content should have been forwarded to the LLM.
    assert "Roof Condition" in (completer.last_user or "")


def test_pipeline_repairs_max_images_zero(sample_pdf):
    payload = make_valid_template()
    payload["content_structure"]["sections"][0]["image_placement"]["max_images"] = 0
    completer = FakeCompleter(payload=payload)
    pipeline = TranslationPipeline(completer=completer)
    result = pipeline.run(sample_pdf)
    # Normalization clamps 0 -> 1 so the template validates and is returned.
    assert result.template.content_structure.sections[0].image_placement.max_images == 1


def test_pipeline_raises_on_invalid_generation(sample_pdf):
    bad = make_valid_template()
    del bad["guidance"]  # make it invalid
    completer = FakeCompleter(payload=bad)
    pipeline = TranslationPipeline(completer=completer)
    with pytest.raises(PipelineError) as exc:
        pipeline.run(sample_pdf)
    assert "validation" in str(exc.value).lower()


def test_generator_rejects_non_json():
    class JunkCompleter:
        def complete(self, *, system: str, user: str) -> str:
            return "this is not json at all"

    generator = TemplateGenerator(completer=JunkCompleter())
    doc = ExtractedDocument(
        source_path="x.pdf", page_count=1, markdown="content", raw_text="content"
    )
    with pytest.raises(GenerationError):
        generator.generate(doc)


def test_generator_strips_markdown_fence():
    class FencedCompleter:
        def complete(self, *, system: str, user: str) -> str:
            return "```json\n" + json.dumps(make_valid_template()) + "\n```"

    generator = TemplateGenerator(completer=FencedCompleter())
    doc = ExtractedDocument(
        source_path="x.pdf", page_count=1, markdown="content", raw_text="content"
    )
    data = generator.generate(doc)
    assert data["document_class"] == "inspection_report"
