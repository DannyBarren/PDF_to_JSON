"""PDF -> clean intermediate content.

The extractor turns a PDF into a hierarchical, LLM-friendly Markdown document
plus lightweight metadata. It prefers ``pymupdf`` (fast, layout-aware, good
heading detection via font sizes) and falls back to ``pdfplumber`` when needed.

The goal is *not* perfect fidelity — it is to give the generation stage clean,
well-structured text with obvious headings so it can reason about section
structure. No OCR / computer vision is required for the MVP.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["ExtractedDocument", "extract_pdf", "ExtractionError"]


class ExtractionError(Exception):
    """Raised when a PDF cannot be read or contains no extractable text."""


@dataclass
class ExtractedDocument:
    """Clean intermediate representation of a PDF."""

    source_path: str
    page_count: int
    markdown: str
    raw_text: str
    detected_headings: list[str] = field(default_factory=list)
    engine: str = "unknown"
    is_probably_scanned: bool = False
    # Image-presence metadata (drives show_photo / image_placement downstream).
    image_count: int = 0
    pages_with_images: list[int] = field(default_factory=list)
    # [{"title": <heading>, "page": <int>, "images": <int>}] for headings that
    # have embedded images associated with them (by nearest preceding heading).
    heading_images: list[dict[str, Any]] = field(default_factory=list)
    # Images that could not be tied to any heading.
    unassociated_images: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "page_count": self.page_count,
            "engine": self.engine,
            "is_probably_scanned": self.is_probably_scanned,
            "detected_headings": self.detected_headings,
            "image_count": self.image_count,
            "pages_with_images": self.pages_with_images,
            "heading_images": self.heading_images,
            "unassociated_images": self.unassociated_images,
            "markdown": self.markdown,
        }

    @property
    def char_count(self) -> int:
        return len(self.raw_text)

    @property
    def image_hints(self) -> dict[str, Any]:
        """Structured image-presence summary for the generation stage."""
        return {
            "total_images": self.image_count,
            "pages_with_images": self.pages_with_images,
            "headings": self.heading_images,
            "unassociated_images": self.unassociated_images,
        }


def extract_pdf(path: str | Path) -> ExtractedDocument:
    """Extract clean intermediate content from a PDF file.

    Tries PyMuPDF first (best structure), then pdfplumber. Raises
    :class:`ExtractionError` if the file is unreadable or effectively empty.
    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise ExtractionError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ExtractionError(f"Not a .pdf file: {pdf_path}")

    errors: list[str] = []

    try:
        doc = _extract_with_pymupdf(pdf_path)
        if doc.char_count >= 20:
            return doc
        errors.append("pymupdf produced almost no text")
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"pymupdf failed: {exc}")

    try:
        doc = _extract_with_pdfplumber(pdf_path)
        if doc.char_count >= 20:
            return doc
        errors.append("pdfplumber produced almost no text")
        # Return the (nearly empty) doc but flag it as probably scanned so the
        # caller can decide. We still raise if truly empty.
        if doc.char_count > 0:
            doc.is_probably_scanned = True
            return doc
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"pdfplumber failed: {exc}")

    raise ExtractionError(
        "Could not extract usable text from the PDF. This may be a scanned "
        "document that requires OCR (not supported in this MVP). Details: "
        + "; ".join(errors)
    )


# --------------------------------------------------------------------------- #
# PyMuPDF engine (preferred)
# --------------------------------------------------------------------------- #
def _extract_with_pymupdf(pdf_path: Path) -> ExtractedDocument:
    import fitz  # type: ignore  # PyMuPDF

    # (text, font_size, page(1-based), y0)
    lines_with_pos: list[tuple[str, float, int, float]] = []
    # (page(1-based), y0) for each embedded image / drawing xobject
    image_positions: list[tuple[int, float]] = []
    raw_parts: list[str] = []

    with fitz.open(pdf_path) as doc:  # type: ignore[attr-defined]
        page_count = doc.page_count
        for page_index in range(page_count):
            page = doc.load_page(page_index)
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                btype = block.get("type", 0)
                if btype == 1:  # image block
                    bbox = block.get("bbox", [0, 0, 0, 0])
                    image_positions.append((page_index + 1, float(bbox[1])))
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    text = "".join(span.get("text", "") for span in spans).strip()
                    if not text:
                        continue
                    max_size = max(float(span.get("size", 0.0)) for span in spans)
                    y0 = float(line.get("bbox", [0, 0, 0, 0])[1])
                    lines_with_pos.append((text, max_size, page_index + 1, y0))
                    raw_parts.append(text)

            # Fallback: some PDFs expose images only via get_images(), not as
            # image blocks. Count any not already seen positionally.
            try:
                img_list = page.get_images(full=True)
            except Exception:  # pragma: no cover - defensive
                img_list = []
            block_images_on_page = sum(1 for p, _ in image_positions if p == page_index + 1)
            extra = len(img_list) - block_images_on_page
            for _ in range(max(0, extra)):
                # Unknown y position; place at top so it associates with the
                # first heading on the page.
                image_positions.append((page_index + 1, 0.0))

    raw_text = "\n".join(raw_parts)
    markdown, headings, heading_positions = _lines_to_markdown(
        lines_with_pos, page_count
    )
    heading_images, unassociated = _associate_images(heading_positions, image_positions)
    pages_with_images = sorted({p for p, _ in image_positions})

    return ExtractedDocument(
        source_path=str(pdf_path),
        page_count=page_count,
        markdown=markdown,
        raw_text=raw_text,
        detected_headings=headings,
        engine="pymupdf",
        is_probably_scanned=len(raw_text.strip()) < 20,
        image_count=len(image_positions),
        pages_with_images=pages_with_images,
        heading_images=heading_images,
        unassociated_images=unassociated,
    )


def _lines_to_markdown(
    lines_with_pos: list[tuple[str, float, int, float]], page_count: int
) -> tuple[str, list[str], list[tuple[str, int, float]]]:
    """Convert (text, font_size, page, y0) tuples into Markdown with headings.

    Returns (markdown, heading_texts, heading_positions) where heading_positions
    is [(title, page, y0), ...] used to associate images with headings.
    """
    if not lines_with_pos:
        return "", [], []

    sizes = [size for _, size, _, _ in lines_with_pos if size > 0]
    if not sizes:
        body = "\n".join(text for text, _, _, _ in lines_with_pos)
        return body, [], []

    body_size = statistics.median(sizes)
    # A line is a heading if noticeably larger than body text and short-ish.
    heading_threshold = body_size * 1.15

    out_lines: list[str] = []
    headings: list[str] = []
    heading_positions: list[tuple[str, int, float]] = []
    current_page = 0

    for text, size, page, y0 in lines_with_pos:
        if page != current_page:
            current_page = page
            if page > 1:
                out_lines.append("")
                out_lines.append(f"<!-- page {page} -->")
        is_heading = (
            size >= heading_threshold
            and len(text) <= 90
            and not text.endswith((".", ",", ";"))
        )
        if is_heading:
            # Two heading levels based on how large the text is.
            level = "#" if size >= body_size * 1.5 else "##"
            out_lines.append("")
            out_lines.append(f"{level} {text}")
            headings.append(text)
            heading_positions.append((text, page, y0))
        else:
            out_lines.append(text)

    markdown = "\n".join(out_lines).strip()
    return markdown, headings, heading_positions


def _associate_images(
    heading_positions: list[tuple[str, int, float]],
    image_positions: list[tuple[int, float]],
) -> tuple[list[dict[str, Any]], int]:
    """Attach each image to the nearest preceding heading (in reading order).

    Returns (heading_images, unassociated_count) where heading_images is
    [{"title", "page", "images"}] for headings that gained >= 1 image.
    """
    if not image_positions:
        return [], 0

    # Sort headings by (page, y) so "preceding" means earlier in reading order.
    ordered = sorted(
        enumerate(heading_positions), key=lambda h: (h[1][1], h[1][2])
    )
    counts: dict[int, int] = {}
    unassociated = 0

    for img_page, img_y in image_positions:
        best_idx: int | None = None
        best_key: tuple[int, float] | None = None
        for orig_idx, (_title, h_page, h_y) in ordered:
            key = (h_page, h_y)
            if key <= (img_page, img_y):
                if best_key is None or key > best_key:
                    best_key = key
                    best_idx = orig_idx
            else:
                break
        if best_idx is None:
            unassociated += 1
        else:
            counts[best_idx] = counts.get(best_idx, 0) + 1

    heading_images: list[dict[str, Any]] = []
    for idx, count in sorted(counts.items(), key=lambda kv: kv[0]):
        title, page, _y = heading_positions[idx]
        heading_images.append({"title": title, "page": page, "images": count})
    return heading_images, unassociated


# --------------------------------------------------------------------------- #
# pdfplumber engine (fallback)
# --------------------------------------------------------------------------- #
def _extract_with_pdfplumber(pdf_path: Path) -> ExtractedDocument:
    import pdfplumber  # type: ignore

    raw_parts: list[str] = []
    md_parts: list[str] = []
    image_count = 0
    pages_with_images: list[int] = []

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            raw_parts.append(text)
            if page_index > 0:
                md_parts.append(f"\n<!-- page {page_index + 1} -->")
            md_parts.append(text)
            page_images = list(getattr(page, "images", []) or [])
            if page_images:
                image_count += len(page_images)
                pages_with_images.append(page_index + 1)

    raw_text = "\n".join(raw_parts)
    markdown = "\n".join(md_parts).strip()

    return ExtractedDocument(
        source_path=str(pdf_path),
        page_count=page_count,
        markdown=markdown,
        raw_text=raw_text,
        detected_headings=[],
        engine="pdfplumber",
        is_probably_scanned=len(raw_text.strip()) < 20,
        image_count=image_count,
        pages_with_images=pages_with_images,
    )
