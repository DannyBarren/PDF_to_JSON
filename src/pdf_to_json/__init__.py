"""PDF -> JSON Template Translator.

Turns a real-world trades PDF (inspection report, estimate, invoice, compliance
checklist, work order, ...) into a valid GenerSwift ReportTemplate JSON
(schema_version 3) that can be dropped straight into the main JobDoc app.
"""

from __future__ import annotations

from .schema import (
    SCHEMA_VERSION,
    ContentSection,
    ContentStructure,
    Guidance,
    GuidanceSection,
    ImagePlacement,
    LayoutHints,
    PdfStyling,
    ReportTemplate,
)
from .normalize import normalize_template
from .validator import (
    TemplateValidationError,
    quality_warnings,
    validate_template,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "ReportTemplate",
    "Guidance",
    "GuidanceSection",
    "ContentStructure",
    "ContentSection",
    "PdfStyling",
    "ImagePlacement",
    "LayoutHints",
    "validate_template",
    "quality_warnings",
    "TemplateValidationError",
    "normalize_template",
]
