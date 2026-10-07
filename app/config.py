"""Application settings.

Env-driven and validated at boot: a missing or malformed setting fails the process
immediately rather than surfacing as a confusing error hours later in a worker.
No secrets in code, ever (see CLAUDE.md).
"""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-not-a-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GRANTS_",
        extra="ignore",
    )

    # Runtime
    env: Literal["development", "testing", "production"] = "development"
    # Signs the session cookie and the sign-in links (app/web/account): in production it
    # must be a real secret, or anyone could mint a link into any account.
    secret_key: str = DEV_SECRET
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

    # Where `flask review export-cases` writes the evaluation cases reviewer
    # decisions become (app/review/cases.py). On the VPS a bind mount of the
    # checkout's evals/cases/from_review, pulled and committed by hand (runbook §7).
    review_cases_dir: str = "evals/cases/from_review"

    # Locale. Macedonian Cyrillic is the launch language (brief 3.1).
    default_language: str = "mk"
    timezone: str = "Europe/Skopje"

    # healthchecks.io check URLs (app/heartbeat.py). The ingest check is pinged by
    # every `flask ingest due`, so silence means cron or the box is dead; the health
    # check is told by `flask ingest health` whether any source needs attention.
    # Unset in development; `flask ingest health` refuses to run without it in production.
    heartbeat_ingest_url: str | None = None
    heartbeat_health_url: str | None = None

    # Hard ceiling on model spend, alarmed rather than enforced (decisions.md D8).
    model_spend_ceiling_eur: float = Field(default=30.0, ge=0)

    # Mail (app/mail.py, P3 s44). "outbox" writes each message as an .eml file to
    # outbox_dir, for development and tests; production sends by SMTP from the domain
    # D2 decides, and refuses to send at all until it is configured.
    mail_backend: Literal["outbox", "smtp"] = "outbox"
    outbox_dir: str = "var/outbox"
    mail_from: str = "Грантови и субвенции <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None

    @model_validator(mode="after")
    def _a_real_secret_in_production(self) -> "Settings":
        if self.is_production and (self.secret_key == DEV_SECRET or len(self.secret_key) < 32):
            raise ValueError(
                "GRANTS_SECRET_KEY must be a real secret (32+ characters) in production"
            )
        return self

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
