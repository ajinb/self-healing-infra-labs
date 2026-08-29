"""Settings. Every knob the chapter's SLO targets depend on is here."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Pin to a dated/versioned model. A model change is a dependency upgrade
    # and gets an eval pass, not a silent rollout.
    TRIAGE_MODEL: str = "claude-sonnet-5"

    # Chapter 5 budget: 1.5s context retrieval + 2.5s model = 4s median.
    CONTEXT_TIMEOUT_S: float = 1.5
    MODEL_TIMEOUT_S: float = 2.5

    # Token-budget pre-flight: refuse rather than truncate. Truncation silently
    # drops the context that made the answer worth having.
    MAX_CONTEXT_TOKENS: int = 6000

    # MCP surface from Chapter 4. "mock" replays fixtures so the lab runs
    # without standing up the Ch 4 fixture.
    MCP_ENDPOINT: str = "mock"

    BREAKER_FAIL_MAX: int = 5
    BREAKER_RESET_TIMEOUT_S: float = 30.0

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")


settings = Settings()
