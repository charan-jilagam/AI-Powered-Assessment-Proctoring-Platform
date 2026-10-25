"""Small helpers that turn ORM rows into JSON-safe dicts. Keeps routers short and answer keys out of candidate payloads."""
from typing import Any, Dict, Optional

from app import models
from app.auth import org_block_reason
from app.tenancy import effective_limits


def user_out(u: models.User) -> Dict[str, Any]:
    return {
        "id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role, "org_id": u.org_id,
        "is_active": u.is_active, "must_change_password": u.must_change_password,
        "last_login_at": u.last_login_at, "created_at": u.created_at,
        "email_verified": bool(u.email_verified_at),
    }


def org_brief(org: Optional[models.Organization]) -> Optional[Dict[str, Any]]:
    if org is None:
        return None
    limits = effective_limits(org)
    return {
        "id": org.id, "name": org.name, "slug": org.slug, "status": org.status,
        "brand_color": org.brand_color, "logo_url": org.logo_url,
        "plan_code": org.plan.code if org.plan else None, "plan_name": org.plan.name if org.plan else None,
        "block_reason": org_block_reason(org),
        "allowed_domains": list(org.allowed_domains or []),
        "candidate_domain_lock": bool(org.candidate_domain_lock),
        "features": {k: bool(limits[k]) for k in ("ai_proctoring", "coding_enabled", "api_access", "webhooks_enabled")},
    }


def plan_out(p: models.Plan) -> Dict[str, Any]:
    return {
        "id": p.id, "code": p.code, "name": p.name, "description": p.description,
        "price_monthly": p.price_monthly, "currency": p.currency, "max_admins": p.max_admins,
        "max_active_tests": p.max_active_tests, "max_candidates_per_month": p.max_candidates_per_month,
        "ai_proctoring": p.ai_proctoring, "coding_enabled": p.coding_enabled, "api_access": p.api_access,
        "webhooks_enabled": p.webhooks_enabled, "evidence_retention_days": p.evidence_retention_days,
        "is_public": p.is_public, "is_active": p.is_active, "sort_order": p.sort_order,
    }


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}" if len(code) == 8 else code
