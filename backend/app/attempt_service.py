"""The attempt lifecycle: timing, finalisation (scoring), expiry sweeping and the candidate-visible result."""
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app import audit, models, scoring, webhooks
from app.constants import (
    ATT_IN_PROGRESS, ATT_SUBMITTED, ATT_TERMINATED, INV_COMPLETED, RESULT_FULL, RESULT_NONE,
)
from app.timeutil import as_utc, utcnow

log = logging.getLogger("proctorai.attempts")

EXPIRY_GRACE_SECONDS = 30  # network slack after the timer hits zero before the server force-submits


def deadline(exam: models.Exam, attempt: models.Attempt):
    if attempt.started_at is None:
        return None
    return as_utc(attempt.started_at) + timedelta(seconds=exam.duration_minutes * 60 + (attempt.extra_seconds or 0))


def remaining_seconds(exam: models.Exam, attempt: models.Attempt) -> int:
    end = deadline(exam, attempt)
    if end is None:
        return exam.duration_minutes * 60
    return max(0, int((end - utcnow()).total_seconds()))


def is_expired(exam: models.Exam, attempt: models.Attempt) -> bool:
    end = deadline(exam, attempt)
    return end is not None and utcnow() > end + timedelta(seconds=EXPIRY_GRACE_SECONDS)


def finalize_attempt(
    db: Session,
    attempt: models.Attempt,
    exam: models.Exam,
    *,
    status: str = ATT_SUBMITTED,
    auto: bool = False,
    reason: Optional[str] = None,
    answers: Optional[Dict[str, Any]] = None,
    flagged: Optional[list] = None,
) -> models.Attempt:
    """Close an in-progress attempt and score it. Safe against double calls / races: only one caller wins."""
    now = utcnow()
    # Atomic claim: only the caller that flips in_progress -> final proceeds to score.
    claimed = db.execute(
        update(models.Attempt)
        .where(models.Attempt.id == attempt.id, models.Attempt.status == ATT_IN_PROGRESS)
        .values(status=status, submitted_at=now, auto_submitted=auto, terminated_reason=reason)
    ).rowcount
    db.refresh(attempt)
    if not claimed:
        return attempt

    if answers is not None:
        attempt.answers = answers
    if flagged is not None:
        attempt.flagged = flagged

    from app import coding  # local import: coding depends on auth/models, avoid a cycle at import time

    objective, objective_max, _ = scoring.score_objective(attempt.answer_key or {}, attempt.answers or {})
    coding_earned, coding_total = coding.coding_score(db, exam.id, attempt.candidate_id, attempt.id)
    total = round(objective + coding_earned, 2)
    max_score = round(objective_max + coding_total, 2)
    attempt.objective_score = objective
    attempt.coding_score = float(coding_earned)
    attempt.score = total
    attempt.max_score = max_score
    attempt.percentage = scoring.percentage(total, max_score)
    attempt.passed = bool(max_score) and attempt.percentage >= (exam.pass_percentage or 0)

    if attempt.invite_id:
        invite = db.get(models.Invite, attempt.invite_id)
        if invite:
            invite.status = INV_COMPLETED

    candidate = db.get(models.User, attempt.candidate_id)
    event = "attempt.terminated" if status == ATT_TERMINATED else "attempt.submitted"
    audit.log_event(
        db, "ATTEMPT_TERMINATED" if status == ATT_TERMINATED else "ATTEMPT_SUBMITTED",
        actor_email=candidate.email if candidate else "candidate", org_id=attempt.org_id,
        entity_type="attempt", entity_id=attempt.id,
        details=f"exam={exam.id} score={total}/{max_score} auto={auto} reason={reason or ''}",
    )
    webhooks.emit(db, attempt.org_id, event, {
        "attempt_id": attempt.id, "test_id": exam.id, "test_title": exam.title,
        "candidate": {"id": attempt.candidate_id, "name": candidate.full_name if candidate else None,
                      "email": candidate.email if candidate else None},
        "score": total, "max_score": max_score, "percentage": attempt.percentage, "passed": attempt.passed,
        "status": status, "risk_score": attempt.risk_score, "violations": attempt.violation_count,
    })
    db.commit()
    return attempt


def sweep_expired(db: Session) -> int:
    """Force-submit every in-progress attempt whose time ran out (candidate closed the browser, lost power...)."""
    done = 0
    rows = (
        db.query(models.Attempt, models.Exam)
        .join(models.Exam, models.Exam.id == models.Attempt.exam_id)
        .filter(models.Attempt.status == ATT_IN_PROGRESS)
        .all()
    )
    for attempt, exam in rows:
        if is_expired(exam, attempt):
            try:
                finalize_attempt(db, attempt, exam, auto=True, reason="Time expired")
                done += 1
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("could not finalise attempt %s", attempt.id)
    return done


def result_for_candidate(attempt: models.Attempt, exam: models.Exam) -> Dict[str, Any]:
    """What the candidate is allowed to see once the attempt is over (controlled by the test's visibility setting)."""
    payload: Dict[str, Any] = {
        "status": attempt.status,
        "submitted_at": attempt.submitted_at,
        "auto_submitted": attempt.auto_submitted,
        "terminated_reason": attempt.terminated_reason if attempt.status == ATT_TERMINATED else None,
        "visibility": exam.result_visibility,
        "test_title": exam.title,
    }
    if exam.result_visibility == RESULT_NONE or attempt.status == ATT_TERMINATED and exam.result_visibility == RESULT_NONE:
        return payload
    if attempt.status == ATT_TERMINATED:
        return payload  # terminated candidates get no score
    payload.update(score=attempt.score, max_score=attempt.max_score, percentage=attempt.percentage, passed=attempt.passed,
                   pass_percentage=exam.pass_percentage)
    if exam.result_visibility == RESULT_FULL:
        _, _, breakdown = scoring.score_objective(attempt.answer_key or {}, attempt.answers or {})
        by_id = {b["question_id"]: b for b in breakdown}
        review = []
        for q in attempt.question_data or []:
            key = (attempt.answer_key or {}).get(str(q["id"]), {})
            b = by_id.get(q["id"], {})
            review.append({
                "question_id": q["id"], "text": q["text"], "type": q["type"], "options": q["options"],
                "your_answer": (attempt.answers or {}).get(str(q["id"])),
                "correct_answer": key.get("correct"), "is_correct": b.get("correct"),
                "awarded": b.get("awarded"), "marks": q.get("marks"), "explanation": key.get("explanation"),
            })
        payload["review"] = review
    return payload
