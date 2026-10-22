"""Dependency that resolves the candidate's attempt from their token (shared by the exam and coding routers)."""
from typing import NamedTuple

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app import attempt_service, auth, models
from app.constants import ATT_IN_PROGRESS, ROLE_CANDIDATE
from app.database import get_db
from app.errors import ApiError, forbidden


class AttemptCtx(NamedTuple):
    attempt: models.Attempt
    exam: models.Exam
    user: models.User


def attempt_ctx(request: Request, user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)) -> AttemptCtx:
    claims = getattr(request.state, "claims", {}) or {}
    if user.role != ROLE_CANDIDATE or not claims.get("aid"):
        raise forbidden("This endpoint is for candidates")
    attempt = db.get(models.Attempt, int(claims["aid"]))
    if attempt is None or attempt.candidate_id != user.id or attempt.org_id != user.org_id:
        raise ApiError(401, "Could not validate credentials", "invalid_token")
    if claims.get("sn") != attempt.session_nonce:
        raise ApiError(401, "This exam was opened in another window or device. Only one session is allowed.", "session_replaced")
    exam = db.get(models.Exam, attempt.exam_id)
    if attempt.status == ATT_IN_PROGRESS and attempt_service.is_expired(exam, attempt):
        attempt_service.finalize_attempt(db, attempt, exam, auto=True, reason="Time expired")
    return AttemptCtx(attempt, exam, user)
