"""Strict validation for generated ReportTemplate payloads.

This is the last line of defense before a template is returned to a caller.
The pipeline MUST run this and MUST refuse to return an invalid template.

The public entry point is :func:`validate_template`, which loads a plain dict
into the strict Pydantic model and raises a :class:`TemplateValidationError`
with clear, human-readable messages when anything is wrong.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .schema import SEVERITY_LEVELS, ReportTemplate

__all__ = ["TemplateValidationError", "validate_template", "format_validation_error"]


class TemplateValidationError(Exception):
    """Raised when a template dict fails strict schema validation.

    Attributes:
        errors: A list of human-readable error strings.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        message = "Template validation failed with %d error(s):\n" % len(errors)
        message += "\n".join(f"  - {e}" for e in errors)
        super().__init__(message)


def format_validation_error(exc: ValidationError) -> list[str]:
    """Convert a pydantic ValidationError into human-readable strings."""
    messages: list[str] = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "<root>"
        msg = err["msg"]
        messages.append(f"{location}: {msg}")
    return messages


def validate_template(data: dict[str, Any]) -> ReportTemplate:
    """Validate a plain dict against the gold-standard schema.

    Args:
        data: The template payload (typically parsed from the LLM's JSON output).

    Returns:
        A fully validated :class:`ReportTemplate`.

    Raises:
        TemplateValidationError: If validation fails, with readable messages.
    """
    if not isinstance(data, dict):
        raise TemplateValidationError(
            [f"Expected a JSON object at the top level, got {type(data).__name__}."]
        )

    try:
        template = ReportTemplate.model_validate(data)
    except ValidationError as exc:
        raise TemplateValidationError(format_validation_error(exc)) from exc

    # Extra semantic checks beyond what the model validators cover. These give
    # friendlier, product-focused messages than raw pydantic errors.
    problems = _semantic_checks(template)
    if problems:
        raise TemplateValidationError(problems)

    return template


# Production-quality thresholds. These are deliberately objective, low bars that
# any genuine day-one instruction clears; only vague one-liners fail. We rely on
# length/count (not fuzzy keyword matching) so we never reject a legitimately
# worded criterion.
_MIN_WORKER_WORDS = 12
_MIN_SUCCESS_WORDS = 8
_MIN_WRITER_WORDS = 15
_MIN_PHRASES = 3


def _semantic_checks(template: ReportTemplate) -> list[str]:
    """Product-quality checks that complement the structural model validators."""
    problems: list[str] = []

    guidance_ids = [s.section_id for s in template.guidance.sections]
    content_ids = [s.section_id for s in template.content_structure.sections]

    # Perfect mirroring (also enforced in the model, re-checked for clarity).
    if set(guidance_ids) != set(content_ids):
        problems.append(
            "guidance and content_structure section_ids must match exactly. "
            f"guidance={sorted(guidance_ids)} content={sorted(content_ids)}"
        )

    # Severity vocabulary MUST use the JobDoc gold standard only.
    gold = set(SEVERITY_LEVELS)
    for map_name, mapping in (
        ("severity_colors", template.pdf_styling.severity_colors),
        ("severity_bands", template.pdf_styling.severity_bands),
    ):
        illegal = [k for k in mapping if k not in gold]
        if illegal:
            problems.append(
                f"pdf_styling.{map_name} uses non-gold severity keys "
                f"{sorted(illegal)}. Allowed values are exactly: "
                f"{list(SEVERITY_LEVELS)} (do not use critical/high/medium/low/info)."
            )

    # Quality bar: min_summary_words should be realistic (45-70 recommended).
    for section in template.content_structure.sections:
        if section.min_summary_words < 20:
            problems.append(
                f"content_structure section '{section.section_id}' has "
                f"min_summary_words={section.min_summary_words}; expected a "
                "realistic value (>= 20, ideally 45-70)."
            )
        if len(section.writer_instructions.split()) < _MIN_WRITER_WORDS:
            problems.append(
                f"content_structure section '{section.section_id}' "
                "writer_instructions is too generic/short to guide the writing "
                f"agent (needs >= {_MIN_WRITER_WORDS} words with specific, "
                "binding direction)."
            )

    # Guidance sections must carry day-one-ready, checkable instructions.
    for section in template.guidance.sections:
        if len(section.worker_instructions.split()) < _MIN_WORKER_WORDS:
            problems.append(
                f"guidance section '{section.section_id}' worker_instructions is "
                f"too short for a day-one technician (needs >= {_MIN_WORKER_WORDS} "
                "words describing what to do, what to look for, and what to capture)."
            )
        if len(section.success_criteria.split()) < _MIN_SUCCESS_WORDS:
            problems.append(
                f"guidance section '{section.section_id}' success_criteria is "
                f"too short to be a checkable pass/fail condition (needs >= "
                f"{_MIN_SUCCESS_WORDS} words)."
            )
        phrases = [p for p in section.suggested_phrases if p.strip()]
        if len(phrases) < _MIN_PHRASES:
            problems.append(
                f"guidance section '{section.section_id}' needs >= {_MIN_PHRASES} "
                "realistic, domain-specific suggested_phrases."
            )

    return problems
