"""Best-effort repair of raw LLM output before strict validation.

Frontier models occasionally return values that are *almost* right — an
``max_images`` of 0, a ``capture_order`` with a gap, a stray unknown
``document_class``, an empty ``suggested_phrases`` list, etc. Rejecting the
whole template for these small, mechanically-fixable issues is a poor user
experience.

:func:`normalize_template` deep-copies the payload and coerces these values into
the valid ranges/shapes defined by the schema. It never invents section
structure and never masks genuinely broken output (missing sections, broken
mirroring, empty required text) — those still fail strict validation with clear
messages. Normalization runs *before* validation; validation remains the final,
authoritative gate.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .schema import (
    DEFAULT_SEVERITY_BANDS,
    DEFAULT_SEVERITY_COLORS,
    SEVERITY_LEVELS,
)

__all__ = ["normalize_template", "apply_image_hints"]

_STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "for", "to", "in", "on", "at", "with",
    "amp", "section", "report", "inspection", "general", "details", "detail",
    "overview", "condition", "conditions", "summary", "recommendation",
    "recommendations", "job", "site", "system", "area", "field",
}

_DOCUMENT_CLASSES = {
    "inspection_report",
    "estimate",
    "invoice",
    "compliance",
    "work_order",
    "custom",
}

# Map legacy / synonymous severity vocabulary onto the JobDoc gold standard.
_SEVERITY_SYNONYMS = {
    "info": "informational",
    "information": "informational",
    "informational": "informational",
    "note": "informational",
    "low": "minor",
    "minor": "minor",
    "trivial": "minor",
    "cosmetic": "minor",
    "medium": "moderate",
    "med": "moderate",
    "moderate": "moderate",
    "elevated": "moderate",
    "high": "major",
    "major": "major",
    "serious": "major",
    "critical": "safety_critical",
    "severe": "safety_critical",
    "urgent": "safety_critical",
    "safety": "safety_critical",
    "safety_critical": "safety_critical",
    "safetycritical": "safety_critical",
}


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _slug(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    s = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not s:
        return default
    if not s[0].isalpha():
        s = "x_" + s
    return s


def normalize_template(data: dict[str, Any]) -> dict[str, Any]:
    """Return a repaired copy of ``data`` with values coerced into valid ranges."""
    if not isinstance(data, dict):
        return data

    data = copy.deepcopy(data)
    data.setdefault("schema_version", 3)

    # document_class: fall back to "custom" for anything unrecognized.
    dc = data.get("document_class")
    if not isinstance(dc, str) or dc not in _DOCUMENT_CLASSES:
        data["document_class"] = "custom"

    # report_type: coerce to a snake_case slug.
    data["report_type"] = _slug(data.get("report_type"), "generated_report")

    _normalize_severity(data.get("pdf_styling"))
    _normalize_guidance(data.get("guidance"))
    _normalize_content(data.get("content_structure"))

    return data


def _canonical_severity(key: Any) -> str | None:
    if not isinstance(key, str):
        return None
    normalized = re.sub(r"[^a-z]", "", key.strip().lower())
    return _SEVERITY_SYNONYMS.get(normalized) or _SEVERITY_SYNONYMS.get(
        key.strip().lower()
    )


def _remap_severity_map(
    provided: Any, defaults: dict[str, str]
) -> dict[str, str]:
    """Rebuild a severity map using ONLY the gold-standard keys.

    Values supplied under legacy keys (critical/high/medium/low/info) are carried
    over onto their gold-standard equivalents; missing levels fall back to the
    default; unknown keys are dropped.
    """
    result: dict[str, str] = {}
    if isinstance(provided, dict):
        for raw_key, value in provided.items():
            canonical = _canonical_severity(raw_key)
            if canonical and canonical not in result and isinstance(value, str) and value.strip():
                result[canonical] = value.strip()
    for level in SEVERITY_LEVELS:
        result.setdefault(level, defaults[level])
    # Return in canonical order.
    return {level: result[level] for level in SEVERITY_LEVELS}


def _tokens(text: Any) -> set[str]:
    if not isinstance(text, str):
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _best_content_match(
    heading_tokens: set[str], content_sections: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find the content section whose title best matches a source heading."""
    if not heading_tokens:
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    for sec in content_sections:
        if not isinstance(sec, dict):
            continue
        sec_tokens = _tokens(sec.get("title")) | _tokens(sec.get("section_id"))
        if not sec_tokens:
            continue
        overlap = heading_tokens & sec_tokens
        if not overlap:
            continue
        # Score by overlap relative to the (smaller) heading token set.
        score = len(overlap) / max(1, len(heading_tokens))
        if score > best_score:
            best_score = score
            best = sec
    # Require at least one meaningful shared token.
    return best if best_score > 0 else None


def apply_image_hints(data: dict[str, Any], image_hints: dict[str, Any] | None) -> dict[str, Any]:
    """Deterministically force photo settings where the source had images.

    For every source heading that had embedded images, the best-matching
    content_structure section is set to ``show_photo=true`` with a required
    image_placement and a ``max_images`` at least as large as the detected count
    (capped). This runs on top of the LLM's judgement so image presence is never
    missed. Returns the same dict (mutated).
    """
    if not isinstance(data, dict) or not image_hints:
        return data
    headings = image_hints.get("headings") or []
    if not headings:
        return data

    content = data.get("content_structure")
    if not isinstance(content, dict):
        return data
    sections = content.get("sections")
    if not isinstance(sections, list):
        return data

    for heading in headings:
        if not isinstance(heading, dict):
            continue
        count = _clamp_int(heading.get("images"), 1, 10, 1)
        match = _best_content_match(_tokens(heading.get("title")), sections)
        if match is None:
            continue
        match["show_photo"] = True
        ip = match.get("image_placement")
        if not isinstance(ip, dict):
            ip = {}
            match["image_placement"] = ip
        ip["required"] = True
        ip.setdefault("position", "after_summary")
        ip.setdefault("caption_style", "narration_excerpt_with_timestamp")
        existing = ip.get("max_images")
        existing = existing if isinstance(existing, int) else 0
        ip["max_images"] = _clamp_int(max(existing, count), 1, 10, 3)
    return data


def _normalize_severity(styling: Any) -> None:
    if not isinstance(styling, dict):
        return
    if "severity_colors" in styling:
        styling["severity_colors"] = _remap_severity_map(
            styling.get("severity_colors"), DEFAULT_SEVERITY_COLORS
        )
    if "severity_bands" in styling:
        styling["severity_bands"] = _remap_severity_map(
            styling.get("severity_bands"), DEFAULT_SEVERITY_BANDS
        )


def _normalize_guidance(guidance: Any) -> None:
    if not isinstance(guidance, dict):
        return

    guidance["estimated_total_minutes"] = _clamp_int(
        guidance.get("estimated_total_minutes"), 1, 100_000, 20
    )

    sections = guidance.get("sections")
    if not isinstance(sections, list):
        return

    # Renumber capture_order into a complete sequential 1..N sequence, preserving
    # the model's intended ordering (by given capture_order, ties broken by index).
    def _order_key(item: tuple[int, Any]) -> tuple[int, int]:
        idx, sec = item
        co = idx + 1
        if isinstance(sec, dict):
            try:
                co = int(sec.get("capture_order"))
            except (TypeError, ValueError):
                co = idx + 1
        return (co, idx)

    ordered = sorted(enumerate(sections), key=_order_key)
    for new_order, (_, sec) in enumerate(ordered, start=1):
        if not isinstance(sec, dict):
            continue
        sec["capture_order"] = new_order
        sec["estimated_seconds"] = _clamp_int(sec.get("estimated_seconds"), 1, 86_400, 90)
        sec["min_marks"] = _clamp_int(sec.get("min_marks"), 0, 999, 1)

        # Clean blank/duplicate phrases but do NOT invent them: weak phrase sets
        # should be rejected by validation, not masked with generic filler.
        phrases = sec.get("suggested_phrases")
        if isinstance(phrases, list):
            seen: set[str] = set()
            cleaned: list[str] = []
            for p in phrases:
                if isinstance(p, str) and p.strip() and p.strip() not in seen:
                    seen.add(p.strip())
                    cleaned.append(p.strip())
            sec["suggested_phrases"] = cleaned


def _normalize_content(content: Any) -> None:
    if not isinstance(content, dict):
        return

    sections = content.get("sections")
    if not isinstance(sections, list):
        return

    for sec in sections:
        if not isinstance(sec, dict):
            continue
        # min_summary_words: keep realistic; floor at 45 (schema/quality range 45-70).
        sec["min_summary_words"] = _clamp_int(sec.get("min_summary_words"), 45, 200, 55)

        ip = sec.get("image_placement")
        if isinstance(ip, dict):
            # The reported failure: max_images must be >= 1 (0 -> 1).
            ip["max_images"] = _clamp_int(ip.get("max_images"), 1, 50, 3)
