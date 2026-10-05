from __future__ import annotations

import io

import requests
from pypdf import PdfReader

REQUEST_TIMEOUT = 30
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 300


class PdfTooLarge(ValueError):
    pass


def download_pdf(pdf_url: str) -> bytes:
    with requests.get(pdf_url, timeout=REQUEST_TIMEOUT, stream=True) as response:
        response.raise_for_status()
        # reject early when the server declares the size
        if int(response.headers.get("Content-Length") or 0) > MAX_PDF_BYTES:
            raise PdfTooLarge(f"PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB")
        data = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            data.extend(chunk)
            if len(data) > MAX_PDF_BYTES:
                raise PdfTooLarge(f"PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB")
        return bytes(data)


def extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise PdfTooLarge(f"PDF has more than {MAX_PDF_PAGES} pages")
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(pages).strip()
    # strip NUL bytes, which Postgres text columns reject
    return text.replace("\x00", "")
