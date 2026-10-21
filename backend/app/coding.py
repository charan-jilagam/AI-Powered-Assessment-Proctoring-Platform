"""
Coding questions: admin authoring + candidate run/submit, judged by Judge0.

Security model
- Candidates can only run code for an exam they have an *active, in-time* session
  for, and only for problems that belong to that exam.
- Hidden test cases (inputs AND expected outputs) never leave the server. Sample
  cases are shown to candidates; hidden ones only report pass/fail.
- Grading is done server-side from stored code submissions, never from a score
  sent by the browser.
- Executions are throttled per user (not per IP, so a whole lab behind one NAT
  isn't locked out together).
"""
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import audit, auth, judge0, models, schemas
from app.database import get_db

router = APIRouter(tags=["coding"])

MAX_SOURCE_CHARS = 64_000
MAX_CUSTOM_INPUT_CHARS = 10_000
MAX_TEST_CASES = 50
MAX_TEST_IO_CHARS = 100_000
EXEC_PER_MINUTE = int(os.getenv("CODE_EXEC_PER_MINUTE", "15"))
TIME_GRACE_SECONDS = 60  # network/latency slack after the exam timer hits zero

# user_id -> timestamps of recent executions (in-memory; fine for one API process)
_exec_log: Dict[int, deque] = defaultdict(deque)


def reset_throttle() -> None:
    _exec_log.clear()


def _throttle(user_id: int) -> None:
    now = time.monotonic()
    recent = _exec_log[user_id]
    while recent and now - recent[0] > 60:
        recent.popleft()
    if len(recent) >= EXEC_PER_MINUTE:
        raise HTTPException(status_code=429, detail="You are running code too quickly. Please wait a few seconds.")
    recent.append(now)


def _require_admin(user: models.User, action: str) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail=f"Only admins can {action}")


# ----------------------------------------------------------------------------
# authoring helpers (also used by POST /exams/create in main.py)
# ----------------------------------------------------------------------------
def validate_problem(p: schemas.CodingProblemCreate) -> None:
    if not p.title.strip():
        raise HTTPException(status_code=400, detail="Every coding problem needs a title")
    if not p.statement.strip():
        raise HTTPException(status_code=400, detail=f"Coding problem '{p.title}' needs a statement")
    if not 1 <= p.points <= 1000:
        raise HTTPException(status_code=400, detail=f"'{p.title}': points must be between 1 and 1000")
    if not 0.5 <= p.time_limit_seconds <= 15:
        raise HTTPException(status_code=400, detail=f"'{p.title}': time limit must be between 0.5 and 15 seconds")
    if not 16 <= p.memory_limit_mb <= 256:
        raise HTTPException(status_code=400, detail=f"'{p.title}': memory limit must be between 16 and 256 MB")
    if not p.test_cases:
        raise HTTPException(status_code=400, detail=f"'{p.title}' needs at least one test case")
    if len(p.test_cases) > MAX_TEST_CASES:
        raise HTTPException(status_code=400, detail=f"'{p.title}' has more than {MAX_TEST_CASES} test cases")
    for i, tc in enumerate(p.test_cases, start=1):
        if not tc.expected_output.strip():
            raise HTTPException(status_code=400, detail=f"'{p.title}': test case {i} has an empty expected output")
        if len(tc.input_data) > MAX_TEST_IO_CHARS or len(tc.expected_output) > MAX_TEST_IO_CHARS:
            raise HTTPException(status_code=400, detail=f"'{p.title}': test case {i} is too large")


def create_problem(db: Session, exam_id: int, p: schemas.CodingProblemCreate) -> models.CodingProblem:
    """Add a problem and its test cases to the session. The caller commits."""
    problem = models.CodingProblem(
        exam_id=exam_id,
        title=p.title.strip(),
        statement=p.statement,
        input_format=p.input_format,
        output_format=p.output_format,
        constraints=p.constraints,
        points=p.points,
        time_limit_seconds=p.time_limit_seconds,
        memory_limit_mb=p.memory_limit_mb,
        test_cases=[
            models.TestCase(
                input_data=tc.input_data,
                expected_output=tc.expected_output,
                is_sample=tc.is_sample,
            )
            for tc in p.test_cases
        ],
    )
    db.add(problem)
    return problem


def admin_view(problem: models.CodingProblem) -> dict:
    return {
        "id": problem.id,
        "exam_id": problem.exam_id,
        "title": problem.title,
        "statement": problem.statement,
        "input_format": problem.input_format,
        "output_format": problem.output_format,
        "constraints": problem.constraints,
        "points": problem.points,
        "time_limit_seconds": problem.time_limit_seconds,
        "memory_limit_mb": problem.memory_limit_mb,
        "test_cases": [
            {
                "id": tc.id,
                "input_data": tc.input_data,
                "expected_output": tc.expected_output,
                "is_sample": tc.is_sample,
            }
            for tc in problem.test_cases
        ],
    }


def student_view(problem: models.CodingProblem) -> dict:
    """What a candidate may see: statement + SAMPLE cases only."""
    return {
        "id": problem.id,
        "title": problem.title,
        "statement": problem.statement,
        "input_format": problem.input_format,
        "output_format": problem.output_format,
        "constraints": problem.constraints,
        "points": problem.points,
        "time_limit_seconds": problem.time_limit_seconds,
        "memory_limit_mb": problem.memory_limit_mb,
        "samples": [
            {"input": tc.input_data, "expected_output": tc.expected_output}
            for tc in problem.test_cases
            if tc.is_sample
        ],
        "hidden_test_count": sum(1 for tc in problem.test_cases if not tc.is_sample),
    }


def student_problem_views(exam: models.Exam) -> List[dict]:
    return [student_view(p) for p in exam.coding_problems]


# ----------------------------------------------------------------------------
# scoring + cleanup helpers (used by main.py)
# ----------------------------------------------------------------------------
def _best_by_problem(db: Session, exam_id: int, student_id: int) -> Dict[int, models.CodeSubmission]:
    rows = (
        db.query(models.CodeSubmission)
        .filter(models.CodeSubmission.exam_id == exam_id, models.CodeSubmission.student_id == student_id)
        .order_by(models.CodeSubmission.id)
        .all()
    )
    best: Dict[int, models.CodeSubmission] = {}
    for row in rows:
        ratio = (row.passed / row.total) if row.total else 0
        current = best.get(row.problem_id)
        current_ratio = (current.passed / current.total) if current and current.total else -1
        if current is None or ratio >= current_ratio:  # later submission wins ties
            best[row.problem_id] = row
    return best


def coding_score(db: Session, exam_id: int, student_id: int) -> Tuple[int, int]:
    """
    (points earned, points available) from the student's best submission per
    problem. Partial credit is rounded DOWN, so full points need every test.
    """
    problems = db.query(models.CodingProblem).filter(models.CodingProblem.exam_id == exam_id).all()
    best = _best_by_problem(db, exam_id, student_id)
    earned = 0
    for problem in problems:
        sub = best.get(problem.id)
        if sub and sub.total:
            earned += (problem.points * sub.passed) // sub.total
    return earned, sum(p.points for p in problems)


def delete_exam_coding_data(db: Session, exam_id: int) -> None:
    """Remove all coding data for an exam (call before deleting the exam row)."""
    db.query(models.CodeSubmission).filter(models.CodeSubmission.exam_id == exam_id).delete()
    problem_ids = [pid for (pid,) in db.query(models.CodingProblem.id).filter(models.CodingProblem.exam_id == exam_id)]
    if problem_ids:
        db.query(models.TestCase).filter(models.TestCase.problem_id.in_(problem_ids)).delete(synchronize_session=False)
    db.query(models.CodingProblem).filter(models.CodingProblem.exam_id == exam_id).delete()


def delete_student_code(db: Session, student_id: int, exam_id: Optional[int] = None) -> None:
    q = db.query(models.CodeSubmission).filter(models.CodeSubmission.student_id == student_id)
    if exam_id is not None:
        q = q.filter(models.CodeSubmission.exam_id == exam_id)
    q.delete()


# ----------------------------------------------------------------------------
# candidate helpers
# ----------------------------------------------------------------------------
def _elapsed_seconds(started_at: datetime) -> float:
    """Seconds since the exam session started, correct for aware (Postgres) and naive (SQLite, UTC) values."""
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started_at).total_seconds()


def _student_problem(db: Session, exam_id: int, problem_id: int, user: models.User) -> models.CodingProblem:
    exam = db.get(models.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    session = db.query(models.ExamSession).filter(
        models.ExamSession.exam_id == exam_id,
        models.ExamSession.student_id == user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=400, detail="Start the exam before running code")
    if session.status != "in_progress":
        raise HTTPException(status_code=403, detail="This exam session is no longer active")

    if _elapsed_seconds(session.started_at) > exam.duration_minutes * 60 + TIME_GRACE_SECONDS:
        raise HTTPException(status_code=400, detail="Time is up for this exam")

    problem = db.query(models.CodingProblem).filter(
        models.CodingProblem.id == problem_id,
        models.CodingProblem.exam_id == exam_id,
    ).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Coding problem not found in this exam")
    return problem


def _check_code(language_id: int, source_code: str) -> None:
    if language_id not in judge0.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported programming language")
    if not source_code.strip():
        raise HTTPException(status_code=400, detail="Write some code first")
    if len(source_code) > MAX_SOURCE_CHARS:
        raise HTTPException(status_code=400, detail="Source code is too long")


def _unavailable(user: models.User, exc: Exception) -> HTTPException:
    audit.log_event("JUDGE0_ERROR", user.email, str(exc)[:300])
    return HTTPException(status_code=503, detail="Code execution service is unavailable right now. Please try again in a moment.")


# ----------------------------------------------------------------------------
# routes: shared
# ----------------------------------------------------------------------------
@router.get("/coding/languages")
def list_languages(current_user: models.User = Depends(auth.get_current_user)):
    return [{"id": lid, "name": name} for lid, name in judge0.SUPPORTED_LANGUAGES.items()]


# ----------------------------------------------------------------------------
# routes: admin authoring
# ----------------------------------------------------------------------------
@router.post("/exams/{exam_id}/coding-problems")
def add_coding_problem(
    exam_id: int,
    problem: schemas.CodingProblemCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_admin(current_user, "add coding problems")
    if not db.get(models.Exam, exam_id):
        raise HTTPException(status_code=404, detail="Exam not found")
    validate_problem(problem)

    created = create_problem(db, exam_id, problem)
    db.commit()
    db.refresh(created)
    audit.log_event("CODING_PROBLEM_ADDED", current_user.email, f"exam_id={exam_id} problem_id={created.id} title='{created.title}'")
    return admin_view(created)


@router.post("/exams/{exam_id}/coding-problems/bulk")
def add_coding_problems_bulk(
    exam_id: int,
    body: schemas.CodingProblemBulkCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_admin(current_user, "add coding problems")
    if not db.get(models.Exam, exam_id):
        raise HTTPException(status_code=404, detail="Exam not found")
    if not body.problems:
        raise HTTPException(status_code=400, detail="No problems provided")
    for p in body.problems:  # validate everything first so the import is all-or-nothing
        validate_problem(p)

    created = [create_problem(db, exam_id, p) for p in body.problems]
    db.commit()
    audit.log_event("CODING_PROBLEMS_IMPORTED", current_user.email, f"exam_id={exam_id} count={len(created)}")
    return {"status": "imported", "count": len(created)}


@router.get("/exams/{exam_id}/coding-problems")
def list_coding_problems(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_admin(current_user, "view coding problems")
    problems = (
        db.query(models.CodingProblem)
        .filter(models.CodingProblem.exam_id == exam_id)
        .order_by(models.CodingProblem.id)
        .all()
    )
    return [admin_view(p) for p in problems]


@router.delete("/coding-problems/{problem_id}")
def delete_coding_problem(
    problem_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_admin(current_user, "delete coding problems")
    problem = db.get(models.CodingProblem, problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Coding problem not found")

    db.query(models.CodeSubmission).filter(models.CodeSubmission.problem_id == problem_id).delete()
    title, exam_id = problem.title, problem.exam_id
    db.delete(problem)  # test cases go with it (cascade)
    db.commit()
    audit.log_event("CODING_PROBLEM_DELETED", current_user.email, f"exam_id={exam_id} problem_id={problem_id} title='{title}'")
    return {"status": "deleted", "problem_id": problem_id}


@router.get("/exams/{exam_id}/coding-submissions")
def list_coding_submissions(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Admin review: every graded code submission for the exam, newest first."""
    _require_admin(current_user, "view code submissions")
    rows = (
        db.query(models.CodeSubmission, models.User, models.CodingProblem)
        .join(models.User, models.User.id == models.CodeSubmission.student_id)
        .join(models.CodingProblem, models.CodingProblem.id == models.CodeSubmission.problem_id)
        .filter(models.CodeSubmission.exam_id == exam_id)
        .order_by(models.CodeSubmission.id.desc())
        .limit(500)
        .all()
    )
    return [
        {
            "id": sub.id,
            "student_id": user.id,
            "student_name": user.full_name,
            "student_email": user.email,
            "problem_id": problem.id,
            "problem_title": problem.title,
            "language": judge0.SUPPORTED_LANGUAGES.get(sub.language_id, str(sub.language_id)),
            "verdict": sub.verdict,
            "passed": sub.passed,
            "total": sub.total,
            "created_at": sub.created_at,
            "source_code": sub.source_code,
        }
        for sub, user, problem in rows
    ]


# ----------------------------------------------------------------------------
# routes: candidate run / submit / progress
# ----------------------------------------------------------------------------
@router.post("/exams/{exam_id}/coding-problems/{problem_id}/run")
def run_code(
    exam_id: int,
    problem_id: int,
    body: schemas.CodeRunRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Practice run: sample tests (or custom stdin). Not graded, not stored."""
    problem = _student_problem(db, exam_id, problem_id, current_user)
    _check_code(body.language_id, body.source_code)
    if body.custom_input is not None and len(body.custom_input) > MAX_CUSTOM_INPUT_CHARS:
        raise HTTPException(status_code=400, detail="Custom input is too long")

    samples = [
        {"input": tc.input_data, "expected": tc.expected_output, "is_sample": True}
        for tc in problem.test_cases
        if tc.is_sample
    ]
    if body.custom_input is None and not samples:
        raise HTTPException(status_code=400, detail="This problem has no sample tests - use custom input to try your code")

    _throttle(current_user.id)
    try:
        if body.custom_input is not None:
            result = judge0.run_custom(body.source_code, body.language_id, body.custom_input,
                                       problem.time_limit_seconds, problem.memory_limit_mb)
            return {"mode": "custom", **result}
        result = judge0.judge(body.source_code, body.language_id, samples,
                              problem.time_limit_seconds, problem.memory_limit_mb)
        return {"mode": "samples", **result}
    except judge0.Judge0Error as exc:
        raise _unavailable(current_user, exc)


@router.post("/exams/{exam_id}/coding-problems/{problem_id}/submit")
def submit_code(
    exam_id: int,
    problem_id: int,
    body: schemas.CodeSubmitRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Graded run against ALL tests. The best submission per problem counts."""
    problem = _student_problem(db, exam_id, problem_id, current_user)
    _check_code(body.language_id, body.source_code)

    cases = [
        {"input": tc.input_data, "expected": tc.expected_output, "is_sample": tc.is_sample}
        for tc in problem.test_cases
    ]
    if not cases:
        raise HTTPException(status_code=400, detail="This problem has no test cases yet")

    _throttle(current_user.id)
    try:
        result = judge0.judge(body.source_code, body.language_id, cases,
                              problem.time_limit_seconds, problem.memory_limit_mb)
    except judge0.Judge0Error as exc:
        raise _unavailable(current_user, exc)

    submission = models.CodeSubmission(
        exam_id=exam_id,
        problem_id=problem_id,
        student_id=current_user.id,
        language_id=body.language_id,
        source_code=body.source_code,
        verdict=result["verdict"],
        passed=result["passed"],
        total=result["total"],
        details=json.dumps([
            {k: c[k] for k in ("label", "passed", "verdict", "time", "memory_kb")}
            for c in result["cases"]
        ]),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    audit.log_event(
        "CODE_SUBMITTED", current_user.email,
        f"exam_id={exam_id} problem_id={problem_id} verdict='{result['verdict']}' passed={result['passed']}/{result['total']}",
    )

    best = _best_by_problem(db, exam_id, current_user.id).get(problem_id)
    return {
        "submission_id": submission.id,
        **result,
        "best_passed": best.passed if best else result["passed"],
        "best_total": best.total if best else result["total"],
    }


@router.get("/exams/{exam_id}/coding-progress")
def coding_progress(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """The candidate's own best result + last code per problem (restores state after a refresh)."""
    best = _best_by_problem(db, exam_id, current_user.id)
    last_by_problem: Dict[int, models.CodeSubmission] = {}
    attempts: Dict[int, int] = defaultdict(int)
    rows = (
        db.query(models.CodeSubmission)
        .filter(models.CodeSubmission.exam_id == exam_id, models.CodeSubmission.student_id == current_user.id)
        .order_by(models.CodeSubmission.id)
        .all()
    )
    for row in rows:
        last_by_problem[row.problem_id] = row
        attempts[row.problem_id] += 1

    return [
        {
            "problem_id": pid,
            "best_passed": sub.passed,
            "best_total": sub.total,
            "best_verdict": sub.verdict,
            "attempts": attempts[pid],
            "last_language_id": last_by_problem[pid].language_id,
            "last_source_code": last_by_problem[pid].source_code,
        }
        for pid, sub in best.items()
    ]
