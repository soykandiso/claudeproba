"""Application settings.

Env-driven and validated at boot: a missing or malformed setting fails the process
immediately rather than surfacing as a confusing error hours later in a worker.
No secrets in code, ever (see CLAUDE.md).
"""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GRANTS_",
        extra="ignore",
    )

    # Runtime
    env: Literal["development", "testing", "production"] = "development"
    secret_key: str = "dev-only-not-a-secret"
    debug: bool = False

    # Release identifier, surfaced by /healthz so a deploy can be confirmed.
    # Set from the git SHA at build time.
    version: str = "dev"

    # Storage. Populated in P0.5 session 2 (compose) and session 3 (models).
    database_url: str = "postgresql+psycopg://grants:grants@localhost:5432/grants"
    redis_url: str = "redis://localhost:6379/0"

    # Locale. Macedonian Cyrillic is the launch language (brief 3.1).
    default_language: str = "mk"
    timezone: str = "Europe/Skopje"

    # Hard ceiling on model spend, alarmed rather than enforced (decisions.md D8).
    model_spend_ceiling_eur: float = Field(default=30.0, ge=0)

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def load_settings(**overrides: object) -> Settings:
    """Build settings, allowing tests to override without touching the environment."""
    return Settings(**overrides)  # type: ignore[arg-type]
