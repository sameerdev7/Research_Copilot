from pathlib import Path

from papers.services import pdf_extract

FIXTURE = Path(__file__).parent / "fixtures" / "sample.pdf"


def test_extract_text_reads_pdf_content():
    text = pdf_extract.extract_text(FIXTURE.read_bytes())

    assert "Hello Research Copilot" in text


def test_extract_text_strips_nul_bytes(monkeypatch):
    # Real-world PDFs can extract to text containing NUL bytes, which PostgreSQL
    # text columns reject outright (psycopg.DataError).
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
