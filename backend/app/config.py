"""Central application settings, read once from environment variables.

Nothing in here is a secret default: in production the app refuses to start without
a real SECRET_KEY, a DATABASE_URL and explicit CORS origins.
"""
import logging
import os
import secrets
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("proctorai.config")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _list(name: str, default: str = "") -> List[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development").lower())
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", ""))

    # Web / CORS
    frontend_url: str = field(default_factory=lambda: os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/"))
    cors_origins: List[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5173"))

    # Auth
    staff_token_minutes: int = field(default_factory=lambda: _int("STAFF_TOKEN_MINUTES", 8 * 60))
    candidate_token_minutes: int = field(default_factory=lambda: _int("CANDIDATE_TOKEN_MINUTES", 12 * 60))
    max_failed_logins: int = field(default_factory=lambda: _int("MAX_FAILED_LOGINS", 5))
    lockout_minutes: int = field(default_factory=lambda: _int("LOCKOUT_MINUTES", 15))
    reset_token_hours: int = field(default_factory=lambda: _int("RESET_TOKEN_HOURS", 2))
    invite_token_days: int = field(default_factory=lambda: _int("INVITE_TOKEN_DAYS", 7))

    # Bootstrap of the very first platform owner (idempotent)
    superadmin_email: str = field(default_factory=lambda: os.getenv("SUPERADMIN_EMAIL", ""))
    superadmin_password: str = field(default_factory=lambda: os.getenv("SUPERADMIN_PASSWORD", ""))
    superadmin_name: str = field(default_factory=lambda: os.getenv("SUPERADMIN_NAME", "Platform Owner"))

    # Email (SMTP). If SMTP_HOST is empty, emails are only recorded in the outbox table.
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    smtp_starttls: bool = field(default_factory=lambda: _bool("SMTP_STARTTLS", True))
    mail_from: str = field(default_factory=lambda: os.getenv("MAIL_FROM", "ProctorAI <no-reply@proctorai.local>"))

    # Proctoring evidence
    evidence_dir: str = field(default_factory=lambda: os.getenv("EVIDENCE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "evidence")))
    max_image_bytes: int = field(default_factory=lambda: _int("MAX_IMAGE_BYTES", 400_000))
    ai_proctoring_enabled: bool = field(default_factory=lambda: _bool("AI_PROCTORING_ENABLED", True))

    # Platform behaviour
    trial_days: int = field(default_factory=lambda: _int("TRIAL_DAYS", 14))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    sweeper_interval_seconds: int = field(default_factory=lambda: _int("SWEEPER_INTERVAL_SECONDS", 60))
    run_sweeper: bool = field(default_factory=lambda: _bool("RUN_SWEEPER", True))
    allow_private_webhooks: bool = field(default_factory=lambda: _bool("ALLOW_PRIVATE_WEBHOOKS", False))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate(self) -> None:
        problems = []
        if not self.secret_key:
            if self.is_production:
                problems.append("SECRET_KEY must be set in production")
            else:
                self.secret_key = secrets.token_hex(32)
                log.warning("SECRET_KEY not set - using a random key for this process (all tokens die on restart).")
        elif self.is_production and len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be at least 32 characters in production")
        if not self.database_url:
            if self.is_production:
                problems.append("DATABASE_URL must be set in production")
            else:
                self.database_url = "sqlite:///./proctorai_dev.db"
        if self.is_production and any("localhost" in o for o in self.cors_origins):
            log.warning("CORS_ORIGINS still contains localhost in production.")
        if problems:
            raise RuntimeError("Invalid configuration: " + "; ".join(problems))


settings = Settings()
settings.validate()
