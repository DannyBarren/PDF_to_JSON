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

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "page_count": self.page_count,
            "engine": self.engine,
            "is_probably_scanned": self.is_probably_scanned,
            "detected_headings": self.detected_headings,
            "markdown": self.markdown,
        }

    @property
    def char_count(self) -> int:
        return len(self.raw_text)


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

    lines_with_size: list[tuple[str, float, int]] = []
    raw_parts: list[str] = []

    with fitz.open(pdf_path) as doc:  # type: ignore[attr-defined]
        page_count = doc.page_count
        for page_index in range(page_count):
            page = doc.load_page(page_index)
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    text = "".join(span.get("text", "") for span in spans).strip()
                    if not text:
                        continue
                    max_size = max(float(span.get("size", 0.0)) for span in spans)
                    lines_with_size.append((text, max_size, page_index + 1))
                    raw_parts.append(text)

    raw_text = "\n".join(raw_parts)
    markdown, headings = _lines_to_markdown(lines_with_size, page_count)

    return ExtractedDocument(
        source_path=str(pdf_path),
        page_count=page_count,
        markdown=markdown,
        raw_text=raw_text,
        detected_headings=headings,
        engine="pymupdf",
        is_probably_scanned=len(raw_text.strip()) < 20,
    )


def _lines_to_markdown(
    lines_with_size: list[tuple[str, float, int]], page_count: int
) -> tuple[str, list[str]]:
    """Convert (text, font_size, page) tuples into Markdown with headings."""
    if not lines_with_size:
        return "", []

    sizes = [size for _, size, _ in lines_with_size if size > 0]
    if not sizes:
        body = "\n".join(text for text, _, _ in lines_with_size)
        return body, []

    body_size = statistics.median(sizes)
    # A line is a heading if noticeably larger than body text and short-ish.
    heading_threshold = body_size * 1.15

    out_lines: list[str] = []
    headings: list[str] = []
    current_page = 0

    for text, size, page in lines_with_size:
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
        else:
            out_lines.append(text)

    markdown = "\n".join(out_lines).strip()
    return markdown, headings


# --------------------------------------------------------------------------- #
# pdfplumber engine (fallback)
# --------------------------------------------------------------------------- #
def _extract_with_pdfplumber(pdf_path: Path) -> ExtractedDocument:
    import pdfplumber  # type: ignore

    raw_parts: list[str] = []
    md_parts: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            raw_parts.append(text)
            if page_index > 0:
                md_parts.append(f"\n<!-- page {page_index + 1} -->")
            md_parts.append(text)

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
    )
