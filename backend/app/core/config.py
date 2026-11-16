from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelTier(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class LLMProvider(StrEnum):
    OLLAMA = "ollama"
    OPENAI = "openai"


class TierSpec(BaseModel, frozen=True):
    model: str
    num_ctx: int
    min_vram_gb: int
    hardware: str


TIER_SPECS: dict[ModelTier, TierSpec] = {
    ModelTier.SMALL: TierSpec(
        model="qwen2.5:3b-instruct-q4_K_M",
        num_ctx=8192,
        min_vram_gb=4,
        hardware="CPU-only or 4 GB VRAM",
    ),
    ModelTier.MEDIUM: TierSpec(
        model="qwen2.5:7b-instruct-q4_K_M",
        num_ctx=16384,
        min_vram_gb=8,
        hardware="8-12 GB VRAM GPU",
    ),
    ModelTier.LARGE: TierSpec(
        model="qwen2.5:14b-instruct-q4_K_M",
        num_ctx=32768,
        min_vram_gb=16,
        hardware="16+ GB server GPU",
    ),
}

# Selectable via LLM_MODEL, never a tier default: Arabic quality is weak.
LAST_RESORT_MODEL = "qwen2.5:1.5b-instruct-q4_K_M"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Sanad"
    log_level: str = "INFO"
    llm_timeout: float = Field(default=120.0, gt=0)

    database_url: str = "postgresql+asyncpg://sanad:sanad@localhost:5432/sanad"
    redis_url: str = "redis://localhost:6379/0"

    model_tier: ModelTier = ModelTier.SMALL
    cpu_only: bool = False

    llm_provider: LLMProvider = LLMProvider.OLLAMA
    llm_model: str | None = None
    llm_num_ctx: int | None = Field(default=None, ge=512, le=131072)

    ollama_base_url: str = "http://localhost:11434"
    ollama_num_gpu: int | None = Field(default=None, ge=0)
    ollama_keep_alive: str = "5m"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: Literal["auto", "cpu", "cuda"] = "auto"
    embedding_batch_size: int = Field(default=16, ge=1, le=256)

    admin_api_key: str | None = None
    data_dir: str = "./data"
    max_upload_mb: int = Field(default=20, ge=1, le=200)
    chunk_size: int = Field(default=1200, ge=200, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=2000)
    tesseract_cmd: str = "tesseract"
    tessdata_prefix: str | None = None
    ocr_languages: str = "ara+fra+eng"

    @model_validator(mode="after")
    def _require_openai_key(self) -> "Settings":
        if self.llm_provider is LLMProvider.OPENAI and not self.openai_api_key:
            raise ValueError("LLM_PROVIDER=openai requires OPENAI_API_KEY")
        return self

    @model_validator(mode="after")
    def _check_chunk_overlap(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return self

    @property
    def tier_spec(self) -> TierSpec:
        return TIER_SPECS[self.model_tier]

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or self.tier_spec.model

    @property
    def resolved_num_ctx(self) -> int:
        return self.llm_num_ctx or self.tier_spec.num_ctx

    @property
    def resolved_ollama_num_gpu(self) -> int | None:
        if self.cpu_only:
            return 0
        return self.ollama_num_gpu

    @property
    def resolved_embedding_device(self) -> str:
        if self.cpu_only:
            return "cpu"
        return self.embedding_device


@lru_cache
def get_settings() -> Settings:
    return Settings()