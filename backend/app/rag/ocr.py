"""Optional OCR for scanned PDFs and images (Tesseract + pypdfium2, no poppler)."""

from app.core.config import Settings
from app.rag.chunking import Block


class OcrUnavailableError(RuntimeError):
    pass


def ocr_available() -> bool:
    try:
        import pypdfium2  # noqa: F401
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def _tesseract_config(settings: Settings) -> str:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    config = ""
    if settings.tessdata_prefix:
        config = f'--tessdata-dir "{settings.tessdata_prefix}"'
    return config


def ocr_image(image, settings: Settings) -> str:
    import pytesseract

    try:
        return pytesseract.image_to_string(
            image, lang=settings.ocr_languages, config=_tesseract_config(settings)
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError(
            "Tesseract executable not found. Install it (Windows: UB-Mannheim build) "
            "and set TESSERACT_CMD to its full path in .env."
        ) from exc
    except pytesseract.TesseractError as exc:
        raise OcrUnavailableError(
            f"Tesseract failed ({exc}). Check OCR_LANGUAGES packs are installed "
            "and TESSDATA_PREFIX points at the tessdata directory."
        ) from exc


def ocr_pdf(data: bytes, settings: Settings) -> list[Block]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    blocks: list[Block] = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=2.0)
            try:
                text = ocr_image(bitmap.to_pil(), settings)
            finally:
                bitmap.close()
            page.close()
            if text.strip():
                blocks.append(Block(text=text, page=i + 1))
    finally:
        pdf.close()
    return blocks