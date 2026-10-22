"""Plan limits, usage metering and tenant-scoped lookups."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.constants import (
    ATT_VOIDED, EXAM_PUBLISHED, ORG_ACTIVE, ORG_TRIAL, ROLE_ADMIN, ROLE_REVIEWER, UNLIMITED,
)
from app.errors import ApiError, forbidden, not_found

LIMIT_KEYS = ("max_admins", "max_active_tests", "max_candidates_per_month", "evidence_retention_days")
FEATURE_KEYS = ("ai_proctoring", "coding_enabled", "api_access", "webhooks_enabled")

# What a tenant with no plan assigned may do (should not happen in practice).
_FALLBACK = {"max_admins": 1, "max_active_tests": 1, "max_candidates_per_month": 10, "evidence_retention_days": 7,
             "ai_proctoring": False, "coding_enabled": False, "api_access": False, "webhooks_enabled": False}


def effective_limits(org: models.Organization) -> Dict[str, Any]:
    """Plan values, overridden key-by-key by the organization's custom deal terms."""
    base = dict(_FALLBACK)
    if org.plan is not None:
        for key in LIMIT_KEYS + FEATURE_KEYS:
            base[key] = getattr(org.plan, key)
    for key, value in (org.limits_override or {}).items():
        if key in base and value is not None:
            base[key] = value
    return base


def month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage_snapshot(db: Session, org: models.Organization) -> Dict[str, Any]:
    limits = effective_limits(org)
    seats = db.query(func.count(models.User.id)).filter(
        models.User.org_id == org.id, models.User.role.in_([ROLE_ADMIN, ROLE_REVIEWER]), models.User.is_active.is_(True)
    ).scalar() or 0
    active_tests = db.query(func.count(models.Exam.id)).filter(
        models.Exam.org_id == org.id, models.Exam.status == EXAM_PUBLISHED
    ).scalar() or 0
    candidates_this_month = db.query(func.count(models.Attempt.id)).filter(
        models.Attempt.org_id == org.id, models.Attempt.started_at >= month_start(), models.Attempt.status != ATT_VOIDED
    ).scalar() or 0
    total_tests = db.query(func.count(models.Exam.id)).filter(models.Exam.org_id == org.id).scalar() or 0
    return {
        "limits": limits,
        "usage": {
            "team_seats": seats,
            "active_tests": active_tests,
            "candidates_this_month": candidates_this_month,
            "total_tests": total_tests,
        },
    }


def _over(limit: int, used: int) -> bool:
    return limit != UNLIMITED and used >= limit


def ensure_capacity(db: Session, org: models.Organization, what: str) -> None:
    """Raise a clear 402 when creating/starting one more `what` would exceed the plan."""
    snap = usage_snapshot(db, org)
    limits, usage = snap["limits"], snap["usage"]
    if what == "seat" and _over(limits["max_admins"], usage["team_seats"]):
        raise ApiError(402, f"Your plan allows {limits['max_admins']} team members. Upgrade to add more.", "plan_limit")
    if what == "active_test" and _over(limits["max_active_tests"], usage["active_tests"]):
        raise ApiError(402, f"Your plan allows {limits['max_active_tests']} published tests at a time. Close one or upgrade.", "plan_limit")
    if what == "candidate" and _over(limits["max_candidates_per_month"], usage["candidates_this_month"]):
        raise ApiError(402, "The monthly candidate allowance for this organization has been used up.", "plan_limit")


def ensure_feature(org: models.Organization, feature: str, label: str) -> None:
    if not effective_limits(org).get(feature):
        raise ApiError(402, f"{label} is not included in your current plan.", "plan_feature")


# ---------------------------------------------------------------------------
# tenant-scoped lookups: the ONLY way routers fetch tenant data by id
# ---------------------------------------------------------------------------
def get_exam(db: Session, exam_id: int, org_id: int) -> models.Exam:
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id, models.Exam.org_id == org_id).first()
    if exam is None:
        raise not_found("Test")
    return exam


def get_attempt(db: Session, attempt_id: int, org_id: int) -> models.Attempt:
    attempt = db.query(models.Attempt).filter(models.Attempt.id == attempt_id, models.Attempt.org_id == org_id).first()
    if attempt is None:
        raise not_found("Attempt")
    return attempt


def get_org_user(db: Session, user_id: int, org_id: int) -> models.User:
    user = db.query(models.User).filter(models.User.id == user_id, models.User.org_id == org_id).first()
    if user is None:
        raise not_found("User")
    return user


def slugify(value: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or "org"


def unique_slug(db: Session, base: str) -> str:
    slug = slugify(base)
    candidate, n = slug, 2
    while db.query(models.Organization.id).filter(models.Organization.slug == candidate).first():
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def trial_or_active(org: models.Organization) -> bool:
    return org.status in (ORG_TRIAL, ORG_ACTIVE)
