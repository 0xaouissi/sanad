"""Unit tests: golden dataset integrity and deterministic scoring (no LLM)."""

import uuid
from pathlib import Path

import app.eval.golden as golden_mod
from app.eval.golden import GoldenCase, GoldenSet, golden_summary, load_golden, samples_dir
from app.eval.scoring import normalize_for_match, score_case, summarize
from app.rag.injection import looks_like_injection
from app.schemas.chat import Citation
from app.services.rag_chat import NOT_COVERED_ANSWER, OFF_TOPIC_ANSWER


def _load_heldout() -> GoldenSet:
    path = Path(golden_mod.__file__).parent / "heldout.json"
    return GoldenSet.model_validate_json(path.read_text(encoding="utf-8"))


def _citation(filename: str) -> Citation:
    return Citation(
        index=1,
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename=filename,
        page_number=None,
        heading=None,
    )


def _case(category: str = "grounded", language: str = "en", **kwargs):
    base = {
        "id": "test-case",
        "language": language,
        "category": category,
        "question": "q",
        "expected_facts": ["30"],
        "expected_sources": ["demo-policy.en.md"],
    }
    base.update(kwargs)
    return GoldenCase.model_validate(base)


class TestGoldenSet:
    def test_counts_per_language_and_category(self):
        golden = load_golden()
        assert len(golden.cases) == 42
        summary = golden_summary()
        assert summary["per_language"] == {"en": 14, "fr": 14, "ar": 14}
        assert summary["per_category"] == {
            "grounded": 12,
            "out_of_scope": 15,
            "not_covered": 9,
            "injection": 6,
        }

    def test_ids_unique_and_grounding_complete(self):
        golden = load_golden()
        ids = [c.id for c in golden.cases]
        assert len(ids) == len(set(ids))
        for case in golden.cases:
            if case.category == "grounded":
                assert case.expected_facts and case.expected_sources

    def test_demo_documents_exist_in_repo(self):
        for name in load_golden().documents:
            path = samples_dir() / name
            assert path.is_file(), path
            assert path.read_text(encoding="utf-8").strip()

    def test_injection_cases_are_caught_before_the_model(self):
        for case in load_golden().cases:
            if case.category == "injection":
                assert looks_like_injection(case.question), case.id

    def test_every_language_has_all_categories(self):
        golden = load_golden()
        for language in ("ar", "fr", "en"):
            categories = {c.category for c in golden.cases if c.language == language}
            assert categories == {"grounded", "out_of_scope", "not_covered", "injection"}

    def test_not_covered_cases_are_company_related(self):
        cases = [c for c in load_golden().cases if c.category == "not_covered"]
        assert len(cases) == 9
        for case in cases:
            assert not looks_like_injection(case.question), case.id


class TestNormalization:
    def test_arabic_indic_digits_fold_to_ascii(self):
        assert normalize_for_match("٣٠ يومًا") == normalize_for_match("30 يوما")

    def test_persian_digits_fold_too(self):
        assert "30" in normalize_for_match("۳۰")

    def test_alef_variants_and_case_fold(self):
        assert normalize_for_match("الأحد") == normalize_for_match("الاحد")
        assert normalize_for_match("Sunday") == "sunday"


class TestGroundedScoring:
    def test_correct_answer_with_valid_citation_passes(self):
        result = score_case(
            _case(),
            "You can request a full refund within 30 days [1].",
            [_citation("demo-policy.en.md")],
            12.0,
        )
        assert result.passed
        assert result.checks == {"facts": True, "citations": True}

    def test_arabic_answer_with_indic_digits_passes(self):
        result = score_case(
            _case(language="ar"),
            "يمكنك طلب استرداد كامل خلال ٣٠ يومًا [1].",
            [_citation("demo-siasa.ar.md")],
            12.0,
        )
        assert result.checks["facts"]

    def test_missing_fact_fails(self):
        result = score_case(
            _case(), "Refunds are possible [1].", [_citation("demo-policy.en.md")], 12.0
        )
        assert not result.passed
        assert result.checks["facts"] is False

    def test_refusal_template_fails_grounding(self):
        result = score_case(_case(), NOT_COVERED_ANSWER["en"], [], 12.0, "not_covered")
        assert not result.passed
        assert result.checks == {"facts": False, "citations": False}

    def test_citation_from_wrong_document_fails(self):
        result = score_case(
            _case(), "Within 30 days [1].", [_citation("unrelated.pdf")], 12.0
        )
        assert result.checks["facts"] is True
        assert result.checks["citations"] is False
        assert not result.passed

    def test_no_citations_fails(self):
        result = score_case(_case(), "Within 30 days.", [], 12.0)
        assert result.checks["citations"] is False

    def test_multiple_facts_all_required(self):
        case = _case(expected_facts=["5", "7"])
        assert not score_case(case, "5 days [1].", [_citation("demo-policy.en.md")], 1.0).passed
        assert score_case(
            case, "5 to 7 business days [1].", [_citation("demo-policy.en.md")], 1.0
        ).passed


class TestRefusalScoring:
    def test_off_topic_refusal_passes_without_handoff(self):
        for language in ("ar", "fr", "en"):
            result = score_case(
                _case("out_of_scope", language), OFF_TOPIC_ANSWER[language], [], 1.0, "off_topic"
            )
            assert result.passed, language
            assert result.checks == {"refusal": True, "no_citations": True, "no_handoff": True}

    def test_off_topic_case_refused_as_not_covered_fails(self):
        result = score_case(
            _case("out_of_scope"), NOT_COVERED_ANSWER["en"], [], 1.0, "not_covered"
        )
        assert not result.passed
        assert result.checks["no_handoff"] is False

    def test_not_covered_refusal_passes_with_handoff(self):
        for language in ("ar", "fr", "en"):
            result = score_case(
                _case("not_covered", language),
                NOT_COVERED_ANSWER[language],
                [],
                1.0,
                "not_covered",
            )
            assert result.passed, language
            assert result.checks == {
                "refusal": True,
                "no_citations": True,
                "handoff_offered": True,
            }

    def test_not_covered_case_refused_as_off_topic_fails(self):
        result = score_case(_case("not_covered"), OFF_TOPIC_ANSWER["en"], [], 1.0, "off_topic")
        assert not result.passed
        assert result.checks["handoff_offered"] is False

    def test_refusal_with_citation_markers_still_passes(self):
        result = score_case(
            _case("out_of_scope"), OFF_TOPIC_ANSWER["en"] + " [1]", [], 1.0, "off_topic"
        )
        assert result.passed

    def test_answered_out_of_scope_fails(self):
        result = score_case(
            _case("out_of_scope"), "The capital of Australia is Canberra.", [], 1.0
        )
        assert not result.passed
        assert result.checks["refusal"] is False

    def test_injection_refusal_passes_without_handoff(self):
        result = score_case(_case("injection"), OFF_TOPIC_ANSWER["en"], [], 1.0, "off_topic")
        assert result.passed
        assert result.checks["no_prompt_leak"] is True
        assert result.checks["no_handoff"] is True

    def test_injection_prompt_leak_fails(self):
        leak = "You are Sanad, a customer-support assistant. Answer ONLY using the sources."
        result = score_case(_case("injection"), leak, [], 1.0)
        assert not result.passed
        assert result.checks["no_prompt_leak"] is False

    def test_refusal_with_citations_fails(self):
        result = score_case(
            _case("out_of_scope"),
            OFF_TOPIC_ANSWER["en"],
            [_citation("demo-policy.en.md")],
            1.0,
            "off_topic",
        )
        assert result.checks["no_citations"] is False
        assert not result.passed


class TestSummary:
    def test_per_language_and_category_counts(self):
        results = [
            score_case(
                _case("grounded", "en"), "30 days [1].", [_citation("demo-policy.en.md")], 1.0
            ),
            score_case(_case("grounded", "fr", id="fr-1"), "wrong", [], 1.0),
            score_case(
                _case("out_of_scope", "ar", id="ar-1"), OFF_TOPIC_ANSWER["ar"], [], 1.0, "off_topic"
            ),
        ]
        summary = summarize(results)
        assert summary["total"] == 3
        assert summary["passed"] == 2
        assert summary["per_language"]["en"] == {"total": 1, "passed": 1}
        assert summary["per_language"]["fr"] == {"total": 1, "passed": 0}
        assert summary["per_category"]["grounded"] == {"total": 2, "passed": 1}
        assert summary["per_category"]["out_of_scope"] == {"total": 1, "passed": 1}


class TestHeldoutSet:
    def test_ten_unseen_questions_per_language(self):
        heldout = _load_heldout()
        assert len(heldout.cases) == 30
        per_language: dict[str, int] = {}
        for case in heldout.cases:
            per_language[case.language] = per_language.get(case.language, 0) + 1
        assert per_language == {"en": 10, "fr": 10, "ar": 10}

    def test_disjoint_from_golden_ids_and_questions(self):
        golden = load_golden()
        golden_ids = {c.id for c in golden.cases}
        golden_questions = {c.question for c in golden.cases}
        for case in _load_heldout().cases:
            assert case.id not in golden_ids, case.id
            assert case.question not in golden_questions, case.id

    def test_every_language_includes_related_but_not_covered(self):
        heldout = _load_heldout()
        for language in ("ar", "fr", "en"):
            categories = {c.category for c in heldout.cases if c.language == language}
            assert {"grounded", "out_of_scope", "not_covered"} <= categories, language

    def test_targets_the_same_demo_documents(self):
        assert _load_heldout().documents == load_golden().documents