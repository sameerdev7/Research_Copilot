"""Download a paper's PDF and extract plain text from it."""

from __future__ import annotations

import io

import requests
from pypdf import PdfReader

REQUEST_TIMEOUT = 30


def download_pdf(pdf_url: str) -> bytes:
    response = requests.get(pdf_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content


def extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(pages).strip()
    # Garbled PDF text extraction can yield NUL bytes, which PostgreSQL text columns
    # reject outright (psycopg.DataError), so strip them before this text is stored.
    return text.replace("\x00", "")
