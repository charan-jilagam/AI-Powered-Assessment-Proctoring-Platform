"""Everything a test taker does: look up a test by code, join, start, answer, be proctored, submit."""
import secrets
from datetime import timedelta
from typing import Any, Dict, List, NamedTuple, Optional

from fastapi import APIRouter, Depends, Query, Request
from app.mongo import func
from app.mongo import Session

from app import (
    attempt_service, audit, auth, coding, exam_service, models, proctor_rules, proctoring, scoring, serializers, staff_service,
    storage, tenancy, webhooks,
)
from app.constants import (
    ACCESS_INVITE, ATT_IN_PROGRESS, ATT_REGISTERED, ATT_SUBMITTED, ATT_TERMINATED, ATT_VOIDED, CLIENT_REPORTABLE,
    EXAM_CLOSED, EXAM_PUBLISHED, FINAL_ATTEMPT_STATUSES, INV_REVOKED, INV_STARTED, ROLE_CANDIDATE, VIOLATION_CATALOG,
)
from app.database import get_db
from app.errors import ApiError, bad_request, conflict, forbidden, not_found
from app.attempt_deps import AttemptCtx, attempt_ctx
from app.limiter import limiter
from app.schemas import AnswersIn, HeartbeatIn, ImageIn, JoinRequest, StartRequest, ViolationIn
from app.timeutil import as_utc, utcnow

public_router = APIRouter(prefix="/public/tests", tags=["candidate"])
router = APIRouter(prefix="/attempt", tags=["candidate"])

MAX_ANSWER_CHARS = 4000
MAX_PERIODIC_SNAPSHOTS = 300
MIN_ANALYZE_GAP_SECONDS = 1.0
# consecutive suspicious frames required before the server records an AI violation (kills one-frame flukes)
STREAK_REQUIRED = {"NO_FACE": 2, "MULTIPLE_FACES": 2, "LOOKING_AWAY": 3, "HEAD_TURNED": 3, "LIP_MOVEMENT": 3,
                   "PROHIBITED_OBJECT": 2, "CAMERA_COVERED": 2}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _exam_by_code(db: Session, code: str) -> models.Exam:
    exam = db.query(models.Exam).filter(models.Exam.code == exam_service.normalize_code(code)).first()
    if exam is None or exam.status in ("draft", "archived"):
        raise ApiError(404, "That test code was not found. Check it and try again.", "code_not_found")
    return exam


def _window_state(exam: models.Exam) -> str:
    now = utcnow()
    if exam.status == EXAM_CLOSED:
        return "closed"
    if exam.start_time and now < as_utc(exam.start_time):
        return "not_started"
    if exam.end_time and now > as_utc(exam.end_time):
        return "ended"
    return "open"


def _candidate_cfg(exam: models.Exam) -> Dict[str, Any]:
    return proctor_rules.config_for(exam)


def _public_test(db: Session, exam: models.Exam, org: models.Organization) -> Dict[str, Any]:
    cfg = _candidate_cfg(exam)
    q_total = db.query(func.count(models.Question.id)).filter(models.Question.exam_id == exam.id).scalar() or 0
    coding_total = db.query(func.count(models.CodingProblem.id)).filter(models.CodingProblem.exam_id == exam.id).scalar() or 0
    shown = min(exam.questions_per_attempt, q_total) if exam.questions_per_attempt else q_total
    state = _window_state(exam)
    blocked = auth.org_block_reason(org)
    return {
        "title": exam.title, "description": exam.description, "code": exam.code,
        "organization": {"name": org.name, "brand_color": org.brand_color, "logo_url": org.logo_url},
        "duration_minutes": exam.duration_minutes, "question_count": shown, "coding_problem_count": coding_total,
        "access_mode": exam.access_mode, "requires_password": bool(exam.access_password_hash),
        "candidate_fields": exam.candidate_fields or [], "window": {"start": exam.start_time, "end": exam.end_time, "state": state},
        "available": state == "open" and not blocked,
        "unavailable_reason": None if (state == "open" and not blocked) else (
            "This test is not available right now. Please contact the organizer." if blocked else
            {"closed": "This test is closed.", "not_started": "This test has not opened yet.", "ended": "The window for this test has ended."}[state]),
        "proctoring": {k: cfg[k] for k in ("webcam_required", "microphone_required", "fullscreen_required", "ai_monitoring", "id_verification")},
        "instructions": exam.instructions,
    }


def _ua(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:300]


def _clean_answers(raw: Dict[str, Any], valid_ids: set) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in (raw or {}).items():
        if str(key).isdigit() and int(key) in valid_ids:
            if isinstance(value, list):
                clean[str(key)] = [str(v)[:MAX_ANSWER_CHARS] for v in value[:12]]
            elif value is None:
                continue
            else:
                clean[str(key)] = str(value)[:MAX_ANSWER_CHARS]
    return clean


def _state_payload(db: Session, ctx: AttemptCtx) -> Dict[str, Any]:
    attempt, exam = ctx.attempt, ctx.exam
    org = db.get(models.Organization, exam.org_id)
    payload: Dict[str, Any] = {
        "attempt": {
            "id": attempt.id, "status": attempt.status, "started_at": attempt.started_at,
            "remaining_seconds": attempt_service.remaining_seconds(exam, attempt) if attempt.status == ATT_IN_PROGRESS else 0,
            "server_time": utcnow(),
        },
        "test": {**_public_test(db, exam, org), "id": exam.id, "result_visibility": exam.result_visibility,
                 "proctoring_config": _candidate_cfg(exam)},
        "candidate": {"name": ctx.user.full_name, "email": ctx.user.email},
    }
    if attempt.status == ATT_IN_PROGRESS:
        payload.update(
            questions=attempt.question_data or [], answers=attempt.answers or {}, flagged=attempt.flagged or [],
            coding_problems=coding.student_problem_views(exam),
            messages=[{"id": m.id, "body": m.body, "created_at": m.created_at}
                      for m in db.query(models.AttemptMessage).filter(models.AttemptMessage.attempt_id == attempt.id).order_by(models.AttemptMessage.id).all()],
            level2_count=attempt.level2_count,
        )
    elif attempt.status in FINAL_ATTEMPT_STATUSES:
        payload["result"] = attempt_service.result_for_candidate(attempt, exam)
    return payload


# ---------------------------------------------------------------------------
# public: look up + join
# ---------------------------------------------------------------------------
@public_router.get("/{code}")
@limiter.limit("60/minute")
def lookup_test(request: Request, code: str, db: Session = Depends(get_db)):
    exam = _exam_by_code(db, code)
    return _public_test(db, exam, db.get(models.Organization, exam.org_id))


@public_router.post("/{code}/join")
@limiter.limit("20/minute")
def join_test(request: Request, code: str, body: JoinRequest, db: Session = Depends(get_db)):
    exam = _exam_by_code(db, code)
    org = db.get(models.Organization, exam.org_id)
    ip = auth.client_ip(request)
    if auth.org_block_reason(org):
        raise ApiError(403, "This test is not available right now. Please contact the organizer.", "unavailable")

    if exam.access_password_hash and not auth.verify_password(body.access_password or "", exam.access_password_hash):
        audit.log_event(db, "JOIN_BAD_PASSWORD", actor_email=body.email, org_id=org.id, entity_type="test", entity_id=exam.id, ip=ip, commit=True)
        raise ApiError(403, "Incorrect access password", "bad_access_password")

    email = staff_service.normalize_email(body.email)
    # --- invite rules
    invite = db.query(models.Invite).filter(models.Invite.exam_id == exam.id, models.Invite.email == email).first()
    if body.invite_token:
        token_invite = db.query(models.Invite).filter(models.Invite.exam_id == exam.id, models.Invite.token == body.invite_token).first()
        if token_invite is None or token_invite.email != email:
            raise ApiError(403, "This invitation link does not match the email you entered.", "invite_mismatch")
        invite = token_invite
    if invite and invite.status == INV_REVOKED:
        invite = None
    if invite and invite.expires_at and as_utc(invite.expires_at) < utcnow() and invite.status != INV_STARTED:
        raise ApiError(403, "Your invitation has expired. Ask the organizer for a new one.", "invite_expired")
    if exam.access_mode == ACCESS_INVITE and invite is None:
        raise ApiError(403, "This test is by invitation only, and that email address was not invited.", "not_invited")

    # --- required custom fields
    fields = {k: (v or "").strip()[:200] for k, v in (body.fields or {}).items()}
    for spec in exam.candidate_fields or []:
        if spec.get("required") and not fields.get(spec["key"]):
            raise bad_request(f"{spec['label']} is required", "missing_field")
    profile = {s["key"]: fields.get(s["key"], "") for s in (exam.candidate_fields or [])}

    # --- candidate account (scoped to the organization)
    candidate = db.query(models.User).filter(
        models.User.org_id == org.id, models.User.role == ROLE_CANDIDATE, func.lower(models.User.email) == email
    ).first()
    if candidate is None:
        candidate = models.User(org_id=org.id, full_name=body.full_name, email=email, role=ROLE_CANDIDATE, phone=body.phone, extra=profile)
        db.add(candidate)
        db.flush()
    elif not candidate.is_active:
        raise ApiError(403, "This account has been blocked by the organizer.", "blocked")
    else:
        candidate.full_name, candidate.phone = body.full_name, body.phone or candidate.phone
        candidate.extra = {**(candidate.extra or {}), **profile}

    attempt = (
        db.query(models.Attempt)
        .filter(models.Attempt.exam_id == exam.id, models.Attempt.candidate_id == candidate.id, models.Attempt.status != ATT_VOIDED)
        .order_by(models.Attempt.attempt_no.desc()).first()
    )

    if attempt is not None and attempt.status in FINAL_ATTEMPT_STATUSES:
        raise ApiError(409, "You have already completed this test. Contact the organizer if you believe this is a mistake.", "already_attempted")

    resumed = False
    if attempt is not None and attempt.status == ATT_IN_PROGRESS:
        if attempt_service.is_expired(exam, attempt):
            attempt_service.finalize_attempt(db, attempt, exam, auto=True, reason="Time expired")
            raise ApiError(409, "Your time for this test has ended and your answers were submitted.", "already_attempted")
        resumed = True
    else:
        state = _window_state(exam)
        if state != "open":
            raise ApiError(403, {"closed": "This test is closed.", "not_started": "This test has not opened yet.", "ended": "The window for this test has ended."}[state], f"window_{state}")
        if attempt is None:
            tenancy.ensure_capacity(db, org, "candidate")
            last_no = db.query(func.max(models.Attempt.attempt_no)).filter(models.Attempt.exam_id == exam.id, models.Attempt.candidate_id == candidate.id).scalar() or 0
            attempt = models.Attempt(org_id=org.id, exam_id=exam.id, candidate_id=candidate.id, attempt_no=last_no + 1,
                                     status=ATT_REGISTERED, invite_id=invite.id if invite else None, profile=profile)
            db.add(attempt)
            db.flush()

    previous_ip = attempt.ip_address
    attempt.session_nonce = secrets.token_hex(12)  # invalidates any token held by an earlier window/device
    attempt.ip_address, attempt.user_agent = ip, _ua(request)
    if invite and invite.status == "pending":
        invite.status = INV_STARTED
        attempt.invite_id = invite.id
    audit.log_event(db, "CANDIDATE_JOINED", actor_email=email, org_id=org.id, entity_type="attempt", entity_id=attempt.id,
                    details=f"exam={exam.id} resumed={resumed}", ip=ip)
    db.commit()
    db.refresh(attempt)

    if resumed:
        proctor_rules.record_violation(db, attempt, exam, "SESSION_RESUMED", details="Session re-opened", source="system")
        if previous_ip and previous_ip != ip:
            proctor_rules.record_violation(db, attempt, exam, "IP_CHANGED", details=f"{previous_ip} -> {ip}", source="system")
    return {
        "token": auth.create_access_token(candidate, attempt=attempt),
        "attempt": {"id": attempt.id, "status": attempt.status, "resumed": resumed},
        "candidate": {"name": candidate.full_name, "email": candidate.email},
    }


# ---------------------------------------------------------------------------
# attempt: state, start, answers, heartbeat
# ---------------------------------------------------------------------------
@router.get("")
def get_state(ctx: AttemptCtx = Depends(attempt_ctx), db: Session = Depends(get_db)):
    return _state_payload(db, ctx)


@router.post("/start")
def start_attempt(request: Request, body: StartRequest, ctx: AttemptCtx = Depends(attempt_ctx), db: Session = Depends(get_db)):
    attempt, exam = ctx.attempt, ctx.exam
    if attempt.status == ATT_IN_PROGRESS:
        return _state_payload(db, ctx)  # idempotent: a double-click must not restart anything
    if attempt.status != ATT_REGISTERED:
        raise conflict("This attempt can no longer be started", "bad_state")
    org = db.get(models.Organization, exam.org_id)
    if auth.org_block_reason(org):
        raise ApiError(403, "This test is not available right now. Please contact the organizer.", "unavailable")
    state = _window_state(exam)
    if state != "open":
        raise ApiError(403, "This test is not open for starting right now.", f"window_{state}")
    if not body.consent:
        raise bad_request("You must accept the proctoring terms to continue", "consent_required")
    cfg = _candidate_cfg(exam)
    if cfg.get("id_verification") and not (body.id_image and body.face_image):
        raise bad_request("A photo of your ID and a photo of your face are required", "id_required")
    tenancy.ensure_capacity(db, org, "candidate")

    questions = db.query(models.Question).filter(models.Question.exam_id == exam.id).order_by(models.Question.position, models.Question.id).all()
    if not questions and not exam.coding_problems:
        raise bad_request("This test has no questions yet", "empty_test")
    question_data, answer_key = scoring.build_attempt_questions(
        questions, per_attempt=exam.questions_per_attempt, shuffle_questions=exam.shuffle_questions, shuffle_options=exam.shuffle_options)

    for kind, image in (("id", body.id_image), ("face", body.face_image)):
        if image:
            rel = storage.save_image(attempt.org_id, attempt.id, kind, image)
            db.add(models.Snapshot(org_id=attempt.org_id, attempt_id=attempt.id, kind=kind, path=rel))

    now = utcnow()
    attempt.question_data, attempt.answer_key = question_data, answer_key
    attempt.status, attempt.started_at, attempt.consent_at = ATT_IN_PROGRESS, now, now
    attempt.system_info = {k: str(v)[:200] for k, v in list((body.system_info or {}).items())[:20]}
    attempt.last_heartbeat_at = now
    audit.log_event(db, "ATTEMPT_STARTED", user=ctx.user, entity_type="attempt", entity_id=attempt.id, details=f"exam={exam.id}", ip=auth.client_ip(request))
    webhooks.emit(db, attempt.org_id, "attempt.started", {"attempt_id": attempt.id, "test_id": exam.id, "test_title": exam.title,
                                                          "candidate": {"name": ctx.user.full_name, "email": ctx.user.email}})
    db.commit()
    db.refresh(attempt)
    return _state_payload(db, ctx)


def _require_live(ctx: AttemptCtx) -> None:
    if ctx.attempt.status != ATT_IN_PROGRESS:
        raise ApiError(409, "This exam is no longer active", f"attempt_{ctx.attempt.status}")


@router.put("/answers")
def save_answers(body: AnswersIn, ctx: AttemptCtx = Depends(attempt_ctx), db: Session = Depends(get_db)):
    """Autosave. Idempotent and cheap - the browser calls it after every change."""
    attempt, exam = ctx.attempt, ctx.exam
    if attempt.status != ATT_IN_PROGRESS:
        return {"status": attempt.status, "remaining_seconds": 0}
    valid_ids = {q["id"] for q in attempt.question_data or []}
    merged = dict(attempt.answers or {})
    merged.update(_clean_answers(body.answers, valid_ids))
    for key in [k for k, v in body.answers.items() if v in (None, "", []) and str(k) in merged]:
        merged.pop(str(key), None)  # clearing an answer
    attempt.answers = merged
    attempt.flagged = [i for i in body.flagged if i in valid_ids]
    db.commit()
    return {"status": attempt.status, "saved_at": utcnow(), "remaining_seconds": attempt_service.remaining_seconds(exam, attempt)}


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, after: int = Query(0, ge=0), ctx: AttemptCtx = Depends(attempt_ctx), db: Session = Depends(get_db)):
    attempt, exam = ctx.attempt, ctx.exam
    out: Dict[str, Any] = {"status": attempt.status, "server_time": utcnow(), "remaining_seconds": 0, "messages": []}
    if attempt.status != ATT_IN_PROGRESS:
        out["terminated_reason"] = attempt.terminated_reason
        return out
    attempt.last_heartbeat_at = utcnow()
    attempt.last_state = {**(attempt.last_state or {}), "visible": body.visible, "fullscreen": body.fullscreen, "camera": body.camera, "mic": body.mic}
    db.commit()
    cfg = _candidate_cfg(exam)
    if cfg.get("webcam_required") and body.camera is False:
        proctor_rules.record_violation(db, attempt, exam, "CAMERA_LOST", details="Reported by heartbeat", source="browser")
        db.refresh(attempt)
    out["status"] = attempt.status
    out["remaining_seconds"] = attempt_service.remaining_seconds(exam, attempt) if attempt.status == ATT_IN_PROGRESS else 0
    out["level2_count"] = attempt.level2_count
    out["terminated_reason"] = attempt.terminated_reason
    out["messages"] = [
        {"id": m.id, "body": m.body, "created_at": m.created_at}
        for m in db.query(models.AttemptMessage).filter(models.AttemptMessage.attempt_id == attempt.id, models.AttemptMessage.id > after).order_by(models.AttemptMessage.id).all()
    ]
    return out


@router.post("/violations")
def report_violation(body: ViolationIn, ctx: AttemptCtx = Depends(attempt_ctx), db: Session = Depends(get_db)):
    """The browser reports WHAT happened; the server decides severity, counting and termination."""
    if body.code not in CLIENT_REPORTABLE:
        raise bad_request("Unknown or non-reportable violation code", "bad_violation")
    outcome = proctor_rules.record_violation(db, ctx.attempt, ctx.exam, body.code, details=body.details, image=body.image, source="browser")
    return outcome


@router.post("/snapshot")
def periodic_snapshot(body: ImageIn, ctx: AttemptCtx = Depends(attempt_ctx), db: Session = Depends(get_db)):
    attempt = ctx.attempt
    if attempt.status != ATT_IN_PROGRESS:
        return {"saved": False}
    count = db.query(func.count(models.Snapshot.id)).filter(models.Snapshot.attempt_id == attempt.id, models.Snapshot.kind == "periodic").scalar() or 0
    if count >= MAX_PERIODIC_SNAPSHOTS:
        return {"saved": False, "reason": "limit"}
    rel = storage.save_image(attempt.org_id, attempt.id, "periodic", body.image)
    db.add(models.Snapshot(org_id=attempt.org_id, attempt_id=attempt.id, kind="periodic", path=rel))
    db.commit()
    return {"saved": True}


@router.post("/analyze")
def analyze(body: ImageIn, ctx: AttemptCtx = Depends(attempt_ctx), db: Session = Depends(get_db)):
    """AI frame analysis. Findings must persist for several consecutive frames before they count."""
    attempt, exam = ctx.attempt, ctx.exam
    cfg = _candidate_cfg(exam)
    empty = {"available": False, "findings": [], "level2_count": attempt.level2_count, "terminated": attempt.status == ATT_TERMINATED}
    if attempt.status != ATT_IN_PROGRESS or not cfg.get("ai_monitoring"):
        return empty
    org = db.get(models.Organization, exam.org_id)
    if not tenancy.effective_limits(org)["ai_proctoring"]:
        return empty

    state = dict(attempt.last_state or {})
    now = utcnow().timestamp()
    if now - float(state.get("last_analyze", 0)) < MIN_ANALYZE_GAP_SECONDS:
        return {**empty, "skipped": True}
    state["last_analyze"] = now

    storage.decode_image(body.image)  # validates size/type before any heavy work
    result = proctoring.analyze_frame(body.image)
    if not result["available"]:
        attempt.last_state = state
        db.commit()
        return empty

    streaks: Dict[str, int] = dict(state.get("streaks", {}))
    present = {f["code"]: f for f in result["findings"]}
    for code in list(streaks):
        if code not in present:
            streaks[code] = 0
    reported = []
    outcome = None
    for code, finding in present.items():
        streaks[code] = streaks.get(code, 0) + 1
        sev, _, label, _ = VIOLATION_CATALOG[code]
        reported.append({"code": code, "label": label, "severity": sev, "detail": finding.get("detail"), "confirmed": streaks[code] >= STREAK_REQUIRED.get(code, 2)})
        if streaks[code] >= STREAK_REQUIRED.get(code, 2):
            outcome = proctor_rules.record_violation(db, attempt, exam, code, details=finding.get("detail"), image=body.image, source="ai")
            streaks[code] = 0
            db.refresh(attempt)
    state["streaks"] = streaks
    attempt.last_state = state
    db.commit()
    return {"available": True, "face_count": result["face_count"], "findings": reported,
            "level2_count": attempt.level2_count, "terminated": attempt.status == ATT_TERMINATED,
            "outcome": outcome}


# ---------------------------------------------------------------------------
# submit + result
# ---------------------------------------------------------------------------
@router.post("/submit")
def submit(body: AnswersIn, ctx: AttemptCtx = Depends(attempt_ctx), db: Session = Depends(get_db)):
    attempt, exam = ctx.attempt, ctx.exam
    if attempt.status == ATT_IN_PROGRESS:
        valid_ids = {q["id"] for q in attempt.question_data or []}
        merged = dict(attempt.answers or {})
        merged.update(_clean_answers(body.answers, valid_ids))
        attempt_service.finalize_attempt(db, attempt, exam, answers=merged, flagged=[i for i in body.flagged if i in valid_ids])
        db.refresh(attempt)
    elif attempt.status not in FINAL_ATTEMPT_STATUSES:
        raise conflict("Start the exam before submitting", "bad_state")
    return attempt_service.result_for_candidate(attempt, exam)


@router.get("/result")
def get_result(ctx: AttemptCtx = Depends(attempt_ctx)):
    if ctx.attempt.status not in FINAL_ATTEMPT_STATUSES:
        raise conflict("The exam is not finished yet", "bad_state")
    return attempt_service.result_for_candidate(ctx.attempt, ctx.exam)
