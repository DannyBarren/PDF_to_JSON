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


def test_mirroring_error_is_readable(clone_valid_template):
    data = clone_valid_template()
    data["content_structure"]["sections"].pop()
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(data)
    assert "mirror" in str(exc.value).lower() or "missing" in str(exc.value).lower()
