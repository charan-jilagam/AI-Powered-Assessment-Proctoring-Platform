"""Authentication, tokens and the permission dependencies every router builds on."""
import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from typing import Callable, Optional

import bcrypt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.constants import (
    ORG_ACTIVE, ORG_TRIAL, ROLE_ADMIN, ROLE_CANDIDATE, ROLE_REVIEWER, ROLE_SUPER_ADMIN,
)
from app.database import get_db
from app.errors import ApiError, forbidden
from app.timeutil import as_utc, utcnow

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


# ---------------------------------------------------------------------------
# passwords
# ---------------------------------------------------------------------------
def _prehash(password: str) -> bytes:
    # bcrypt silently/loudly breaks past 72 bytes; hashing first makes any length safe.
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(_prehash(plain_password), hashed_password.encode("utf-8"))
    except ValueError:
        return False


_DUMMY_HASH = hash_password("dummy-password-for-timing")


def burn_password_check(plain_password: str) -> None:
    """Spend the same time as a real check so 'unknown email' is not distinguishable from 'wrong password'."""
    verify_password(plain_password, _DUMMY_HASH)


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if not re.search(r"[A-Za-z]", password):
        problems.append("a letter")
    if not re.search(r"\d", password):
        problems.append("a number")
    return problems


def validate_password(password: str) -> None:
    problems = password_problems(password)
    if problems:
        raise ApiError(400, "Password must contain " + ", ".join(problems), "weak_password")


# ---------------------------------------------------------------------------
# opaque tokens (reset / invite / api keys / invites)
# ---------------------------------------------------------------------------
def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(user: models.User, *, attempt: Optional[models.Attempt] = None) -> str:
    is_candidate = user.role == ROLE_CANDIDATE
    minutes = settings.candidate_token_minutes if is_candidate else settings.staff_token_minutes
    claims = {
        "sub": str(user.id),
        "role": user.role,
        "org": user.org_id,
        "tv": user.token_version,
        "exp": utcnow() + timedelta(minutes=minutes),
    }
    if attempt is not None:
        claims["aid"] = attempt.id
        claims["sn"] = attempt.session_nonce
    return jwt.encode(claims, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise ApiError(401, "Could not validate credentials", "invalid_token")


# ---------------------------------------------------------------------------
# organization state
# ---------------------------------------------------------------------------
def org_block_reason(org: Optional[models.Organization]) -> Optional[str]:
    """Why this organization may not operate right now (None = fine)."""
    if org is None:
        return None
    if org.status == "suspended":
        return org.suspended_reason or "This organization's account is suspended."
    if org.status == "cancelled":
        return "This organization's account has been closed."
    now = utcnow()
    if org.status == ORG_TRIAL and org.trial_ends_at and as_utc(org.trial_ends_at) < now:
        return "The free trial has ended. Please contact the platform owner to activate a plan."
    if org.status == ORG_ACTIVE and org.subscription_ends_at and as_utc(org.subscription_ends_at) < now:
        return "The subscription has expired. Please renew to continue."
    return None


# ---------------------------------------------------------------------------
# current user
# ---------------------------------------------------------------------------
def _user_from_api_key(db: Session, raw: str) -> models.User:
    key = db.query(models.ApiKey).filter(models.ApiKey.key_hash == hash_token(raw), models.ApiKey.revoked_at.is_(None)).first()
    if not key:
        raise ApiError(401, "Invalid API key", "invalid_api_key")
    owner = db.get(models.User, key.created_by)
    if not owner or not owner.is_active or owner.role != ROLE_ADMIN or owner.org_id != key.org_id:
        raise ApiError(401, "This API key's owner is no longer active", "invalid_api_key")
    org = db.get(models.Organization, key.org_id)
    plan = org.plan if org else None
    if plan is not None and not plan.api_access and not (org.limits_override or {}).get("api_access"):
        raise forbidden("API access is not included in this organization's plan", "plan_feature")
    key.last_used_at = utcnow()
    db.commit()
    owner._via_api_key = True  # type: ignore[attr-defined]
    return owner


def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    raw = token
    if not raw:
        raw = request.headers.get("X-API-Key")
    if not raw:
        raise ApiError(401, "Not authenticated", "not_authenticated")

    if raw.startswith("pk_"):
        user = _user_from_api_key(db, raw)
        request.state.claims = {}
    else:
        claims = decode_token(raw)
        try:
            user = db.get(models.User, int(claims.get("sub")))
        except (TypeError, ValueError):
            raise ApiError(401, "Could not validate credentials", "invalid_token")
        if user is None or not user.is_active:
            raise ApiError(401, "Could not validate credentials", "invalid_token")
        if claims.get("tv") != user.token_version:
            raise ApiError(401, "Your session has expired. Please sign in again.", "session_revoked")
        request.state.claims = claims

    if user.org_id and user.role != ROLE_CANDIDATE:
        reason = org_block_reason(db.get(models.Organization, user.org_id))
        if reason and request.url.path not in ("/auth/me", "/auth/logout-all"):
            raise ApiError(403, reason, "org_blocked")
    return user


def require_roles(*roles: str) -> Callable:
    allowed = set(roles)

    def dependency(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in allowed:
            raise forbidden()
        return user

    return dependency


require_super_admin = require_roles(ROLE_SUPER_ADMIN)
require_org_admin = require_roles(ROLE_ADMIN)
require_org_staff = require_roles(ROLE_ADMIN, ROLE_REVIEWER)
require_any_staff = require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_REVIEWER)


def get_current_org(user: models.User = Depends(require_org_staff), db: Session = Depends(get_db)) -> models.Organization:
    org = db.get(models.Organization, user.org_id)
    if org is None:
        raise ApiError(403, "Organization not found", "org_missing")
    return org


def client_ip(request: Request) -> str:
    # Behind nginx / a load balancer uvicorn rewrites request.client when --proxy-headers is on.
    return request.client.host if request.client else "unknown"
