"""The committed example fixture must stay a valid, synthetic ReportTemplate."""

from __future__ import annotations

import json
from pathlib import Path

from pdf_to_json.validator import validate_template

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sample_output.json"


def test_committed_sample_output_validates():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    template = validate_template(data)
    assert template.schema_version == 3
    assert template.document_class == "inspection_report"
    assert len(template.guidance.sections) >= 6
    assert template.business_name == ""
    assert template.job_address == ""


def test_committed_sample_uses_synthetic_location_only():
    text = SAMPLE.read_text(encoding="utf-8")
    assert "100 Example Parkway" in text
    assert "Tamiami" not in text
    assert "MasterCraft" not in text
