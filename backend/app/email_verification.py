"""Proof of mailbox ownership for candidates: a 6-digit code e-mailed to the address they typed.

The code is stored only as an HMAC, expires after EMAIL_CODE_MINUTES, allows MAX_ATTEMPTS guesses, and a new code
cannot be requested more than once per RESEND_SECONDS or more than MAX_PER_HOUR times per address and test.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from app.mongo import func
from app.mongo import Session

from app import mailer, models
from app.config import settings
from app.errors import ApiError
from app.timeutil import as_utc, utcnow

MAX_ATTEMPTS = 5
RESEND_SECONDS = 45
MAX_PER_HOUR = 6


def _hash(exam_id: int, email: str, code: str) -> str:
    msg = f"{exam_id}:{email}:{code}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


def issue(db: Session, exam: models.Exam, org: models.Organization, email: str, full_name: str = "") -> str:
    """Create and e-mail a fresh code (older unused codes stop working). The caller commits. Returns the code."""
    now = utcnow()
    recent = db.query(models.EmailCode).filter(models.EmailCode.exam_id == exam.id, models.EmailCode.email == email,
                                               models.EmailCode.created_at >= now - timedelta(hours=1)).order_by(models.EmailCode.id.desc()).all()
    if recent and (now - as_utc(recent[0].created_at)).total_seconds() < RESEND_SECONDS:
        wait = int(RESEND_SECONDS - (now - as_utc(recent[0].created_at)).total_seconds()) + 1
        raise ApiError(429, f"A code was just sent. You can ask for another in {wait} seconds.", "code_cooldown")
    if len(recent) >= MAX_PER_HOUR:
        raise ApiError(429, "Too many codes requested for this address. Try again in an hour.", "code_limit")
    db.query(models.EmailCode).filter(models.EmailCode.exam_id == exam.id, models.EmailCode.email == email,
                                      models.EmailCode.used_at.is_(None)).update({"used_at": now})
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(models.EmailCode(org_id=org.id, exam_id=exam.id, email=email, code_hash=_hash(exam.id, email, code),
                            expires_at=now + timedelta(minutes=settings.email_code_minutes)))
    greeting = f"Hi {full_name}," if full_name else "Hello,"
    mailer.queue_email(
        db, email, f"Your verification code for {exam.title}",
        mailer.render("Confirm your e-mail address",
                      [greeting, f"Your code to join “{exam.title}” is:", code,
                       f"It works for {settings.email_code_minutes} minutes. If you did not ask for it, ignore this message."],
                      org_name=org.name, brand=org.brand_color),
        org_id=org.id,
    )
    return code


def check(db: Session, exam: models.Exam, email: str, code: str) -> None:
    """Accept the code (and burn it) or raise. Failed guesses are committed so they count even though the request errors."""
    row = (db.query(models.EmailCode).filter(models.EmailCode.exam_id == exam.id, models.EmailCode.email == email,
                                             models.EmailCode.used_at.is_(None)).order_by(models.EmailCode.id.desc()).first())
    if row is None or as_utc(row.expires_at) < utcnow():
        raise ApiError(400, "That code has expired. Ask for a new one.", "email_code_expired")
    if row.attempts >= MAX_ATTEMPTS:
        raise ApiError(429, "Too many wrong codes. Ask for a new one.", "email_code_locked")
    if not hmac.compare_digest(row.code_hash, _hash(exam.id, email, (code or "").strip())):
        row.attempts += 1
        db.commit()
        left = MAX_ATTEMPTS - row.attempts
        raise ApiError(400, f"That code is not right. {left} attempt(s) left." if left > 0 else "Too many wrong codes. Ask for a new one.", "email_code_wrong")
    row.used_at = utcnow()
