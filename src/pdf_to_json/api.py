"""FastAPI service exposing the translation pipeline.

Endpoints:
    GET  /           -> service info + links
    GET  /health     -> liveness/readiness probe (+ config diagnostics)
    GET  /schema     -> the JSON Schema of the ReportTemplate output contract
    POST /translate  -> multipart PDF upload, returns the validated JSON template

Run locally:
    uvicorn pdf_to_json.api:app --reload

Run in production (Render / Docker / Railway / Fly.io):
    uvicorn pdf_to_json.api:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .generator import configured_api_key
from .pipeline import PipelineError, TranslationPipeline
from .schema import ReportTemplate

_STATIC_DIR = Path(__file__).parent / "static"


def _load_index_html() -> str | None:
    index = _STATIC_DIR / "index.html"
    try:
        return index.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - only if packaging missed the asset
        return None

logging.basicConfig(
    level=os.getenv("PDF_TO_JSON_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pdf_to_json.api")


def _max_upload_bytes() -> int:
    try:
        mb = int(os.getenv("PDF_TO_JSON_MAX_UPLOAD_MB", "25"))
    except ValueError:
        mb = 25
    return max(1, mb) * 1024 * 1024


def _cors_origins() -> list[str]:
    """Comma-separated allowed origins, or '*' (default) for all."""
    raw = os.getenv("PDF_TO_JSON_CORS_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def _lifespan(app: FastAPI):  # pragma: no cover - side-effect only
    configured = bool(configured_api_key())
    model = os.getenv("PDF_TO_JSON_MODEL", "gpt-4o")
    logger.info(
        "pdf_to_json api v%s starting (llm_configured=%s, model=%s, cors=%s)",
        __version__,
        configured,
        model,
        _origins,
    )
    if not configured:
        logger.warning(
            "OPENAI_API_KEY is not set. /translate will fail with 422 until a "
            "key is configured in the environment."
        )
    yield


app = FastAPI(
    title="PDF -> JSON Template Translator",
    description=(
        "Translate real-world trades PDFs into valid GenerSwift ReportTemplate "
        "JSON (schema_version 3)."
    ),
    version=__version__,
    lifespan=_lifespan,
)

_origins = _cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Credentials cannot be combined with the "*" wildcard per the CORS spec.
    allow_credentials=_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_INDEX_HTML = _load_index_html()


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    """Serve the browser UI (falls back to JSON info if the asset is missing)."""
    if _INDEX_HTML is not None:
        return HTMLResponse(content=_INDEX_HTML)
    return HTMLResponse(
        content=(
            "<h1>PDF -> JSON Template Translator</h1>"
            "<p>UI asset not found. See <a href='/docs'>/docs</a> and "
            "<a href='/info'>/info</a>.</p>"
        ),
        status_code=200,
    )


@app.get("/info")
def info() -> dict[str, object]:
    """Machine-readable service info + endpoint map."""
    return {
        "service": "PDF -> JSON Template Translator",
        "version": __version__,
        "schema_version": 3,
        "endpoints": {
            "ui": "GET /",
            "health": "GET /health",
            "schema": "GET /schema",
            "translate": "POST /translate (multipart form field 'file')",
            "docs": "GET /docs",
        },
    }


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness/readiness probe with lightweight config diagnostics."""
    return {
        "status": "ok",
        "version": __version__,
        "schema_version": 3,
        "llm_configured": bool(configured_api_key()),
        "model": os.getenv("PDF_TO_JSON_MODEL", "gpt-4o"),
    }


@app.get("/schema")
def schema() -> dict[str, object]:
    """Return the JSON Schema of the ReportTemplate output contract."""
    return ReportTemplate.model_json_schema()


@app.post("/translate")
async def translate(file: UploadFile = File(...)) -> JSONResponse:
    """Accept a multipart PDF upload and return the validated JSON template."""
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are accepted.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    max_bytes = _max_upload_bytes()
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (>{max_bytes // (1024 * 1024)} MB).",
        )

    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / Path(filename).name
        tmp_path.write_bytes(contents)

        pipeline = TranslationPipeline()
        try:
            result = pipeline.run(tmp_path)
        except PipelineError as exc:
            # 422: the request was fine but we couldn't produce a valid template.
            logger.info("translate failed for %s: %s", filename, exc)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive catch-all
            logger.exception("Unexpected error translating %s", filename)
            raise HTTPException(
                status_code=500, detail=f"Unexpected error: {exc}"
            ) from exc

    elapsed = time.perf_counter() - started
    logger.info(
        "translated %s -> %s (%d sections) in %.1fs",
        filename,
        result.template.report_type,
        len(result.template.guidance.sections),
        elapsed,
    )
    return JSONResponse(content=result.template.model_dump(mode="json"))


@app.exception_handler(Exception)
async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:  # pragma: no cover - defensive
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error."},
    )
