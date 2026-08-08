"""End-to-end orchestration: extract -> generate -> validate.

This is the single entry point most callers (CLI, API, scripts) should use.
It guarantees that the returned object is always a fully validated
:class:`ReportTemplate` — or it raises with a useful, human-readable error.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .extractor import ExtractedDocument, ExtractionError, extract_pdf
from .generator import ChatCompleter, GenerationError, TemplateGenerator
from .normalize import normalize_template
from .schema import ReportTemplate
from .validator import TemplateValidationError, validate_template

__all__ = ["PipelineError", "PipelineResult", "translate_pdf", "TranslationPipeline"]


class PipelineError(Exception):
    """Top-level error wrapping any stage failure with a clear message."""


@dataclass
class PipelineResult:
    template: ReportTemplate
    document: ExtractedDocument
    raw_generation: dict[str, Any]

    @property
    def json(self) -> str:
        return self.template.model_dump_json(indent=2)


class TranslationPipeline:
    """Reusable pipeline. Inject a custom generator/completer for testing."""

    def __init__(
        self,
        generator: TemplateGenerator | None = None,
        completer: ChatCompleter | None = None,
    ) -> None:
        if generator is not None and completer is not None:
            raise ValueError("Pass either a generator or a completer, not both.")
        if generator is None:
            generator = TemplateGenerator(completer=completer)
        self.generator = generator

    def run(self, pdf_path: str | Path) -> PipelineResult:
        # 1. Extract
        try:
            document = extract_pdf(pdf_path)
        except ExtractionError as exc:
            raise PipelineError(f"Extraction failed: {exc}") from exc

        # 2. Generate
        try:
            raw = self.generator.generate(document)
        except GenerationError as exc:
            raise PipelineError(f"Generation failed: {exc}") from exc

        # 3. Normalize small, mechanically-fixable quirks, then validate
        #    (validation is still the authoritative, final gate).
        repaired = normalize_template(raw)
        try:
            template = validate_template(repaired)
        except TemplateValidationError as exc:
            raise PipelineError(
                "The generated template failed strict validation:\n"
                f"{exc}\n\nThis usually means the model omitted or malformed a "
                "required field. Try re-running; if it persists, the source PDF "
                "may be too sparse or unusual."
            ) from exc

        return PipelineResult(
            template=template, document=document, raw_generation=raw
        )


def translate_pdf(
    pdf_path: str | Path,
    *,
    completer: ChatCompleter | None = None,
) -> ReportTemplate:
    """Convenience one-shot: translate a PDF into a validated ReportTemplate."""
    pipeline = TranslationPipeline(completer=completer)
    return pipeline.run(pdf_path).template
