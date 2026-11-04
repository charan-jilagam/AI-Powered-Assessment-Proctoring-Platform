"""OMR sheet downloads for staff: one attempt, every attempt of a test (one PDF or a ZIP), and a blank template."""
import io
import zipfile
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from app.mongo import Session

from app import audit, auth, models, omr_pdf, omr_service, scoring, tenancy
from app.constants import ATT_IN_PROGRESS, ATT_VOIDED, FINAL_ATTEMPT_STATUSES, ROLE_ADMIN
from app.database import get_db
from app.errors import bad_request, conflict, forbidden

router = APIRouter(tags=["omr"])

PDF_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _pdf(data: bytes, filename: str) -> Response:
    return Response(data, media_type="application/pdf", headers={**PDF_HEADERS, "Content-Disposition": f'attachment; filename="{filename}"'})


def _check_evaluated(evaluated: bool, user: models.User) -> None:
    if evaluated and user.role != ROLE_ADMIN:     # an evaluated copy carries the answer key, which reviewers never see
        raise forbidden("Only an admin can download evaluated OMR sheets")


def _set_filter(exam: models.Exam, letter: Optional[str]) -> Optional[str]:
    if not letter:
        return None
    try:
        scoring.set_index(letter)
    except ValueError as exc:
        raise bad_request(str(exc))
    return letter.strip().upper()


def _attempts(db: Session, exam: models.Exam, *, include_live: bool, letter: Optional[str]) -> List[models.Attempt]:
    rows = db.query(models.Attempt).filter(models.Attempt.exam_id == exam.id, models.Attempt.status != ATT_VOIDED).all()
    allowed = set(FINAL_ATTEMPT_STATUSES) | ({ATT_IN_PROGRESS} if include_live else set())
    rows = [a for a in rows if a.status in allowed and a.question_data and (not letter or a.paper_set == letter)]
    return rows


def _sheets(db: Session, exam: models.Exam, attempts: List[models.Attempt], *, evaluated: bool, tz: Optional[str]) -> List[omr_pdf.OmrSheet]:
    org = db.get(models.Organization, exam.org_id)
    people = {u.id: u for u in db.query(models.User).filter(models.User.id.in_(list({a.candidate_id for a in attempts}))).all()} if attempts else {}
    attempts = sorted(attempts, key=lambda a: (a.paper_set or "", (people[a.candidate_id].full_name or "").lower(), a.id))
    return [omr_service.sheet_for_attempt(a, exam, org, people[a.candidate_id], evaluated=evaluated, tz=tz) for a in attempts]


@router.get("/attempts/{attempt_id}/omr.pdf")
def attempt_omr(attempt_id: int, request: Request, evaluated: bool = False, tz: Optional[str] = Query(default=None, max_length=64),
                user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    """The OMR sheet of one candidate. ``evaluated=true`` (admins) colours right / wrong answers and prints the score."""
    _check_evaluated(evaluated, user)
    attempt = tenancy.get_attempt(db, attempt_id, user.org_id)
    if not attempt.question_data:
        raise conflict("This candidate has not started the test, so there is no answer sheet yet", "not_started")
    exam = db.get(models.Exam, attempt.exam_id)
    candidate = db.get(models.User, attempt.candidate_id)
    sheet = omr_service.sheet_for_attempt(attempt, exam, db.get(models.Organization, exam.org_id), candidate, evaluated=evaluated, tz=tz)
    audit.log_event(db, "OMR_DOWNLOADED", user=user, entity_type="attempt", entity_id=attempt.id, details=f"evaluated={evaluated}", ip=auth.client_ip(request))
    db.commit()
    return _pdf(omr_pdf.render([sheet]), f"OMR-{omr_service.safe_filename(candidate.full_name)}-{attempt.id}{'-evaluated' if evaluated else ''}.pdf")


@router.get("/tests/{exam_id}/omr.pdf")
def test_omr_pdf(exam_id: int, request: Request, evaluated: bool = False, set: Optional[str] = Query(default=None, max_length=1),
                 include_live: bool = False, tz: Optional[str] = Query(default=None, max_length=64),
                 user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    """Every candidate's OMR sheet in ONE PDF (each sheet starts on a new page), grouped by set then by name."""
    _check_evaluated(evaluated, user)
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    attempts = _attempts(db, exam, include_live=include_live, letter=_set_filter(exam, set))
    if not attempts:
        raise conflict("There are no submitted attempts to export yet", "nothing_to_export")
    if len(attempts) > omr_service.MAX_SHEETS_PER_EXPORT:
        raise bad_request(f"That is more than {omr_service.MAX_SHEETS_PER_EXPORT} sheets; filter by set or download them one set at a time")
    sheets = _sheets(db, exam, attempts, evaluated=evaluated, tz=tz)
    audit.log_event(db, "OMR_EXPORTED", user=user, entity_type="test", entity_id=exam.id, details=f"sheets={len(sheets)} evaluated={evaluated} set={set or 'all'}", ip=auth.client_ip(request))
    db.commit()
    return _pdf(omr_pdf.render(sheets), f"{omr_service.safe_filename(exam.title)}-OMR{'-evaluated' if evaluated else ''}{'-set-' + set.upper() if set else ''}.pdf")


@router.get("/tests/{exam_id}/omr.zip")
def test_omr_zip(exam_id: int, request: Request, evaluated: bool = False, set: Optional[str] = Query(default=None, max_length=1),
                 include_live: bool = False, tz: Optional[str] = Query(default=None, max_length=64),
                 user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    """The same sheets as separate PDF files in a ZIP, named ``001-Set-A-Jane-Doe.pdf``."""
    _check_evaluated(evaluated, user)
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    attempts = _attempts(db, exam, include_live=include_live, letter=_set_filter(exam, set))
    if not attempts:
        raise conflict("There are no submitted attempts to export yet", "nothing_to_export")
    if len(attempts) > omr_service.MAX_SHEETS_PER_EXPORT:
        raise bad_request(f"That is more than {omr_service.MAX_SHEETS_PER_EXPORT} sheets; filter by set or download them one set at a time")
    sheets = _sheets(db, exam, attempts, evaluated=evaluated, tz=tz)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, sheet in enumerate(sheets, start=1):
            name = f"{n:03d}-{'Set-' + sheet.set_letter + '-' if sheet.set_letter else ''}{omr_service.safe_filename(sheet.candidate_name, 'candidate')}.pdf"
            z.writestr(name, omr_pdf.render([sheet]))
    audit.log_event(db, "OMR_EXPORTED", user=user, entity_type="test", entity_id=exam.id, details=f"zip sheets={len(sheets)} evaluated={evaluated}", ip=auth.client_ip(request))
    db.commit()
    return Response(buf.getvalue(), media_type="application/zip", headers={
        **PDF_HEADERS, "Content-Disposition": f'attachment; filename="{omr_service.safe_filename(exam.title)}-OMR{"-evaluated" if evaluated else ""}.zip"'})


@router.get("/tests/{exam_id}/omr/blank.pdf")
def test_omr_blank(exam_id: int, set: Optional[str] = Query(default=None, max_length=1), tz: Optional[str] = Query(default=None, max_length=64),
                   user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    """A printable, empty OMR sheet for this test (one per set when the test has sets) to hand out on paper."""
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    letter = _set_filter(exam, set)
    if letter and scoring.set_index(letter) >= int(exam.question_sets or 1):
        raise bad_request(f"This test has no Set {letter}")
    questions = db.query(models.Question).filter(models.Question.exam_id == exam.id).order_by(models.Question.position, models.Question.id).all()
    if not questions:
        raise conflict("Add questions to the test first", "empty_test")
    sheets = omr_service.blank_sheets(exam, db.get(models.Organization, exam.org_id), questions, set_letter=letter, tz=tz)
    return _pdf(omr_pdf.render(sheets), f"{omr_service.safe_filename(exam.title)}-OMR-blank{'-set-' + letter if letter else ''}.pdf")
