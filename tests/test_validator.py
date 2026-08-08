"""Tests for the human-readable validator layer."""

from __future__ import annotations

import pytest

from pdf_to_json.validator import (
    TemplateValidationError,
    quality_warnings,
    validate_template,
)


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


def test_low_min_summary_words_is_a_warning_not_error(clone_valid_template):
    data = clone_valid_template()
    data["content_structure"]["sections"][0]["min_summary_words"] = 5
    # Valid template: should NOT raise, but should be flagged as a warning.
    template = validate_template(data)
    assert any("min_summary_words" in w for w in quality_warnings(template))


def test_short_writer_instructions_is_a_warning_not_error(clone_valid_template):
    data = clone_valid_template()
    data["content_structure"]["sections"][0]["writer_instructions"] = "Write it well."
    template = validate_template(data)
    assert any("writer_instructions" in w for w in quality_warnings(template))


def test_non_gold_severity_keys_rejected(clone_valid_template):
    data = clone_valid_template()
    data["pdf_styling"] = {
        "severity_colors": {"critical": "#dc2626", "info": "#2563eb"},
    }
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "severity" in str(exc.value).lower()


def test_short_worker_instructions_is_a_warning_not_error(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][0]["worker_instructions"] = "Check the roof."
    template = validate_template(data)
    assert any("worker_instructions" in w for w in quality_warnings(template))


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


def test_short_success_criteria_is_a_warning_not_error(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][0]["success_criteria"] = "Looks fine."
    template = validate_template(data)
    assert any("success_criteria" in w for w in quality_warnings(template))


def test_thin_general_information_section_does_not_block(clone_valid_template):
    # Regression guard for the reported failure: a terse general_information
    # section must NOT block an otherwise valid template.
    data = clone_valid_template()
    data["guidance"]["sections"][0]["section_id"] = "general_information"
    data["content_structure"]["sections"][0]["section_id"] = "general_information"
    data["guidance"]["sections"][0]["success_criteria"] = "Details recorded."
    data["content_structure"]["sections"][0]["writer_instructions"] = "State the job details."
    template = validate_template(data)  # must not raise
    assert template.report_type


def test_too_few_suggested_phrases_is_a_warning_not_error(clone_valid_template):
    data = clone_valid_template()
    data["guidance"]["sections"][0]["suggested_phrases"] = ["only one phrase"]
    template = validate_template(data)
    assert any("suggested_phrase" in w for w in quality_warnings(template))


def test_mirroring_error_is_readable(clone_valid_template):
    data = clone_valid_template()
    data["content_structure"]["sections"].pop()
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "mirror" in str(exc.value).lower() or "missing" in str(exc.value).lower()
