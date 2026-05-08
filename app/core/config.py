"""Centralized application configuration.

Loaded once at import time via pydantic-settings. All other modules should
import :data:`settings` instead of reading environment variables directly.

Mock-mode fallback: if neither ``OPENAI_API_KEY`` nor ``ANTHROPIC_API_KEY``
is set and ``LLM_PROVIDER`` is unspecified, the system silently selects
``MockProvider`` and ``HashEmbedder`` so tests and demos run offline.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Annotated


def _empty_str_to_none(v):
    """Treat blank or whitespace-only strings as ``None``.

    Lets ``.env`` files leave optional keys empty (``OPENAI_API_KEY=``)
    without breaking strict ``Literal`` validators.
    """
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


_OptStr = Annotated[str | None, BeforeValidator(_empty_str_to_none)]

LLMProviderName = Literal["openai", "anthropic", "mock"]
EmbeddingProviderName = Literal["openai", "hash"]


class Settings(BaseSettings):
    """Runtime configuration sourced from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- service ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # --- database ---
    database_url: str = (
        "postgresql+psycopg://openfiling:openfiling@localhost:5432/openfiling"
    )
    pgvector_dim: int = 1536

    # --- LLM / embedding providers ---
    llm_provider: Annotated[LLMProviderName | None, BeforeValidator(_empty_str_to_none)] = None
    llm_model: _OptStr = None
    embedding_provider: Annotated[
        EmbeddingProviderName | None, BeforeValidator(_empty_str_to_none)
    ] = None
    embedding_model: _OptStr = None

    # --- credentials ---
    openai_api_key: _OptStr = None
    anthropic_api_key: _OptStr = None
    alpha_vantage_api_key: _OptStr = None
    massive_api_key: _OptStr = None
    massive_base_url: str = "https://api.massive.com"

    # --- SEC EDGAR (free, default — no key required, but identify yourself) ---
    sec_edgar_user_agent: str = (
        "OpenFilingRAG/0.1 (https://github.com/yourname/openfilingrag) "
        "contact@example.invalid"
    )
    sec_edgar_cache_dir: str = "data/edgar_cache"
    sec_edgar_filings_dir: str = "data/sample_filings"

    # --- demo ---
    next_public_api_base_url: str = "http://localhost:8000"

    # --- retrieval defaults ---
    default_top_k: int = Field(default=12, ge=1, le=100)
    min_evidence_score: float = Field(default=0.05, ge=0.0, le=1.0)

    # --- cross-encoder reranker (Phase 3) ---
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_top_n: int = Field(default=10, ge=1, le=100)
    # Pool size handed to the cross-encoder. Bigger = better recall after
    # reranking, but each pair costs ~5–20 ms on CPU. 30–40 is a sane
    # default for an interactive query.
    reranker_pool_k: int = Field(default=30, ge=1, le=200)

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    @property
    def has_valid_edgar_user_agent(self) -> bool:
        """SEC requires a real contact in the User-Agent.

        See https://www.sec.gov/os/accessing-edgar-data — the default
        placeholder will get the requesting IP throttled or blocked.
        """
        ua_lower = self.sec_edgar_user_agent.lower()
        # Must contain something that looks like an email — SEC's policy
        # is "Sample Company Name AdminContact@<sample company domain>.com".
        if "@" not in ua_lower:
            return False
        domain = ua_lower.split("@", 1)[1].split()[0]  # strip trailing tokens
        if "." not in domain:
            return False
        # Block reserved-for-docs domains and obvious placeholders. RFC
        # 2606 reserves example.{com,net,org} and the .invalid / .test /
        # .localhost TLDs explicitly so they never resolve to real hosts.
        bad_domains = {"example.com", "example.net", "example.org"}
        bad_tlds = {".invalid", ".test", ".localhost", ".example"}
        if domain in bad_domains or any(domain.endswith(t) for t in bad_tlds):
            return False
        if any(token in ua_lower for token in ("yourname", "yourcompany", "you@")):
            return False
        return True

    # ---- derived helpers ----

    @property
    def effective_llm_provider(self) -> LLMProviderName:
        """Resolve the active LLM provider, falling back to mock when no keys exist."""
        if self.llm_provider:
            return self.llm_provider
        if self.openai_api_key:
            return "openai"
        if self.anthropic_api_key:
            return "anthropic"
        return "mock"

    @property
    def effective_embedding_provider(self) -> EmbeddingProviderName:
        if self.embedding_provider:
            return self.embedding_provider
        if self.openai_api_key:
            return "openai"
        return "hash"

    @property
    def is_mock_mode(self) -> bool:
        return (
            self.effective_llm_provider == "mock"
            and self.effective_embedding_provider == "hash"
        )

    @property
    def has_optional_enrichment(self) -> bool:
        """True if at least one optional paid enrichment provider is configured."""
        return bool(self.alpha_vantage_api_key or self.massive_api_key)

    @property
    def configured_enrichment_providers(self) -> list[str]:
        out = []
        if self.alpha_vantage_api_key:
            out.append("alpha_vantage")
        if self.massive_api_key:
            out.append("massive")
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    if s.is_mock_mode:
        logging.getLogger("openfilingrag").warning(
            "MOCK MODE active — no OPENAI_API_KEY or ANTHROPIC_API_KEY detected. "
            "Reports will use deterministic templates and a hash-based embedder. "
            "For real research set OPENAI_API_KEY in your .env."
        )
    return s


settings = get_settings()
