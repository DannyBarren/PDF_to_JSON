"""Strict validation for generated ReportTemplate payloads.

This is the last line of defense before a template is returned to a caller.
The pipeline MUST run this and MUST refuse to return a structurally invalid
template.

There are two tiers of checks:

* **Hard errors** (raise :class:`TemplateValidationError`) — anything that makes
  the template an invalid ReportTemplate or breaks the JobDoc contract: wrong
  types, empty required fields, broken section_id mirroring, incomplete
  capture_order, or non-gold severity vocabulary.
* **Quality warnings** (returned, never raised) — advisory suggestions such as
  thin ``worker_instructions`` or a short ``success_criteria``. These are
  surfaced to the caller but MUST NOT block delivery of an otherwise valid
  template. The prompt is what primarily drives writing quality; validation only
  *flags* soft issues (see :func:`quality_warnings`).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .schema import SEVERITY_LEVELS, ReportTemplate

__all__ = [
    "TemplateValidationError",
    "validate_template",
    "quality_warnings",
    "format_validation_error",
]


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

    # Hard, contractual checks beyond what the model validators cover. Only these
    # can block delivery. Quality issues are surfaced separately as warnings.
    problems = _hard_checks(template)
    if problems:
        raise TemplateValidationError(problems)

    return template


# Advisory quality thresholds. These NEVER block a schema-valid template; they
# only produce warnings. They are objective (length/count), so they don't reject
# legitimately worded content.
_MIN_WORKER_WORDS = 12
_MIN_SUCCESS_WORDS = 8
_MIN_WRITER_WORDS = 15
_MIN_PHRASES = 3


def _hard_checks(template: ReportTemplate) -> list[str]:
    """Contractual checks that MUST hold for a valid, JobDoc-ready template."""
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

    return problems


def quality_warnings(template: ReportTemplate) -> list[str]:
    """Return advisory quality suggestions (never fatal).

    These flag templates that are valid and usable but could be improved (thin
    instructions, short success criteria, few phrases). Callers may surface them
    but must still deliver the template.
    """
    warnings: list[str] = []

    for section in template.content_structure.sections:
        if section.min_summary_words < 20:
            warnings.append(
                f"content section '{section.section_id}': min_summary_words="
                f"{section.min_summary_words} is low (ideal 45-70)."
            )
        if len(section.writer_instructions.split()) < _MIN_WRITER_WORDS:
            warnings.append(
                f"content section '{section.section_id}': writer_instructions is "
                "brief; consider more specific, binding direction for the writer."
            )

    for section in template.guidance.sections:
        if len(section.worker_instructions.split()) < _MIN_WORKER_WORDS:
            warnings.append(
                f"guidance section '{section.section_id}': worker_instructions is "
                "brief; add concrete on-site steps for a day-one technician."
            )
        if len(section.success_criteria.split()) < _MIN_SUCCESS_WORDS:
            warnings.append(
                f"guidance section '{section.section_id}': success_criteria is "
                "brief; state a clearly checkable pass/fail condition."
            )
        phrases = [p for p in section.suggested_phrases if p.strip()]
        if len(phrases) < _MIN_PHRASES:
            warnings.append(
                f"guidance section '{section.section_id}': only {len(phrases)} "
                "suggested_phrase(s); 3+ domain-specific phrases are recommended."
            )

    return warnings
