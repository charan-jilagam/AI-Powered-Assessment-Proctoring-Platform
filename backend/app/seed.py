"""Idempotent bootstrap data: default subscription plans and the first platform owner."""
import logging

from app.mongo import Session

from app import auth, models
from app.config import settings
from app.constants import ROLE_SUPER_ADMIN

log = logging.getLogger("orvexa.seed")

DEFAULT_PLANS = [
    dict(code="trial", name="Free Trial", description="Try the platform with a small group of candidates.", price_monthly=0,
         max_admins=2, max_active_tests=2, max_candidates_per_month=25, ai_proctoring=True, coding_enabled=False,
         api_access=False, webhooks_enabled=False, evidence_retention_days=14, is_public=False, sort_order=0),
    dict(code="starter", name="Starter", description="For small teams running regular assessments.", price_monthly=999, currency="INR",
         max_admins=3, max_active_tests=5, max_candidates_per_month=200, ai_proctoring=False, coding_enabled=True,
         api_access=False, webhooks_enabled=False, evidence_retention_days=30, is_public=True, sort_order=1),
    dict(code="professional", name="Professional", description="AI proctoring, coding tests and integrations for growing companies.",
         price_monthly=3999, currency="INR", max_admins=10, max_active_tests=25, max_candidates_per_month=1500, ai_proctoring=True,
         coding_enabled=True, api_access=True, webhooks_enabled=True, evidence_retention_days=90, is_public=True, sort_order=2),
    dict(code="enterprise", name="Enterprise", description="Unlimited scale with custom terms and priority support.", price_monthly=0,
         max_admins=-1, max_active_tests=-1, max_candidates_per_month=-1, ai_proctoring=True, coding_enabled=True,
         api_access=True, webhooks_enabled=True, evidence_retention_days=365, is_public=True, sort_order=3),
]


def seed_plans(db: Session) -> int:
    created = 0
    for spec in DEFAULT_PLANS:
        if not db.query(models.Plan.id).filter(models.Plan.code == spec["code"]).first():
            db.add(models.Plan(**spec))
            created += 1
    db.commit()
    return created


def bootstrap_super_admin(db: Session) -> bool:
    """Create the platform owner from SUPERADMIN_EMAIL / SUPERADMIN_PASSWORD when none exists yet."""
    if db.query(models.User.id).filter(models.User.role == ROLE_SUPER_ADMIN).first():
        return False
    if not (settings.superadmin_email and settings.superadmin_password):
        log.warning("No super admin exists. Set SUPERADMIN_EMAIL and SUPERADMIN_PASSWORD, or run `python manage.py create-superadmin`.")
        return False
    auth.validate_password(settings.superadmin_password)
    db.add(models.User(
        org_id=None, full_name=settings.superadmin_name, email=settings.superadmin_email.strip().lower(),
        hashed_password=auth.hash_password(settings.superadmin_password), role=ROLE_SUPER_ADMIN, is_active=True,
    ))
    db.commit()
    log.info("Platform owner created: %s", settings.superadmin_email)
    return True
