"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest


def _guidance_section(section_id: str, order: int, title: str) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "title": title,
        "capture_order": order,
        "required": True,
        "min_marks": 1,
        "voice_prompt": f"Please capture the {title.lower()} now, describing what you see.",
        "on_screen_text": title,
        "worker_instructions": (
            f"Walk to the {title.lower()} area and inspect it in overlapping "
            "passes. Take a close-up photo of every defect with something for "
            "scale, then one wide shot showing where it sits, and say out loud "
            "what you see and whether the surface feels solid or soft."
        ),
        "success_criteria": (
            "At least two clear photos of the worst defects plus a spoken "
            "confirmation of the condition are recorded, or the technician "
            "explicitly states no defects were found here."
        ),
        "suggested_phrases": [
            "This area looks in good condition",
            "I see some damage here on the surface",
            "The material feels soft right here",
            "No defects found in this area",
        ],
        "estimated_seconds": 150,
    }


def _content_section(section_id: str, title: str) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "title": title,
        "default_text": f"The {title.lower()} was not observed during this visit.",
        "fields": ["condition_summary", "findings", "recommendations", "severity"],
        "writer_instructions": (
            f"Describe the observed condition of the {title.lower()} using the "
            "technician's specific locations. Name each defect, assign a JobDoc "
            "severity, and use clear recommend-replace versus recommend-maintain "
            "language based on what was captured. Do not invent findings."
        ),
        "tone": "professional neutral",
        "min_summary_words": 55,
        "show_photo": True,
        "show_severity_badge": True,
        "image_placement": {
            "required": True,
            "position": "after_summary",
            "caption_style": "narration_excerpt_with_timestamp",
            "max_images": 3,
        },
        "layout_hints": {"page_break_before": False, "callout_style": "severity_border"},
    }


def make_valid_template() -> dict[str, Any]:
    """Return a minimal-but-valid schema_version 3 template dict."""
    sections = [
        ("site_details", "Site & Job Details"),
        ("roof_condition", "Roof Condition"),
        ("summary_recommendations", "Summary & Recommendations"),
    ]
    guidance_sections = [
        _guidance_section(sid, i + 1, title)
        for i, (sid, title) in enumerate(sections)
    ]
    content_sections = [_content_section(sid, title) for sid, title in sections]

    return {
        "schema_version": 3,
        "document_class": "inspection_report",
        "report_type": "roof_inspection",
        "title": "Roof Inspection Report",
        "business_name": "",
        "logo_url": None,
        "job_address": "",
        "template_description": "Guided roof inspection capture workflow.",
        "guidance": {
            "intro_script": "Welcome. We'll walk through the roof inspection together.",
            "outro_script": "Great work. The inspection capture is complete.",
            "identification_phrase": "Mark this.",
            "estimated_total_minutes": 15,
            "sections": guidance_sections,
        },
        "content_structure": {
            "summary_page_title": "Executive Summary",
            "organization": "section_order",
            "sections": content_sections,
        },
    }


@pytest.fixture()
def valid_template() -> dict[str, Any]:
    return make_valid_template()


@pytest.fixture()
def clone_valid_template():
    def _clone() -> dict[str, Any]:
        return copy.deepcopy(make_valid_template())

    return _clone


@pytest.fixture()
def sample_pdf(tmp_path: Path) -> Path:
    """Create a small text-native PDF for extraction tests (requires pymupdf)."""
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    text = (
        "ACME Property Inspections\n"
        "Roof Inspection Report\n\n"
        "Site & Job Details\n"
        "Address: 123 Main St. Inspector: J. Smith.\n\n"
        "Roof Condition\n"
        "Shingles show moderate wear. Two cracked tiles near the ridge.\n\n"
        "Summary & Recommendations\n"
        "Replace cracked tiles within 60 days.\n"
    )
    page.insert_text((72, 72), text, fontsize=12)
    doc.save(pdf_path)
    doc.close()
    return pdf_path
