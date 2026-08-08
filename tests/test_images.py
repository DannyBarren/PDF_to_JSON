"""Image-presence detection + deterministic photo forcing."""

from __future__ import annotations

import json

from pdf_to_json.extractor import extract_pdf
from pdf_to_json.normalize import apply_image_hints
from pdf_to_json.pipeline import TranslationPipeline
from tests.conftest import make_valid_template


def test_extractor_detects_embedded_images(pdf_with_image):
    doc = extract_pdf(pdf_with_image)
    assert doc.image_count >= 1
    assert 1 in doc.pages_with_images
    hints = doc.image_hints
    assert hints["total_images"] >= 1
    titles = [h["title"] for h in hints["headings"]]
    # The image sits under the "Roof Condition" heading.
    assert any("Roof" in t for t in titles)
    # ...and not under the later image-free heading.
    assert not any("Interior" in t for t in titles)


def test_extractor_no_images_when_absent(sample_pdf):
    doc = extract_pdf(sample_pdf)
    assert doc.image_count == 0
    assert doc.image_hints["headings"] == []


def test_apply_image_hints_forces_photo_settings():
    data = make_valid_template()
    for s in data["content_structure"]["sections"]:
        if s["section_id"] == "roof_condition":
            s["show_photo"] = False
            s["image_placement"]["required"] = False
            s["image_placement"]["max_images"] = 1

    hints = {
        "total_images": 4,
        "pages_with_images": [1],
        "headings": [{"title": "Roof Condition", "page": 1, "images": 4}],
        "unassociated_images": 0,
    }
    apply_image_hints(data, hints)

    sec = next(s for s in data["content_structure"]["sections"] if s["section_id"] == "roof_condition")
    assert sec["show_photo"] is True
    assert sec["image_placement"]["required"] is True
    assert sec["image_placement"]["max_images"] >= 4
    # A non-matching section is untouched.
    site = next(s for s in data["content_structure"]["sections"] if s["section_id"] == "site_details")
    assert site["image_placement"]["max_images"] == 3


def test_apply_image_hints_noop_without_hints():
    data = make_valid_template()
    before = json.dumps(data)
    apply_image_hints(data, None)
    apply_image_hints(data, {"total_images": 0, "headings": []})
    assert json.dumps(data) == before


class _Fake:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, *, system, user):
        return json.dumps(self.payload)


def test_pipeline_forces_photo_from_source_images(pdf_with_image):
    payload = make_valid_template()
    for s in payload["content_structure"]["sections"]:
        if s["section_id"] == "roof_condition":
            s["show_photo"] = False
            s["image_placement"]["required"] = False
            s["image_placement"]["max_images"] = 1

    pipeline = TranslationPipeline(completer=_Fake(payload))
    result = pipeline.run(pdf_with_image)

    roof = next(
        s for s in result.template.content_structure.sections
        if s.section_id == "roof_condition"
    )
    assert roof.show_photo is True
    assert roof.image_placement.required is True
    assert roof.image_placement.max_images >= 1


def test_pipeline_passes_image_hints_to_generator(pdf_with_image):
    captured = {}

    class _Capture:
        def complete(self, *, system, user):
            captured["user"] = user
            return json.dumps(make_valid_template())

    TranslationPipeline(completer=_Capture()).run(pdf_with_image)
    assert "SOURCE IMAGE PRESENCE" in captured["user"]
    assert "Roof Condition" in captured["user"]
