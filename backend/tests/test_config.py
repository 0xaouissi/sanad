import pytest
from pydantic import ValidationError

from app.core.config import (
    LAST_RESORT_MODEL,
    TIER_SPECS,
    LLMProvider,
    ModelTier,
    Settings,
    is_research_license_model,
)


def test_default_tier_is_small() -> None:
    s = Settings()
    assert s.model_tier is ModelTier.SMALL
    assert s.resolved_llm_model == "qwen3:4b-instruct-2507-q4_K_M"
    assert s.resolved_num_ctx == 8192


@pytest.mark.parametrize("tier", list(ModelTier))
def test_every_tier_has_documented_default(tier: ModelTier) -> None:
    spec = TIER_SPECS[tier]
    s = Settings(model_tier=tier)
    assert s.resolved_llm_model == spec.model
    assert s.resolved_num_ctx == spec.num_ctx
    assert spec.model.startswith(("qwen2.5:", "qwen3:"))
    assert "q4_K_M" in spec.model


def test_env_vars_drive_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_TIER", "medium")
    monkeypatch.setenv("LLM_NUM_CTX", "4096")
    s = Settings()
    assert s.model_tier is ModelTier.MEDIUM
    assert s.resolved_llm_model == "qwen2.5:7b-instruct-q4_K_M"
    assert s.resolved_num_ctx == 4096


def test_model_override_changes_name_and_quantization() -> None:
    s = Settings(llm_model="qwen2.5:3b-instruct-q8_0")
    assert s.resolved_llm_model == "qwen2.5:3b-instruct-q8_0"
    assert s.resolved_num_ctx == 8192


def test_last_resort_model_is_selectable() -> None:
    s = Settings(llm_model=LAST_RESORT_MODEL)
    assert s.resolved_llm_model == "qwen2.5:1.5b-instruct-q4_K_M"


def test_invalid_tier_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(model_tier="xlarge")


@pytest.mark.parametrize("ctx", [256, 200000])
def test_num_ctx_out_of_bounds_rejected(ctx: int) -> None:
    with pytest.raises(ValidationError):
        Settings(llm_num_ctx=ctx)


def test_cpu_only_forces_cpu_everywhere() -> None:
    s = Settings(cpu_only=True, ollama_num_gpu=99, embedding_device="cuda")
    assert s.resolved_ollama_num_gpu == 0
    assert s.resolved_embedding_device == "cpu"


def test_gpu_offload_respected_when_not_cpu_only() -> None:
    assert Settings(ollama_num_gpu=20).resolved_ollama_num_gpu == 20
    assert Settings().resolved_ollama_num_gpu is None


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(ValidationError):
        Settings(llm_provider="openai")


def test_openai_provider_with_key() -> None:
    s = Settings(llm_provider="openai", openai_api_key="sk-test")
    assert s.llm_provider is LLMProvider.OPENAI
    assert s.openai_model == "gpt-4o-mini"


def test_embedding_device_override() -> None:
    assert Settings(embedding_device="cuda").resolved_embedding_device == "cuda"
    assert Settings().resolved_embedding_device == "auto"

def test_step2_defaults() -> None:
    s = Settings()
    assert s.chunk_size == 1200
    assert s.chunk_overlap == 200
    assert s.max_upload_mb == 20
    assert s.embedding_batch_size == 16
    assert s.ocr_languages == "ara+fra+eng"
    assert s.admin_api_key is None
    assert s.tessdata_prefix is None


def test_step2_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHUNK_SIZE", "800")
    monkeypatch.setenv("CHUNK_OVERLAP", "100")
    monkeypatch.setenv("MAX_UPLOAD_MB", "50")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    monkeypatch.setenv("TESSERACT_CMD", "C:/tools/tesseract.exe")
    s = Settings()
    assert s.chunk_size == 800
    assert s.chunk_overlap == 100
    assert s.max_upload_mb == 50
    assert s.admin_api_key == "admin-secret"
    assert s.tesseract_cmd == "C:/tools/tesseract.exe"


def test_overlap_must_be_smaller_than_size() -> None:
    with pytest.raises(ValidationError, match="CHUNK_OVERLAP"):
        Settings(chunk_size=500, chunk_overlap=500)


def test_chunk_size_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(chunk_size=50)


def test_hf_home_override(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().hf_home is None
    monkeypatch.setenv("HF_HOME", "F:/sanad/models/hf")
    assert Settings().hf_home == "F:/sanad/models/hf"


def test_step3_retrieval_defaults() -> None:
    s = Settings()
    assert s.rerank_enabled is None
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert s.rerank_candidates == 8
    assert s.retrieval_top_k == 5
    assert s.retrieval_min_score == 0.43
    assert s.retrieval_off_topic_score == 0.41
    assert s.memory_max_turns == 6


@pytest.mark.parametrize(
    ("tier", "expected"),
    [(ModelTier.SMALL, False), (ModelTier.MEDIUM, True), (ModelTier.LARGE, True)],
)
def test_rerank_tier_default(tier: ModelTier, expected: bool) -> None:
    assert Settings(model_tier=tier).resolved_rerank_enabled is expected


@pytest.mark.parametrize("override", [True, False])
def test_rerank_env_override_beats_tier(override: bool) -> None:
    s = Settings(model_tier=ModelTier.SMALL, rerank_enabled=override)
    assert s.resolved_rerank_enabled is override


@pytest.mark.parametrize(
    ("tier", "budget"),
    [(ModelTier.SMALL, 8.0), (ModelTier.MEDIUM, 3.0), (ModelTier.LARGE, 3.0)],
)
def test_first_token_budget_per_tier(tier: ModelTier, budget: float) -> None:
    assert Settings(model_tier=tier).first_token_budget_s == budget


def test_rerank_candidates_must_cover_top_k() -> None:
    with pytest.raises(ValidationError, match="RERANK_CANDIDATES"):
        Settings(rerank_candidates=3, retrieval_top_k=5)


def test_off_topic_score_must_not_exceed_min_score() -> None:
    with pytest.raises(ValidationError, match="RETRIEVAL_OFF_TOPIC_SCORE"):
        Settings(retrieval_min_score=0.43, retrieval_off_topic_score=0.5)
    # Equal is allowed: every weak hit is then treated as off-topic.
    assert Settings(retrieval_min_score=0.43, retrieval_off_topic_score=0.43)


def test_off_topic_score_bounds() -> None:
    with pytest.raises(ValidationError, match="retrieval_off_topic_score"):
        Settings(retrieval_off_topic_score=1.5)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"retrieval_min_score": 1.5}, "retrieval_min_score"),
        ({"retrieval_top_k": 0}, "retrieval_top_k"),
        ({"memory_max_turns": -1}, "memory_max_turns"),
    ],
)
def test_step3_bounds(kwargs: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        Settings(**kwargs)


def test_step3_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "0.7")
    monkeypatch.setenv("RETRIEVAL_OFF_TOPIC_SCORE", "0.6")
    monkeypatch.setenv("MEMORY_MAX_TURNS", "0")
    s = Settings()
    assert s.resolved_rerank_enabled is True
    assert s.retrieval_min_score == 0.7
    assert s.retrieval_off_topic_score == 0.6
    assert s.memory_max_turns == 0


def test_llm_think_defaults_to_unset() -> None:
    assert Settings().llm_think is None


@pytest.mark.parametrize("value", [True, False])
def test_llm_think_override(value: bool) -> None:
    assert Settings(llm_think=value).llm_think is value


def test_llm_think_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_THINK", "false")
    assert Settings().llm_think is False


@pytest.mark.parametrize(
    "model",
    [
        "qwen2.5:3b-instruct-q4_K_M",
        "qwen2.5:3b-instruct-q8_0",
        "qwen2.5:3b",
        "Qwen/Qwen2.5-3B-Instruct",
        "qwen2.5-3b-instruct",
    ],
)
def test_research_license_detected_for_3b(model: str) -> None:
    assert is_research_license_model(model) is True


@pytest.mark.parametrize(
    "model",
    [
        "qwen2.5:7b-instruct-q4_K_M",
        "qwen2.5:14b-instruct-q4_K_M",
        "qwen2.5:1.5b-instruct-q4_K_M",
        "qwen2.5:0.5b-instruct-q4_K_M",
        "qwen2.5:32b-instruct-q4_K_M",
        "qwen3:4b",
        "qwen3:4b-instruct-2507-q4_K_M",
        "gpt-4o-mini",
        "",
    ],
)
def test_research_license_not_detected_for_others(model: str) -> None:
    assert is_research_license_model(model) is False
