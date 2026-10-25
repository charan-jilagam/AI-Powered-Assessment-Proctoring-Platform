"""Central application settings, read once from environment variables.

Nothing in here is a secret default: in production the app refuses to start without
a real signing secret (SECRET_KEY or JWT_SECRET), a MONGODB_URI and explicit CORS origins.
"""
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("orvexa.config")


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


def _duration_minutes(raw: str, default: int) -> int:
    """'7d', '12h', '90m', '3600s' or plain minutes -> minutes."""
    m = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", raw or "")
    if not m:
        return default
    n, unit = int(m.group(1)), m.group(2) or "m"
    return max(1, {"s": n // 60, "m": n, "h": n * 60, "d": n * 1440}[unit])


def _list(name: str, default: str = "") -> List[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development").lower())
    app_name: str = "ORVEXA"
    mongodb_uri: str = field(default_factory=lambda: os.getenv("MONGODB_URI", ""))
    mongodb_db: str = field(default_factory=lambda: os.getenv("MONGODB_DB", "orvexa"))
    # JWT_SECRET is accepted as an alias so the same variable names work on Render, Heroku-style platforms and locally.
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET", ""))

    # Web / CORS
    frontend_url: str = field(default_factory=lambda: os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/"))
    cors_origins: List[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5173"))

    # Auth
    # JWT_EXPIRE (e.g. "7d") sets how long staff sign-ins last; STAFF_TOKEN_MINUTES wins if both are set.
    staff_token_minutes: int = field(default_factory=lambda: _int("STAFF_TOKEN_MINUTES", _duration_minutes(os.getenv("JWT_EXPIRE", ""), 8 * 60)))
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
    mail_from: str = field(default_factory=lambda: os.getenv("MAIL_FROM", "ORVEXA <no-reply@orvexa.local>"))
    # HTTPS mail APIs (work on hosts that block outbound SMTP, e.g. Render's free tier). Checked before SMTP.
    brevo_api_key: str = field(default_factory=lambda: os.getenv("BREVO_API_KEY", ""))
    resend_api_key: str = field(default_factory=lambda: os.getenv("RESEND_API_KEY", ""))

    # E-mail verification. Staff: org admins/reviewers must verify before creating tests.
    # Candidates: a 6-digit code e-mailed to them must be entered before they can join a test.
    staff_email_verification: bool = field(default_factory=lambda: _bool("STAFF_EMAIL_VERIFICATION", True))
    candidate_email_verification: bool = field(default_factory=lambda: _bool("CANDIDATE_EMAIL_VERIFICATION", True))
    verify_token_hours: int = field(default_factory=lambda: _int("VERIFY_TOKEN_HOURS", 48))
    email_code_minutes: int = field(default_factory=lambda: _int("EMAIL_CODE_MINUTES", 10))

    # Evidence storage: Cloudinary when configured (CLOUDINARY_URL or the three CLOUDINARY_* values), else local disk.
    cloudinary_url: str = field(default_factory=lambda: os.getenv("CLOUDINARY_URL", ""))
    cloudinary_cloud_name: str = field(default_factory=lambda: os.getenv("CLOUDINARY_CLOUD_NAME", ""))
    cloudinary_api_key: str = field(default_factory=lambda: os.getenv("CLOUDINARY_API_KEY", ""))
    cloudinary_api_secret: str = field(default_factory=lambda: os.getenv("CLOUDINARY_API_SECRET", ""))
    cloudinary_folder: str = field(default_factory=lambda: os.getenv("CLOUDINARY_FOLDER", "orvexa"))

    # Razorpay (plan purchases)
    razorpay_key_id: str = field(default_factory=lambda: os.getenv("RAZORPAY_KEY_ID", ""))
    razorpay_key_secret: str = field(default_factory=lambda: os.getenv("RAZORPAY_KEY_SECRET", ""))
    razorpay_webhook_secret: str = field(default_factory=lambda: os.getenv("RAZORPAY_WEBHOOK_SECRET", ""))

    # Serve the built frontend from this process (single-service deployments such as Render)
    static_dir: str = field(default_factory=lambda: os.getenv("STATIC_DIR", ""))

    # Proctoring evidence (local fallback)
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
    def mail_provider(self) -> str:
        """Which transport delivers e-mail: 'brevo' | 'resend' | 'smtp' | '' (none: messages are only stored in the outbox)."""
        if self.brevo_api_key:
            return "brevo"
        if self.resend_api_key:
            return "resend"
        return "smtp" if self.smtp_host else ""

    @property
    def mail_enabled(self) -> bool:
        return bool(self.mail_provider)

    @property
    def razorpay_enabled(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def cloudinary_enabled(self) -> bool:
        return bool(self.cloudinary_url or (self.cloudinary_cloud_name and self.cloudinary_api_key and self.cloudinary_api_secret))

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
        if not self.mongodb_uri:
            if self.env == "test":
                self.mongodb_uri = "mongomock://"          # in-memory fake for the automated tests only
            else:
                problems.append("MONGODB_URI must be set (e.g. mongodb+srv://user:pass@cluster/ or mongodb://localhost:27017)")
        elif not self.mongodb_uri.startswith(("mongodb://", "mongodb+srv://", "mongomock://")):
            problems.append("MONGODB_URI must start with mongodb:// or mongodb+srv://")
        if self.is_production and any("localhost" in o for o in self.cors_origins):
            log.warning("CORS_ORIGINS still contains localhost in production.")
        if self.is_production and not self.mail_enabled and (self.staff_email_verification or self.candidate_email_verification):
            log.warning("E-mail verification is on but no mail transport is configured (BREVO_API_KEY, RESEND_API_KEY or SMTP_HOST): "
                        "nobody can receive verification links or codes.")
        if problems:
            raise RuntimeError("Invalid configuration: " + "; ".join(problems))


settings = Settings()
settings.validate()
