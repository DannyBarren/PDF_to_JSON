"""Vercel Python serverless entry point.

Vercel's Python runtime auto-detects the ASGI ``app`` exported here. We add
``src/`` to the path so the ``pdf_to_json`` package resolves without an editable
install.

NOTE: Vercel serverless functions have a maximum execution duration (60s on the
Hobby plan). The LLM generation stage can approach or exceed this on large PDFs.
For reliable production use prefer Render / Docker (see README "Deployment").
Set the project's Root Directory to ``PDF_to_JSON`` in the Vercel dashboard.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pdf_to_json.api import app  # noqa: E402

__all__ = ["app"]
