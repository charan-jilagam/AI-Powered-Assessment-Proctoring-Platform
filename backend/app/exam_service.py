"""Test (exam) helpers: join codes, serialisation, publishing rules, duplication, CSV question import."""
import csv
import io
import secrets
from typing import Any, Dict, List, Optional, Tuple

from app.mongo import func
from app.mongo import Session

from app import auth, models, question_rules, serializers, tenancy
from app.config import settings
from app.constants import (
    ATT_IN_PROGRESS, ATT_VOIDED, DEFAULT_PROCTORING, EXAM_DRAFT, EXAM_PUBLISHED, FINAL_ATTEMPT_STATUSES,
)
from app.errors import ApiError, bad_request
from app.timeutil import as_utc, utcnow

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L - easy to read out loud
MAX_QUESTIONS_PER_TEST = 1000
MAX_CSV_BYTES = 2 * 1024 * 1024


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in (raw or "").upper() if ch.isalnum())


def new_code(db: Session) -> str:
    for _ in range(50):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.query(models.Exam.id).filter(models.Exam.code == code).first():
            return code
    raise ApiError(500, "Could not allocate a test code, please retry", "code_exhausted")


def join_url(exam: models.Exam, invite_token: Optional[str] = None) -> str:
    url = f"{settings.frontend_url}/t/{exam.code}"
    return f"{url}?invite={invite_token}" if invite_token else url


def exam_counts(db: Session, exam_id: int) -> Dict[str, int]:
    rows = dict(
        db.query(models.Attempt.status, func.count(models.Attempt.id))
        .filter(models.Attempt.exam_id == exam_id, models.Attempt.status != ATT_VOIDED)
        .group_by(models.Attempt.status).all()
    )
    return {
        "registered": rows.get("registered", 0),
        "in_progress": rows.get("in_progress", 0),
        "submitted": rows.get("submitted", 0),
        "terminated": rows.get("terminated", 0),
    }


def exam_summary(db: Session, exam: models.Exam) -> Dict[str, Any]:
    counts = exam_counts(db, exam.id)
    q_count = db.query(func.count(models.Question.id)).filter(models.Question.exam_id == exam.id).scalar() or 0
    coding_count = db.query(func.count(models.CodingProblem.id)).filter(models.CodingProblem.exam_id == exam.id).scalar() or 0
    marks = db.query(func.coalesce(func.sum(models.Question.marks), 0)).filter(models.Question.exam_id == exam.id).scalar() or 0
    return {
        "id": exam.id, "title": exam.title, "description": exam.description, "status": exam.status,
        "code": exam.code, "code_display": serializers.format_code(exam.code), "join_url": join_url(exam),
        "duration_minutes": exam.duration_minutes, "start_time": exam.start_time, "end_time": exam.end_time,
        "access_mode": exam.access_mode, "has_password": bool(exam.access_password_hash),
        "question_count": q_count, "coding_problem_count": coding_count, "total_marks": float(marks),
        "attempts": counts, "attempts_total": sum(counts.values()),
        "created_at": exam.created_at, "published_at": exam.published_at,
        "is_sample": bool(exam.is_sample),
    }


def exam_detail(db: Session, exam: models.Exam) -> Dict[str, Any]:
    from app import coding

    data = exam_summary(db, exam)
    data.update(
        instructions=exam.instructions,
        questions_per_attempt=exam.questions_per_attempt,
        shuffle_questions=exam.shuffle_questions,
        shuffle_options=exam.shuffle_options,
        pass_percentage=exam.pass_percentage,
        result_visibility=exam.result_visibility,
        proctoring={**DEFAULT_PROCTORING, **(exam.proctoring or {})},
        candidate_fields=exam.candidate_fields or [],
        questions=[question_rules.question_to_dict(q) for q in exam.questions],
        coding_problems=[coding.admin_view(p) for p in exam.coding_problems],
    )
    return data


def clamp_proctoring_to_plan(org: models.Organization, cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    cfg = dict(cfg)
    if cfg.get("ai_monitoring") and not tenancy.effective_limits(org)["ai_proctoring"]:
        cfg["ai_monitoring"] = False
        warnings.append("AI monitoring is not included in your plan, so it was switched off for this test.")
    return cfg, warnings


def validate_schedule(start, end) -> None:
    if start and end and as_utc(end) <= as_utc(start):
        raise bad_request("The end of the window must be after its start", "bad_schedule")


def readiness_problems(db: Session, exam: models.Exam) -> List[str]:
    problems: List[str] = []
    q_count = db.query(func.count(models.Question.id)).filter(models.Question.exam_id == exam.id).scalar() or 0
    coding_count = db.query(func.count(models.CodingProblem.id)).filter(models.CodingProblem.exam_id == exam.id).scalar() or 0
    if q_count + coding_count == 0:
        problems.append("Add at least one question or coding problem.")
    if exam.questions_per_attempt and q_count and exam.questions_per_attempt > q_count:
        problems.append(f"'Questions per candidate' ({exam.questions_per_attempt}) is more than the {q_count} questions available.")
    if exam.end_time and as_utc(exam.end_time) <= utcnow():
        problems.append("The access window has already ended - extend the end time.")
    return problems


def add_question(db: Session, exam: models.Exam, data: Dict[str, Any], user: models.User) -> models.Question:
    clean = _normalize(data)
    count = db.query(func.count(models.Question.id)).filter(models.Question.exam_id == exam.id).scalar() or 0
    if count >= MAX_QUESTIONS_PER_TEST:
        raise bad_request(f"A test can have at most {MAX_QUESTIONS_PER_TEST} questions")
    position = (db.query(func.max(models.Question.position)).filter(models.Question.exam_id == exam.id).scalar() or 0) + 1
    q = models.Question(org_id=exam.org_id, exam_id=exam.id, position=position, created_by=user.id, **clean)
    db.add(q)
    return q


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return question_rules.normalize_question(data)
    except ValueError as exc:
        raise bad_request(str(exc), "bad_question")


def clone_question(src: models.Question, *, org_id: int, exam_id: Optional[int], user_id: Optional[int]) -> models.Question:
    return models.Question(
        org_id=org_id, exam_id=exam_id, question_type=src.question_type, question_text=src.question_text,
        options=list(src.options or []), correct=list(src.correct or []), marks=src.marks, negative_marks=src.negative_marks,
        section=src.section, difficulty=src.difficulty, tags=list(src.tags or []), explanation=src.explanation, created_by=user_id,
    )


def duplicate_exam(db: Session, src: models.Exam, user: models.User) -> models.Exam:
    copy = models.Exam(
        org_id=src.org_id, created_by=user.id, title=f"Copy of {src.title}"[:200], description=src.description,
        instructions=src.instructions, code=new_code(db), status=EXAM_DRAFT, duration_minutes=src.duration_minutes,
        access_mode=src.access_mode, access_password_hash=src.access_password_hash, questions_per_attempt=src.questions_per_attempt,
        shuffle_questions=src.shuffle_questions, shuffle_options=src.shuffle_options, pass_percentage=src.pass_percentage,
        result_visibility=src.result_visibility, proctoring=dict(src.proctoring or {}), candidate_fields=list(src.candidate_fields or []),
    )
    db.add(copy)
    db.flush()
    for q in src.questions:
        c = clone_question(q, org_id=src.org_id, exam_id=copy.id, user_id=user.id)
        c.position = q.position
        db.add(c)
    for p in src.coding_problems:
        db.add(models.CodingProblem(
            exam_id=copy.id, title=p.title, statement=p.statement, input_format=p.input_format, output_format=p.output_format,
            constraints=p.constraints, points=p.points, time_limit_seconds=p.time_limit_seconds, memory_limit_mb=p.memory_limit_mb,
            test_cases=[models.TestCase(input_data=t.input_data, expected_output=t.expected_output, is_sample=t.is_sample) for t in p.test_cases],
        ))
    return copy


# ---------------------------------------------------------------------------
# CSV import / template
# ---------------------------------------------------------------------------
CSV_COLUMNS = ["Type", "Question", "Option A", "Option B", "Option C", "Option D", "Option E", "Option F",
               "Answer", "Marks", "Negative Marks", "Section", "Difficulty", "Tags", "Explanation"]

CSV_TEMPLATE_ROWS = [
    ["single", "Which planet is known as the Red Planet?", "Venus", "Mars", "Jupiter", "Saturn", "", "", "B", "1", "0", "General", "easy", "space", "Mars looks red because of iron oxide."],
    ["multiple", "Select all prime numbers", "2", "3", "4", "9", "", "", "A;B", "2", "0.5", "Maths", "medium", "numbers", ""],
    ["true_false", "The Earth orbits the Sun.", "", "", "", "", "", "", "True", "1", "0", "General", "easy", "", ""],
    ["short_text", "Capital of France?", "", "", "", "", "", "", "Paris|paris", "1", "0", "General", "easy", "geography", ""],
]


def csv_template() -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    writer.writerows(CSV_TEMPLATE_ROWS)
    return buf.getvalue()


def parse_csv(content: bytes) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (valid normalized questions, errors[{row, error}]). Understands the legacy 6-column format too."""
    if len(content) > MAX_CSV_BYTES:
        raise bad_request("CSV is larger than 2 MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise bad_request("CSV must be UTF-8 encoded")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise bad_request("The CSV file is empty")
    headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    if "question" not in headers or "answer" not in headers:
        raise bad_request("CSV must have at least the columns: Question, Option A, Option B, Answer (download the template)")

    def cell(row, name):
        h = headers.get(name)
        return (row.get(h) or "").strip() if h else ""

    good, errors = [], []
    for line_no, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue
        try:
            qtype = (cell(row, "type") or "single").lower()
            options = [cell(row, f"option {c}") for c in "abcdef"]
            options = [o for o in options if o]
            answer = cell(row, "answer")
            if qtype == "short_text":
                correct: List[Any] = [a for a in answer.split("|") if a.strip()]
            elif qtype == "multiple":
                correct = [a for a in answer.replace(",", ";").split(";") if a.strip()]
            else:
                correct = [answer]
            data = question_rules.normalize_question({
                "question_type": qtype, "question_text": cell(row, "question"), "options": options, "correct": correct,
                "marks": float(cell(row, "marks") or 1), "negative_marks": float(cell(row, "negative marks") or 0),
                "section": cell(row, "section"), "difficulty": cell(row, "difficulty") or "medium",
                "tags": [t for t in cell(row, "tags").replace("|", ",").replace(";", ",").split(",") if t.strip()],
                "explanation": cell(row, "explanation"),
            })
            good.append(data)
        except (ValueError, TypeError) as exc:
            errors.append({"row": line_no, "error": str(exc)})
    return good, errors


def has_started_attempts(db: Session, exam_id: int) -> bool:
    return db.query(models.Attempt.id).filter(models.Attempt.exam_id == exam_id, models.Attempt.status != ATT_VOIDED, models.Attempt.started_at.isnot(None)).first() is not None


def has_live_attempts(db: Session, exam_id: int) -> bool:
    return db.query(models.Attempt.id).filter(models.Attempt.exam_id == exam_id, models.Attempt.status == ATT_IN_PROGRESS).first() is not None
