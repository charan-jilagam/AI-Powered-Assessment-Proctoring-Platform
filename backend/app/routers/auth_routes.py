from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from app.mongo import Session

from app import audit, auth, mailer, models, serializers, staff_service
from app.config import settings
from app.database import get_db
from app.errors import ApiError
from app.limiter import limiter
from app.schemas import LoginRequest, TokenResponse
from app.timeutil import as_utc, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1, max_length=200)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    ip = auth.client_ip(request)
    user = staff_service.find_staff_by_email(db, body.email)

    if user is None:
        auth.burn_password_check(body.password)
        audit.log_event(db, "LOGIN_FAILED", actor_email=body.email, details="unknown account", ip=ip, commit=True)
        raise ApiError(401, "Invalid email or password", "invalid_credentials")

    now = utcnow()
    if user.locked_until and as_utc(user.locked_until) > now:
        minutes = int((as_utc(user.locked_until) - now).total_seconds() // 60) + 1
        raise ApiError(429, f"Too many failed attempts. Try again in {minutes} minute(s).", "account_locked")

    if not user.is_active or not auth.verify_password(body.password, user.hashed_password):
        if user.is_active:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                user.failed_login_count = 0
        audit.log_event(db, "LOGIN_FAILED", user=user, details="bad password or disabled", ip=ip, commit=True)
        raise ApiError(401, "Invalid email or password", "invalid_credentials")

    org = db.get(models.Organization, user.org_id) if user.org_id else None
    reason = auth.org_block_reason(org)
    if reason:
        raise ApiError(403, reason, "org_blocked")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    audit.log_event(db, "LOGIN_SUCCESS", user=user, details=f"role={user.role}", ip=ip)
    db.commit()
    return {
        "access_token": auth.create_access_token(user),
        "token_type": "bearer",
        "user": serializers.user_out(user),
        "organization": serializers.org_brief(org),
    }


@router.get("/me")
def me(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    org = db.get(models.Organization, user.org_id) if user.org_id else None
    return {"user": serializers.user_out(user), "organization": serializers.org_brief(org)}


@router.post("/change-password")
@limiter.limit("10/minute")
def change_password(request: Request, body: ChangePassword, user: models.User = Depends(auth.require_any_staff), db: Session = Depends(get_db)):
    if not auth.verify_password(body.current_password, user.hashed_password):
        raise ApiError(400, "Current password is incorrect", "bad_password")
    auth.validate_password(body.new_password)
    if auth.verify_password(body.new_password, user.hashed_password):
        raise ApiError(400, "Choose a password you have not used just now", "same_password")
    user.hashed_password = auth.hash_password(body.new_password)
    user.must_change_password = False
    user.token_version += 1  # signs out every other session
    audit.log_event(db, "PASSWORD_CHANGED", user=user, ip=auth.client_ip(request))
    db.commit()
    return {"access_token": auth.create_access_token(user), "token_type": "bearer"}


@router.post("/logout-all")
def logout_all(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    db.commit()
    return {"status": "signed_out_everywhere"}


@router.post("/forgot-password")
@limiter.limit("5/minute")
def forgot_password(request: Request, body: ForgotPassword, db: Session = Depends(get_db)):
    """Always answers 200 so the endpoint cannot be used to discover which e-mails have accounts."""
    user = staff_service.find_staff_by_email(db, body.email)
    if user and user.is_active:
        org = db.get(models.Organization, user.org_id) if user.org_id else None
        raw = staff_service.issue_token(db, user, "reset")
        url = staff_service.activation_url(raw, "reset")
        mailer.queue_email(
            db, user.email, "Reset your ORVEXA password",
            mailer.render("Reset your password", [f"Hi {user.full_name},", "We received a request to reset your password. This link works once and expires soon.",
                                                  "If you did not ask for this, you can ignore this email."],
                          cta_label="Choose a new password", cta_url=url, org_name=org.name if org else None,
                          brand=org.brand_color if org else None),
            org_id=user.org_id,
        )
        audit.log_event(db, "PASSWORD_RESET_REQUESTED", user=user, ip=auth.client_ip(request))
        db.commit()
    return {"status": "If that email has an account, a reset link is on its way."}


def _valid_token_row(db: Session, raw: str) -> models.PasswordToken:
    row = db.query(models.PasswordToken).filter(models.PasswordToken.token_hash == auth.hash_token(raw)).first()
    if row is None or row.used_at is not None or as_utc(row.expires_at) < utcnow():
        raise ApiError(400, "This link is invalid or has expired. Please request a new one.", "bad_token")
    return row


@router.get("/token-info")
def token_info(token: str, db: Session = Depends(get_db)):
    row = _valid_token_row(db, token)
    user = db.get(models.User, row.user_id)
    org = db.get(models.Organization, user.org_id) if user.org_id else None
    return {"purpose": row.purpose, "full_name": user.full_name, "email": user.email, "organization": org.name if org else "ORVEXA"}


@router.post("/reset-password")
@limiter.limit("10/minute")
def reset_password(request: Request, body: ResetPassword, db: Session = Depends(get_db)):
    """Used both for 'forgot password' and for accepting a staff invitation."""
    row = _valid_token_row(db, body.token)
    auth.validate_password(body.new_password)
    user = db.get(models.User, row.user_id)
    user.hashed_password = auth.hash_password(body.new_password)
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None
    user.token_version += 1
    row.used_at = utcnow()
    audit.log_event(db, "PASSWORD_SET", user=user, details=f"via {row.purpose}", ip=auth.client_ip(request))
    db.commit()
    return {"status": "password_set"}
