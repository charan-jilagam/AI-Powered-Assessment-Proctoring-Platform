"""Platform owner console: tenants, plans, platform staff, platform-wide health and audit."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import audit, auth, mailer, models, serializers, staff_service, tenancy
from app.config import settings
from app.constants import (
    ATT_VOIDED, EXAM_PUBLISHED, ORG_ACTIVE, ORG_CANCELLED, ORG_STATUSES, ORG_SUSPENDED, ORG_TRIAL,
    ROLE_ADMIN, ROLE_CANDIDATE, ROLE_REVIEWER, ROLE_SUPER_ADMIN,
)
from app.database import get_db
from app.errors import ApiError, bad_request, conflict, not_found
from app.pagination import PageParams, paginate
from app.timeutil import as_utc, utcnow

router = APIRouter(prefix="/superadmin", tags=["super admin"])


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------
class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: Optional[str] = Field(default=None, max_length=80)
    plan_code: str
    status: Literal["trial", "active"] = "trial"
    trial_days: Optional[int] = Field(default=None, ge=1, le=365)
    subscription_ends_at: Optional[datetime] = None
    contact_email: Optional[EmailStr] = None
    internal_notes: Optional[str] = None
    admin_name: str = Field(min_length=2, max_length=160)
    admin_email: EmailStr
    admin_temp_password: Optional[str] = None
    send_invite: bool = True


class OrgPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    plan_code: Optional[str] = None
    status: Optional[Literal["trial", "active", "suspended", "cancelled"]] = None
    suspended_reason: Optional[str] = Field(default=None, max_length=300)
    trial_ends_at: Optional[datetime] = None
    subscription_ends_at: Optional[datetime] = None
    contact_email: Optional[EmailStr] = None
    internal_notes: Optional[str] = None
    limits_override: Optional[Dict[str, Any]] = None


class PlanIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_-]{2,40}$")
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = None
    price_monthly: int = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    max_admins: int = Field(default=3, ge=-1)
    max_active_tests: int = Field(default=3, ge=-1)
    max_candidates_per_month: int = Field(default=50, ge=-1)
    ai_proctoring: bool = True
    coding_enabled: bool = True
    api_access: bool = False
    webhooks_enabled: bool = False
    evidence_retention_days: int = Field(default=30, ge=1, le=3650)
    is_public: bool = True
    is_active: bool = True
    sort_order: int = 0


class AdminCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    role: Literal["admin", "reviewer"] = "admin"
    temp_password: Optional[str] = None
    send_invite: bool = True


class UserPatch(BaseModel):
    is_active: Optional[bool] = None
    role: Optional[Literal["admin", "reviewer"]] = None


class DemoPatch(BaseModel):
    status: Literal["new", "contacted", "converted", "dismissed"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _org(db: Session, org_id: int) -> models.Organization:
    org = db.get(models.Organization, org_id)
    if org is None:
        raise not_found("Organization")
    return org


def _plan_by_code(db: Session, code: str) -> models.Plan:
    plan = db.query(models.Plan).filter(models.Plan.code == code).first()
    if plan is None:
        raise bad_request(f"Unknown plan '{code}'", "unknown_plan")
    return plan


def _clean_overrides(raw: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in tenancy.LIMIT_KEYS:
            if not isinstance(value, int) or isinstance(value, bool) or value < -1:
                raise bad_request(f"'{key}' must be a whole number (-1 = unlimited)")
            clean[key] = value
        elif key in tenancy.FEATURE_KEYS:
            if not isinstance(value, bool):
                raise bad_request(f"'{key}' must be true or false")
            clean[key] = value
        else:
            raise bad_request(f"Unknown limit '{key}'")
    return clean


def _org_row(db: Session, org: models.Organization) -> Dict[str, Any]:
    snap = tenancy.usage_snapshot(db, org)
    return {
        "id": org.id, "name": org.name, "slug": org.slug, "status": org.status,
        "plan_code": org.plan.code if org.plan else None, "plan_name": org.plan.name if org.plan else None,
        "contact_email": org.contact_email, "trial_ends_at": org.trial_ends_at,
        "subscription_ends_at": org.subscription_ends_at, "created_at": org.created_at,
        "block_reason": auth.org_block_reason(org), "usage": snap["usage"], "limits": snap["limits"],
    }


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------
@router.get("/overview")
def overview(user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    by_status = dict(db.query(models.Organization.status, func.count(models.Organization.id)).group_by(models.Organization.status).all())
    month = tenancy.month_start()
    attempts_month = db.query(func.count(models.Attempt.id)).filter(models.Attempt.started_at >= month, models.Attempt.status != ATT_VOIDED).scalar() or 0
    since = utcnow() - timedelta(days=30)
    daily = dict(
        db.query(func.date(models.Attempt.started_at), func.count(models.Attempt.id))
        .filter(models.Attempt.started_at >= since, models.Attempt.status != ATT_VOIDED)
        .group_by(func.date(models.Attempt.started_at)).all()
    )
    series = []
    for i in range(29, -1, -1):
        day = (utcnow() - timedelta(days=i)).date().isoformat()
        series.append({"date": day, "attempts": int(daily.get(day, 0))})

    mrr: Dict[str, int] = {}
    for plan, in_ in db.query(models.Plan, func.count(models.Organization.id)).join(
        models.Organization, models.Organization.plan_id == models.Plan.id
    ).filter(models.Organization.status == ORG_ACTIVE).group_by(models.Plan.id).all():
        mrr[plan.currency] = mrr.get(plan.currency, 0) + plan.price_monthly * in_

    top = (
        db.query(models.Organization.id, models.Organization.name, func.count(models.Attempt.id))
        .join(models.Attempt, models.Attempt.org_id == models.Organization.id)
        .filter(models.Attempt.started_at >= month, models.Attempt.status != ATT_VOIDED)
        .group_by(models.Organization.id).order_by(func.count(models.Attempt.id).desc()).limit(5).all()
    )
    soon = utcnow() + timedelta(days=7)
    expiring = [
        {"id": o.id, "name": o.name, "trial_ends_at": o.trial_ends_at}
        for o in db.query(models.Organization).filter(
            models.Organization.status == ORG_TRIAL, models.Organization.trial_ends_at.isnot(None), models.Organization.trial_ends_at <= soon
        ).order_by(models.Organization.trial_ends_at).limit(10).all()
    ]
    return {
        "organizations": {"total": sum(by_status.values()), **{s: by_status.get(s, 0) for s in ORG_STATUSES}},
        "staff_users": db.query(func.count(models.User.id)).filter(models.User.role.in_([ROLE_ADMIN, ROLE_REVIEWER])).scalar() or 0,
        "tests": {
            "total": db.query(func.count(models.Exam.id)).scalar() or 0,
            "published": db.query(func.count(models.Exam.id)).filter(models.Exam.status == EXAM_PUBLISHED).scalar() or 0,
        },
        "attempts": {
            "total": db.query(func.count(models.Attempt.id)).filter(models.Attempt.status != ATT_VOIDED).scalar() or 0,
            "this_month": attempts_month,
            "in_progress_now": db.query(func.count(models.Attempt.id)).filter(models.Attempt.status == "in_progress").scalar() or 0,
        },
        "candidates": db.query(func.count(models.User.id)).filter(models.User.role == ROLE_CANDIDATE).scalar() or 0,
        "mrr": mrr,
        "attempts_last_30_days": series,
        "top_organizations": [{"id": i, "name": n, "attempts": c} for i, n, c in top],
        "trials_ending_soon": expiring,
        "new_demo_requests": db.query(func.count(models.DemoRequest.id)).filter(models.DemoRequest.status == "new").scalar() or 0,
    }


# ---------------------------------------------------------------------------
# organizations
# ---------------------------------------------------------------------------
@router.get("/organizations")
def list_orgs(
    q: Optional[str] = None, status: Optional[str] = None, plan: Optional[str] = None,
    params: PageParams = Depends(), user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db),
):
    query = db.query(models.Organization)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(models.Organization.name).like(like), func.lower(models.Organization.slug).like(like),
                                 func.lower(models.Organization.contact_email).like(like)))
    if status:
        query = query.filter(models.Organization.status == status)
    if plan:
        query = query.join(models.Plan, models.Plan.id == models.Organization.plan_id).filter(models.Plan.code == plan)
    return paginate(query.order_by(models.Organization.created_at.desc()), params, lambda o: _org_row(db, o))


@router.post("/organizations", status_code=201)
def create_org(body: OrgCreate, request: Request, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    plan = _plan_by_code(db, body.plan_code)
    if staff_service.find_staff_by_email(db, body.admin_email):
        raise conflict("A staff account with this email already exists", "email_taken")
    now = utcnow()
    org = models.Organization(
        name=body.name.strip(), slug=tenancy.unique_slug(db, body.slug or body.name), status=body.status, plan_id=plan.id,
        contact_email=body.contact_email or body.admin_email, internal_notes=body.internal_notes,
        trial_ends_at=(now + timedelta(days=body.trial_days or settings.trial_days)) if body.status == ORG_TRIAL else None,
        subscription_ends_at=body.subscription_ends_at if body.status == ORG_ACTIVE else None,
        settings={},
    )
    db.add(org)
    db.flush()
    created = staff_service.create_staff(
        db, org=org, full_name=body.admin_name, email=body.admin_email, role=ROLE_ADMIN,
        temp_password=body.admin_temp_password, send_invite=body.send_invite, invited_by="The ProctorAI platform team",
    )
    audit.log_event(db, "ORG_CREATED", user=user, org_id=org.id, entity_type="organization", entity_id=org.id,
                    details=f"name='{org.name}' plan={plan.code} admin={body.admin_email}", ip=auth.client_ip(request))
    db.commit()
    db.refresh(org)
    return {
        "organization": _org_row(db, org),
        "admin": {**serializers.user_out(created["user"]), "invite_url": created["invite_url"], "temp_password": created["temp_password"]},
    }


@router.get("/organizations/{org_id}")
def org_detail(org_id: int, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    org = _org(db, org_id)
    staff = db.query(models.User).filter(models.User.org_id == org.id, models.User.role.in_([ROLE_ADMIN, ROLE_REVIEWER])).order_by(models.User.created_at).all()
    recent = db.query(models.AuditLog).filter(models.AuditLog.org_id == org.id).order_by(models.AuditLog.id.desc()).limit(15).all()
    return {
        **_org_row(db, org),
        "limits_override": org.limits_override or {},
        "internal_notes": org.internal_notes,
        "suspended_reason": org.suspended_reason,
        "users": [serializers.user_out(u) for u in staff],
        "candidates": db.query(func.count(models.User.id)).filter(models.User.org_id == org.id, models.User.role == ROLE_CANDIDATE).scalar() or 0,
        "recent_activity": [
            {"id": a.id, "action": a.action, "actor_email": a.actor_email, "details": a.details, "created_at": a.created_at} for a in recent
        ],
    }


@router.patch("/organizations/{org_id}")
def update_org(org_id: int, body: OrgPatch, request: Request, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    org = _org(db, org_id)
    changes = body.model_dump(exclude_unset=True)
    notes: List[str] = []
    if "plan_code" in changes and changes["plan_code"]:
        plan = _plan_by_code(db, changes.pop("plan_code"))
        org.plan_id = plan.id
        notes.append(f"plan={plan.code}")
    else:
        changes.pop("plan_code", None)
    if "limits_override" in changes:
        org.limits_override = _clean_overrides(changes.pop("limits_override") or {})
        notes.append("limits_override updated")
    if changes.get("status"):
        new_status = changes.pop("status")
        if new_status == ORG_SUSPENDED:
            org.suspended_reason = changes.pop("suspended_reason", None) or "Suspended by the platform owner."
        else:
            org.suspended_reason = None
            changes.pop("suspended_reason", None)
        if new_status != org.status:
            notes.append(f"status {org.status}->{new_status}")
            org.status = new_status
        if new_status == ORG_ACTIVE and org.trial_ends_at and "trial_ends_at" not in changes:
            pass
    else:
        changes.pop("status", None)
    for field in ("name", "contact_email", "internal_notes", "trial_ends_at", "subscription_ends_at"):
        if field in changes:
            setattr(org, field, changes[field])
            notes.append(field)
    audit.log_event(db, "ORG_UPDATED", user=user, org_id=org.id, entity_type="organization", entity_id=org.id,
                    details=", ".join(notes), ip=auth.client_ip(request))
    db.commit()
    db.refresh(org)
    return _org_row(db, org)


@router.delete("/organizations/{org_id}")
def cancel_org(org_id: int, request: Request, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    """Soft delete: the account is closed and nobody can sign in, but data is retained for the retention period."""
    org = _org(db, org_id)
    org.status = ORG_CANCELLED
    for member in db.query(models.User).filter(models.User.org_id == org.id, models.User.role != ROLE_CANDIDATE).all():
        member.token_version += 1
    audit.log_event(db, "ORG_CANCELLED", user=user, org_id=org.id, entity_type="organization", entity_id=org.id, ip=auth.client_ip(request))
    db.commit()
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# an organization's staff
# ---------------------------------------------------------------------------
@router.post("/organizations/{org_id}/admins", status_code=201)
def add_org_admin(org_id: int, body: AdminCreate, request: Request, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    org = _org(db, org_id)
    created = staff_service.create_staff(
        db, org=org, full_name=body.full_name, email=body.email, role=body.role,
        temp_password=body.temp_password, send_invite=body.send_invite, invited_by="The ProctorAI platform team",
    )
    audit.log_event(db, "ORG_STAFF_CREATED", user=user, org_id=org.id, entity_type="user", entity_id=created["user"].id,
                    details=f"{body.email} as {body.role}", ip=auth.client_ip(request))
    db.commit()
    return {**serializers.user_out(created["user"]), "invite_url": created["invite_url"], "temp_password": created["temp_password"]}


@router.post("/organizations/{org_id}/users/{user_id}/reset-link")
def issue_reset_link(org_id: int, user_id: int, request: Request, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    org = _org(db, org_id)
    target = tenancy.get_org_user(db, user_id, org.id)
    raw = staff_service.issue_token(db, target, "reset")
    url = staff_service.activation_url(raw, "reset")
    mailer.queue_email(db, target.email, "Reset your ProctorAI password",
                       mailer.render("Reset your password", [f"Hi {target.full_name},", "The platform team has issued a password reset link for your account."],
                                     cta_label="Choose a new password", cta_url=url, org_name=org.name, brand=org.brand_color), org_id=org.id)
    audit.log_event(db, "RESET_LINK_ISSUED", user=user, org_id=org.id, entity_type="user", entity_id=target.id, ip=auth.client_ip(request))
    db.commit()
    return {"reset_url": url}


@router.patch("/organizations/{org_id}/users/{user_id}")
def patch_org_user(org_id: int, user_id: int, body: UserPatch, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    target = tenancy.get_org_user(db, user_id, _org(db, org_id).id)
    if body.is_active is not None:
        target.is_active = body.is_active
        if not body.is_active:
            target.token_version += 1
    if body.role:
        target.role = body.role
    audit.log_event(db, "ORG_STAFF_UPDATED", user=user, org_id=org_id, entity_type="user", entity_id=target.id, details=str(body.model_dump(exclude_none=True)))
    db.commit()
    return serializers.user_out(target)


# ---------------------------------------------------------------------------
# plans
# ---------------------------------------------------------------------------
@router.get("/plans")
def list_plans(user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    counts = dict(db.query(models.Organization.plan_id, func.count(models.Organization.id)).group_by(models.Organization.plan_id).all())
    return [{**serializers.plan_out(p), "organizations": counts.get(p.id, 0)} for p in db.query(models.Plan).order_by(models.Plan.sort_order, models.Plan.id).all()]


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    if db.query(models.Plan.id).filter(models.Plan.code == body.code).first():
        raise conflict("A plan with this code already exists", "plan_exists")
    plan = models.Plan(**body.model_dump())
    db.add(plan)
    audit.log_event(db, "PLAN_CREATED", user=user, details=body.code)
    db.commit()
    return serializers.plan_out(plan)


@router.put("/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanIn, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    plan = db.get(models.Plan, plan_id)
    if plan is None:
        raise not_found("Plan")
    if body.code != plan.code and db.query(models.Plan.id).filter(models.Plan.code == body.code).first():
        raise conflict("A plan with this code already exists", "plan_exists")
    for key, value in body.model_dump().items():
        setattr(plan, key, value)
    audit.log_event(db, "PLAN_UPDATED", user=user, details=plan.code)
    db.commit()
    return serializers.plan_out(plan)


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    plan = db.get(models.Plan, plan_id)
    if plan is None:
        raise not_found("Plan")
    if db.query(models.Organization.id).filter(models.Organization.plan_id == plan.id).first():
        plan.is_active = False
        plan.is_public = False
        db.commit()
        return {"status": "deactivated", "detail": "Organizations still use this plan, so it was hidden instead of deleted."}
    db.delete(plan)
    audit.log_event(db, "PLAN_DELETED", user=user, details=plan.code)
    db.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# platform staff (other super admins)
# ---------------------------------------------------------------------------
@router.get("/platform-admins")
def list_platform_admins(user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    return [serializers.user_out(u) for u in db.query(models.User).filter(models.User.role == ROLE_SUPER_ADMIN).order_by(models.User.id).all()]


class PlatformAdminCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr


@router.post("/platform-admins", status_code=201)
def create_platform_admin(body: PlatformAdminCreate, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    if staff_service.find_staff_by_email(db, body.email):
        raise conflict("A staff account with this email already exists", "email_taken")
    new_user = models.User(org_id=None, full_name=body.full_name.strip(), email=staff_service.normalize_email(body.email), role=ROLE_SUPER_ADMIN)
    db.add(new_user)
    db.flush()
    url = staff_service.activation_url(staff_service.issue_token(db, new_user, "invite"), "invite")
    mailer.queue_email(db, new_user.email, "You have been added as a ProctorAI platform admin",
                       mailer.render("Platform admin access", [f"Hi {new_user.full_name},", "You now have platform-owner access to ProctorAI."],
                                     cta_label="Set your password", cta_url=url))
    audit.log_event(db, "PLATFORM_ADMIN_CREATED", user=user, entity_type="user", entity_id=new_user.id, details=body.email)
    db.commit()
    return {**serializers.user_out(new_user), "invite_url": url}


@router.patch("/platform-admins/{user_id}")
def update_platform_admin(user_id: int, body: UserPatch, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    target = db.query(models.User).filter(models.User.id == user_id, models.User.role == ROLE_SUPER_ADMIN).first()
    if target is None:
        raise not_found("Platform admin")
    if target.id == user.id and body.is_active is False:
        raise bad_request("You cannot deactivate your own account")
    if body.is_active is not None:
        target.is_active = body.is_active
        if not body.is_active:
            target.token_version += 1
    audit.log_event(db, "PLATFORM_ADMIN_UPDATED", user=user, entity_type="user", entity_id=target.id, details=str(body.model_dump(exclude_none=True)))
    db.commit()
    return serializers.user_out(target)


# ---------------------------------------------------------------------------
# audit log, outbox, leads
# ---------------------------------------------------------------------------
@router.get("/audit-log")
def platform_audit(
    org_id: Optional[int] = None, action: Optional[str] = None, q: Optional[str] = None,
    params: PageParams = Depends(), user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db),
):
    query = db.query(models.AuditLog)
    if org_id:
        query = query.filter(models.AuditLog.org_id == org_id)
    if action:
        query = query.filter(models.AuditLog.action == action)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(models.AuditLog.actor_email).like(like), func.lower(models.AuditLog.details).like(like)))
    return paginate(query.order_by(models.AuditLog.id.desc()), params, lambda a: {
        "id": a.id, "org_id": a.org_id, "actor_email": a.actor_email, "action": a.action, "entity_type": a.entity_type,
        "entity_id": a.entity_id, "details": a.details, "ip_address": a.ip_address, "created_at": a.created_at,
    })


@router.get("/outbox")
def outbox(params: PageParams = Depends(), user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    return paginate(db.query(models.EmailOutbox).order_by(models.EmailOutbox.id.desc()), params, lambda e: {
        "id": e.id, "org_id": e.org_id, "to_email": e.to_email, "subject": e.subject, "status": e.status,
        "error": e.error, "created_at": e.created_at, "body_html": e.body_html,
    })


@router.get("/demo-requests")
def demo_requests(params: PageParams = Depends(), user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    return paginate(db.query(models.DemoRequest).order_by(models.DemoRequest.id.desc()), params, lambda d: {
        "id": d.id, "name": d.name, "email": d.email, "company": d.company, "phone": d.phone, "message": d.message,
        "status": d.status, "created_at": d.created_at,
    })


@router.patch("/demo-requests/{request_id}")
def update_demo(request_id: int, body: DemoPatch, user: models.User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    row = db.get(models.DemoRequest, request_id)
    if row is None:
        raise not_found("Request")
    row.status = body.status
    db.commit()
    return {"id": row.id, "status": row.status}
