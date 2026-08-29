from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Pinned. Changing it is a release event, not a config tweak.
    DRAFTER_MODEL: str = "claude-sonnet-5"
    CLASSIFIER_MODEL: str = "claude-haiku-4-5-20251001"

    # Nudges are bounded so the scribe stays a colleague rather than a manager.
    NUDGE_MAX_PER_INCIDENT: int = 3
    NUDGE_MIN_TIMELINE_ENTRIES: int = 5
    NUDGE_HYPOTHESIS_AFTER_MIN: int = 20

    # Only needed when binding to a live workspace; the lab runs on recorded
    # threads without them.
    SLACK_BOT_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""

    # Ch 4 MCP audit surface. "stdout" runs the scribe without the fixture up.
    AUDIT_SINK: str = "stdout"
    MCP_ENDPOINT: str = "mock"

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")


settings = Settings()
