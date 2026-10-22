"""Run side effects (e-mail, webhooks) only AFTER the database transaction that caused them has committed.

Services call `after_commit(db, fn, *args)`. When the session commits, the callables are handed to a small
thread pool (or run inline when BACKGROUND_INLINE=true, which the test-suite uses to stay deterministic).
A rolled-back transaction discards its pending side effects, so nobody is e-mailed about something that never happened.
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger("proctorai.background")
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="proctorai-bg")
_KEY = "after_commit_jobs"


def inline() -> bool:
    return os.getenv("BACKGROUND_INLINE", "false").lower() in {"1", "true", "yes"}


def after_commit(db: Session, fn, *args) -> None:
    db.info.setdefault(_KEY, []).append((fn, args))


def _safe(fn, args):
    try:
        fn(*args)
    except Exception:  # a failed side effect must never take the API down
        log.exception("background job %s failed", getattr(fn, "__name__", fn))


@event.listens_for(Session, "after_commit")
def _run_jobs(session: Session) -> None:
    jobs = session.info.pop(_KEY, [])
    for fn, args in jobs:
        if inline():
            _safe(fn, args)
        else:
            _executor.submit(_safe, fn, args)


@event.listens_for(Session, "after_rollback")
def _drop_jobs(session: Session) -> None:
    session.info.pop(_KEY, None)
