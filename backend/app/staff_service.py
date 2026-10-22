"""Creating staff accounts (org admins, reviewers) and issuing the one-time links that activate them."""
from datetime import timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import auth, mailer, models
from app.config import settings
from app.constants import ORG_STAFF_ROLES, ROLE_ADMIN, STAFF_ROLES
from app.errors import ApiError, conflict
from app.timeutil import utcnow


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_staff_by_email(db: Session, email: str) -> Optional[models.User]:
    return (
        db.query(models.User)
        .filter(func.lower(models.User.email) == normalize_email(email), models.User.role.in_(STAFF_ROLES))
        .first()
    )


def issue_token(db: Session, user: models.User, purpose: str, hours: Optional[int] = None) -> str:
    """Create a single-use token (invalidating older unused ones of the same purpose) and return the raw value."""
    db.query(models.PasswordToken).filter(
        models.PasswordToken.user_id == user.id, models.PasswordToken.purpose == purpose,
        models.PasswordToken.used_at.is_(None),
    ).update({"used_at": utcnow()})
    raw = auth.new_token()
    lifetime = timedelta(hours=hours) if hours else (
        timedelta(days=settings.invite_token_days) if purpose == "invite" else timedelta(hours=settings.reset_token_hours)
    )
    db.add(models.PasswordToken(user_id=user.id, token_hash=auth.hash_token(raw), purpose=purpose, expires_at=utcnow() + lifetime))
    db.flush()
    return raw


def activation_url(raw_token: str, purpose: str) -> str:
    page = "accept-invite" if purpose == "invite" else "reset-password"
    return f"{settings.frontend_url}/{page}?token={raw_token}"


def create_staff(
    db: Session,
    *,
    org: models.Organization,
    full_name: str,
    email: str,
    role: str = ROLE_ADMIN,
    temp_password: Optional[str] = None,
    send_invite: bool = True,
    invited_by: Optional[str] = None,
) -> dict:
    """Create an org staff user. Returns {"user", "invite_url", "temp_password"} (caller commits)."""
    if role not in ORG_STAFF_ROLES:
        raise ApiError(400, "Role must be admin or reviewer", "bad_role")
    if find_staff_by_email(db, email):
        raise conflict("A staff account with this email already exists", "email_taken")

    user = models.User(org_id=org.id, full_name=full_name.strip(), email=normalize_email(email), role=role, is_active=True)
    result = {"user": user, "invite_url": None, "temp_password": None}
    if temp_password:
        auth.validate_password(temp_password)
        user.hashed_password = auth.hash_password(temp_password)
        user.must_change_password = True
        result["temp_password"] = temp_password
    db.add(user)
    db.flush()

    if send_invite or not temp_password:
        raw = issue_token(db, user, "invite")
        url = activation_url(raw, "invite")
        result["invite_url"] = url
        mailer.queue_email(
            db, user.email, f"You have been invited to {org.name} on ProctorAI",
            mailer.render(
                f"Welcome to {org.name}",
                [f"Hi {user.full_name},", f"{invited_by or 'The platform team'} has created a {role} account for you on ProctorAI.",
                 "Use the button below to choose your password and sign in."],
                cta_label="Set your password", cta_url=url, org_name=org.name, brand=org.brand_color,
            ),
            org_id=org.id,
        )
    return result
