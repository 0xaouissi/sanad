"""Arabic normalization and RTL-order repair."""

import arabic_reshaper
from bidi.algorithm import get_display

from app.rag.arabic import clean_text, fix_rtl_order, normalize_arabic


def test_strips_diacritics():
    assert normalize_arabic("مَرْحَبًا بِكُمْ") == "مرحبا بكم"


def test_unifies_alef_variants():
    assert normalize_arabic("أحمد إبراهيم آدم ٱلله") == "احمد ابراهيم ادم الله"


def test_unifies_ya_and_ta_marbuta():
    assert normalize_arabic("على مدرسة") == "علي مدرسه"


def test_strips_tatweel():
    assert normalize_arabic("عــربــي") == "عربي"


def test_latin_untouched():
    assert normalize_arabic("Bonjour à tous, hello!") == "Bonjour à tous, hello!"


def test_logical_order_untouched():
    text = "مرحبا بكم في شركة ساناد"
    assert fix_rtl_order(text) == text


def test_visual_order_repaired():
    logical = "مرحبا بكم في الشركة"
    visual = get_display(arabic_reshaper.reshape(logical))
    assert visual != logical
    assert fix_rtl_order(visual) == logical


def test_mixed_visual_order_repaired():
    logical = "سياسة الاسترجاع خلال 30 يوما"
    visual = get_display(arabic_reshaper.reshape(logical))
    repaired = fix_rtl_order(visual)
    assert "سياسة" in repaired
    assert "30" in repaired


def test_clean_text_collapses_whitespace():
    assert clean_text("  a \t b\r\n\r\n\r\nc  ") == "a b\n\nc"


def test_clean_text_strips_control_chars():
    assert clean_text("a\x00b\x1fc") == "abc"