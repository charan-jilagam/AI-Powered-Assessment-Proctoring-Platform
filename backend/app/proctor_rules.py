"""Server-authoritative violation handling. Browsers REPORT codes; the server decides severity, dedupes,
counts, scores risk and terminates. A tampered client can omit reports but cannot downgrade or fake severity."""
from datetime import timedelta
from typing import Any, Dict, Optional

from app.mongo import Session

from app import audit, models, storage
from app.constants import (
    ATT_IN_PROGRESS, ATT_TERMINATED, DEFAULT_PROCTORING, DUPLICATE_WINDOW_SECONDS,
    MAX_VIOLATIONS_PER_ATTEMPT, VIOLATION_CATALOG,
)
from app.errors import ApiError
from app.timeutil import as_utc, utcnow


def config_for(exam: models.Exam) -> Dict[str, Any]:
    cfg = dict(DEFAULT_PROCTORING)
    cfg.update(exam.proctoring or {})
    return cfg


def risk_level(score: int) -> str:
    if score >= 40:
        return "high"
    if score >= 15:
        return "medium"
    return "low"


def classify(code: str):
    if code not in VIOLATION_CATALOG:
        raise ApiError(400, "Unknown violation code", "bad_violation")
    return VIOLATION_CATALOG[code]


def _enabled(cfg: Dict[str, Any], code: str) -> bool:
    if code in ("TAB_SWITCH", "WINDOW_BLUR") and not cfg.get("detect_tab_switch", True):
        return False
    if code == "COPY_PASTE" and not cfg.get("block_copy_paste", True):
        return False
    if code == "RIGHT_CLICK" and not cfg.get("block_right_click", True):
        return False
    if code == "FULLSCREEN_EXIT" and not cfg.get("fullscreen_required", True):
        return False
    return True


def record_violation(
    db: Session,
    attempt: models.Attempt,
    exam: models.Exam,
    code: str,
    *,
    details: Optional[str] = None,
    image: Optional[str] = None,
    source: str = "browser",
) -> Dict[str, Any]:
    """Persist one violation (if it counts) and apply the termination rule. Returns the candidate-visible outcome."""
    severity, category, label, weight = classify(code)
    cfg = config_for(exam)
    max_l2 = int(cfg.get("max_level2_violations", 3))
    outcome = {"recorded": False, "code": code, "severity": severity, "label": label,
               "level2_count": attempt.level2_count, "max_level2": max_l2, "terminated": attempt.status == ATT_TERMINATED}

    if attempt.status != ATT_IN_PROGRESS or not _enabled(cfg, code):
        return outcome
    if attempt.violation_count >= MAX_VIOLATIONS_PER_ATTEMPT:
        return outcome

    since = utcnow() - timedelta(seconds=DUPLICATE_WINDOW_SECONDS)
    recent = (
        db.query(models.Violation.id)
        .filter(models.Violation.attempt_id == attempt.id, models.Violation.code == code, models.Violation.created_at >= since)
        .first()
    )
    if recent:
        return outcome  # same event repeating inside the dedupe window counts once

    violation = models.Violation(
        org_id=attempt.org_id, exam_id=attempt.exam_id, attempt_id=attempt.id, candidate_id=attempt.candidate_id,
        code=code, category=category, severity=severity, label=label,
        details=(f"[{source}] " + details) if details else f"[{source}]",
    )
    db.add(violation)
    db.flush()

    if image:
        try:
            rel = storage.save_image(attempt.org_id, attempt.id, "violation", image)
            db.add(models.Snapshot(org_id=attempt.org_id, attempt_id=attempt.id, violation_id=violation.id, kind="violation", path=rel))
        except ApiError:
            pass  # a bad evidence image must not lose the violation itself

    attempt.violation_count += 1
    attempt.risk_score = min(100, (attempt.risk_score or 0) + weight)
    counts_toward_termination = severity == 2 and (category != "ai" or cfg.get("ai_can_terminate", False))
    if counts_toward_termination:
        attempt.level2_count += 1
    outcome.update(recorded=True, level2_count=attempt.level2_count, violation_id=violation.id)

    if cfg.get("auto_terminate", True) and counts_toward_termination and attempt.level2_count >= max_l2:
        from app import attempt_service

        attempt_service.finalize_attempt(
            db, attempt, exam, status=ATT_TERMINATED,
            reason=f"Terminated automatically after {attempt.level2_count} serious violations",
        )
        outcome["terminated"] = True
    else:
        db.commit()
    return outcome


def recompute_risk(db: Session, attempt: models.Attempt) -> int:
    """Risk score from non-dismissed violations (used after a reviewer dismisses or confirms flags)."""
    total = 0
    l1 = l2 = 0
    for v in db.query(models.Violation).filter(models.Violation.attempt_id == attempt.id).all():
        if v.status == "dismissed":
            continue
        total += VIOLATION_CATALOG.get(v.code, (1, "", "", 1))[3]
        l1 += 1
        if v.severity == 2:
            l2 += 1
    attempt.risk_score = min(100, total)
    return attempt.risk_score


def seen_recently(attempt: models.Attempt, window_seconds: int = 45) -> bool:
    ts = as_utc(attempt.last_heartbeat_at)
    return ts is not None and (utcnow() - ts).total_seconds() <= window_seconds
