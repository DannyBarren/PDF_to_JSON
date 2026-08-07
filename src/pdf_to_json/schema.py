"""Gold-standard Pydantic models for the GenerSwift ReportTemplate (schema_version 3).

This module is the single source of truth for the output contract of the whole
system. It is intentionally self-contained: it has **zero** runtime dependency on
the main report_automation / JobDoc codebase. The only contract between the two
systems is the shape defined here.

The models are strict:

* All human-facing text fields are validated as non-empty.
* ``section_id`` values must be snake_case and must mirror perfectly between
  ``guidance.sections`` and ``content_structure.sections``.
* ``capture_order`` must be a complete, sequential ``1..N`` sequence.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

__all__ = [
    "DocumentClass",
    "ImagePlacement",
    "LayoutHints",
    "PdfStyling",
    "GuidanceSection",
    "Guidance",
    "ContentSection",
    "ContentStructure",
    "ReportTemplate",
    "SCHEMA_VERSION",
]

SCHEMA_VERSION = 3

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

DocumentClass = Literal[
    "inspection_report",
    "estimate",
    "invoice",
    "compliance",
    "work_order",
    "custom",
]


# --------------------------------------------------------------------------- #
# Reusable validated string types
# --------------------------------------------------------------------------- #
def _non_empty(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-empty string")
    return value.strip()


def _snake_case(value: str) -> str:
    value = _non_empty(value)
    if not _SNAKE_CASE_RE.match(value):
        raise ValueError(
            f"'{value}' must be snake_case (lowercase letters, digits and "
            "underscores, starting with a letter)"
        )
    return value


def _hex_color(value: str) -> str:
    value = _non_empty(value)
    if not _HEX_COLOR_RE.match(value):
        raise ValueError(f"'{value}' is not a valid hex color (e.g. #1e3a8a)")
    return value


NonEmptyStr = Annotated[str, AfterValidator(_non_empty)]
SnakeCaseStr = Annotated[str, AfterValidator(_snake_case)]
HexColor = Annotated[str, AfterValidator(_hex_color)]


class _StrictModel(BaseModel):
    """Base model with a shared, forgiving-but-typed configuration.

    ``extra="ignore"`` keeps the pipeline robust against a stray key from the
    LLM while still enforcing that every declared field is present and valid.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)


# --------------------------------------------------------------------------- #
# pdf_styling
# --------------------------------------------------------------------------- #
class PdfStyling(_StrictModel):
    primary_color: HexColor = "#1e3a8a"
    secondary_color: HexColor = "#64748b"
    accent_color: HexColor = "#2563eb"
    font_family: NonEmptyStr = "Helvetica, Arial, sans-serif"
    header_style: NonEmptyStr = "bold"
    photo_grid: NonEmptyStr = "2-column with caption below"
    include_timestamps: bool = True
    include_narration_in_caption: bool = True
    page_footer: NonEmptyStr = (
        "{business_name} · Confidential · Page {page} of {total_pages}"
    )
    page_header: NonEmptyStr = "{report_title}"
    logo_placement: NonEmptyStr = "header-left"
    show_summary_page: bool = True
    show_disclaimer: bool = True
    disclaimer_text: NonEmptyStr = (
        "This report documents conditions observed during a guided field "
        "inspection. It reflects the state of the property or equipment at the "
        "time of the visit and is not a warranty or guarantee of future "
        "performance."
    )
    show_photo_appendix: bool = True
    section_page_break: Literal["before", "after", "none"] = "before"
    severity_colors: dict[str, str] = Field(
        default_factory=lambda: {
            "critical": "#dc2626",
            "high": "#ea580c",
            "medium": "#d97706",
            "low": "#16a34a",
            "info": "#2563eb",
        }
    )
    severity_bands: dict[str, str] = Field(
        default_factory=lambda: {
            "critical": "Immediate action required",
            "high": "Address promptly",
            "medium": "Plan to repair",
            "low": "Monitor",
            "info": "Informational only",
        }
    )

    @field_validator("severity_colors")
    @classmethod
    def _validate_severity_colors(cls, value: dict[str, str]) -> dict[str, str]:
        for key, color in value.items():
            if not _HEX_COLOR_RE.match(str(color)):
                raise ValueError(
                    f"severity_colors['{key}'] = '{color}' is not a valid hex color"
                )
        return value


# --------------------------------------------------------------------------- #
# guidance
# --------------------------------------------------------------------------- #
class GuidanceSection(_StrictModel):
    section_id: SnakeCaseStr
    title: NonEmptyStr
    capture_order: int = Field(ge=1)
    required: bool = True
    min_marks: int = Field(default=1, ge=0)
    voice_prompt: NonEmptyStr
    on_screen_text: NonEmptyStr
    worker_instructions: NonEmptyStr
    success_criteria: NonEmptyStr
    suggested_phrases: list[NonEmptyStr] = Field(min_length=1)
    estimated_seconds: int = Field(ge=1)


class Guidance(_StrictModel):
    intro_script: NonEmptyStr
    outro_script: NonEmptyStr
    identification_phrase: NonEmptyStr = "Mark this."
    estimated_total_minutes: int = Field(ge=1)
    sections: list[GuidanceSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_capture_order(self) -> "Guidance":
        orders = [s.capture_order for s in self.sections]
        expected = list(range(1, len(self.sections) + 1))
        if sorted(orders) != expected:
            raise ValueError(
                "guidance.sections capture_order must be a complete sequential "
                f"sequence 1..{len(self.sections)}; got {sorted(orders)}"
            )
        ids = [s.section_id for s in self.sections]
        if len(set(ids)) != len(ids):
            raise ValueError(
                f"guidance.sections contains duplicate section_id values: {ids}"
            )
        return self


# --------------------------------------------------------------------------- #
# content_structure
# --------------------------------------------------------------------------- #
class ImagePlacement(_StrictModel):
    required: bool = True
    position: Literal[
        "before_summary", "after_summary", "inline", "appendix"
    ] = "after_summary"
    caption_style: NonEmptyStr = "narration_excerpt_with_timestamp"
    max_images: int = Field(default=3, ge=1, le=50)


class LayoutHints(_StrictModel):
    page_break_before: bool = False
    callout_style: NonEmptyStr = "severity_border"


class ContentSection(_StrictModel):
    section_id: SnakeCaseStr
    title: NonEmptyStr
    default_text: NonEmptyStr
    fields: list[NonEmptyStr] = Field(min_length=1)
    writer_instructions: NonEmptyStr
    tone: NonEmptyStr = "professional neutral"
    min_summary_words: int = Field(ge=1)
    show_photo: bool = True
    show_severity_badge: bool = True
    image_placement: ImagePlacement = Field(default_factory=ImagePlacement)
    layout_hints: LayoutHints = Field(default_factory=LayoutHints)


class ContentStructure(_StrictModel):
    summary_page_title: NonEmptyStr = "Executive Summary"
    organization: NonEmptyStr = "section_order"
    sections: list[ContentSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "ContentStructure":
        ids = [s.section_id for s in self.sections]
        if len(set(ids)) != len(ids):
            raise ValueError(
                f"content_structure.sections contains duplicate section_id "
                f"values: {ids}"
            )
        return self


# --------------------------------------------------------------------------- #
# top-level template
# --------------------------------------------------------------------------- #
class ReportTemplate(_StrictModel):
    schema_version: Literal[3] = SCHEMA_VERSION
    document_class: DocumentClass
    report_type: SnakeCaseStr
    title: NonEmptyStr
    business_name: str = ""
    logo_url: str | None = None
    job_address: str = ""
    template_description: NonEmptyStr
    pdf_styling: PdfStyling = Field(default_factory=PdfStyling)
    guidance: Guidance
    content_structure: ContentStructure

    @model_validator(mode="after")
    def _check_section_mirroring(self) -> "ReportTemplate":
        guidance_ids = [s.section_id for s in self.guidance.sections]
        content_ids = [s.section_id for s in self.content_structure.sections]

        guidance_set = set(guidance_ids)
        content_set = set(content_ids)

        missing_in_content = guidance_set - content_set
        missing_in_guidance = content_set - guidance_set

        problems: list[str] = []
        if missing_in_content:
            problems.append(
                "section_id(s) present in guidance but missing in "
                f"content_structure: {sorted(missing_in_content)}"
            )
        if missing_in_guidance:
            problems.append(
                "section_id(s) present in content_structure but missing in "
                f"guidance: {sorted(missing_in_guidance)}"
            )
        if problems:
            raise ValueError("Section mirroring failed. " + " ".join(problems))
        return self

    def ordered_section_ids(self) -> list[str]:
        """Return section_ids in capture order (source-of-truth ordering)."""
        return [
            s.section_id
            for s in sorted(self.guidance.sections, key=lambda s: s.capture_order)
        ]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportTemplate":
        """Convenience constructor from a plain dict."""
        return cls.model_validate(data)
