"""Extract text blocks (with page/heading metadata) from uploaded files."""

import io
import re

from app.core.config import Settings
from app.rag.arabic import clean_text, fix_rtl_order
from app.rag.chunking import Block

TEXT_EXTENSIONS = {".txt", ".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
SUPPORTED_EXTENSIONS = {".pdf", ".docx"} | TEXT_EXTENSIONS | IMAGE_EXTENSIONS

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


class ParseError(ValueError):
    """Unreadable or unsupported file; message tells the user how to fix it."""


def _pdf_blocks(data: bytes, settings: Settings) -> list[Block]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseError(
                "This PDF is password-protected. Remove the password and upload again."
            )
        blocks: list[Block] = []
        for i, page in enumerate(reader.pages):
            text = clean_text(fix_rtl_order(page.extract_text() or ""))
            if text:
                blocks.append(Block(text=text, page=i + 1))
    except PdfReadError as exc:
        raise ParseError(f"Unreadable PDF file: {exc}. Re-export the PDF and retry.") from exc

    if blocks:
        return blocks

    # No extractable text on any page: likely a scan.
    from app.rag import ocr

    if not ocr.ocr_available():
        raise ParseError(
            "This PDF appears to be scanned (no text layer). OCR is not installed: "
            "run `pip install -e .[ocr]` and install Tesseract with the ara/fra packs, "
            "then set TESSERACT_CMD in .env."
        )
    try:
        blocks = ocr.ocr_pdf(data, settings)
    except ocr.OcrUnavailableError as exc:
        raise ParseError(str(exc)) from exc
    if not blocks:
        raise ParseError(
            "No text found in this PDF, even with OCR. The file may be blank or unreadable."
        )
    return blocks


def _docx_blocks(data: bytes) -> list[Block]:
    from zipfile import BadZipFile

    from docx import Document as DocxDocument
    from docx.opc.exceptions import PackageNotFoundError

    try:
        doc = DocxDocument(io.BytesIO(data))
    except (PackageNotFoundError, BadZipFile, KeyError, ValueError) as exc:
        raise ParseError(
            f"Unreadable DOCX file: {exc}. Only .docx is supported (not legacy .doc)."
        ) from exc
    blocks: list[Block] = []
    heading: str | None = None
    for para in doc.paragraphs:
        text = clean_text(para.text)
        if not text:
            continue
        style = (para.style.name or "") if para.style is not None else ""
        if style.startswith("Heading") or style == "Title":
            heading = text
        blocks.append(Block(text=text, heading=heading))
    return blocks


def _markdown_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    heading: str | None = None
    pos = 0
    for match in _MD_HEADING.finditer(text):
        body = text[pos : match.start()]
        if body.strip():
            blocks.append(Block(text=body.strip(), heading=heading))
        heading = match.group(2).strip()
        pos = match.end()
    tail = text[pos:]
    if tail.strip():
        blocks.append(Block(text=tail.strip(), heading=heading))
    return blocks


def parse_file(filename: str, data: bytes, settings: Settings) -> list[Block]:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise ParseError(
            f"Unsupported file type '{ext or filename}'. "
            "Upload PDF, DOCX, TXT, MD, or a PNG/JPG image (OCR)."
        )
    if not data:
        raise ParseError("The file is empty.")

    if ext == ".pdf":
        blocks = _pdf_blocks(data, settings)
    elif ext == ".docx":
        blocks = _docx_blocks(data)
    elif ext in IMAGE_EXTENSIONS:
        from app.rag import ocr

        if not ocr.ocr_available():
            raise ParseError(
                "Image upload requires OCR: run `pip install -e .[ocr]` and install "
                "Tesseract with the ara/fra packs, then set TESSERACT_CMD in .env."
            )
        from PIL import Image

        try:
            image = Image.open(io.BytesIO(data))
            text = ocr.ocr_image(image, settings)
        except ocr.OcrUnavailableError as exc:
            raise ParseError(str(exc)) from exc
        except OSError as exc:
            raise ParseError(f"Unreadable image file: {exc}.") from exc
        blocks = [Block(text=text)] if text.strip() else []
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        text = clean_text(text)
        blocks = _markdown_blocks(text) if ext == ".md" else [Block(text=text)]

    blocks = [b for b in blocks if b.text.strip()]
    if not blocks:
        raise ParseError(
            f"No text could be extracted from '{filename}'. "
            "If it is a scan, install the OCR extras; otherwise re-export the file."
        )
    return blocks