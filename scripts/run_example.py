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
MasterCraft Roofing
Commercial Low-Slope Roof Inspection Report

Site & Job Details
Property: 333 S Tamiami Trail. Roof system: gravel-surfaced built-up roof (BUR),
approx. 6,500 sq ft, estimated 18 years old.

Roof Access & General Overview
Accessed via interior hatch. Overall gravel surfacing thin in several areas.

South Roof Field - Membrane & Surface
Ponding observed near south parapet. Blistering and bald spots noted. Decking
soft/spongy in one area.

Main Roof Field - Membrane & Ponding
Widespread ponding across central field. Multiple membrane splits along seams.

Flashings, Penetrations & Curbs
Base flashing at HVAC curb lifting. Pitch pockets dried and cracked.

Drainage: Drains, Scuppers & Gutters
Two interior drains partially blocked with gravel. Scupper rusted.

Edge Metal, Gravel Stop & Parapet Coping
Gravel stop loose along west edge. Coping joints open.

Interior Leak Evidence & Ceiling Staining
Active water staining on ceiling tiles below south field.

Summary & Recommendations
Roof at end of service life. Full replacement recommended.
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


_OFFLINE_TEMPLATE = {
    "schema_version": 3,
    "document_class": "inspection_report",
    "report_type": "commercial_low_slope_roof_inspection",
    "title": "Commercial Low-Slope Roof Inspection Report",
    "business_name": "",
    "logo_url": None,
    "job_address": "",
    "template_description": (
        "Guided capture workflow for a commercial low-slope (built-up / "
        "modified-bitumen) roof inspection, covering the roof fields, flashings, "
        "drainage, edge metal, and interior leak evidence."
    ),
    "guidance": {
        "intro_script": (
            "Welcome. We're going to inspect this low-slope roof one area at a "
            "time - the fields, the flashings, the drains, the edges, and any "
            "leak evidence inside. Work safely, stay away from the edge, and just "
            "describe what you see and feel out loud. I'll turn it into the report."
        ),
        "outro_script": (
            "That completes the roof capture. Make sure every required area has at "
            "least one photo and a spoken note, and that you called your overall "
            "recommendation - repair or replace - before you submit."
        ),
        "identification_phrase": "Mark this.",
        "estimated_total_minutes": 30,
        "sections": [
            _g(
                "site_job_details", 1, "Site & Job Details",
                "Start by confirming the property address and the roof system. Read the roof type, approximate size, and estimated age from your paperwork, and photograph the building front.",
                "Site & job details",
                "Confirm and say the property address out loud. From your work order or a quick look at the roof, state the roof system type (for example gravel-surfaced built-up roof, modified bitumen, or single-ply TPO), the approximate square footage, and the estimated age in years. Take one photo of the building front and one of the point where you accessed the roof.",
                "The property address and roof system type are stated out loud, and at least one photo of the building and one of the roof access point are captured.",
                ["This is a gravel-surfaced built-up roof", "Roof is about six thousand five hundred square feet", "Estimated eighteen years old", "Address is 333 South Tamiami Trail", "Accessed through the interior roof hatch"],
                120, min_marks=1,
            ),
            _g(
                "roof_access_overview", 2, "Roof Access & General Overview",
                "Once you're safely on the roof, give me a slow full pan of the whole roof and call out your first overall impression of its condition.",
                "Access & overview",
                "After reaching the roof safely, stand in one spot and slowly pan the camera 360 degrees so the whole roof is captured in one wide shot. Walk the perimeter first and note the general condition of the surfacing - is the gravel or granule surface intact or thin and worn. Say your overall first impression (good, fair, poor) and point out any obviously failed areas you can already see.",
                "One wide 360-degree pan of the roof is captured plus a spoken overall first impression (good / fair / poor), and any obviously failed areas are pointed out on camera.",
                ["Gravel surfacing is thin across most of the roof", "Overall this roof looks to be in poor condition", "I can already see ponding in the middle", "The surface looks fair near the edges", "No obvious failures from here"],
                180, min_marks=2,
            ),
            _g(
                "field_membrane_south", 3, "South Roof Field - Membrane & Surface",
                "Walk the south roof field slowly. Call out any ponding, blistering, or bald spots as you find them and hold the camera on each one.",
                "South field: membrane",
                "Start at the south edge and walk the whole field in overlapping passes so you cover every square foot. Look for standing water or dark water-staining (ponding), raised bubbles in the membrane (blistering), and areas worn down to the black felt where the surfacing is gone (bald spots), plus any splits or open seams. Press each suspect area firmly with your foot and say whether it feels solid or soft/spongy. Take a close-up of every defect with your hand or a tape in frame for scale, then one wide shot showing where it sits.",
                "At least two close-up photos of the worst defects plus one wide context shot, and for each defect a spoken statement of its type (ponding / blistering / bald / split) and whether the decking felt solid or soft - or an explicit spoken 'no defects found on the south field'.",
                ["There's ponding about ten feet in from the south parapet", "This whole area is blistered and worn to the felt", "I've got a membrane split running along this seam", "The decking feels soft and spongy right here", "Surfacing is bald but the decking feels solid", "No defects found on the south field"],
                210, min_marks=2,
            ),
            _g(
                "field_membrane_main", 4, "Main Roof Field - Membrane & Ponding",
                "Now cover the main central field the same way. I especially want every ponding area and any seam splits photographed and pressed underfoot.",
                "Main field: membrane",
                "Walk the central field in overlapping passes. Wherever you see standing water or a dark ponding ring, stop, photograph it wide and close, and estimate how large the area is in feet. Follow every seam and look for splits or open laps; photograph each split with scale. Press ponding and split areas with your foot and state whether the decking feels solid or soft. Note how much of the field is affected (a small spot vs most of the field).",
                "Every ponding area and seam split in the main field is photographed close-up and wide, the approximate size of the affected area is stated, and the technician confirms out loud whether the decking felt solid or soft.",
                ["Ponding covers most of the central field", "This seam has split wide open here", "The ponded area is roughly fifteen by twenty feet", "Decking is soft across this whole section", "Multiple splits along the laps", "Central field decking still feels solid"],
                240, min_marks=3,
            ),
            _g(
                "flashings_penetrations", 5, "Flashings, Penetrations & Curbs",
                "Check every flashing and penetration - base flashings, pitch pockets, and the HVAC curbs. Show me anything lifting, cracked, or open.",
                "Flashings & penetrations",
                "Go to each vertical transition and penetration: base flashings where the roof meets walls and curbs, pitch pockets around pipes, and the flashing around every rooftop HVAC unit. Look for flashing that is lifting, pulling away, cracked, or has open/unsealed laps, and for pitch pockets that are dried out or cracked. Photograph each defect close-up and say exactly which penetration or curb it is on. Gently tug lifting flashing to show whether it is loose.",
                "Each flashing/penetration defect is photographed close-up with a spoken note of exactly which curb or penetration it is on, and the technician states whether lifting flashing is loose - or explicitly confirms flashings are sound.",
                ["Base flashing at the HVAC curb is lifting and loose", "This pitch pocket is dried out and cracked", "Flashing lap is open on the north curb", "Sealant has failed around this pipe", "All flashings here look sound and sealed"],
                210, min_marks=2,
            ),
            _g(
                "drainage_system", 6, "Drainage: Drains, Scuppers & Gutters",
                "Check every drain, scupper, and gutter. Tell me if water can actually get off this roof or if the drains are blocked.",
                "Drainage",
                "Locate each roof drain, scupper, and gutter. At each one, clear away loose gravel by hand if safe and look down the drain: is it open and flowing or packed with gravel and debris. Photograph each drain and the area around it, note any ponding that has formed because water cannot reach the drain, and check scuppers and gutters for rust, blockage, or separation. Say for each whether it is clear or blocked.",
                "Every drain and scupper is photographed and the technician states for each whether it is clear or blocked, and any ponding caused by a blocked drain is called out on camera.",
                ["This interior drain is partially blocked with gravel", "Water is ponding because it can't reach the drain", "The scupper is rusted through", "This drain is clear and flowing", "Gutter has pulled away from the edge"],
                180, min_marks=2,
            ),
            _g(
                "edge_metal_parapet", 7, "Edge Metal, Gravel Stop & Parapet Coping",
                "Walk the whole perimeter. Check the gravel stop, edge metal, and parapet coping for anything loose, lifted, or with open joints.",
                "Edge metal & coping",
                "Walk the entire roof edge (stay back from the edge and keep your footing). Inspect the gravel stop and edge metal for sections that are loose, lifted, or corroded, and check parapet coping caps for open joints, missing sealant, or gaps where water can get behind them. Push lightly on suspect edge metal to show if it is loose. Photograph each defect and say which side of the building (north/south/east/west) it is on.",
                "Loose or lifted edge metal and open coping joints are photographed with a spoken note of which building side they are on, and the technician confirms whether edge metal is loose - or states the perimeter is sound.",
                ["Gravel stop is loose along the west edge", "Coping joints are open on the north parapet", "Edge metal has lifted here and water can get behind it", "Sealant is missing at this coping joint", "The east edge metal is secure"],
                180, min_marks=2,
            ),
            _g(
                "interior_leak_evidence", 8, "Interior Leak Evidence & Ceiling Staining",
                "Go inside under the areas that looked worst and check the ceiling for active leaks or staining. Match any stains to the roof area above.",
                "Interior leak evidence",
                "Go into the interior spaces below the roof areas that showed ponding or splits. Look up at the ceiling tiles, deck, and any exposed structure for water stains, active dripping, sagging tiles, or mold. For each stain, photograph it and say which roof area is directly above it (for example 'this is under the south field'). Touch a stained tile if safe and say whether it is dry or still damp.",
                "Any interior water staining is photographed with a spoken note of which roof area is directly above it and whether it is dry or still damp - or the technician explicitly states no interior leak evidence was found.",
                ["Active water staining on the ceiling tiles under the south field", "This tile is sagging and still damp", "The stain lines up with the ponding above", "No interior leak evidence in this area", "There's mold starting on this ceiling tile"],
                180, min_marks=1,
            ),
            _g(
                "summary_recommendations", 9, "Summary & Recommendations",
                "Wrap up with your overall verdict. Say clearly whether this roof needs targeted repairs or full replacement, and why.",
                "Summary & recommendations",
                "Give a plain-language overall assessment of the roof's condition and its remaining service life. State your single clear recommendation - targeted repairs versus full replacement - and the main reasons (for example widespread ponding, soft decking, and active interior leaks point to replacement). List the highest-priority items a building owner should act on first. Do not introduce any problem you did not actually observe earlier.",
                "A spoken overall verdict is recorded with a clear repair-versus-replace recommendation and its main reasons, plus a prioritized list of the top items to address.",
                ["Overall this roof is at the end of its service life", "I'm recommending full replacement, not spot repairs", "The widespread ponding and soft decking drive that call", "Active interior leaks confirm the membrane has failed", "First priority is protecting the interior from further water"],
                180, min_marks=1,
            ),
        ],
    },
    "content_structure": {
        "summary_page_title": "Executive Summary",
        "organization": "section_order",
        "sections": [
            _c(
                "site_job_details", "Site & Job Details",
                "The property and roof system details were not recorded during this inspection.",
                ["property_address", "roof_system_type", "approx_square_footage", "estimated_age", "severity"],
                "State the property address and full roof-system description (type, approximate square footage, estimated age) from the capture. Keep this section factual and do not assess condition here; reserve findings for the field sections. Assign an informational severity.",
                min_words=45, max_images=3,
            ),
            _c(
                "roof_access_overview", "Roof Access & General Overview",
                "The overall roof condition was not assessed during this inspection.",
                ["access_method", "overall_condition", "surfacing_condition", "severity", "recommendation"],
                "Summarize the overall roof condition from the technician's 360 overview using their own words (good/fair/poor) and describe the state of the gravel or granule surfacing. Assign a JobDoc severity to the overall condition. Frame this as the high-level picture; specific defects belong in the field sections. If the overview shows widespread failure, note that the detailed sections support a replacement discussion.",
                min_words=55, max_images=4,
            ),
            _c(
                "field_membrane_south", "South Roof Field - Membrane & Surface",
                "The south roof field membrane and surface were not accessible or were not assessed during this inspection.",
                ["location", "observed_conditions", "decking_condition", "severity", "recommendation"],
                "Describe the south field using the technician's specific locations (e.g. 'about 10 ft in from the south parapet'). Name every defect observed (ponding, blistering, bald/worn surfacing, membrane split, open seam) and tie each to what was felt underfoot. Assign a JobDoc severity. If soft/spongy decking, widespread ponding, or splits were reported, state clearly that replacement of the affected area is recommended; if defects are isolated and cosmetic over solid decking, recommend targeted maintenance instead. Do not generalize to other areas.",
                min_words=65, max_images=6,
            ),
            _c(
                "field_membrane_main", "Main Roof Field - Membrane & Ponding",
                "The main roof field was not accessible or was not assessed during this inspection.",
                ["location", "ponding_extent", "seam_condition", "decking_condition", "severity", "recommendation"],
                "Describe the main field ponding and seam condition using the technician's stated locations and approximate sizes. State how much of the field is affected. Name each defect (ponding, seam split, open lap) and tie it to the decking feel. Assign a JobDoc severity. Widespread ponding, soft decking, or multiple splits must be stated as evidence that full-area replacement is recommended; isolated issues over solid decking warrant targeted repair. Never soften a safety_critical condition.",
                min_words=65, max_images=6,
            ),
            _c(
                "flashings_penetrations", "Flashings, Penetrations & Curbs",
                "Flashings, penetrations, and curbs were not accessible or were not assessed during this inspection.",
                ["location", "flashing_condition", "penetration_condition", "severity", "recommendation"],
                "For each flashing, pitch pocket, and HVAC curb the technician inspected, describe the condition at its specific location (which curb/penetration). Name each defect (lifting/loose base flashing, cracked pitch pocket, open lap, failed sealant). Assign a JobDoc severity. Recommend re-flashing or resealing for isolated defects; where flashing failure is widespread or contributing to interior leaks, tie it into the replacement recommendation. Do not invent penetrations that were not inspected.",
                min_words=60, max_images=5,
            ),
            _c(
                "drainage_system", "Drainage: Drains, Scuppers & Gutters",
                "The roof drainage system was not accessible or was not assessed during this inspection.",
                ["drain_condition", "scupper_condition", "gutter_condition", "ponding_relationship", "severity", "recommendation"],
                "For each drain, scupper, and gutter, state whether it was clear or blocked at its location. Explicitly connect any blocked drainage to the ponding observed in the fields (blocked drains that cause standing water). Assign a JobDoc severity. Recommend cleaning/clearing for simple blockages and repair/replacement for rusted-through or separated components. Reference the technician's specific locations; do not generalize.",
                min_words=60, max_images=4,
            ),
            _c(
                "edge_metal_parapet", "Edge Metal, Gravel Stop & Parapet Coping",
                "Edge metal, gravel stop, and parapet coping were not accessible or were not assessed during this inspection.",
                ["location", "edge_metal_condition", "coping_condition", "severity", "recommendation"],
                "Describe the perimeter edge metal, gravel stop, and coping using the building side (north/south/east/west) the technician stated. Name each defect (loose/lifted edge metal, open coping joint, missing sealant, corrosion) and note where water can get behind the system. Assign a JobDoc severity. Recommend refastening/resealing for isolated edge defects; widespread edge failure supports the replacement recommendation. Do not soften a finding where water intrusion is likely.",
                min_words=55, max_images=4,
            ),
            _c(
                "interior_leak_evidence", "Interior Leak Evidence & Ceiling Staining",
                "The interior was not accessed and no interior leak evidence was assessed during this inspection.",
                ["location", "staining_description", "active_or_dry", "roof_area_above", "severity", "recommendation"],
                "Describe any interior water staining using the technician's location and, critically, the roof area directly above it (e.g. 'under the south field'). State whether each stain was dry or still damp. Assign a JobDoc severity - active/damp staining tied to a failed field is major or safety_critical. Make clear that confirmed active leaks strongly support full replacement and immediate interior protection. If no evidence was found, state that plainly.",
                min_words=55, max_images=4,
            ),
            _c(
                "summary_recommendations", "Summary & Recommendations",
                "No overall summary or recommendation was recorded for this inspection.",
                ["overall_condition", "remaining_service_life", "primary_recommendation", "prioritized_actions", "severity"],
                "Provide a concise overall assessment of roof condition and remaining service life, then give ONE clear primary recommendation: targeted repair or full replacement, with the specific findings that drive it (e.g. widespread ponding, soft decking, active interior leaks). Provide a prioritized action list for the owner. Assign the highest severity observed. Do not introduce any issue that was not captured in the sections above.",
                min_words=65, show_photo=False,
            ),
        ],
    },
}


if __name__ == "__main__":
    raise SystemExit(main())
