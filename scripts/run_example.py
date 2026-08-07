#!/usr/bin/env python3
"""Generate a sample PDF and translate it end-to-end.

This script demonstrates the full pipeline. By default it uses a built-in
*offline* completer so it runs without an API key and always produces the
committed ``examples/sample_output.json``. Pass ``--live`` to call the real LLM
(requires OPENAI_API_KEY).

Usage:
    python scripts/run_example.py                 # offline, deterministic
    python scripts/run_example.py --live report.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make `src/` importable when run directly from the repo.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pdf_to_json.pipeline import TranslationPipeline  # noqa: E402


SAMPLE_PDF_TEXT = """\
Summit HVAC Services
Residential HVAC Maintenance & Inspection Report

Site & Job Details
Customer: R. Alvarez   Address: 482 Cedar Lane
System: Split-system heat pump, 3-ton, installed 2016.

Thermostat & Controls
Verified thermostat operation and calibration. Programmable schedule active.

Air Filter
Filter is a 16x25x1 MERV 8. Moderately dirty; recommend replacement.

Outdoor Condenser Unit
Coil has light debris. Fan motor operates normally. Refrigerant lines insulated.

Indoor Air Handler & Coil
Blower wheel clean. Condensate drain flows freely. No visible corrosion.

Electrical & Safety
Disconnect present and labeled. Contactor and capacitor within spec.

Summary & Recommendations
System operating normally. Replace air filter and schedule coil cleaning.
"""


def _build_sample_pdf(path: Path) -> None:
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 60), SAMPLE_PDF_TEXT, fontsize=11)
    doc.save(path)
    doc.close()


class _OfflineCompleter:
    """Deterministic completer that returns a hand-authored HVAC template."""

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(_OFFLINE_TEMPLATE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", help="PDF to translate (live mode).")
    parser.add_argument(
        "--live", action="store_true", help="Call the real LLM (needs OPENAI_API_KEY)."
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "examples" / "sample_output.json"),
        help="Where to write the resulting JSON.",
    )
    args = parser.parse_args()

    tmp_pdf = ROOT / "examples" / "_sample_input.pdf"
    if args.live:
        if not args.pdf:
            print("--live requires a PDF path argument.", file=sys.stderr)
            return 2
        pdf_path = Path(args.pdf)
        pipeline = TranslationPipeline()
    else:
        _build_sample_pdf(tmp_pdf)
        pdf_path = tmp_pdf
        pipeline = TranslationPipeline(completer=_OfflineCompleter())

    result = pipeline.run(pdf_path)
    output = Path(args.output)
    output.write_text(result.template.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote validated template -> {output}")
    print(
        f"  document_class={result.template.document_class} · "
        f"{len(result.template.guidance.sections)} sections · "
        f"~{result.template.guidance.estimated_total_minutes} min"
    )

    if not args.live and tmp_pdf.exists():
        tmp_pdf.unlink()
    return 0


# --------------------------------------------------------------------------- #
# Hand-authored, schema-valid example template (offline mode)
# --------------------------------------------------------------------------- #
def _g(section_id, order, title, voice, on_screen, worker, success, phrases, seconds, min_marks=1, required=True):
    return {
        "section_id": section_id,
        "title": title,
        "capture_order": order,
        "required": required,
        "min_marks": min_marks,
        "voice_prompt": voice,
        "on_screen_text": on_screen,
        "worker_instructions": worker,
        "success_criteria": success,
        "suggested_phrases": phrases,
        "estimated_seconds": seconds,
    }


def _c(section_id, title, default_text, fields, writer, min_words=55, max_images=3, show_photo=True):
    return {
        "section_id": section_id,
        "title": title,
        "default_text": default_text,
        "fields": fields,
        "writer_instructions": writer,
        "tone": "professional neutral",
        "min_summary_words": min_words,
        "show_photo": show_photo,
        "show_severity_badge": True,
        "image_placement": {
            "required": show_photo,
            "position": "after_summary",
            "caption_style": "narration_excerpt_with_timestamp",
            "max_images": max_images,
        },
        "layout_hints": {"page_break_before": False, "callout_style": "severity_border"},
    }


_SECTIONS = [
    ("site_details", "Site & Job Details"),
    ("thermostat_controls", "Thermostat & Controls"),
    ("air_filter", "Air Filter"),
    ("outdoor_condenser", "Outdoor Condenser Unit"),
    ("indoor_air_handler", "Indoor Air Handler & Coil"),
    ("electrical_safety", "Electrical & Safety"),
    ("summary_recommendations", "Summary & Recommendations"),
]

_OFFLINE_TEMPLATE = {
    "schema_version": 3,
    "document_class": "inspection_report",
    "report_type": "residential_hvac_maintenance_inspection",
    "title": "Residential HVAC Maintenance & Inspection Report",
    "business_name": "",
    "logo_url": None,
    "job_address": "",
    "template_description": (
        "Guided capture workflow for a residential HVAC maintenance and "
        "inspection visit on a split-system heat pump."
    ),
    "guidance": {
        "intro_script": (
            "Welcome. We're going to walk through this HVAC maintenance visit "
            "together, one system at a time. Take your time and describe what "
            "you see out loud — I'll turn it into the report."
        ),
        "outro_script": (
            "That completes the HVAC inspection capture. Double-check that every "
            "required section has a photo and a spoken note, then submit."
        ),
        "identification_phrase": "Mark this.",
        "estimated_total_minutes": 20,
        "sections": [
            _g(
                "site_details", 1, "Site & Job Details",
                "Start by confirming the customer, the address, and the system you're servicing. Read the system type, tonnage, and install year off the unit's data plate.",
                "Site & job details",
                "Find the outdoor unit's data plate (a metal sticker on the side of the condenser). Say the customer name, service address, system type (for example 'split-system heat pump'), tonnage, and the year it was installed. Photograph the data plate so the details are on record.",
                "Customer name and address are stated, and a legible photo of the system data plate is captured showing model and tonnage.",
                ["This is a 3-ton split-system heat pump", "Installed in 2016", "Customer is R. Alvarez at 482 Cedar Lane"],
                120,
            ),
            _g(
                "thermostat_controls", 2, "Thermostat & Controls",
                "Go to the thermostat. Cycle it through heating and cooling and tell me whether the system responds and whether the schedule looks correct.",
                "Thermostat & controls",
                "At the thermostat, switch to cooling and then heating and wait to hear the system respond. Confirm the programmed schedule is active. Photograph the thermostat screen. Note any error codes or calibration issues you hear or see.",
                "Thermostat is shown responding to at least one mode change, a photo of the display is captured, and the technician states whether calibration/schedule are correct.",
                ["Thermostat is calling for cooling", "The schedule is active and correct", "Display reads 72 degrees", "No error codes"],
                90,
            ),
            _g(
                "air_filter", 3, "Air Filter",
                "Pull the air filter. Read the size and MERV rating out loud and tell me how dirty it is.",
                "Air filter",
                "Locate and remove the return air filter. Read the printed size (for example 16x25x1) and MERV rating aloud. Hold it up to the light and describe how dirty it is. Photograph the filter face. Note if it needs replacement.",
                "Filter size and rating are stated, a photo of the filter is captured, and its condition (clean / dirty / needs replacement) is clearly described.",
                ["This is a 16 by 25 by 1 MERV 8", "The filter is moderately dirty", "Recommend replacing this filter", "Filter is clean"],
                75,
            ),
            _g(
                "outdoor_condenser", 4, "Outdoor Condenser Unit",
                "Move to the outdoor condenser. Pan across the coil, the fan, and the refrigerant lines, and describe anything that looks off.",
                "Outdoor condenser",
                "At the outdoor unit, inspect the coil for debris or bent fins, watch the fan motor run, and check that the refrigerant lines are insulated. Slowly pan across the unit on camera and describe the condition of each part as you go.",
                "The coil, fan operation, and refrigerant line insulation are each shown on camera and described; any debris or damage is called out or the technician states none was found.",
                ["Coil has light debris", "Fan motor runs smoothly", "Refrigerant lines are insulated", "No damage to the fins"],
                150,
            ),
            _g(
                "indoor_air_handler", 5, "Indoor Air Handler & Coil",
                "Open up the indoor air handler. Show me the blower wheel, the evaporator coil, and the condensate drain, and tell me if the drain is flowing.",
                "Air handler & coil",
                "Access the indoor air handler. Inspect the blower wheel for dust buildup, check the evaporator coil for corrosion, and confirm the condensate drain is flowing freely. Photograph each and describe what you see.",
                "Blower wheel, evaporator coil, and condensate drain are each captured and described, and drain flow (flowing / blocked) is stated.",
                ["Blower wheel is clean", "Condensate drain is flowing freely", "No corrosion on the coil", "Drain line is clear"],
                150,
            ),
            _g(
                "electrical_safety", 6, "Electrical & Safety",
                "Check the electrical disconnect and controls. Confirm the disconnect is present and labeled, and that the contactor and capacitor are within spec.",
                "Electrical & safety",
                "Locate the electrical disconnect near the outdoor unit and confirm it is present and labeled. If trained and safe to do so, verify the contactor and capacitor readings are within spec. Photograph the disconnect and any readings. Never open live electrical components you are not trained to service.",
                "The disconnect is shown present and labeled, and the technician states whether the contactor/capacitor are within spec or notes any electrical concern.",
                ["Disconnect is present and labeled", "Contactor is within spec", "Capacitor reads within range", "No electrical concerns"],
                120,
            ),
            _g(
                "summary_recommendations", 7, "Summary & Recommendations",
                "Wrap up with your overall assessment. Summarize the system's condition and list any recommended repairs or follow-up work.",
                "Summary & recommendations",
                "Give a plain-language summary of how the system is running overall, then list every recommendation you made (for example replacing the filter or cleaning the coil) with a rough priority. Note anything the customer should schedule.",
                "A spoken overall assessment is recorded and every recommendation from the visit is listed with a priority the customer can act on.",
                ["System is operating normally", "Recommend replacing the air filter", "Schedule a coil cleaning", "No urgent repairs needed"],
                120,
            ),
        ],
    },
    "content_structure": {
        "summary_page_title": "Executive Summary",
        "organization": "section_order",
        "sections": [
            _c(
                "site_details", "Site & Job Details",
                "System and site details were not recorded during this visit.",
                ["customer", "job_address", "system_type", "tonnage", "install_year"],
                "State the customer, service address, and full system description (type, tonnage, install year) from the captured data plate. Keep it factual; do not assess condition here.",
                min_words=45,
            ),
            _c(
                "thermostat_controls", "Thermostat & Controls",
                "Thermostat operation was not assessed during this visit.",
                ["operation", "calibration", "schedule", "findings", "severity"],
                "Describe how the thermostat responded to mode changes and whether calibration and schedule are correct. Report any error codes verbatim and assign a severity to any fault.",
            ),
            _c(
                "air_filter", "Air Filter",
                "The air filter was not inspected during this visit.",
                ["filter_size", "merv_rating", "condition", "recommendation", "severity"],
                "Record the filter size and MERV rating, describe its condition, and give a clear replacement recommendation. Flag a dirty filter as at least low severity affecting efficiency.",
                min_words=45,
            ),
            _c(
                "outdoor_condenser", "Outdoor Condenser Unit",
                "The outdoor condenser unit was not accessible or not assessed during this visit.",
                ["coil_condition", "fan_operation", "refrigerant_lines", "findings", "recommendations", "severity"],
                "Summarize coil condition, fan operation, and refrigerant line insulation. List any debris, bent fins, or damage with location and severity, and recommend cleaning or repair where warranted.",
                min_words=60,
            ),
            _c(
                "indoor_air_handler", "Indoor Air Handler & Coil",
                "The indoor air handler and coil were not accessible or not assessed during this visit.",
                ["blower_condition", "coil_condition", "condensate_drain", "findings", "recommendations", "severity"],
                "Describe the blower wheel and evaporator coil condition and confirm condensate drain flow. Call out any corrosion or blockage with severity and recommend corrective action.",
                min_words=60,
            ),
            _c(
                "electrical_safety", "Electrical & Safety",
                "Electrical components were not assessed during this visit.",
                ["disconnect", "contactor", "capacitor", "findings", "severity"],
                "Confirm the disconnect is present and labeled and report contactor/capacitor status. Treat any electrical safety defect as high or critical severity and recommend a licensed technician.",
                min_words=50,
            ),
            _c(
                "summary_recommendations", "Summary & Recommendations",
                "No overall summary was recorded for this visit.",
                ["overall_assessment", "prioritized_recommendations", "follow_up"],
                "Provide a concise overall assessment of system health and a prioritized, actionable list of recommendations drawn from the section findings. Do not introduce issues not captured earlier.",
                min_words=60,
                show_photo=False,
            ),
        ],
    },
}


if __name__ == "__main__":
    raise SystemExit(main())
