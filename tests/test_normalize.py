"""Tests for the normalization / repair layer."""

from __future__ import annotations

import pytest

from pdf_to_json.normalize import normalize_template
from pdf_to_json.validator import validate_template
from tests.conftest import make_valid_template


def test_max_images_zero_is_repaired_and_validates():
    data = make_valid_template()
    # Reproduce the reported failure: model returns max_images = 0.
    data["content_structure"]["sections"][0]["image_placement"]["max_images"] = 0
    data["content_structure"]["sections"][1]["image_placement"]["max_images"] = 0

    repaired = normalize_template(data)
    assert repaired["content_structure"]["sections"][0]["image_placement"]["max_images"] == 1

    # The repaired template must pass strict validation.
    template = validate_template(repaired)
    assert template.content_structure.sections[0].image_placement.max_images == 1


def test_max_images_too_large_is_clamped():
    data = make_valid_template()
    data["content_structure"]["sections"][0]["image_placement"]["max_images"] = 9999
    repaired = normalize_template(data)
    assert repaired["content_structure"]["sections"][0]["image_placement"]["max_images"] == 50


def test_capture_order_gaps_are_renumbered():
    data = make_valid_template()
    data["guidance"]["sections"][0]["capture_order"] = 5
    data["guidance"]["sections"][1]["capture_order"] = 9
    data["guidance"]["sections"][2]["capture_order"] = 12
    repaired = normalize_template(data)
    orders = [s["capture_order"] for s in repaired["guidance"]["sections"]]
    assert sorted(orders) == [1, 2, 3]
    # Original relative order is preserved.
    assert orders == [1, 2, 3]
    validate_template(repaired)  # should not raise


def test_low_min_summary_words_is_floored():
    data = make_valid_template()
    data["content_structure"]["sections"][0]["min_summary_words"] = 3
    repaired = normalize_template(data)
    assert repaired["content_structure"]["sections"][0]["min_summary_words"] == 45


def test_zero_estimated_seconds_is_fixed():
    data = make_valid_template()
    data["guidance"]["sections"][0]["estimated_seconds"] = 0
    repaired = normalize_template(data)
    assert repaired["guidance"]["sections"][0]["estimated_seconds"] >= 1


def test_weak_suggested_phrases_are_not_masked():
    from pdf_to_json.validator import TemplateValidationError

    data = make_valid_template()
    # Blank/duplicate phrases should be cleaned, not padded with filler...
    data["guidance"]["sections"][0]["suggested_phrases"] = ["ok", "  ", "ok"]
    repaired = normalize_template(data)
    assert repaired["guidance"]["sections"][0]["suggested_phrases"] == ["ok"]
    # ...and the too-thin set must then be rejected by validation.
    with pytest.raises(TemplateValidationError):
        validate_template(repaired)


def test_unknown_document_class_falls_back_to_custom():
    data = make_valid_template()
    data["document_class"] = "totally_made_up"
    repaired = normalize_template(data)
    assert repaired["document_class"] == "custom"


def test_report_type_is_slugified():
    data = make_valid_template()
    data["report_type"] = "Roof Inspection (Residential)!"
    repaired = normalize_template(data)
    assert repaired["report_type"] == "roof_inspection_residential"
    validate_template(repaired)


def test_legacy_severity_keys_are_remapped_to_gold():
    data = make_valid_template()
    data["pdf_styling"] = {
        "severity_colors": {
            "critical": "#dc2626",
            "high": "#ea580c",
            "medium": "#d97706",
            "low": "#16a34a",
            "info": "#2563eb",
        },
        "severity_bands": {
            "critical": "Immediate action required",
            "info": "FYI only",
        },
    }
    repaired = normalize_template(data)
    colors = repaired["pdf_styling"]["severity_colors"]
    assert set(colors) == {
        "informational",
        "minor",
        "moderate",
        "major",
        "safety_critical",
    }
    # Legacy value carried onto the gold key.
    assert colors["safety_critical"] == "#dc2626"
    assert colors["minor"] == "#16a34a"

    bands = repaired["pdf_styling"]["severity_bands"]
    assert bands["safety_critical"] == "Immediate action required"
    assert bands["informational"] == "FYI only"
    # Missing levels filled with defaults.
    assert "moderate" in bands

    # And the remapped template validates.
    validate_template(repaired)


def test_default_severity_is_gold_standard():
    template = validate_template(make_valid_template())
    assert set(template.pdf_styling.severity_colors) == {
        "informational",
        "minor",
        "moderate",
        "major",
        "safety_critical",
    }


def test_normalize_does_not_hide_structural_errors():
    from pdf_to_json.validator import TemplateValidationError

    data = make_valid_template()
    del data["guidance"]  # genuinely broken
    repaired = normalize_template(data)
    try:
        validate_template(repaired)
    except TemplateValidationError:
        return
    raise AssertionError("Expected validation to fail for a template missing guidance")
