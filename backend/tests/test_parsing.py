"""File parsers: PDF, DOCX, TXT, MD, images, and clear error paths."""

import io

import pytest
from docx import Document as DocxDocument
from pytest import MonkeyPatch

from app.core.config import Settings
from app.rag.parsing import ParseError, parse_file
from tests.pdf_builder import make_pdf


@pytest.fixture
def settings() -> Settings:
    return Settings()


def test_txt(settings):
    blocks = parse_file("notes.txt", b"Hello world\nSecond line", settings)
    assert len(blocks) == 1
    assert "Hello world" in blocks[0].text
    assert blocks[0].page is None


def test_pdf_pages(settings):
    data = make_pdf(["First page text", "Second page text"])
    blocks = parse_file("policy.pdf", data, settings)
    assert [b.page for b in blocks] == [1, 2]
    assert "First page" in blocks[0].text
    assert "Second page" in blocks[1].text


def test_markdown_headings(settings):
    md = b"# Refunds\nYou have 30 days.\n## Exceptions\nFinal sale items.\n# Shipping\nWe ship."
    blocks = parse_file("policy.md", md, settings)
    assert [b.heading for b in blocks] == ["Refunds", "Exceptions", "Shipping"]
    assert "30 days" in blocks[0].text


def test_docx_headings(settings):
    doc = DocxDocument()
    doc.add_heading("Refund policy", level=1)
    doc.add_paragraph("Refunds within 30 days.")
    doc.add_heading("Contact", level=2)
    doc.add_paragraph("Email support@example.com.")
    buf = io.BytesIO()
    doc.save(buf)
    blocks = parse_file("policy.docx", buf.getvalue(), settings)
    assert [b.heading for b in blocks] == [
        "Refund policy",
        "Refund policy",
        "Contact",
        "Contact",
    ]
    assert blocks[0].page is None


def test_unsupported_extension(settings):
    with pytest.raises(ParseError, match="Unsupported file type"):
        parse_file("virus.exe", b"MZ", settings)


def test_empty_file(settings):
    with pytest.raises(ParseError, match="empty"):
        parse_file("empty.txt", b"", settings)


def test_corrupted_pdf(settings):
    with pytest.raises(ParseError, match="Unreadable PDF"):
        parse_file("broken.pdf", b"%PDF-1.4 this is not a real pdf", settings)


def test_corrupted_docx(settings):
    with pytest.raises(ParseError, match="Unreadable DOCX"):
        parse_file("broken.docx", b"not a zip", settings)


def test_scanned_pdf_without_ocr(settings, monkeypatch: MonkeyPatch):
    monkeypatch.setattr("app.rag.ocr.ocr_available", lambda: False)
    data = make_pdf([""])
    with pytest.raises(ParseError, match="OCR is not installed"):
        parse_file("scan.pdf", data, settings)


def test_image_without_ocr(settings, monkeypatch: MonkeyPatch):
    monkeypatch.setattr("app.rag.ocr.ocr_available", lambda: False)
    with pytest.raises(ParseError, match="requires OCR"):
        parse_file("scan.png", b"\x89PNG fake", settings)


def test_txt_latin1_fallback(settings):
    blocks = parse_file("legacy.txt", "café".encode("latin-1"), settings)
    assert blocks[0].text