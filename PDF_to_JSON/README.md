# PDF → JSON Template Translator

Turn a real-world trades PDF (inspection report, estimate, invoice, compliance
checklist, work order, …) into a **fully valid GenerSwift `ReportTemplate` JSON
(`schema_version: 3`)** that can be dropped straight into the main JobDoc app
with zero further editing required for basic use.

```
report.pdf  ──►  extract  ──►  LLM reasoning  ──►  strict validation  ──►  template.json
```

---

## What this tool does

Static PDFs are dead documents. GenerSwift JobDoc turns work into **guided,
voice-driven capture sessions** that a brand-new technician can follow, and then
has a writing agent author a professional report from what was captured.

This tool bridges the two: it reads the PDF a business already uses and designs
the matching `ReportTemplate`, including:

- **Metadata** — `document_class`, `report_type`, `title`, `template_description`.
- **`guidance`** — an intro/outro script plus ordered capture sections, each with
  a `voice_prompt`, `on_screen_text`, day-one `worker_instructions`, checkable
  `success_criteria`, natural `suggested_phrases`, `min_marks`, and
  `estimated_seconds`.
- **`content_structure`** — per-section `writer_instructions`, required `fields`,
  professional `default_text`, `min_summary_words`, `image_placement`, and
  `layout_hints` for the report-writing agent.
- **`pdf_styling`** — sensible defaults (colors, fonts, headers/footers,
  severity colors and bands).

## How it relates to GenerSwift JobDoc

**This system is completely isolated.** It has **zero** runtime dependency on the
`report_automation` / JobDoc codebase. The *only* contract between the two
systems is the gold-standard schema in
[`src/pdf_to_json/schema.py`](src/pdf_to_json/schema.py). If the output validates
against that schema, JobDoc can consume it.

## Architecture

| Stage | Module | Responsibility |
| ----- | ------ | -------------- |
| Extract | `extractor.py` | PDF → clean, hierarchical Markdown (+ page count, headings). Prefers PyMuPDF, falls back to pdfplumber. No OCR/CV required. |
| Generate | `generator.py` + `prompts.py` | Extracted content → template dict via a frontier LLM in JSON mode. Backend is injectable for testing. |
| Validate | `validator.py` + `schema.py` | Strict Pydantic v2 models + section-mirroring / quality checks with human-readable errors. |
| Orchestrate | `pipeline.py` | `extract → generate → validate`. **Never returns an invalid template.** |
| Interfaces | `cli.py`, `api.py` | Typer CLI and FastAPI service. |

---

## Installation

Requires **Python 3.11+**.

```bash
cd PDF_to_JSON

# (Recommended) create and activate a virtualenv, then:
pip install -e ".[dev]"
```

This installs the `pdf-to-json` CLI entry point. You can also run the tool with
`python -m pdf_to_json`.

## Configure your API key

The generation stage uses OpenAI by default.

```bash
cp .env.example .env
# then edit .env and set:
#   OPENAI_API_KEY=sk-...
#   PDF_TO_JSON_MODEL=gpt-4o      # any JSON-mode-capable model
```

The `.env` file is loaded automatically by the CLI and API. You can also just
`export OPENAI_API_KEY=...` in your shell.

---

## CLI usage

```bash
# Translate a PDF and write a pretty JSON template to a file
pdf-to-json translate path/to/report.pdf --output template.json

# Print the template to stdout (great for piping)
pdf-to-json translate path/to/report.pdf --pretty > template.json

# Inspect the intermediate extraction WITHOUT calling the LLM (no key needed)
pdf-to-json extract path/to/report.pdf

# Validate an existing template against the strict schema (no key needed)
pdf-to-json validate template.json
```

## API usage

Start the service:

```bash
uvicorn pdf_to_json.api:app --reload --port 8000
```

Endpoints:

- `GET /health` → `{"status": "ok", "version": "...", "schema_version": "3"}`
- `POST /translate` → multipart form upload (`file`), returns the validated JSON template.

Example:

```bash
curl -s -F "file=@path/to/report.pdf" http://localhost:8000/translate | jq .
```

Errors are reported clearly:
- `400` — not a PDF / empty upload
- `413` — file too large
- `422` — a template could not be produced or failed strict validation (the body
  contains the exact reasons)

---

## Try it in under 5 minutes (offline demo)

You do **not** need an API key to see a complete, valid example. This builds a
sample HVAC PDF and translates it with a built-in deterministic generator:

```bash
python scripts/run_example.py
# -> writes examples/sample_output.json (validated)
```

A committed example lives at
[`examples/sample_output.json`](examples/sample_output.json).

To run the **live** pipeline against your own PDF:

```bash
python scripts/run_example.py --live path/to/report.pdf
```

---

## Reviewing a generated template before using it in JobDoc

The output always passes strict validation, but you should still skim it:

1. **Sections** — do `guidance.sections` follow the logical flow of the source
   PDF? Section count is usually 6–12.
2. **`worker_instructions` / `success_criteria`** — could a brand-new technician
   complete each section using only these? They must be concrete and checkable.
3. **`writer_instructions` / `fields`** — are they specific enough for the writing
   agent to produce a high-quality section?
4. **`document_class` / `report_type`** — correctly inferred?
5. **`business_name` / `job_address`** — intentionally left blank unless clearly
   present in the source; fill in per-job in JobDoc.

Re-validate any edits at any time:

```bash
pdf-to-json validate template.json
```

---

## The output contract (schema_version 3)

Enforced by [`src/pdf_to_json/schema.py`](src/pdf_to_json/schema.py). Hard rules:

- Every `section_id` in `guidance.sections` exists in `content_structure.sections`
  and vice-versa (**perfect 1:1 mirroring**).
- `capture_order` is a **complete sequential** `1..N` sequence.
- All human-facing text fields are **non-empty**; `section_id` and `report_type`
  are snake_case; colors are valid hex.
- `worker_instructions`, `success_criteria`, and `writer_instructions` must be
  substantive (length-checked), and `min_summary_words` must be realistic.

See the full annotated shape in the schema module and a real example in
[`examples/sample_output.json`](examples/sample_output.json).

---

## Development & tests

The schema and validator tests run **without an API key** (the pipeline test uses
a fake LLM completer):

```bash
pytest            # 23 tests, all offline
```

Project layout:

```
PDF_to_JSON/
├── src/pdf_to_json/
│   ├── schema.py       # Gold-standard Pydantic models (schema_version 3)
│   ├── extractor.py    # PDF → clean intermediate content
│   ├── prompts.py      # System prompt + few-shot + prompt assembly
│   ├── generator.py    # Intermediate → template dict (LLM reasoning)
│   ├── validator.py    # Strict validation + mirroring/quality checks
│   ├── pipeline.py     # extract → generate → validate
│   ├── cli.py          # Typer CLI
│   └── api.py          # FastAPI app
├── tests/              # schema, validator, pipeline (offline)
├── examples/           # sample_output.json
└── scripts/run_example.py
```

## Design principles

- **Validation is mandatory.** The pipeline never returns an invalid template.
- **Isolated.** The schema is the only contract with JobDoc.
- **Explicit over clever.** Typed, readable, maintainable code.
- **No CV dependency** for the MVP — text extraction + LLM reasoning is enough.

## License

MIT
