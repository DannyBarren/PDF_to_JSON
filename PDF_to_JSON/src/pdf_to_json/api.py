"""FastAPI service exposing the translation pipeline.

Endpoints:
    GET  /health      -> liveness/readiness probe
    POST /translate   -> multipart PDF upload, returns the validated JSON template

Run locally:
    uvicorn pdf_to_json.api:app --reload
"""

from __future__ import annotations

import tempfile
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .pipeline import PipelineError, TranslationPipeline

app = FastAPI(
    title="PDF -> JSON Template Translator",
    description=(
        "Translate real-world trades PDFs into valid GenerSwift ReportTemplate "
        "JSON (schema_version 3)."
    ),
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_MAX_BYTES = 25 * 1024 * 1024  # 25 MB upload cap.


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness/readiness probe."""
    return {"status": "ok", "version": __version__, "schema_version": "3"}


@app.post("/translate")
async def translate(file: UploadFile = File(...)) -> JSONResponse:
    """Accept a multipart PDF upload and return the validated JSON template."""
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are accepted.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(contents) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (>{_MAX_BYTES // (1024 * 1024)} MB).",
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / filename
        tmp_path.write_bytes(contents)

        pipeline = TranslationPipeline()
        try:
            result = pipeline.run(tmp_path)
        except PipelineError as exc:
            # 422: the request was fine but we couldn't produce a valid template.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive catch-all
            raise HTTPException(
                status_code=500, detail=f"Unexpected error: {exc}"
            ) from exc

    return JSONResponse(content=result.template.model_dump(mode="json"))
