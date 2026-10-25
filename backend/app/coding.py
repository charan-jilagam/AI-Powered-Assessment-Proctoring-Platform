"""
Coding questions: admin authoring + candidate run/submit, judged by Judge0.

Security model
- Candidates can only run code inside their own *active, in-time* attempt, and only for problems
  that belong to that attempt's test. Admin endpoints are scoped to the caller's organization.
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

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import ValidationError
from app.mongo import Session

from app import attempt_service, audit, auth, judge0, models, schemas, tenancy
from app.attempt_deps import AttemptCtx, attempt_ctx
from app.constants import ATT_IN_PROGRESS
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
def _best_by_problem(db: Session, exam_id: int, candidate_id: int, attempt_id: Optional[int] = None) -> Dict[int, models.CodeSubmission]:
    query = db.query(models.CodeSubmission).filter(
        models.CodeSubmission.exam_id == exam_id, models.CodeSubmission.candidate_id == candidate_id
    )
    if attempt_id is not None:
        query = query.filter(models.CodeSubmission.attempt_id == attempt_id)
    rows = query.order_by(models.CodeSubmission.id).all()
    best: Dict[int, models.CodeSubmission] = {}
    for row in rows:
        ratio = (row.passed / row.total) if row.total else 0
        current = best.get(row.problem_id)
        current_ratio = (current.passed / current.total) if current and current.total else -1
        if current is None or ratio >= current_ratio:  # later submission wins ties
            best[row.problem_id] = row
    return best


def coding_score(db: Session, exam_id: int, candidate_id: int, attempt_id: Optional[int] = None) -> Tuple[int, int]:
    """
    (points earned, points available) from the student's best submission per
    problem. Partial credit is rounded DOWN, so full points need every test.
    """
    problems = db.query(models.CodingProblem).filter(models.CodingProblem.exam_id == exam_id).all()
    best = _best_by_problem(db, exam_id, candidate_id, attempt_id)
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


def delete_candidate_code(db: Session, candidate_id: int, exam_id: Optional[int] = None) -> None:
    q = db.query(models.CodeSubmission).filter(models.CodeSubmission.candidate_id == candidate_id)
    if exam_id is not None:
        q = q.filter(models.CodeSubmission.exam_id == exam_id)
    q.delete()


# ----------------------------------------------------------------------------
# candidate helpers
# ----------------------------------------------------------------------------
def _candidate_problem(db: Session, ctx: AttemptCtx, problem_id: int) -> models.CodingProblem:
    attempt, exam = ctx.attempt, ctx.exam
    if attempt.status != ATT_IN_PROGRESS:
        raise HTTPException(status_code=403, detail="This exam session is no longer active")
    problem = db.query(models.CodingProblem).filter(
        models.CodingProblem.id == problem_id,
        models.CodingProblem.exam_id == exam.id,
    ).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Coding problem not found in this exam")
    return problem


def _check_code(language_id: int, source_code: str) -> None:
    if language_id not in judge0.get_languages():
        raise HTTPException(status_code=400, detail="Unsupported programming language")
    if not source_code.strip():
        raise HTTPException(status_code=400, detail="Write some code first")
    if len(source_code) > MAX_SOURCE_CHARS:
        raise HTTPException(status_code=400, detail="Source code is too long")


def _unavailable(email: str, exc: Exception) -> HTTPException:
    audit.log_event(None, "JUDGE0_ERROR", actor_email=email, details=str(exc)[:300])
    return HTTPException(status_code=503, detail="Code execution service is unavailable right now. Please try again in a moment.")


def _admin_exam(db: Session, exam_id: int, user: models.User, org: models.Organization, *, need_feature: bool = False) -> models.Exam:
    exam = tenancy.get_exam(db, exam_id, user.org_id)
    if need_feature:
        tenancy.ensure_feature(org, "coding_enabled", "Coding questions")
    return exam


# ----------------------------------------------------------------------------
# JSON import
# ----------------------------------------------------------------------------
MAX_IMPORT_PROBLEMS = 50

JSON_FORMAT_DOC = [
    {"field": "problems", "type": "array", "required": True, "note": "The list of coding problems. A bare array [ ... ] or a single problem object is accepted too."},
    {"field": "title", "type": "string", "required": True, "note": "Shown to the candidate."},
    {"field": "statement", "type": "string", "required": True, "note": "The problem description. Plain text; line breaks are kept."},
    {"field": "input_format", "type": "string", "required": False, "note": "How the input is laid out."},
    {"field": "output_format", "type": "string", "required": False, "note": "What the program must print."},
    {"field": "constraints", "type": "string", "required": False, "note": "Limits on the input, e.g. 1 <= n <= 1000."},
    {"field": "points", "type": "integer", "required": False, "note": "1 to 1000. Default 10. Partial credit is given per test case passed."},
    {"field": "time_limit_seconds", "type": "number", "required": False, "note": "0.5 to 15. Default 2."},
    {"field": "memory_limit_mb", "type": "integer", "required": False, "note": "16 to 256. Default 256."},
    {"field": "test_cases", "type": "array", "required": True, "note": "At least one, at most 50. Candidates run the sample cases and are graded on all of them."},
    {"field": "test_cases[].input_data", "type": "string", "required": False, "note": "Text sent to the program's standard input (\\n for new lines). Empty if the program reads nothing."},
    {"field": "test_cases[].expected_output", "type": "string", "required": True, "note": "What the program must print. Trailing spaces and blank lines at the end are ignored."},
    {"field": "test_cases[].is_sample", "type": "boolean", "required": False, "note": "true = shown to candidates and used by Run. false (default) = hidden; only pass/fail is revealed."},
]

JSON_FORMAT_EXAMPLE = {
    "problems": [
        {
            "title": "Sum of Two Numbers",
            "statement": "Read two integers a and b and print their sum.",
            "input_format": "One line with two integers a and b separated by a space.",
            "output_format": "A single integer: a + b.",
            "constraints": "-10^9 <= a, b <= 10^9",
            "points": 10,
            "time_limit_seconds": 2,
            "memory_limit_mb": 256,
            "test_cases": [
                {"input_data": "3 4\n", "expected_output": "7\n", "is_sample": True},
                {"input_data": "-5 12\n", "expected_output": "7\n", "is_sample": True},
                {"input_data": "0 0\n", "expected_output": "0\n", "is_sample": False},
                {"input_data": "1000000000 1000000000\n", "expected_output": "2000000000\n", "is_sample": False},
            ],
        },
        {
            "title": "Palindrome Check",
            "statement": "Read a word. Print YES if it reads the same forwards and backwards, otherwise NO.",
            "input_format": "One line with a lowercase word.",
            "output_format": "YES or NO.",
            "points": 20,
            "test_cases": [
                {"input_data": "level\n", "expected_output": "YES\n", "is_sample": True},
                {"input_data": "coding\n", "expected_output": "NO\n", "is_sample": False},
            ],
        },
    ]
}

_TC_ALIASES = {"input": "input_data", "stdin": "input_data", "output": "expected_output", "expected": "expected_output", "stdout": "expected_output", "sample": "is_sample"}
_P_ALIASES = {"testcases": "test_cases", "testCases": "test_cases", "tests": "test_cases", "name": "title", "description": "statement",
              "timeLimit": "time_limit_seconds", "memoryLimit": "memory_limit_mb", "inputFormat": "input_format", "outputFormat": "output_format"}


def _text(value) -> str:
    """Numbers are fine as test data ("expected_output": 7); None means empty."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else json.dumps(value) if isinstance(value, (list, dict)) else str(value)


def _normalize_problem(raw: dict) -> dict:
    p = {_P_ALIASES.get(k, k): v for k, v in raw.items()}
    cases = []
    for tc in p.get("test_cases") or []:
        if not isinstance(tc, dict):
            cases.append(tc)  # let validation report it
            continue
        tc = {_TC_ALIASES.get(k, k): v for k, v in tc.items()}
        for key in ("input_data", "expected_output"):
            if key in tc:
                tc[key] = _text(tc[key])
        cases.append(tc)
    if "test_cases" in p or cases:
        p["test_cases"] = cases
    return p


def parse_import(payload) -> List[schemas.CodingProblemCreate]:
    """Turn pasted JSON into validated problems or raise one 422 that lists every mistake, with the problem number."""
    if isinstance(payload, dict) and isinstance(payload.get("problems"), list):
        items = payload["problems"]
    elif isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and ("title" in payload or "statement" in payload):
        items = [payload]
    else:
        raise HTTPException(status_code=422, detail='Expected {"problems": [ ... ]}, a list of problems, or a single problem object.')
    if not items:
        raise HTTPException(status_code=422, detail="The list of problems is empty.")
    if len(items) > MAX_IMPORT_PROBLEMS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_IMPORT_PROBLEMS} problems can be imported at once (you sent {len(items)}).")

    problems: List[schemas.CodingProblemCreate] = []
    errors: List[str] = []
    for n, raw in enumerate(items, start=1):
        label = f"Problem {n}"
        if not isinstance(raw, dict):
            errors.append(f"{label}: must be an object with title, statement and test_cases.")
            continue
        if isinstance(raw.get("title"), str) and raw["title"].strip():
            label += f" (\u201c{raw['title'].strip()[:60]}\u201d)"
        try:
            problem = schemas.CodingProblemCreate(**_normalize_problem(raw))
            validate_problem(problem)
            problems.append(problem)
        except ValidationError as exc:
            for err in exc.errors()[:4]:
                where = ".".join(str(x) for x in err["loc"]) or "problem"
                errors.append(f"{label}: {where} - {err['msg']}")
        except HTTPException as exc:
            errors.append(f"{label}: {exc.detail}")
        except (TypeError, ValueError) as exc:
            errors.append(f"{label}: {exc}")
    if errors:
        shown = errors[:12]
        more = f" (+{len(errors) - len(shown)} more)" if len(errors) > len(shown) else ""
        raise HTTPException(status_code=422, detail=" | ".join(shown) + more)
    return problems


# ----------------------------------------------------------------------------
# routes: admin authoring (organization-scoped)
# ----------------------------------------------------------------------------
@router.post("/tests/{exam_id}/coding-problems")
def add_coding_problem(
    exam_id: int,
    problem: schemas.CodingProblemCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_verified_admin),
    org: models.Organization = Depends(auth.get_current_org),
):
    _admin_exam(db, exam_id, user, org, need_feature=True)
    validate_problem(problem)
    created = create_problem(db, exam_id, problem)
    audit.log_event(db, "CODING_PROBLEM_ADDED", user=user, entity_type="test", entity_id=exam_id, details=f"title='{problem.title}'")
    db.commit()
    db.refresh(created)
    return admin_view(created)


@router.post("/tests/{exam_id}/coding-problems/bulk")
def add_coding_problems_bulk(
    exam_id: int,
    body: schemas.CodingProblemBulkCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_verified_admin),
    org: models.Organization = Depends(auth.get_current_org),
):
    _admin_exam(db, exam_id, user, org, need_feature=True)
    if not body.problems:
        raise HTTPException(status_code=400, detail="No problems provided")
    for p in body.problems:  # validate everything first so the import is all-or-nothing
        validate_problem(p)
    created = [create_problem(db, exam_id, p) for p in body.problems]
    audit.log_event(db, "CODING_PROBLEMS_IMPORTED", user=user, entity_type="test", entity_id=exam_id, details=f"count={len(created)}")
    db.commit()
    return {"status": "imported", "count": len(created)}


@router.get("/coding-problems/json-format")
def coding_json_format(user: models.User = Depends(auth.require_org_admin)):
    """The JSON layout accepted by the importer - shown to whoever builds the test."""
    return {"fields": JSON_FORMAT_DOC, "example": JSON_FORMAT_EXAMPLE, "max_problems": MAX_IMPORT_PROBLEMS, "max_test_cases": MAX_TEST_CASES}


@router.post("/tests/{exam_id}/coding-problems/import-json")
def import_coding_problems_json(
    exam_id: int,
    payload=Body(...),
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_verified_admin),
    org: models.Organization = Depends(auth.get_current_org),
):
    """Add coding problems from JSON. All-or-nothing: if anything is wrong nothing is added and every mistake is listed.
    With dry_run=true the JSON is only checked and summarised."""
    _admin_exam(db, exam_id, user, org, need_feature=True)
    problems = parse_import(payload)
    summary = [{"title": p.title, "points": p.points, "test_cases": len(p.test_cases), "samples": sum(1 for t in p.test_cases if t.is_sample)} for p in problems]
    if dry_run:
        return {"status": "valid", "count": len(problems), "problems": summary, "dry_run": True}
    for p in problems:
        create_problem(db, exam_id, p)
    audit.log_event(db, "CODING_PROBLEMS_IMPORTED", user=user, entity_type="test", entity_id=exam_id, details=f"json count={len(problems)}")
    db.commit()
    return {"status": "imported", "count": len(problems), "problems": summary, "dry_run": False}


@router.get("/tests/{exam_id}/coding-problems")
def list_coding_problems(
    exam_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_org_admin),
):
    tenancy.get_exam(db, exam_id, user.org_id)
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
    user: models.User = Depends(auth.require_org_admin),
):
    problem = db.get(models.CodingProblem, problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Coding problem not found")
    tenancy.get_exam(db, problem.exam_id, user.org_id)  # 404 if it belongs to another organization
    db.query(models.CodeSubmission).filter(models.CodeSubmission.problem_id == problem_id).delete()
    title, exam_id = problem.title, problem.exam_id
    db.delete(problem)  # test cases go with it (cascade)
    audit.log_event(db, "CODING_PROBLEM_DELETED", user=user, entity_type="test", entity_id=exam_id, details=f"title='{title}'")
    db.commit()
    return {"status": "deleted", "problem_id": problem_id}


@router.get("/tests/{exam_id}/coding-submissions")
def list_coding_submissions(
    exam_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_org_staff),
):
    """Review: every graded code submission for the test, newest first."""
    tenancy.get_exam(db, exam_id, user.org_id)
    rows = (
        db.query(models.CodeSubmission, models.User, models.CodingProblem)
        .join(models.User, models.User.id == models.CodeSubmission.candidate_id)
        .join(models.CodingProblem, models.CodingProblem.id == models.CodeSubmission.problem_id)
        .filter(models.CodeSubmission.exam_id == exam_id)
        .order_by(models.CodeSubmission.id.desc())
        .limit(500)
        .all()
    )
    return [
        {
            "id": sub.id,
            "candidate_id": u.id,
            "candidate_name": u.full_name,
            "candidate_email": u.email,
            "problem_id": problem.id,
            "problem_title": problem.title,
            "language": judge0.language_name(sub.language_id),
            "verdict": sub.verdict,
            "passed": sub.passed,
            "total": sub.total,
            "created_at": sub.created_at,
            "source_code": sub.source_code,
        }
        for sub, u, problem in rows
    ]


# ----------------------------------------------------------------------------
# routes: candidate (bound to the caller's own in-progress attempt)
# ----------------------------------------------------------------------------
@router.get("/attempt/coding/languages")
def list_languages(ctx: AttemptCtx = Depends(attempt_ctx)):
    return [{"id": lid, "name": name, "family": judge0.family_of(name)} for lid, name in judge0.get_languages().items()]


@router.post("/attempt/coding/{problem_id}/run")
def run_code(
    problem_id: int,
    body: schemas.CodeRunRequest,
    db: Session = Depends(get_db),
    ctx: AttemptCtx = Depends(attempt_ctx),
):
    """Practice run: sample tests (or custom stdin). Not graded, not stored."""
    problem = _candidate_problem(db, ctx, problem_id)
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

    _throttle(ctx.user.id)
    try:
        if body.custom_input is not None:
            result = judge0.run_custom(body.source_code, body.language_id, body.custom_input,
                                       problem.time_limit_seconds, problem.memory_limit_mb)
            return {"mode": "custom", **result}
        result = judge0.judge(body.source_code, body.language_id, samples,
                              problem.time_limit_seconds, problem.memory_limit_mb)
        return {"mode": "samples", **result}
    except judge0.Judge0Error as exc:
        raise _unavailable(ctx.user.email, exc)


@router.post("/attempt/coding/{problem_id}/submit")
def submit_code(
    problem_id: int,
    body: schemas.CodeSubmitRequest,
    db: Session = Depends(get_db),
    ctx: AttemptCtx = Depends(attempt_ctx),
):
    """Graded run against ALL tests. The best submission per problem counts."""
    problem = _candidate_problem(db, ctx, problem_id)
    _check_code(body.language_id, body.source_code)

    cases = [
        {"input": tc.input_data, "expected": tc.expected_output, "is_sample": tc.is_sample}
        for tc in problem.test_cases
    ]
    if not cases:
        raise HTTPException(status_code=400, detail="This problem has no test cases yet")

    _throttle(ctx.user.id)
    try:
        result = judge0.judge(body.source_code, body.language_id, cases,
                              problem.time_limit_seconds, problem.memory_limit_mb)
    except judge0.Judge0Error as exc:
        raise _unavailable(ctx.user.email, exc)

    exam_id = ctx.exam.id
    submission = models.CodeSubmission(
        exam_id=exam_id,
        problem_id=problem_id,
        candidate_id=ctx.user.id,
        attempt_id=ctx.attempt.id,
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
    audit.log_event(
        db, "CODE_SUBMITTED", user=ctx.user, org_id=ctx.exam.org_id, entity_type="test", entity_id=exam_id,
        details=f"problem_id={problem_id} verdict='{result['verdict']}' passed={result['passed']}/{result['total']}",
    )
    db.commit()
    db.refresh(submission)

    best = _best_by_problem(db, exam_id, ctx.user.id, ctx.attempt.id).get(problem_id)
    return {
        "submission_id": submission.id,
        **result,
        "best_passed": best.passed if best else result["passed"],
        "best_total": best.total if best else result["total"],
    }


@router.get("/attempt/coding/progress")
def coding_progress(
    db: Session = Depends(get_db),
    ctx: AttemptCtx = Depends(attempt_ctx),
):
    """The candidate's own best result + last code per problem (restores state after a refresh)."""
    exam_id, user_id = ctx.exam.id, ctx.user.id
    best = _best_by_problem(db, exam_id, user_id, ctx.attempt.id)
    last_by_problem: Dict[int, models.CodeSubmission] = {}
    attempts: Dict[int, int] = defaultdict(int)
    rows = (
        db.query(models.CodeSubmission)
        .filter(models.CodeSubmission.exam_id == exam_id, models.CodeSubmission.candidate_id == user_id,
                models.CodeSubmission.attempt_id == ctx.attempt.id)
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
