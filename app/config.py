"""Application settings.

Env-driven and validated at boot: a missing or malformed setting fails the process
immediately rather than surfacing as a confusing error hours later in a worker.
No secrets in code, ever (see CLAUDE.md).
"""

from typing import Literal

from pydantic import Field, model_validator
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

    # Browser auto-refresh on file changes (app/web/devreload.py). Development
    # only; enabled by docker-compose.dev.yml, and refused in production.
    live_reload: bool = False

    # Release identifier, surfaced by /healthz so a deploy can be confirmed.
    # Set from the git SHA at build time.
    version: str = "dev"

    # Storage. Stored as a plain libpq URL so psycopg can use it directly;
    # SQLAlchemy gets the dialect-qualified form from sqlalchemy_url below.
    database_url: str = "postgresql://grants:grants@localhost:5432/grants"
    redis_url: str = "redis://localhost:6379/0"

    # Raw fetched bytes, content-addressed (app/ingestion/snapshots.py). Copied
    # off-site by ops/backup.sh.
    snapshot_dir: str = "snapshots"

    # The local embedding model's files (app/retrieval/embedder.py), fetched once
    # with `flask ingest fetch-model`. About 2.2 GB; a Docker volume on the VPS.
    model_dir: str = "models"

    # Where a site operator can read what the crawler does and ask it to stop.
    # Becomes https://<domain>/crawler once the domain exists (decisions.md D2).
    crawler_contact_url: str = "https://github.com/soykandiso/claudeproba"

    # Locale. Macedonian Cyrillic is the launch language (brief 3.1).
    default_language: str = "mk"
    timezone: str = "Europe/Skopje"

    # Hard ceiling on model spend, alarmed rather than enforced (decisions.md D8).
    model_spend_ceiling_eur: float = Field(default=30.0, ge=0)

    @model_validator(mode="after")
    def _no_live_reload_in_production(self) -> "Settings":
        if self.live_reload and self.is_production:
            raise ValueError("GRANTS_LIVE_RELOAD must not be enabled in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def sqlalchemy_url(self) -> str:
        """The database URL in SQLAlchemy's dialect-qualified form."""
        scheme, _, rest = self.database_url.partition("://")
        return f"{scheme}+psycopg://{rest}"


def load_settings(**overrides: object) -> Settings:
    """Build settings, allowing tests to override without touching the environment."""
    return Settings(**overrides)  # type: ignore[arg-type]
