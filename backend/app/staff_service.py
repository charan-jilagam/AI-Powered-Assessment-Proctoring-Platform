"""Creating staff accounts (org admins, reviewers) and issuing the one-time links that activate them."""
from datetime import timedelta
import re
from typing import Iterable, List, Optional

from app.mongo import func
from app.mongo import Session

from app import auth, mailer, models
from app.config import settings
from app.constants import ORG_STAFF_ROLES, ROLE_ADMIN, STAFF_ROLES
from app.errors import ApiError, conflict
from app.timeutil import utcnow


def normalize_email(email: str) -> str:
    return email.strip().lower()


_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MAX_DOMAINS = 10


def normalize_domains(raw: Optional[Iterable[str]]) -> List[str]:
    """['@SconexSoft.com', 'sconexsoft.com ', 'mail.acme.io'] -> ['sconexsoft.com', 'mail.acme.io'] (validated, de-duplicated)."""
    out: List[str] = []
    for item in raw or []:
        d = str(item).strip().lower().lstrip("@")
        if not d:
            continue
        if not _DOMAIN_RE.match(d):
            raise ApiError(400, f"'{item}' is not a valid e-mail domain. Use the part after the @, for example sconexsoft.com.", "bad_domain")
        if d not in out:
            out.append(d)
    if len(out) > MAX_DOMAINS:
        raise ApiError(400, f"At most {MAX_DOMAINS} domains per organization.", "too_many_domains")
    return out


def email_domain(email: str) -> str:
    return normalize_email(email).rpartition("@")[2]


def domain_allowed(domains: Optional[Iterable[str]], email: str) -> bool:
    """True when the organization has no domain list, or the address is at one of its domains (sub-domains count)."""
    allowed = [d for d in (domains or []) if d]
    if not allowed:
        return True
    host = email_domain(email)
    return any(host == d or host.endswith("." + d) for d in allowed)


def ensure_staff_domain(org: models.Organization, email: str) -> None:
    if not domain_allowed(org.allowed_domains, email):
        raise ApiError(400, f"{email} is not at this organization's e-mail domain(s): {', '.join('@' + d for d in org.allowed_domains)}. "
                            "Use a work address, or ask the platform owner to add the domain.", "email_domain_not_allowed")


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


def verification_url(raw_token: str) -> str:
    return f"{settings.frontend_url}/verify-email?token={raw_token}"


def send_verification(db: Session, user: models.User, org: Optional[models.Organization] = None) -> str:
    """E-mail the account owner a one-time link that proves the mailbox is theirs. Returns the link (caller commits)."""
    raw = issue_token(db, user, "verify", hours=settings.verify_token_hours)
    url = verification_url(raw)
    mailer.queue_email(
        db, user.email, "Verify your e-mail address",
        mailer.render("Verify your e-mail address",
                      [f"Hi {user.full_name},", "Please confirm that this is your e-mail address. Until you do, you can look around "
                       "but cannot create tests.", f"The link works once and expires in {settings.verify_token_hours} hours."],
                      cta_label="Verify my e-mail", cta_url=url, org_name=org.name if org else None, brand=org.brand_color if org else None),
        org_id=user.org_id,
    )
    return url


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
    ensure_staff_domain(org, email)
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
            db, user.email, f"You have been invited to {org.name} on ORVEXA",
            mailer.render(
                f"Welcome to {org.name}",
                [f"Hi {user.full_name},", f"{invited_by or 'The platform team'} has created a {role} account for you on ORVEXA.",
                 "Use the button below to choose your password and sign in."],
                cta_label="Set your password", cta_url=url, org_name=org.name, brand=org.brand_color,
            ),
            org_id=org.id,
        )
    if settings.staff_email_verification:
        send_verification(db, user, org)
    return result
