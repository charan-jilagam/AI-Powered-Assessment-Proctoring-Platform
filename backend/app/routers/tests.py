"""Test (assessment) management for client admins: create, edit, publish, questions, CSV import."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from app.mongo import func, or_
from app.mongo import Session

from app import audit, auth, coding, exam_service, models, question_rules, tenancy, webhooks
from app.constants import (
    ATT_VOIDED, EXAM_ARCHIVED, EXAM_CLOSED, EXAM_DRAFT, EXAM_PUBLISHED, EXAM_STATUSES, ORG_ACTIVE,
)
from app.database import get_db
from app.errors import ApiError, bad_request, conflict
from app.pagination import PageParams, paginate
from app.schemas import ExamIn, ExamPatch, ProctoringConfig, QuestionIn
from app.timeutil import utcnow

router = APIRouter(prefix="/tests", tags=["tests"])


# ---------------------------------------------------------------------------
# static routes first (they must not be swallowed by /{exam_id})
# ---------------------------------------------------------------------------
@router.get("/questions-template.csv")
def questions_template(user: models.User = Depends(auth.require_org_staff)):
    return Response(exam_service.csv_template(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="orvexa-questions-template.csv"'})


@router.get("")
def list_tests(
    status: Optional[str] = None, q: Optional[str] = None, params: PageParams = Depends(),
    user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db),
):
    query = db.query(models.Exam).filter(models.Exam.org_id == user.org_id)
    if status in EXAM_STATUSES:
        query = query.filter(models.Exam.status == status)
    else:
        query = query.filter(models.Exam.status != EXAM_ARCHIVED)  # archived tests are hidden unless asked for
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(models.Exam.title).like(like), models.Exam.code.like(q.upper().replace("-", "") + "%")))
    return paginate(query.order_by(models.Exam.id.desc()), params, lambda e: exam_service.exam_summary(db, e))


@router.post("", status_code=201)
def create_test(
    body: ExamIn, request: Request, user: models.User = Depends(auth.require_org_admin),
    org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db),
):
    exam_service.validate_schedule(body.start_time, body.end_time)
    if body.coding_problems:
        tenancy.ensure_feature(org, "coding_enabled", "Coding questions")
        for problem in body.coding_problems:
            coding.validate_problem(problem)

    default_cfg = (org.settings or {}).get("default_proctoring")
    cfg = body.proctoring.model_dump() if ("proctoring" in body.model_fields_set or not default_cfg) else dict(default_cfg)
    cfg, warnings = exam_service.clamp_proctoring_to_plan(org, cfg)
    if body.questions_per_attempt and body.questions and body.questions_per_attempt > len(body.questions):
        raise bad_request("'Questions per candidate' is more than the questions you supplied")

    exam = models.Exam(
        org_id=org.id, created_by=user.id, title=body.title.strip(), description=body.description, instructions=body.instructions,
        code=exam_service.new_code(db), status=EXAM_DRAFT, duration_minutes=body.duration_minutes,
        start_time=body.start_time, end_time=body.end_time, access_mode=body.access_mode,
        access_password_hash=auth.hash_password(body.access_password) if body.access_password else None,
        questions_per_attempt=body.questions_per_attempt, shuffle_questions=body.shuffle_questions,
        shuffle_options=body.shuffle_options, pass_percentage=body.pass_percentage, result_visibility=body.result_visibility,
        proctoring=cfg, candidate_fields=[f.model_dump() for f in body.candidate_fields],
    )
    db.add(exam)
    db.flush()
    for q in body.questions:
        exam_service.add_question(db, exam, q.model_dump(), user)
    for problem in body.coding_problems:
        coding.create_problem(db, exam.id, problem)
    audit.log_event(db, "TEST_CREATED", user=user, entity_type="test", entity_id=exam.id, details=f"'{exam.title}' code={exam.code}", ip=auth.client_ip(request))
    db.commit()
    db.refresh(exam)
    return {**exam_service.exam_detail(db, exam), "warnings": warnings}


@router.get("/{exam_id}")
def get_test(exam_id: int, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    detail = exam_service.exam_detail(db, exam)
    if user.role != "admin":  # reviewers never see the answer key
        for q in detail["questions"]:
            q["correct"] = []
            q["explanation"] = None
        detail["coding_problems"] = [{**p, "test_cases": [t for t in p["test_cases"] if t["is_sample"]]} for p in detail["coding_problems"]]
    return detail


@router.patch("/{exam_id}")
def update_test(
    exam_id: int, body: ExamPatch, request: Request, user: models.User = Depends(auth.require_org_admin),
    org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db),
):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    if exam.status == EXAM_ARCHIVED:
        raise conflict("Archived tests cannot be edited", "archived")
    data = body.model_dump(exclude_unset=True)
    if "duration_minutes" in data and data["duration_minutes"] != exam.duration_minutes and exam_service.has_live_attempts(db, exam.id):
        raise conflict("Candidates are taking this test right now - the duration cannot change until they finish", "live_attempts")

    warnings: List[str] = []
    if data.pop("clear_schedule", False):
        exam.start_time = exam.end_time = None
        data.pop("start_time", None)
        data.pop("end_time", None)
    start = data.get("start_time", exam.start_time)
    end = data.get("end_time", exam.end_time)
    exam_service.validate_schedule(start, end)

    if "access_password" in data:
        pw = data.pop("access_password")
        if pw == "":
            exam.access_password_hash = None
        elif pw is not None:
            exam.access_password_hash = auth.hash_password(pw)
    if "questions_per_attempt" in data:
        exam.questions_per_attempt = data.pop("questions_per_attempt") or None
    if "proctoring" in data and body.proctoring is not None:
        cfg, warnings = exam_service.clamp_proctoring_to_plan(org, body.proctoring.model_dump())
        exam.proctoring = cfg
        data.pop("proctoring")
    if "candidate_fields" in data and body.candidate_fields is not None:
        exam.candidate_fields = [f.model_dump() for f in body.candidate_fields]
        data.pop("candidate_fields")
    for key, value in data.items():
        setattr(exam, key, value)
    audit.log_event(db, "TEST_UPDATED", user=user, entity_type="test", entity_id=exam.id, details=", ".join(sorted(body.model_dump(exclude_unset=True))), ip=auth.client_ip(request))
    db.commit()
    db.refresh(exam)
    return {**exam_service.exam_detail(db, exam), "warnings": warnings}


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
@router.post("/{exam_id}/publish")
def publish_test(exam_id: int, request: Request, user: models.User = Depends(auth.require_org_admin),
                 org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    if exam.status == EXAM_PUBLISHED:
        return exam_service.exam_summary(db, exam)
    if exam.status == EXAM_ARCHIVED:
        raise conflict("Archived tests cannot be published", "archived")
    problems = exam_service.readiness_problems(db, exam)
    if problems:
        raise ApiError(422, " ".join(problems), "not_ready")
    tenancy.ensure_capacity(db, org, "active_test")
    exam.status = EXAM_PUBLISHED
    exam.published_at = exam.published_at or utcnow()
    exam.closed_at = None
    audit.log_event(db, "TEST_PUBLISHED", user=user, entity_type="test", entity_id=exam.id, details=exam.title, ip=auth.client_ip(request))
    webhooks.emit(db, org.id, "test.published", {"test_id": exam.id, "title": exam.title, "code": exam.code})
    db.commit()
    return exam_service.exam_summary(db, exam)


@router.post("/{exam_id}/close")
def close_test(exam_id: int, request: Request, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    """Stop new candidates from joining. Candidates already taking the test can still finish."""
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    if exam.status != EXAM_PUBLISHED:
        raise conflict("Only a published test can be closed", "bad_state")
    exam.status = EXAM_CLOSED
    exam.closed_at = utcnow()
    audit.log_event(db, "TEST_CLOSED", user=user, entity_type="test", entity_id=exam.id, ip=auth.client_ip(request))
    webhooks.emit(db, user.org_id, "test.closed", {"test_id": exam.id, "title": exam.title})
    db.commit()
    return exam_service.exam_summary(db, exam)


@router.post("/{exam_id}/unpublish")
def unpublish_test(exam_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    """Back to draft for editing - only possible while nobody has started the test."""
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    if exam_service.has_started_attempts(db, exam.id):
        raise conflict("Candidates have already started this test, so it cannot go back to draft. Close it instead.", "has_attempts")
    exam.status = EXAM_DRAFT
    audit.log_event(db, "TEST_UNPUBLISHED", user=user, entity_type="test", entity_id=exam.id)
    db.commit()
    return exam_service.exam_summary(db, exam)


@router.post("/{exam_id}/archive")
def archive_test(exam_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    if exam_service.has_live_attempts(db, exam.id):
        raise conflict("Candidates are taking this test right now", "live_attempts")
    exam.status = EXAM_ARCHIVED
    audit.log_event(db, "TEST_ARCHIVED", user=user, entity_type="test", entity_id=exam.id)
    db.commit()
    return exam_service.exam_summary(db, exam)


@router.post("/{exam_id}/duplicate", status_code=201)
def duplicate_test(exam_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    src = tenancy.get_exam(db, exam_id, user.org_id)
    copy = exam_service.duplicate_exam(db, src, user)
    audit.log_event(db, "TEST_DUPLICATED", user=user, entity_type="test", entity_id=copy.id, details=f"from {src.id}")
    db.commit()
    db.refresh(copy)
    return exam_service.exam_summary(db, copy)


@router.post("/{exam_id}/regenerate-code")
def regenerate_code(exam_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    """Issue a fresh join code (use if the code leaked). The old one stops working immediately."""
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    exam.code = exam_service.new_code(db)
    audit.log_event(db, "TEST_CODE_REGENERATED", user=user, entity_type="test", entity_id=exam.id)
    db.commit()
    return exam_service.exam_summary(db, exam)


@router.delete("/{exam_id}")
def delete_test(exam_id: int, request: Request, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    if db.query(models.Attempt.id).filter(models.Attempt.exam_id == exam.id).first():
        raise conflict("This test has candidate data. Archive it instead of deleting it.", "has_attempts")
    title = exam.title
    db.query(models.Invite).filter(models.Invite.exam_id == exam.id).delete()
    coding.delete_exam_coding_data(db, exam.id)
    db.delete(exam)
    audit.log_event(db, "TEST_DELETED", user=user, entity_type="test", entity_id=exam_id, details=title, ip=auth.client_ip(request))
    db.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# questions
# ---------------------------------------------------------------------------
@router.post("/{exam_id}/questions", status_code=201)
def add_question(exam_id: int, body: QuestionIn, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    q = exam_service.add_question(db, exam, body.model_dump(), user)
    db.commit()
    db.refresh(q)
    return question_rules.question_to_dict(q)


@router.put("/{exam_id}/questions/{question_id}")
def update_question(exam_id: int, question_id: int, body: QuestionIn, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    q = db.query(models.Question).filter(models.Question.id == question_id, models.Question.exam_id == exam.id).first()
    if q is None:
        raise ApiError(404, "Question not found", "not_found")
    for key, value in exam_service._normalize(body.model_dump()).items():
        setattr(q, key, value)
    db.commit()
    return question_rules.question_to_dict(q)


@router.delete("/{exam_id}/questions/{question_id}")
def delete_question(exam_id: int, question_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    q = db.query(models.Question).filter(models.Question.id == question_id, models.Question.exam_id == exam.id).first()
    if q is None:
        raise ApiError(404, "Question not found", "not_found")
    db.delete(q)
    db.commit()
    return {"status": "deleted"}


class ReorderIn(BaseModel):
    ids: List[int]


@router.post("/{exam_id}/questions/reorder")
def reorder_questions(exam_id: int, body: ReorderIn, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    by_id = {q.id: q for q in exam.questions}
    for position, qid in enumerate(body.ids, start=1):
        if qid in by_id:
            by_id[qid].position = position
    db.commit()
    return {"status": "reordered"}


@router.post("/{exam_id}/questions/import-csv")
async def import_questions_csv(
    exam_id: int, file: UploadFile = File(...), dry_run: bool = Form(False),
    user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db),
):
    """All-or-nothing: if any row is invalid nothing is imported and every problem is reported."""
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    good, errors = exam_service.parse_csv(await file.read())
    if errors or dry_run:
        return {"imported": 0, "valid_rows": len(good), "errors": errors, "dry_run": dry_run}
    existing = db.query(func.count(models.Question.id)).filter(models.Question.exam_id == exam.id).scalar() or 0
    if existing + len(good) > exam_service.MAX_QUESTIONS_PER_TEST:
        raise bad_request(f"A test can have at most {exam_service.MAX_QUESTIONS_PER_TEST} questions")
    position = (db.query(func.max(models.Question.position)).filter(models.Question.exam_id == exam.id).scalar() or 0)
    for row in good:
        position += 1
        db.add(models.Question(org_id=exam.org_id, exam_id=exam.id, position=position, created_by=user.id, **row))
    audit.log_event(db, "QUESTIONS_IMPORTED", user=user, entity_type="test", entity_id=exam.id, details=f"count={len(good)}")
    db.commit()
    return {"imported": len(good), "valid_rows": len(good), "errors": [], "dry_run": False}


class FromBankIn(BaseModel):
    question_ids: List[int] = Field(min_length=1, max_length=500)


@router.post("/{exam_id}/questions/from-bank")
def add_from_bank(exam_id: int, body: FromBankIn, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    rows = db.query(models.Question).filter(models.Question.id.in_(body.question_ids), models.Question.org_id == user.org_id, models.Question.exam_id.is_(None)).all()
    if not rows:
        raise bad_request("None of those questions were found in your question bank")
    position = (db.query(func.max(models.Question.position)).filter(models.Question.exam_id == exam.id).scalar() or 0)
    for src in rows:
        position += 1
        c = exam_service.clone_question(src, org_id=user.org_id, exam_id=exam.id, user_id=user.id)
        c.position = position
        db.add(c)
    db.commit()
    return {"added": len(rows)}


@router.post("/{exam_id}/questions/{question_id}/save-to-bank")
def save_to_bank(exam_id: int, question_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    q = db.query(models.Question).filter(models.Question.id == question_id, models.Question.exam_id == exam.id).first()
    if q is None:
        raise ApiError(404, "Question not found", "not_found")
    db.add(exam_service.clone_question(q, org_id=user.org_id, exam_id=None, user_id=user.id))
    db.commit()
    return {"status": "saved"}
