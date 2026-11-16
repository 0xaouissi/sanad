"""Visitor language detection, restricted to the three supported languages."""

from functools import lru_cache

from lingua import Language, LanguageDetectorBuilder

SUPPORTED_LANGUAGES = ("ar", "fr", "en")
DEFAULT_LANGUAGE = "en"

_TO_CODE = {Language.ARABIC: "ar", Language.FRENCH: "fr", Language.ENGLISH: "en"}


@lru_cache
def _detector():
    return (
        LanguageDetectorBuilder.from_languages(
            Language.ARABIC, Language.FRENCH, Language.ENGLISH
        )
        .with_preloaded_language_models()
        .build()
    )


def detect_language(text: str) -> str:
    text = text.strip()
    if not text:
        return DEFAULT_LANGUAGE
    # Arabic script is unambiguous, even in short or mixed-language messages.
    if any("؀" <= ch <= "ۿ" for ch in text):
        return "ar"
    detected = _detector().detect_language_of(text)
    return _TO_CODE.get(detected, DEFAULT_LANGUAGE)