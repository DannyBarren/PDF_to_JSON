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

from .schema import ReportTemplate

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

    # Quality bar: min_summary_words should be realistic (45-70 recommended).
    for section in template.content_structure.sections:
        if section.min_summary_words < 20:
            problems.append(
                f"content_structure section '{section.section_id}' has "
                f"min_summary_words={section.min_summary_words}; expected a "
                "realistic value (>= 20, ideally 45-70)."
            )

    # Guidance sections should each carry meaningful instructions (length check).
    for section in template.guidance.sections:
        if len(section.worker_instructions.split()) < 4:
            problems.append(
                f"guidance section '{section.section_id}' worker_instructions is "
                "too short to be useful for a day-one technician."
            )
        if len(section.success_criteria.split()) < 3:
            problems.append(
                f"guidance section '{section.section_id}' success_criteria is "
                "too short to be a checkable pass/fail condition."
            )

    for section in template.content_structure.sections:
        if len(section.writer_instructions.split()) < 5:
            problems.append(
                f"content_structure section '{section.section_id}' "
                "writer_instructions is too generic/short to guide the writing agent."
            )

    return problems
