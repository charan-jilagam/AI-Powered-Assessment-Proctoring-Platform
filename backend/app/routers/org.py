"""Everything a client organization manages about itself: profile, team, integrations, dashboard, audit."""
from datetime import timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import audit, auth, mailer, models, serializers, staff_service, tenancy, webhooks
from app.constants import (
    ATT_IN_PROGRESS, ATT_SUBMITTED, ATT_TERMINATED, ATT_VOIDED, EXAM_PUBLISHED, REVIEW_PENDING, ROLE_ADMIN, ROLE_REVIEWER,
)
from app.database import get_db
from app.errors import ApiError, bad_request, conflict, not_found
from app.pagination import PageParams, paginate
from app.schemas import ProctoringConfig
from app.timeutil import as_utc, utcnow

router = APIRouter(prefix="/org", tags=["organization"])


# ---------------------------------------------------------------------------
# profile + branding
# ---------------------------------------------------------------------------
class OrgProfilePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    brand_color: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    logo_url: Optional[str] = Field(default=None, max_length=500)
    contact_email: Optional[EmailStr] = None
    default_proctoring: Optional[ProctoringConfig] = None
    candidate_data_retention_days: Optional[int] = Field(default=None, ge=30, le=3650)


@router.get("")
def get_org(user: models.User = Depends(auth.require_org_staff), org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    settings_ = org.settings or {}
    return {
        **serializers.org_brief(org),
        "contact_email": org.contact_email,
        "trial_ends_at": org.trial_ends_at,
        "subscription_ends_at": org.subscription_ends_at,
        "default_proctoring": settings_.get("default_proctoring"),
        "candidate_data_retention_days": settings_.get("candidate_data_retention_days", 365),
        "plan": serializers.plan_out(org.plan) if org.plan else None,
        **tenancy.usage_snapshot(db, org),
    }


@router.patch("")
def update_org(body: OrgProfilePatch, request: Request, user: models.User = Depends(auth.require_org_admin),
               org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if data.get("logo_url") and not data["logo_url"].startswith("https://"):
        raise bad_request("Logo must be an https:// image URL")
    settings_ = dict(org.settings or {})
    for field in ("name", "brand_color", "logo_url", "contact_email"):
        if field in data:
            setattr(org, field, data[field] or None if field != "name" else data[field])
    if "default_proctoring" in data and body.default_proctoring is not None:
        settings_["default_proctoring"] = body.default_proctoring.model_dump()
    if "candidate_data_retention_days" in data:
        settings_["candidate_data_retention_days"] = body.candidate_data_retention_days
    org.settings = settings_
    audit.log_event(db, "ORG_SETTINGS_UPDATED", user=user, entity_type="organization", entity_id=org.id, details=", ".join(data), ip=auth.client_ip(request))
    db.commit()
    return {"status": "saved", "organization": serializers.org_brief(org)}


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------
@router.get("/dashboard")
def dashboard(user: models.User = Depends(auth.require_org_staff), org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    A, E = models.Attempt, models.Exam
    base = db.query(A).filter(A.org_id == org.id, A.status != ATT_VOIDED)
    since30 = utcnow() - timedelta(days=30)
    finals = base.filter(A.status.in_([ATT_SUBMITTED, ATT_TERMINATED]), A.submitted_at >= since30)
    submitted = finals.filter(A.status == ATT_SUBMITTED).all()
    avg_pct = round(sum(a.percentage or 0 for a in submitted) / len(submitted), 1) if submitted else None
    pass_rate = round(100 * sum(1 for a in submitted if a.passed) / len(submitted), 1) if submitted else None

    by_status = dict(db.query(E.status, func.count(E.id)).filter(E.org_id == org.id).group_by(E.status).all())
    daily = dict(
        db.query(func.date(A.started_at), func.count(A.id))
        .filter(A.org_id == org.id, A.started_at >= utcnow() - timedelta(days=14), A.status != ATT_VOIDED)
        .group_by(func.date(A.started_at)).all()
    )
    series = [{"date": (utcnow() - timedelta(days=i)).date().isoformat(), "attempts": 0} for i in range(13, -1, -1)]
    for point in series:
        point["attempts"] = int(daily.get(point["date"], 0))

    recent = (
        db.query(A, E, models.User).join(E, E.id == A.exam_id).join(models.User, models.User.id == A.candidate_id)
        .filter(A.org_id == org.id, A.status != ATT_VOIDED).order_by(A.id.desc()).limit(8).all()
    )
    flagged = (
        db.query(func.count(A.id))
        .filter(A.org_id == org.id, A.status.in_([ATT_SUBMITTED, ATT_TERMINATED]), A.review_status == REVIEW_PENDING, A.risk_score >= 15).scalar() or 0
    )
    snap = tenancy.usage_snapshot(db, org)
    return {
        "tests": {"total": sum(by_status.values()), **by_status},
        "in_progress_now": base.filter(A.status == ATT_IN_PROGRESS).count(),
        "attempts_last_30_days": finals.count(),
        "average_percentage": avg_pct,
        "pass_rate": pass_rate,
        "awaiting_review": flagged,
        "attempts_per_day": series,
        "recent_attempts": [
            {"id": a.id, "test_id": e.id, "test_title": e.title, "candidate_name": c.full_name, "candidate_email": c.email,
             "status": a.status, "percentage": a.percentage, "passed": a.passed, "risk_score": a.risk_score, "started_at": a.started_at}
            for a, e, c in recent
        ],
        **snap,
        "block_reason": auth.org_block_reason(org),
    }


# ---------------------------------------------------------------------------
# team
# ---------------------------------------------------------------------------
class TeamInvite(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    role: Literal["admin", "reviewer"] = "reviewer"


class TeamPatch(BaseModel):
    role: Optional[Literal["admin", "reviewer"]] = None
    is_active: Optional[bool] = None


def _active_admin_count(db: Session, org_id: int) -> int:
    return db.query(func.count(models.User.id)).filter(
        models.User.org_id == org_id, models.User.role == ROLE_ADMIN, models.User.is_active.is_(True)
    ).scalar() or 0


@router.get("/team")
def team(user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    rows = db.query(models.User).filter(models.User.org_id == user.org_id, models.User.role.in_([ROLE_ADMIN, ROLE_REVIEWER])).order_by(models.User.created_at).all()
    return [serializers.user_out(u) for u in rows]


@router.post("/team", status_code=201)
def invite_member(body: TeamInvite, request: Request, user: models.User = Depends(auth.require_org_admin),
                  org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    tenancy.ensure_capacity(db, org, "seat")
    created = staff_service.create_staff(db, org=org, full_name=body.full_name, email=body.email, role=body.role, invited_by=user.full_name)
    audit.log_event(db, "TEAM_MEMBER_INVITED", user=user, entity_type="user", entity_id=created["user"].id, details=f"{body.email} as {body.role}", ip=auth.client_ip(request))
    db.commit()
    return {**serializers.user_out(created["user"]), "invite_url": created["invite_url"]}


@router.patch("/team/{member_id}")
def update_member(member_id: int, body: TeamPatch, user: models.User = Depends(auth.require_org_admin),
                  org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    member = tenancy.get_org_user(db, member_id, org.id)
    if member.role not in (ROLE_ADMIN, ROLE_REVIEWER):
        raise not_found("Team member")
    if member.id == user.id and (body.is_active is False or (body.role and body.role != ROLE_ADMIN)):
        raise bad_request("You cannot remove your own admin access")
    losing_admin = member.role == ROLE_ADMIN and member.is_active and (body.is_active is False or (body.role and body.role != ROLE_ADMIN))
    if losing_admin and _active_admin_count(db, org.id) <= 1:
        raise bad_request("An organization needs at least one active admin")
    if body.is_active is True and not member.is_active:
        tenancy.ensure_capacity(db, org, "seat")
    if body.role:
        member.role = body.role
    if body.is_active is not None:
        member.is_active = body.is_active
        if not body.is_active:
            member.token_version += 1
    audit.log_event(db, "TEAM_MEMBER_UPDATED", user=user, entity_type="user", entity_id=member.id, details=str(body.model_dump(exclude_none=True)))
    db.commit()
    return serializers.user_out(member)


@router.post("/team/{member_id}/reset-link")
def member_reset_link(member_id: int, user: models.User = Depends(auth.require_org_admin),
                      org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    member = tenancy.get_org_user(db, member_id, org.id)
    raw = staff_service.issue_token(db, member, "reset")
    url = staff_service.activation_url(raw, "reset")
    mailer.queue_email(db, member.email, "Reset your ProctorAI password",
                       mailer.render("Reset your password", [f"Hi {member.full_name},", f"{user.full_name} issued a password reset link for your account."],
                                     cta_label="Choose a new password", cta_url=url, org_name=org.name, brand=org.brand_color), org_id=org.id)
    audit.log_event(db, "RESET_LINK_ISSUED", user=user, entity_type="user", entity_id=member.id)
    db.commit()
    return {"reset_url": url}


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
class ApiKeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


@router.get("/api-keys")
def list_keys(user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    rows = db.query(models.ApiKey).filter(models.ApiKey.org_id == user.org_id).order_by(models.ApiKey.id.desc()).all()
    return [{"id": k.id, "name": k.name, "key_prefix": k.key_prefix, "created_at": k.created_at, "last_used_at": k.last_used_at,
             "revoked": k.revoked_at is not None} for k in rows]


@router.post("/api-keys", status_code=201)
def create_key(body: ApiKeyIn, user: models.User = Depends(auth.require_org_admin),
               org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    tenancy.ensure_feature(org, "api_access", "API access")
    if db.query(func.count(models.ApiKey.id)).filter(models.ApiKey.org_id == org.id, models.ApiKey.revoked_at.is_(None)).scalar() >= 10:
        raise bad_request("You can have at most 10 active API keys")
    raw = "pk_live_" + auth.new_token(30)
    key = models.ApiKey(org_id=org.id, name=body.name.strip(), key_prefix=raw[:12], key_hash=auth.hash_token(raw), created_by=user.id)
    db.add(key)
    audit.log_event(db, "API_KEY_CREATED", user=user, entity_type="api_key", details=body.name)
    db.commit()
    return {"id": key.id, "name": key.name, "key": raw, "key_prefix": key.key_prefix,
            "notice": "Copy this key now - it will never be shown again."}


@router.delete("/api-keys/{key_id}")
def revoke_key(key_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    key = db.query(models.ApiKey).filter(models.ApiKey.id == key_id, models.ApiKey.org_id == user.org_id).first()
    if key is None:
        raise not_found("API key")
    key.revoked_at = utcnow()
    audit.log_event(db, "API_KEY_REVOKED", user=user, entity_type="api_key", entity_id=key.id)
    db.commit()
    return {"status": "revoked"}


# ---------------------------------------------------------------------------
# webhooks
# ---------------------------------------------------------------------------
class WebhookIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    events: List[str] = []
    is_active: bool = True


def _hook_out(h: models.Webhook, reveal: bool = False) -> Dict[str, Any]:
    return {"id": h.id, "url": h.url, "events": h.events or [], "is_active": h.is_active, "created_at": h.created_at,
            **({"secret": h.secret} if reveal else {"secret_hint": h.secret[:10] + "…"})}


def _validate_hook(body: WebhookIn) -> None:
    unknown = [e for e in body.events if e not in webhooks.EVENTS]
    if unknown:
        raise bad_request(f"Unknown event(s): {', '.join(unknown)}")
    problem = webhooks.check_url(body.url)
    if problem:
        raise bad_request(problem, "bad_webhook_url")


@router.get("/webhooks/events")
def webhook_events(user: models.User = Depends(auth.require_org_admin)):
    return list(webhooks.EVENTS)


@router.get("/webhooks")
def list_hooks(user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    return [_hook_out(h) for h in db.query(models.Webhook).filter(models.Webhook.org_id == user.org_id).order_by(models.Webhook.id).all()]


@router.post("/webhooks", status_code=201)
def create_hook(body: WebhookIn, user: models.User = Depends(auth.require_org_admin),
                org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    tenancy.ensure_feature(org, "webhooks_enabled", "Webhooks")
    _validate_hook(body)
    hook = models.Webhook(org_id=org.id, url=body.url, events=body.events, is_active=body.is_active, secret=webhooks.new_secret())
    db.add(hook)
    audit.log_event(db, "WEBHOOK_CREATED", user=user, entity_type="webhook", details=body.url)
    db.commit()
    return _hook_out(hook, reveal=True)


def _hook(db: Session, hook_id: int, org_id: int) -> models.Webhook:
    hook = db.query(models.Webhook).filter(models.Webhook.id == hook_id, models.Webhook.org_id == org_id).first()
    if hook is None:
        raise not_found("Webhook")
    return hook


@router.put("/webhooks/{hook_id}")
def update_hook(hook_id: int, body: WebhookIn, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    hook = _hook(db, hook_id, user.org_id)
    _validate_hook(body)
    hook.url, hook.events, hook.is_active = body.url, body.events, body.is_active
    db.commit()
    return _hook_out(hook)


@router.delete("/webhooks/{hook_id}")
def delete_hook(hook_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    hook = _hook(db, hook_id, user.org_id)
    db.query(models.WebhookDelivery).filter(models.WebhookDelivery.webhook_id == hook.id).delete()
    db.delete(hook)
    audit.log_event(db, "WEBHOOK_DELETED", user=user, entity_type="webhook", entity_id=hook_id)
    db.commit()
    return {"status": "deleted"}


@router.post("/webhooks/{hook_id}/test")
def test_hook(hook_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    hook = _hook(db, hook_id, user.org_id)
    delivery = models.WebhookDelivery(org_id=user.org_id, webhook_id=hook.id, event="ping", payload={"event": "ping", "data": {"message": "Hello from ProctorAI"}})
    db.add(delivery)
    db.flush()
    from app.background import after_commit
    after_commit(db, webhooks.deliver, delivery.id)
    db.commit()
    return {"delivery_id": delivery.id}


@router.get("/webhooks/{hook_id}/deliveries")
def hook_deliveries(hook_id: int, params: PageParams = Depends(), user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    _hook(db, hook_id, user.org_id)
    q = db.query(models.WebhookDelivery).filter(models.WebhookDelivery.webhook_id == hook_id).order_by(models.WebhookDelivery.id.desc())
    return paginate(q, params, lambda d: {"id": d.id, "event": d.event, "success": d.success, "status_code": d.status_code,
                                          "attempts": d.attempts, "error": d.error, "created_at": d.created_at})


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------
@router.get("/audit-log")
def org_audit(action: Optional[str] = None, params: PageParams = Depends(), user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    q = db.query(models.AuditLog).filter(models.AuditLog.org_id == user.org_id)
    if action:
        q = q.filter(models.AuditLog.action == action)
    return paginate(q.order_by(models.AuditLog.id.desc()), params, lambda a: {
        "id": a.id, "actor_email": a.actor_email, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
        "details": a.details, "ip_address": a.ip_address, "created_at": a.created_at})
