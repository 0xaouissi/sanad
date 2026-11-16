import pytest

from app.rag.language import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ما هي سياسة الاسترجاع؟", "ar"),
        ("Quelle est la politique de remboursement ?", "fr"),
        ("What is the refund policy?", "en"),
        ("كيف يمكنني طلب استرجاع المبلغ بعد الشراء؟", "ar"),
        ("Je voudrais un remboursement pour ma commande.", "fr"),
        ("I would like a refund for my order.", "en"),
        ("Bonjour", "fr"),
        ("Refund please", "en"),
        ("استرجاع", "ar"),
    ],
)
def test_detects_supported_languages(text: str, expected: str) -> None:
    assert detect_language(text) == expected


def test_arabic_wins_in_mixed_text() -> None:
    assert detect_language("Please explain سياسة الاسترجاع for me") == "ar"


def test_arabic_with_diacritics() -> None:
    assert detect_language("مَا هِيَ سِيَاسَةُ الإِسْتِرْجَاعِ؟") == "ar"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_blank_defaults_to_english(text: str) -> None:
    assert detect_language(text) == DEFAULT_LANGUAGE


def test_result_always_supported() -> None:
    for text in ["xyz", "12345", "ok", "merci beaucoup pour votre aide"]:
        assert detect_language(text) in SUPPORTED_LANGUAGES