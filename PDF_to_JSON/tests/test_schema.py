"""Tests proving the strict schema accepts good templates and rejects bad ones."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pdf_to_json.schema import PdfStyling, ReportTemplate


def test_valid_template_parses(valid_template):
    template = ReportTemplate.model_validate(valid_template)
    assert template.schema_version == 3
    assert template.document_class == "inspection_report"
    assert len(template.guidance.sections) == 3
    assert template.ordered_section_ids() == [
        "site_details",
        "roof_condition",
        "summary_recommendations",
    ]


def test_defaults_fill_pdf_styling(valid_template):
    template = ReportTemplate.model_validate(valid_template)
    assert isinstance(template.pdf_styling, PdfStyling)
    assert template.pdf_styling.primary_color == "#1e3a8a"
    assert "critical" in template.pdf_styling.severity_colors


def test_mirroring_failure_rejected(clone_valid_template):
    data = clone_valid_template()
    # Break mirroring: rename a guidance section_id only.
    data["guidance"]["sections"][1]["section_id"] = "renamed_section"
    with pytest.raises(ValidationError) as exc:
        ReportTemplate.model_validate(data)
    assert "mirroring" in str(exc.value).lower()


def test_capture_order_gap_rejected(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][2]["capture_order"] = 9  # gap
    with pytest.raises(ValidationError) as exc:
        ReportTemplate.model_validate(data)
    assert "capture_order" in str(exc.value)


def test_empty_worker_instructions_rejected(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][0]["worker_instructions"] = "   "
    with pytest.raises(ValidationError):
        ReportTemplate.model_validate(data)


def test_non_snake_case_section_id_rejected(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][0]["section_id"] = "Not Snake"
    data["content_structure"]["sections"][0]["section_id"] = "Not Snake"
    with pytest.raises(ValidationError):
        ReportTemplate.model_validate(data)


def test_bad_hex_color_rejected(clone_valid_template):
    data = clone_valid_template()
    data["pdf_styling"] = {"primary_color": "blue"}
    with pytest.raises(ValidationError):
        ReportTemplate.model_validate(data)


def test_empty_suggested_phrases_rejected(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][0]["suggested_phrases"] = []
    with pytest.raises(ValidationError):
        ReportTemplate.model_validate(data)


def test_wrong_schema_version_rejected(clone_valid_template):
    data = clone_valid_template()
    data["schema_version"] = 2
    with pytest.raises(ValidationError):
        ReportTemplate.model_validate(data)


def test_missing_guidance_rejected(clone_valid_template):
    data = clone_valid_template()
    del data["guidance"]
    with pytest.raises(ValidationError):
        ReportTemplate.model_validate(data)
