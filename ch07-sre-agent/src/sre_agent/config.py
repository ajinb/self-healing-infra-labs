from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Cost/quality split: planning quality matters more than per-call cost;
    # workers run narrow, well-specified tasks on a cheaper model.
    PLANNING_MODEL: str = "claude-opus-5"
    DIAGNOSIS_MODEL: str = "claude-sonnet-5"
    RETRIEVAL_MODEL: str = "claude-sonnet-5"

    # Chapter 7 budget: <=16s, <=$0.15 per investigation.
    CHAIN_DEADLINE_MS: int = 16_000
    COST_CEILING_USD: float = 0.15
    MAX_RETRIEVAL_SUBTASKS: int = 3

    # Pre-flight, not truncation. Over budget returns a structured error and
    # the on-call sees the raw alert.
    MAX_CHAIN_TOKENS: int = 8_000

    MCP_ENDPOINT: str = "mock"

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")


settings = Settings()
