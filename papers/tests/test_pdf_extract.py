from pathlib import Path

import pytest

from papers.services import pdf_extract

FIXTURE = Path(__file__).parent / "fixtures" / "sample.pdf"


def test_extract_text_reads_pdf_content():
    text = pdf_extract.extract_text(FIXTURE.read_bytes())

    assert "Hello Research Copilot" in text


def test_extract_text_strips_nul_bytes(monkeypatch):
    # NUL bytes would crash the Postgres insert
    class FakePage:
        def extract_text(self):
            return "before\x00after"

    class FakeReader:
        def __init__(self, *args, **kwargs):
            self.pages = [FakePage()]

    monkeypatch.setattr(pdf_extract, "PdfReader", FakeReader)

    text = pdf_extract.extract_text(b"irrelevant")

    assert "\x00" not in text
    assert text == "beforeafter"


class FakeResponse:
    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield from self._chunks


def test_download_returns_the_bytes(monkeypatch):
    monkeypatch.setattr(pdf_extract.requests, "get", lambda *a, **k: FakeResponse([b"%PDF", b"-1.7"]))

    assert pdf_extract.download_pdf("https://x/pdf") == b"%PDF-1.7"


def test_download_rejects_a_declared_oversize_pdf(monkeypatch):
    headers = {"Content-Length": str(pdf_extract.MAX_PDF_BYTES + 1)}
    monkeypatch.setattr(pdf_extract.requests, "get", lambda *a, **k: FakeResponse([b"x"], headers))

    with pytest.raises(pdf_extract.PdfTooLarge):
        pdf_extract.download_pdf("https://x/pdf")


def test_download_stops_when_the_stream_exceeds_the_cap(monkeypatch):
    monkeypatch.setattr(pdf_extract, "MAX_PDF_BYTES", 10)
    monkeypatch.setattr(pdf_extract.requests, "get", lambda *a, **k: FakeResponse([b"x" * 6, b"x" * 6]))

    with pytest.raises(pdf_extract.PdfTooLarge):
        pdf_extract.download_pdf("https://x/pdf")


def test_extract_rejects_too_many_pages(monkeypatch):
    class FakeReader:
        def __init__(self, *args, **kwargs):
            self.pages = [object()] * (pdf_extract.MAX_PDF_PAGES + 1)

    monkeypatch.setattr(pdf_extract, "PdfReader", FakeReader)

    with pytest.raises(pdf_extract.PdfTooLarge):
        pdf_extract.extract_text(b"irrelevant")
