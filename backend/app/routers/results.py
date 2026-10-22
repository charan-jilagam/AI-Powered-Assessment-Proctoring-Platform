"""Staff-side view of attempts: results, live monitoring, analytics, reports, proctor actions, evidence."""
import csv
import io
import statistics
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import (
    attempt_service, audit, auth, judge0, models, proctor_rules, scoring, storage, tenancy, webhooks,
)
from app.constants import (
    ATT_IN_PROGRESS, ATT_REGISTERED, ATT_SUBMITTED, ATT_TERMINATED, ATT_VOIDED, FINAL_ATTEMPT_STATUSES, INV_PENDING,
    REVIEW_CLEARED, REVIEW_DISQUALIFIED, REVIEW_PENDING, REVIEW_STATUSES, REVIEW_SUSPICIOUS, ROLE_ADMIN, ROLE_CANDIDATE,
    VIOLATION_CATALOG,
)
from app.database import get_db
from app.errors import ApiError, bad_request, conflict, not_found
from app.pagination import PageParams, paginate
from app.timeutil import as_utc, utcnow

router = APIRouter(tags=["results"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _time_taken(a: models.Attempt) -> Optional[int]:
    if a.started_at and a.submitted_at:
        return int((as_utc(a.submitted_at) - as_utc(a.started_at)).total_seconds())
    return None


def final_result(a: models.Attempt) -> Optional[str]:
    if a.review_status == REVIEW_DISQUALIFIED:
        return "disqualified"
    if a.status == ATT_TERMINATED:
        return "terminated"
    if a.status == ATT_SUBMITTED:
        return "pass" if a.passed else "fail"
    return None


def _ranks(db: Session, exam_id: int) -> Dict[int, int]:
    rows = (
        db.query(models.Attempt.id, models.Attempt.percentage)
        .filter(models.Attempt.exam_id == exam_id, models.Attempt.status == ATT_SUBMITTED, models.Attempt.review_status != REVIEW_DISQUALIFIED)
        .order_by(models.Attempt.percentage.desc(), models.Attempt.id).all()
    )
    ranks, last_pct, last_rank = {}, None, 0
    for index, (aid, pct) in enumerate(rows, start=1):
        if pct != last_pct:
            last_rank, last_pct = index, pct
        ranks[aid] = last_rank
    return ranks


def _row(a: models.Attempt, c: models.User, ranks: Dict[int, int]) -> Dict[str, Any]:
    return {
        "id": a.id, "exam_id": a.exam_id, "attempt_no": a.attempt_no,
        "candidate": {"id": c.id, "name": c.full_name, "email": c.email, "phone": c.phone, "profile": a.profile or {}},
        "status": a.status, "started_at": a.started_at, "submitted_at": a.submitted_at, "time_taken_seconds": _time_taken(a),
        "score": a.score, "max_score": a.max_score, "percentage": a.percentage, "passed": a.passed,
        "final_result": final_result(a), "rank": ranks.get(a.id),
        "objective_score": a.objective_score, "coding_score": a.coding_score,
        "violation_count": a.violation_count, "level2_count": a.level2_count, "risk_score": a.risk_score,
        "risk_level": proctor_rules.risk_level(a.risk_score or 0), "review_status": a.review_status,
        "auto_submitted": a.auto_submitted, "terminated_reason": a.terminated_reason, "ip_address": a.ip_address,
    }


def _attempt_for_staff(db: Session, attempt_id: int, user: models.User) -> models.Attempt:
    return tenancy.get_attempt(db, attempt_id, user.org_id)


def _csv_safe(value: Any) -> Any:
    """Stop spreadsheet formula injection: cells that start with = + - @ would execute in Excel."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


# ---------------------------------------------------------------------------
# per-test lists
# ---------------------------------------------------------------------------
@router.get("/tests/{exam_id}/attempts")
def list_attempts(
    exam_id: int, status: Optional[str] = None, review_status: Optional[str] = None, min_risk: Optional[int] = None,
    q: Optional[str] = None, sort: Literal["recent", "score", "risk", "name"] = "recent", params: PageParams = Depends(),
    user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db),
):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    A, U = models.Attempt, models.User
    query = db.query(A, U).join(U, U.id == A.candidate_id).filter(A.exam_id == exam.id, A.status != ATT_VOIDED)
    if status:
        query = query.filter(A.status == status)
    if review_status:
        query = query.filter(A.review_status == review_status)
    if min_risk is not None:
        query = query.filter(A.risk_score >= min_risk)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(U.full_name).like(like), func.lower(U.email).like(like)))
    order = {"recent": A.id.desc(), "score": A.percentage.desc().nulls_last(),
             "risk": A.risk_score.desc(), "name": U.full_name}[sort]
    ranks = _ranks(db, exam.id)
    total = query.count()
    rows = query.order_by(order).offset((params.page - 1) * params.page_size).limit(params.page_size).all()
    return {"items": [_row(a, c, ranks) for a, c in rows], "total": total, "page": params.page, "page_size": params.page_size,
            "test": {"id": exam.id, "title": exam.title, "pass_percentage": exam.pass_percentage}}


@router.get("/tests/{exam_id}/live")
def live_monitor(exam_id: int, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    A, U = models.Attempt, models.User
    rows = (
        db.query(A, U).join(U, U.id == A.candidate_id)
        .filter(A.exam_id == exam.id, A.status.in_([ATT_IN_PROGRESS, ATT_REGISTERED])).order_by(A.id).all()
    )
    last_viol: Dict[int, models.Violation] = {}
    if rows:
        ids = [a.id for a, _ in rows]
        for v in db.query(models.Violation).filter(models.Violation.attempt_id.in_(ids)).order_by(models.Violation.id).all():
            last_viol[v.attempt_id] = v
    now = utcnow()
    items = []
    for a, c in rows:
        hb = as_utc(a.last_heartbeat_at)
        silent = (now - hb).total_seconds() if hb else None
        total_q = len(a.question_data or [])
        lv = last_viol.get(a.id)
        items.append({
            "id": a.id, "candidate": {"id": c.id, "name": c.full_name, "email": c.email}, "status": a.status,
            "started_at": a.started_at, "remaining_seconds": attempt_service.remaining_seconds(exam, a) if a.status == ATT_IN_PROGRESS else None,
            "seconds_since_heartbeat": int(silent) if silent is not None else None,
            "online": silent is not None and silent <= 30,
            "answered": len(a.answers or {}), "total_questions": total_q,
            "violation_count": a.violation_count, "level2_count": a.level2_count, "risk_score": a.risk_score,
            "risk_level": proctor_rules.risk_level(a.risk_score or 0), "state": a.last_state or {}, "ip_address": a.ip_address,
            "last_violation": {"label": lv.label, "severity": lv.severity, "at": lv.created_at} if lv else None,
        })
    return {"test": {"id": exam.id, "title": exam.title, "status": exam.status},
            "summary": {"in_progress": sum(1 for i in items if i["status"] == ATT_IN_PROGRESS), "in_lobby": sum(1 for i in items if i["status"] == ATT_REGISTERED),
                        "offline": sum(1 for i in items if i["status"] == ATT_IN_PROGRESS and not i["online"]),
                        "high_risk": sum(1 for i in items if i["risk_level"] == "high")},
            "items": items, "server_time": now}


# ---------------------------------------------------------------------------
# analytics + export
# ---------------------------------------------------------------------------
@router.get("/tests/{exam_id}/analytics")
def analytics(exam_id: int, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    attempts = db.query(models.Attempt).filter(models.Attempt.exam_id == exam.id, models.Attempt.status != ATT_VOIDED).limit(5000).all()
    finals = [a for a in attempts if a.status in FINAL_ATTEMPT_STATUSES]
    submitted = [a for a in finals if a.status == ATT_SUBMITTED]
    pcts = [a.percentage or 0 for a in submitted]
    times = [t for t in (_time_taken(a) for a in submitted) if t is not None]

    bins = [0] * 10
    for p in pcts:
        bins[min(int(p // 10), 9)] += 1
    histogram = [{"label": f"{i * 10}-{i * 10 + 10}", "count": bins[i]} for i in range(10)]

    stats: Dict[str, Dict[str, Any]] = {}
    wrong_answers: Dict[str, Counter] = defaultdict(Counter)
    for a in finals:
        text_by_id = {str(q["id"]): q for q in (a.question_data or [])}
        for qid, key in (a.answer_key or {}).items():
            ans = (a.answers or {}).get(qid)
            entry = stats.setdefault(qid, {"question_id": int(qid), "text": (text_by_id.get(qid) or {}).get("text", "")[:140],
                                           "type": key["type"], "shown": 0, "answered": 0, "correct": 0})
            entry["shown"] += 1
            if scoring.is_answered(ans):
                entry["answered"] += 1
                if scoring.is_correct(key["type"], key["correct"], ans):
                    entry["correct"] += 1
                elif key["type"] in ("single", "true_false"):
                    wrong_answers[qid][str(ans)] += 1
    question_stats = []
    for qid, e in stats.items():
        rate = round(100 * e["correct"] / e["shown"], 1) if e["shown"] else 0
        common = wrong_answers[qid].most_common(1)
        question_stats.append({**e, "correct_rate": rate, "skipped": e["shown"] - e["answered"],
                               "difficulty": "hard" if rate < 35 else "medium" if rate < 70 else "easy",
                               "most_common_wrong": common[0][0] if common else None})
    question_stats.sort(key=lambda x: x["correct_rate"])

    viol = dict(
        db.query(models.Violation.code, func.count(models.Violation.id))
        .filter(models.Violation.exam_id == exam.id, models.Violation.status != "dismissed").group_by(models.Violation.code).all()
    )
    risk = Counter(proctor_rules.risk_level(a.risk_score or 0) for a in finals)
    top = sorted(submitted, key=lambda a: -(a.percentage or 0))[:10]
    names = {u.id: u.full_name for u in db.query(models.User).filter(models.User.id.in_([a.candidate_id for a in top] or [0])).all()}
    return {
        "test": {"id": exam.id, "title": exam.title, "pass_percentage": exam.pass_percentage},
        "summary": {
            "total_attempts": len(attempts), "submitted": len(submitted), "terminated": sum(1 for a in finals if a.status == ATT_TERMINATED),
            "in_progress": sum(1 for a in attempts if a.status == ATT_IN_PROGRESS), "not_started": sum(1 for a in attempts if a.status == ATT_REGISTERED),
            "average_percentage": round(statistics.mean(pcts), 1) if pcts else None,
            "median_percentage": round(statistics.median(pcts), 1) if pcts else None,
            "highest_percentage": max(pcts) if pcts else None, "lowest_percentage": min(pcts) if pcts else None,
            "pass_rate": round(100 * sum(1 for a in submitted if a.passed) / len(submitted), 1) if submitted else None,
            "average_time_minutes": round(statistics.mean(times) / 60, 1) if times else None,
            "average_risk": round(statistics.mean(a.risk_score or 0 for a in finals), 1) if finals else None,
        },
        "histogram": histogram, "question_stats": question_stats,
        "violations_by_type": sorted(({"code": c, "label": VIOLATION_CATALOG.get(c, (0, "", c, 0))[2], "count": n} for c, n in viol.items()), key=lambda x: -x["count"]),
        "risk_distribution": {"low": risk.get("low", 0), "medium": risk.get("medium", 0), "high": risk.get("high", 0)},
        "leaderboard": [{"attempt_id": a.id, "name": names.get(a.candidate_id, "-"), "percentage": a.percentage, "score": a.score, "max_score": a.max_score} for a in top],
    }


@router.get("/tests/{exam_id}/export.csv")
def export_csv(exam_id: int, request: Request, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    rows = (
        db.query(models.Attempt, models.User).join(models.User, models.User.id == models.Attempt.candidate_id)
        .filter(models.Attempt.exam_id == exam.id, models.Attempt.status != ATT_VOIDED).order_by(models.Attempt.id).all()
    )
    ranks = _ranks(db, exam.id)
    field_keys = [f["key"] for f in (exam.candidate_fields or [])]
    field_labels = [f["label"] for f in (exam.candidate_fields or [])]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Rank", "Name", "Email", "Phone", *field_labels, "Status", "Result", "Score", "Max score", "Percentage", "Objective score",
                "Coding score", "Started (UTC)", "Submitted (UTC)", "Time taken (min)", "Violations", "Serious violations", "Risk score",
                "Risk level", "Review status", "Review note", "Auto-submitted"])
    for a, c in rows:
        taken = _time_taken(a)
        w.writerow([_csv_safe(x) for x in [
            ranks.get(a.id, ""), c.full_name, c.email, c.phone or "", *[(a.profile or {}).get(k, "") for k in field_keys],
            a.status, final_result(a) or "", a.score if a.score is not None else "", a.max_score if a.max_score is not None else "",
            a.percentage if a.percentage is not None else "", a.objective_score if a.objective_score is not None else "",
            a.coding_score if a.coding_score is not None else "", a.started_at.isoformat() if a.started_at else "",
            a.submitted_at.isoformat() if a.submitted_at else "", round(taken / 60, 1) if taken is not None else "",
            a.violation_count, a.level2_count, a.risk_score, proctor_rules.risk_level(a.risk_score or 0), a.review_status,
            a.review_note or "", "yes" if a.auto_submitted else "",
        ]])
    audit.log_event(db, "RESULTS_EXPORTED", user=user, entity_type="test", entity_id=exam.id, ip=auth.client_ip(request), commit=True)
    safe = "".join(ch if ch.isalnum() else "-" for ch in exam.title)[:40].strip("-") or "results"
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{safe}-results.csv"'})


# ---------------------------------------------------------------------------
# one attempt: the full report
# ---------------------------------------------------------------------------
@router.get("/attempts/{attempt_id}")
def attempt_report(attempt_id: int, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    a = _attempt_for_staff(db, attempt_id, user)
    exam = db.get(models.Exam, a.exam_id)
    c = db.get(models.User, a.candidate_id)
    _, _, breakdown = scoring.score_objective(a.answer_key or {}, a.answers or {})
    by_id = {b["question_id"]: b for b in breakdown}
    show_key = user.role == ROLE_ADMIN
    questions = []
    for q in a.question_data or []:
        key = (a.answer_key or {}).get(str(q["id"]), {})
        b = by_id.get(q["id"], {})
        questions.append({
            "question_id": q["id"], "text": q["text"], "type": q["type"], "options": q["options"], "section": q.get("section"),
            "answer": (a.answers or {}).get(str(q["id"])), "answered": b.get("answered", False), "is_correct": b.get("correct"),
            "awarded": b.get("awarded"), "marks": q.get("marks"), "flagged": q["id"] in (a.flagged or []),
            "correct_answer": key.get("correct") if show_key else None, "explanation": key.get("explanation") if show_key else None,
        })
    subs = (
        db.query(models.CodeSubmission, models.CodingProblem).join(models.CodingProblem, models.CodingProblem.id == models.CodeSubmission.problem_id)
        .filter(models.CodeSubmission.attempt_id == a.id).order_by(models.CodeSubmission.id).all()
    )
    violations = db.query(models.Violation).filter(models.Violation.attempt_id == a.id).order_by(models.Violation.id).all()
    snaps = db.query(models.Snapshot).filter(models.Snapshot.attempt_id == a.id).order_by(models.Snapshot.id).all()
    snap_by_violation = {s.violation_id: s.id for s in snaps if s.violation_id}
    reviewer = db.get(models.User, a.reviewer_id) if a.reviewer_id else None
    return {
        **_row(a, c, _ranks(db, exam.id)),
        "test": {"id": exam.id, "title": exam.title, "pass_percentage": exam.pass_percentage, "duration_minutes": exam.duration_minutes},
        "review": {"status": a.review_status, "note": a.review_note, "reviewer": reviewer.full_name if reviewer else None, "reviewed_at": a.reviewed_at},
        "questions": questions,
        "coding": [{"id": s.id, "problem": p.title, "language": judge0.SUPPORTED_LANGUAGES.get(s.language_id, str(s.language_id)), "verdict": s.verdict,
                    "passed": s.passed, "total": s.total, "created_at": s.created_at, "source_code": s.source_code} for s, p in subs],
        "violations": [{"id": v.id, "code": v.code, "label": v.label, "severity": v.severity, "category": v.category, "details": v.details,
                        "status": v.status, "created_at": v.created_at, "snapshot_id": snap_by_violation.get(v.id)} for v in violations],
        "snapshots": [{"id": s.id, "kind": s.kind, "created_at": s.created_at, "violation_id": s.violation_id} for s in snaps if s.kind != "violation"],
        "messages": [{"body": m.body, "created_at": m.created_at} for m in db.query(models.AttemptMessage).filter(models.AttemptMessage.attempt_id == a.id).all()],
        "environment": {"ip_address": a.ip_address, "user_agent": a.user_agent, "system_info": a.system_info or {}, "consent_at": a.consent_at},
        "can_void": user.role == ROLE_ADMIN,
    }


# ---------------------------------------------------------------------------
# proctor actions
# ---------------------------------------------------------------------------
class TerminateIn(BaseModel):
    reason: str = Field(default="Ended by a proctor", max_length=200)


class ExtendIn(BaseModel):
    minutes: int = Field(ge=1, le=120)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=500)


class ReviewIn(BaseModel):
    status: Literal["pending", "cleared", "suspicious", "disqualified"]
    note: Optional[str] = Field(default=None, max_length=2000)


def _live(a: models.Attempt) -> None:
    if a.status != ATT_IN_PROGRESS:
        raise conflict("The candidate is not taking the test right now", "not_live")


@router.post("/attempts/{attempt_id}/terminate")
def terminate(attempt_id: int, body: TerminateIn, request: Request, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    a = _attempt_for_staff(db, attempt_id, user)
    _live(a)
    exam = db.get(models.Exam, a.exam_id)
    attempt_service.finalize_attempt(db, a, exam, status=ATT_TERMINATED, reason=body.reason)
    audit.log_event(db, "ATTEMPT_TERMINATED_BY_STAFF", user=user, entity_type="attempt", entity_id=a.id, details=body.reason, ip=auth.client_ip(request), commit=True)
    return {"status": a.status}


@router.post("/attempts/{attempt_id}/force-submit")
def force_submit(attempt_id: int, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    a = _attempt_for_staff(db, attempt_id, user)
    _live(a)
    attempt_service.finalize_attempt(db, a, db.get(models.Exam, a.exam_id), reason="Submitted by a proctor")
    audit.log_event(db, "ATTEMPT_FORCE_SUBMITTED", user=user, entity_type="attempt", entity_id=a.id, commit=True)
    return {"status": a.status}


@router.post("/attempts/{attempt_id}/extend")
def extend_time(attempt_id: int, body: ExtendIn, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    a = _attempt_for_staff(db, attempt_id, user)
    _live(a)
    a.extra_seconds = (a.extra_seconds or 0) + body.minutes * 60
    db.add(models.AttemptMessage(attempt_id=a.id, sender_id=user.id, body=f"A proctor added {body.minutes} minute(s) to your time."))
    audit.log_event(db, "TIME_EXTENDED", user=user, entity_type="attempt", entity_id=a.id, details=f"+{body.minutes}min")
    db.commit()
    return {"extra_seconds": a.extra_seconds, "remaining_seconds": attempt_service.remaining_seconds(db.get(models.Exam, a.exam_id), a)}


@router.post("/attempts/{attempt_id}/message")
def message_candidate(attempt_id: int, body: MessageIn, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    a = _attempt_for_staff(db, attempt_id, user)
    _live(a)
    msg = models.AttemptMessage(attempt_id=a.id, sender_id=user.id, body=body.body.strip())
    db.add(msg)
    db.commit()
    return {"id": msg.id}


@router.post("/attempts/{attempt_id}/void")
def void_attempt(attempt_id: int, request: Request, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    """Cancel this attempt so the candidate can start fresh (their data is kept for the audit trail but excluded from results)."""
    a = _attempt_for_staff(db, attempt_id, user)
    if a.status == ATT_VOIDED:
        return {"status": a.status}
    a.status = ATT_VOIDED
    a.session_nonce = None  # any open window is logged out
    if a.invite_id:
        inv = db.get(models.Invite, a.invite_id)
        if inv and inv.status != "revoked":
            inv.status = INV_PENDING
    audit.log_event(db, "ATTEMPT_VOIDED", user=user, entity_type="attempt", entity_id=a.id, ip=auth.client_ip(request))
    db.commit()
    return {"status": a.status}


@router.post("/attempts/{attempt_id}/review")
def review_attempt(attempt_id: int, body: ReviewIn, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    a = _attempt_for_staff(db, attempt_id, user)
    if a.status not in FINAL_ATTEMPT_STATUSES:
        raise conflict("You can review an attempt once it has finished", "not_final")
    a.review_status, a.review_note, a.reviewer_id, a.reviewed_at = body.status, body.note, user.id, utcnow()
    audit.log_event(db, "ATTEMPT_REVIEWED", user=user, entity_type="attempt", entity_id=a.id, details=f"{body.status}: {(body.note or '')[:200]}")
    webhooks.emit(db, a.org_id, "attempt.reviewed", {"attempt_id": a.id, "test_id": a.exam_id, "review_status": body.status,
                                                     "reviewer": user.full_name, "score": a.score, "percentage": a.percentage})
    db.commit()
    return {"review_status": a.review_status, "final_result": final_result(a)}


class ViolationReviewIn(BaseModel):
    status: Literal["open", "confirmed", "dismissed"]


@router.patch("/violations/{violation_id}")
def review_violation(violation_id: int, body: ViolationReviewIn, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    v = db.query(models.Violation).filter(models.Violation.id == violation_id, models.Violation.org_id == user.org_id).first()
    if v is None:
        raise not_found("Violation")
    v.status, v.reviewed_by = body.status, user.id
    a = db.get(models.Attempt, v.attempt_id)
    risk = proctor_rules.recompute_risk(db, a)
    db.commit()
    return {"status": v.status, "risk_score": risk, "risk_level": proctor_rules.risk_level(risk)}


# ---------------------------------------------------------------------------
# review queue + evidence + candidates
# ---------------------------------------------------------------------------
@router.get("/review-queue")
def review_queue(min_risk: int = 15, params: PageParams = Depends(), user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    A, U, E = models.Attempt, models.User, models.Exam
    query = (
        db.query(A, U, E).join(U, U.id == A.candidate_id).join(E, E.id == A.exam_id)
        .filter(A.org_id == user.org_id, A.status.in_(list(FINAL_ATTEMPT_STATUSES)), A.review_status == REVIEW_PENDING, A.risk_score >= min_risk)
        .order_by(A.risk_score.desc(), A.id.desc())
    )
    total = query.count()
    rows = query.offset((params.page - 1) * params.page_size).limit(params.page_size).all()
    return {"items": [{**_row(a, c, {}), "test": {"id": e.id, "title": e.title}} for a, c, e in rows], "total": total, "page": params.page, "page_size": params.page_size}


@router.get("/evidence/{snapshot_id}")
def evidence(snapshot_id: int, user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    snap = db.query(models.Snapshot).filter(models.Snapshot.id == snapshot_id, models.Snapshot.org_id == user.org_id).first()
    if snap is None:
        raise not_found("Image")
    found = storage.read_image(snap.path)
    if found is None:
        raise not_found("Image")
    data, media_type = found
    return Response(data, media_type=media_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/candidates")
def list_candidates(q: Optional[str] = None, params: PageParams = Depends(), user: models.User = Depends(auth.require_org_staff), db: Session = Depends(get_db)):
    U, A = models.User, models.Attempt
    query = db.query(U).filter(U.org_id == user.org_id, U.role == ROLE_CANDIDATE)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(U.full_name).like(like), func.lower(U.email).like(like)))
    total = query.count()
    people = query.order_by(U.id.desc()).offset((params.page - 1) * params.page_size).limit(params.page_size).all()
    counts = {}
    if people:
        counts = dict(db.query(A.candidate_id, func.count(A.id)).filter(A.candidate_id.in_([p.id for p in people]), A.status != ATT_VOIDED).group_by(A.candidate_id).all())
    return {"items": [{"id": p.id, "name": p.full_name, "email": p.email, "phone": p.phone, "is_active": p.is_active,
                       "attempts": counts.get(p.id, 0), "created_at": p.created_at} for p in people],
            "total": total, "page": params.page, "page_size": params.page_size}


class CandidatePatch(BaseModel):
    is_active: bool


@router.patch("/candidates/{candidate_id}")
def block_candidate(candidate_id: int, body: CandidatePatch, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    c = tenancy.get_org_user(db, candidate_id, user.org_id)
    if c.role != ROLE_CANDIDATE:
        raise not_found("Candidate")
    c.is_active = body.is_active
    audit.log_event(db, "CANDIDATE_BLOCKED" if not body.is_active else "CANDIDATE_UNBLOCKED", user=user, entity_type="user", entity_id=c.id)
    db.commit()
    return {"id": c.id, "is_active": c.is_active}


@router.delete("/candidates/{candidate_id}")
def erase_candidate(candidate_id: int, request: Request, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    """Privacy erasure: personal data and webcam evidence are destroyed; anonymised scores remain for statistics."""
    c = tenancy.get_org_user(db, candidate_id, user.org_id)
    if c.role != ROLE_CANDIDATE:
        raise not_found("Candidate")
    snaps = db.query(models.Snapshot).join(models.Attempt, models.Attempt.id == models.Snapshot.attempt_id).filter(models.Attempt.candidate_id == c.id).all()
    for s in snaps:
        storage.delete_image(s.path)
        db.delete(s)
    db.query(models.Invite).filter(models.Invite.org_id == user.org_id, func.lower(models.Invite.email) == c.email.lower()).delete(synchronize_session=False)
    for a in db.query(models.Attempt).filter(models.Attempt.candidate_id == c.id).all():
        a.profile, a.ip_address, a.user_agent, a.system_info, a.session_nonce = {}, None, None, {}, None
    db.query(models.CodeSubmission).filter(models.CodeSubmission.candidate_id == c.id).update({"source_code": "[erased]"})
    c.full_name, c.email, c.phone, c.extra, c.is_active = "Erased candidate", f"erased-{c.id}@erased.invalid", None, {}, False
    audit.log_event(db, "CANDIDATE_ERASED", user=user, entity_type="user", entity_id=c.id, ip=auth.client_ip(request))
    db.commit()
    return {"status": "erased"}
