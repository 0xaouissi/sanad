import uuid

import pytest

from app.rag.retrieval import RetrievalHit
from app.services.rag_chat import (
    LANGUAGE_NAMES,
    NO_ANSWER,
    build_context,
    build_system_prompt,
    is_no_answer,
    parse_citations,
)


def _hit(index: int, filename: str = "policy.pdf", page: int | None = 2) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename=filename,
        page_number=page,
        heading=f"Section {index}",
        content=f"Content number {index}.",
        score=0.8,
    )


def test_context_numbers_sources_with_filename_page_and_heading() -> None:
    context = build_context([_hit(1), _hit(2, "guide.docx", None)])
    assert "[1] (policy.pdf, page 2, section \"Section 1\")" in context
    assert "[2] (guide.docx, section \"Section 2\")" in context
    assert "Content number 1." in context


@pytest.mark.parametrize("language", ["ar", "fr", "en"])
def test_prompt_is_strict_and_localized(language: str) -> None:
    prompt = build_system_prompt(language, "[1] (a.md)\ntext")
    assert LANGUAGE_NAMES[language] in prompt
    assert "ONLY using the numbered sources" in prompt
    assert "whatever language the question is written in" in prompt
    assert "Never use outside knowledge" in prompt
    assert NO_ANSWER[language] in prompt
    assert "[1] (a.md)" in prompt


def test_citations_follow_markers_in_answer() -> None:
    hits = [_hit(1), _hit(2), _hit(3)]
    citations = parse_citations("Use [3] and [1].", hits)
    assert [c.index for c in citations] == [1, 3]
    assert citations[0].chunk_id == hits[0].chunk_id
    assert citations[1].filename == hits[2].filename


def test_citations_ignore_out_of_range_and_duplicates() -> None:
    hits = [_hit(1), _hit(2)]
    citations = parse_citations("[2] [2] [9] [0]", hits)
    assert [c.index for c in citations] == [2]


def test_citations_fall_back_to_all_sources_when_unmarked() -> None:
    hits = [_hit(1), _hit(2)]
    citations = parse_citations("No markers here.", hits)
    assert [c.index for c in citations] == [1, 2]


def test_no_answer_templates_exist_for_all_languages() -> None:
    assert set(NO_ANSWER) == {"ar", "fr", "en"}
    assert any("؀" <= ch <= "ۿ" for ch in NO_ANSWER["ar"])
    for text in NO_ANSWER.values():
        assert text.strip()


@pytest.mark.parametrize(
    ("language", "contact_word"),
    [("en", "contact"), ("fr", "contacter"), ("ar", "التواصل")],
)
def test_no_answer_offers_contact(language: str, contact_word: str) -> None:
    assert contact_word in NO_ANSWER[language]


@pytest.mark.parametrize("language", ["ar", "fr", "en"])
def test_is_no_answer_matches_template_with_or_without_markers(language: str) -> None:
    template = NO_ANSWER[language]
    assert is_no_answer(template, language)
    assert is_no_answer(f"  {template} [1] [4]  ", language)


def test_is_no_answer_rejects_real_answers_and_other_languages() -> None:
    assert not is_no_answer("You have 30 days to request a refund. [1]", "en")
    assert not is_no_answer(NO_ANSWER["fr"], "en")
    assert not is_no_answer("I don't know, sorry!", "en")