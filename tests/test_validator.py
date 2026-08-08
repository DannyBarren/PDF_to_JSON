"""Tests for the human-readable validator layer."""

from __future__ import annotations

import pytest

from pdf_to_json.validator import TemplateValidationError, validate_template


def test_validate_good_template(valid_template):
    template = validate_template(valid_template)
    assert template.report_type == "roof_inspection"


def test_non_dict_input_rejected():
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(["not", "a", "dict"])  # type: ignore[arg-type]
    assert "top level" in str(exc.value)


def test_missing_field_gives_readable_error(clone_valid_template):
    data = clone_valid_template()
    del data["template_description"]
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "template_description" in str(exc.value)


def test_low_min_summary_words_flagged(clone_valid_template):
    data = clone_valid_template()
    data["content_structure"]["sections"][0]["min_summary_words"] = 5
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "min_summary_words" in str(exc.value)


def test_short_writer_instructions_flagged(clone_valid_template):
    data = clone_valid_template()
    data["content_structure"]["sections"][0]["writer_instructions"] = "Write it well."
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "writer_instructions" in str(exc.value)


def test_non_gold_severity_keys_rejected(clone_valid_template):
    data = clone_valid_template()
    data["pdf_styling"] = {
        "severity_colors": {"critical": "#dc2626", "info": "#2563eb"},
    }
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "severity" in str(exc.value).lower()


def test_short_worker_instructions_rejected(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][0]["worker_instructions"] = "Check the roof."
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "worker_instructions" in str(exc.value)


def test_photoless_success_criteria_accepted(clone_valid_template):
    # Regression guard: a valid, well-formed success_criteria for a non-photo
    # section (e.g. general info / summary) must NOT be rejected just because it
    # doesn't contain photo/spoken keywords.
    data = clone_valid_template()
    data["guidance"]["sections"][0]["success_criteria"] = (
        "All identifying job details (client, address, and roof system type) are "
        "entered accurately and the overall recommendation is provided before the "
        "session is submitted."
    )
    # Should validate without raising.
    validate_template(data)


def test_short_success_criteria_still_rejected(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][0]["success_criteria"] = "Looks fine."
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "success_criteria" in str(exc.value)


def test_too_few_suggested_phrases_rejected(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][0]["suggested_phrases"] = ["only one phrase"]
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "suggested_phrases" in str(exc.value)


def test_mirroring_error_is_readable(clone_valid_template):
    data = clone_valid_template()
    data["content_structure"]["sections"].pop()
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "mirror" in str(exc.value).lower() or "missing" in str(exc.value).lower()
