# syntax=docker/dockerfile:1
# Portable container image for the PDF -> JSON Template Translator API.
# Works on Render, Railway, Fly.io, Cloud Run, and any Docker host.
FROM python:3.12-slim AS base

# System deps: PyMuPDF / pdfplumber wheels are self-contained, but we keep a
# minimal toolchain available for safety on odd platforms.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

# Bind to the platform-provided $PORT (defaults to 8000 locally).
CMD ["sh", "-c", "uvicorn pdf_to_json.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
