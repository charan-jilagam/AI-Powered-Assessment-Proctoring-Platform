"""Candidate invitations: invite-only tests, bulk e-mail, personal links."""
import csv
import io
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import audit, auth, exam_service, mailer, models, staff_service, tenancy, webhooks
from app.constants import EXAM_PUBLISHED, INV_COMPLETED, INV_PENDING, INV_REVOKED, INV_STARTED
from app.database import get_db
from app.errors import ApiError, bad_request, not_found
from app.timeutil import utcnow

router = APIRouter(prefix="/tests/{exam_id}/invites", tags=["invites"])

MAX_INVITES_PER_REQUEST = 500


class Invitee(BaseModel):
    email: EmailStr
    name: Optional[str] = Field(default=None, max_length=160)


class InviteBatch(BaseModel):
    invitees: List[Invitee] = Field(min_length=1, max_length=MAX_INVITES_PER_REQUEST)
    send_email: bool = True
    expires_in_days: Optional[int] = Field(default=14, ge=1, le=365)


def _row(inv: models.Invite, exam: models.Exam) -> dict:
    return {"id": inv.id, "email": inv.email, "name": inv.name, "status": inv.status, "sent_at": inv.sent_at,
            "expires_at": inv.expires_at, "created_at": inv.created_at, "link": exam_service.join_url(exam, inv.token)}


def _send(db: Session, org: models.Organization, exam: models.Exam, inv: models.Invite) -> None:
    window = ""
    if exam.start_time or exam.end_time:
        parts = []
        if exam.start_time:
            parts.append(f"opens {exam.start_time:%d %b %Y %H:%M} UTC")
        if exam.end_time:
            parts.append(f"closes {exam.end_time:%d %b %Y %H:%M} UTC")
        window = "The test " + " and ".join(parts) + "."
    paragraphs = [
        f"Hi {inv.name or 'there'},",
        f"{org.name} has invited you to take \"{exam.title}\".",
        f"You will have {exam.duration_minutes} minutes once you start. {window}".strip(),
        "Use a laptop or desktop with a working webcam" + (" and microphone" if (exam.proctoring or {}).get("microphone_required") else "") + ", and a stable internet connection.",
        f"Your personal link is below. You can also join at any time with the test code {serializers_code(exam)}.",
    ]
    mailer.queue_email(
        db, inv.email, f"You are invited: {exam.title}",
        mailer.render(f"You are invited to {exam.title}", paragraphs, cta_label="Open your test", cta_url=exam_service.join_url(exam, inv.token),
                      org_name=org.name, brand=org.brand_color),
        org_id=org.id,
    )
    inv.sent_at = utcnow()


def serializers_code(exam: models.Exam) -> str:
    from app.serializers import format_code
    return format_code(exam.code)


@router.get("")
def list_invites(exam_id: int, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    rows = db.query(models.Invite).filter(models.Invite.exam_id == exam.id).order_by(models.Invite.id.desc()).all()
    counts = {s: 0 for s in (INV_PENDING, INV_STARTED, INV_COMPLETED, INV_REVOKED)}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {"items": [_row(r, exam) for r in rows], "counts": counts, "total": len(rows)}


@router.post("", status_code=201)
def create_invites(exam_id: int, body: InviteBatch, user: models.User = Depends(auth.require_org_admin),
                   org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    created, skipped = [], []
    seen = set()
    for person in body.invitees:
        email = staff_service.normalize_email(person.email)
        if email in seen:
            continue
        seen.add(email)
        existing = db.query(models.Invite).filter(models.Invite.exam_id == exam.id, models.Invite.email == email).first()
        if existing and existing.status != INV_REVOKED:
            skipped.append({"email": email, "reason": "already invited"})
            continue
        expires = utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None
        if existing:  # re-inviting someone whose invite was revoked
            existing.status, existing.token, existing.expires_at, existing.name = INV_PENDING, auth.new_token(24), expires, person.name or existing.name
            inv = existing
        else:
            inv = models.Invite(org_id=org.id, exam_id=exam.id, email=email, name=person.name, token=auth.new_token(24),
                                expires_at=expires, created_by=user.id)
            db.add(inv)
        db.flush()
        if body.send_email and exam.status == EXAM_PUBLISHED:
            _send(db, org, exam, inv)
        created.append(inv)
    audit.log_event(db, "CANDIDATES_INVITED", user=user, entity_type="test", entity_id=exam.id, details=f"count={len(created)} skipped={len(skipped)}")
    webhooks.emit(db, org.id, "candidate.invited", {"test_id": exam.id, "count": len(created)})
    db.commit()
    note = None
    if body.send_email and exam.status != EXAM_PUBLISHED:
        note = "Invites were saved but not e-mailed because the test is not published yet. Publish it, then use 'Resend'."
    return {"created": [_row(i, exam) for i in created], "skipped": skipped, "note": note}


@router.post("/import-csv", status_code=201)
async def import_invites_csv(exam_id: int, file: UploadFile = File(...), user: models.User = Depends(auth.require_org_admin),
                             org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    raw = await file.read()
    if len(raw) > 1_000_000:
        raise bad_request("CSV is larger than 1 MB")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
    headers = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
    if "email" not in headers:
        raise bad_request("CSV needs an 'email' column (and optionally 'name')")
    invitees, bad = [], []
    for line, row in enumerate(reader, start=2):
        email = (row.get(headers["email"]) or "").strip()
        if not email:
            continue
        try:
            invitees.append(Invitee(email=email, name=(row.get(headers.get("name", ""), "") or "").strip() or None))
        except ValueError:
            bad.append({"row": line, "error": f"'{email}' is not a valid email"})
    if len(invitees) > MAX_INVITES_PER_REQUEST:
        raise bad_request(f"Import at most {MAX_INVITES_PER_REQUEST} candidates at a time")
    if not invitees:
        raise bad_request("No valid email addresses found in the file")
    result = create_invites(exam_id, InviteBatch(invitees=invitees), user, org, db)
    result["invalid_rows"] = bad
    return result


def _invite(db: Session, exam: models.Exam, invite_id: int) -> models.Invite:
    inv = db.query(models.Invite).filter(models.Invite.id == invite_id, models.Invite.exam_id == exam.id).first()
    if inv is None:
        raise not_found("Invite")
    return inv


@router.post("/{invite_id}/resend")
def resend_invite(exam_id: int, invite_id: int, user: models.User = Depends(auth.require_org_admin),
                  org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    inv = _invite(db, exam, invite_id)
    if inv.status in (INV_REVOKED, INV_COMPLETED):
        raise bad_request("This invite can no longer be used")
    if exam.status != EXAM_PUBLISHED:
        raise bad_request("Publish the test before sending invitations")
    _send(db, org, exam, inv)
    db.commit()
    return _row(inv, exam)


@router.delete("/{invite_id}")
def revoke_invite(exam_id: int, invite_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    inv = _invite(db, exam, invite_id)
    inv.status = INV_REVOKED
    audit.log_event(db, "INVITE_REVOKED", user=user, entity_type="invite", entity_id=inv.id, details=inv.email)
    db.commit()
    return {"status": "revoked"}
