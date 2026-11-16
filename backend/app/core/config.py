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
    # Empty = in-memory cache/counters (single process). Set for shared state
    # across workers; unreachable Redis falls back to memory with a warning.
    redis_url: str = ""

    # Answer cache (Step 5a). Keys include company id + language + question +
    # a per-company document epoch, so answers never leak across companies
    # and go stale when documents change.
    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=3600, ge=1)

    # Visitor abuse protection (Step 5a). 0 disables a limit.
    rate_limit_per_ip: int = Field(default=30, ge=0)  # requests/minute
    rate_limit_per_site: int = Field(default=120, ge=0)  # requests/minute/company
    daily_cap_per_company: int = Field(default=1000, ge=0)  # chats/UTC day
    # Behind a reverse proxy, count the first X-Forwarded-For entry instead of
    # the proxy IP. Only enable when the proxy overwrites the header — clients
    # can spoof it otherwise.
    trust_forwarded_for: bool = False
    # Widget bot deterrent: hidden honeypot field + minimum time between
    # opening the panel and sending. Not a security boundary.
    bot_check_enabled: bool = True
    bot_check_min_seconds: float = Field(default=2.0, ge=0)

    # Dashboard (Step 5b). Sessions live in the KV store (Redis or memory)
    # and are referenced by an httpOnly cookie; mutations need the session's
    # CSRF token in X-CSRF-Token.
    dashboard_session_hours: int = Field(default=12, ge=1)
    login_rate_limit_per_minute: int = Field(default=10, ge=0)  # 0 disables
    # Set true when the dashboard is served over HTTPS.
    cookie_secure: bool = False

    # Website crawler (Step 6b). SSRF guards: http/https only, same domain,
    # every DNS answer checked against private/local ranges, redirects
    # re-validated, robots.txt respected.
    crawl_max_pages: int = Field(default=20, ge=1, le=200)
    crawl_max_page_bytes: int = Field(default=2_000_000, ge=1024)
    crawl_timeout_seconds: float = Field(default=15.0, gt=0)
    crawl_max_seconds: float = Field(default=300.0, gt=0)
    # Scheduled re-sync interval per source. 0 disables the background loop.
    crawl_resync_hours: int = Field(default=24, ge=0)
    # DANGEROUS, dev/tests only: allow crawling private/local IPs (loopback,
    # LAN, link-local). Never enable on a server reachable by untrusted users.
    crawl_allow_private: bool = False
    crawl_user_agent: str = "SanadBot/0.1 (self-hosted RAG indexer; respects robots.txt)"

    model_tier: ModelTier = ModelTier.SMALL
    cpu_only: bool = False

    llm_provider: LLMProvider = LLMProvider.OLLAMA
    llm_model: str | None = None
    llm_num_ctx: int | None = Field(default=None, ge=512, le=131072)
    # Grounded support answers should be reproducible: 0 = greedy decoding.
    # Raise only if you want more varied phrasing (and flakier small models).
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    ollama_base_url: str = "http://localhost:11434"
    ollama_num_gpu: int | None = Field(default=None, ge=0)
    ollama_keep_alive: str = "5m"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: Literal["auto", "cpu", "cuda"] = "auto"
    embedding_batch_size: int = Field(default=16, ge=1, le=256)
    hf_home: str | None = None

    admin_api_key: str | None = None
    data_dir: str = "./data"
    max_upload_mb: int = Field(default=20, ge=1, le=200)
    chunk_size: int = Field(default=1200, ge=200, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=2000)
    tesseract_cmd: str = "tesseract"
    tessdata_prefix: str | None = None
    ocr_languages: str = "ara+fra+eng"

    # Retrieval (Step 3). RERANK_ENABLED unset = tier default: off on small
    # (CPU reranking eats the latency budget), on for medium/large GPUs.
    rerank_enabled: bool | None = None
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidates: int = Field(default=8, ge=1, le=50)
    retrieval_top_k: int = Field(default=5, ge=1, le=20)
    # Calibrated on real BGE-M3 scores (tests/e2e/test_live_chat.py): in-scope
    # queries score >= 0.45, off-topic <= 0.39. Near-misses above the threshold
    # are refused by the LLM's grounding rule instead of by retrieval.
    retrieval_min_score: float = Field(default=0.43, ge=0.0, le=1.0)
    memory_max_turns: int = Field(default=6, ge=0, le=50)

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

    @model_validator(mode="after")
    def _check_retrieval(self) -> "Settings":
        if self.rerank_candidates < self.retrieval_top_k:
            raise ValueError("RERANK_CANDIDATES must be >= RETRIEVAL_TOP_K")
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

    @property
    def resolved_rerank_enabled(self) -> bool:
        if self.rerank_enabled is not None:
            return self.rerank_enabled
        return self.model_tier is not ModelTier.SMALL

    @property
    def first_token_budget_s(self) -> float:
        # Step 3 latency targets: small tier (CPU) gets more headroom.
        return 8.0 if self.model_tier is ModelTier.SMALL else 3.0


@lru_cache
def get_settings() -> Settings:
    return Settings()