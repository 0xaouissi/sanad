import re
import unicodedata

from bidi.algorithm import get_display

# Arabic diacritics (harakat) U+064B-U+0652 plus superscript alef U+0670.
_DIACRITICS = re.compile(r"[ً-ْٰ]")
# Arabic presentation forms: a PDF emitting these stored text in visual order.
_PRESENTATION_FORMS = re.compile(r"[ﹰ-﻿]")
_ALEF_VARIANTS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا"})


def fix_rtl_order(text: str) -> str:
    """Convert visual-order Arabic (from some PDF extractors) back to logical order.

    Logical-order text is returned untouched: running the bidi display algorithm
    on it would corrupt it.
    """
    if _PRESENTATION_FORMS.search(text):
        text = unicodedata.normalize("NFKC", text)
        text = get_display(text)
    return text


def normalize_arabic(text: str) -> str:
    """Unify letter variants and strip diacritics/tatweel so search matches ignore them."""
    text = _DIACRITICS.sub("", text)
    text = text.replace("ـ", "")
    text = text.translate(_ALEF_VARIANTS)
    text = text.replace("ى", "ي").replace("ة", "ه")
    return text


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()