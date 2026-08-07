"""Typer CLI for the PDF -> JSON Template Translator.

Examples:
    pdf-to-json translate report.pdf --output template.json
    pdf-to-json translate report.pdf --pretty
    pdf-to-json extract report.pdf          # inspect the intermediate content
    pdf-to-json validate template.json      # validate an existing template
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

try:  # Load .env if python-dotenv is available.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

from . import __version__
from .extractor import ExtractionError, extract_pdf
from .pipeline import PipelineError, TranslationPipeline
from .validator import TemplateValidationError, validate_template

app = typer.Typer(
    add_completion=False,
    help="Translate real-world trades PDFs into GenerSwift ReportTemplate JSON "
    "(schema_version 3).",
)


def _err(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)


def _ok(message: str) -> None:
    typer.secho(message, fg=typer.colors.GREEN, err=True)


@app.command()
def translate(
    pdf: Path = typer.Argument(..., exists=False, help="Path to the input PDF."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write the JSON template to this file."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", help="Pretty-print JSON to stdout (indent=2)."
    ),
) -> None:
    """Translate a PDF into a validated ReportTemplate JSON."""
    pipeline = TranslationPipeline()
    try:
        result = pipeline.run(pdf)
    except PipelineError as exc:
        _err(str(exc))
        raise typer.Exit(code=1)

    template_json = result.template.model_dump_json(indent=2 if (pretty or output) else None)

    if output:
        output.write_text(template_json, encoding="utf-8")
        _ok(f"Wrote validated template to {output}")
        _ok(
            f"  document_class={result.template.document_class} · "
            f"{len(result.template.guidance.sections)} sections · "
            f"~{result.template.guidance.estimated_total_minutes} min"
        )
    else:
        # Template JSON goes to stdout so it can be piped/redirected cleanly.
        typer.echo(template_json)


@app.command()
def extract(
    pdf: Path = typer.Argument(..., help="Path to the input PDF."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write extracted markdown to this file."
    ),
) -> None:
    """Extract and print the clean intermediate content from a PDF (no LLM)."""
    try:
        document = extract_pdf(pdf)
    except ExtractionError as exc:
        _err(str(exc))
        raise typer.Exit(code=1)

    _ok(
        f"engine={document.engine} · pages={document.page_count} · "
        f"chars={document.char_count} · headings={len(document.detected_headings)}"
    )
    if output:
        output.write_text(document.markdown, encoding="utf-8")
        _ok(f"Wrote extracted markdown to {output}")
    else:
        typer.echo(document.markdown)


@app.command()
def validate(
    template: Path = typer.Argument(..., help="Path to a JSON template to validate."),
) -> None:
    """Validate an existing ReportTemplate JSON file against the strict schema."""
    try:
        data = json.loads(template.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _err(f"Could not read/parse {template}: {exc}")
        raise typer.Exit(code=1)

    try:
        validated = validate_template(data)
    except TemplateValidationError as exc:
        _err(str(exc))
        raise typer.Exit(code=1)

    _ok(
        f"VALID · document_class={validated.document_class} · "
        f"{len(validated.guidance.sections)} sections"
    )


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


def main() -> None:  # pragma: no cover - console entry helper
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
