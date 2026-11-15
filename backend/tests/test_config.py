import pytest
from pydantic import ValidationError

from app.core.config import (
    LAST_RESORT_MODEL,
    TIER_SPECS,
    LLMProvider,
    ModelTier,
    Settings,
)


def test_default_tier_is_small() -> None:
    s = Settings()
    assert s.model_tier is ModelTier.SMALL
    assert s.resolved_llm_model == "qwen2.5:3b-instruct-q4_K_M"
    assert s.resolved_num_ctx == 8192


@pytest.mark.parametrize("tier", list(ModelTier))
def test_every_tier_has_documented_default(tier: ModelTier) -> None:
    spec = TIER_SPECS[tier]
    s = Settings(model_tier=tier)
    assert s.resolved_llm_model == spec.model
    assert s.resolved_num_ctx == spec.num_ctx
    assert spec.model.startswith("qwen2.5:")
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