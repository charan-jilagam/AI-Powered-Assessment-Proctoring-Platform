"""Builds OMR sheets (see ``omr_pdf``) from attempts and tests, and the header the live sheet in the exam room shows.

Everything here is read-only. Answers are stored as option TEXT (so shuffling can never corrupt scoring); an OMR
bubble is simply the position of that text in the options *as this candidate saw them*, which is exactly what the
exam room labels A, B, C ... on screen.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app import models, omr_pdf, scoring
from app.constants import Q_MULTIPLE, Q_SHORT, Q_SINGLE, Q_TRUE_FALSE
from app.timeutil import as_utc, utcnow

MAX_SHEETS_PER_EXPORT = 1000


# ---------------------------------------------------------------------------
# time zone: the browser sends its IANA name; unknown / missing names fall back to UTC
# ---------------------------------------------------------------------------
def _zone(name: Optional[str]):
    if name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - bad name, or no tz database on this machine
            pass
    return timezone.utc


def _stamp(dt: Optional[datetime], tz_name: Optional[str]) -> Dict[str, str]:
    if dt is None:
        return {"date": "", "time": ""}
    local = as_utc(dt).astimezone(_zone(tz_name))
    return {"date": local.strftime("%d %b %Y"), "time": f"{local.strftime('%H:%M')} {local.tzname() or 'UTC'}"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def labels_for(qtype: str, option_count: int) -> List[str]:
    return ["T", "F"] if qtype == Q_TRUE_FALSE else [chr(65 + i) for i in range(option_count)]


def _indexes(options: List[str], values: Iterable[Any]) -> List[int]:
    wanted = {scoring.norm(v) for v in values}
    return [i for i, o in enumerate(options) if scoring.norm(o) in wanted]


def _given(answer: Any) -> List[Any]:
    if answer is None:
        return []
    return list(answer) if isinstance(answer, (list, tuple, set)) else [answer]


def candidate_extras(exam: models.Exam, attempt: models.Attempt) -> List[tuple]:
    profile = attempt.profile or {}
    return [(str(f.get("label") or f.get("key")), str(profile.get(f.get("key"), "") or "")) for f in (exam.candidate_fields or []) if f.get("key")]


def _sets_text(exam: models.Exam) -> str:
    n = int(exam.question_sets or 1)
    return scoring.SET_LETTERS[:n] if n > 1 else ""


def institute_name(exam: models.Exam, org: models.Organization) -> str:
    return (exam.omr_institute or "").strip() or (org.name if org else "") or "Institute"


# ---------------------------------------------------------------------------
# sheets
# ---------------------------------------------------------------------------
def sheet_for_attempt(attempt: models.Attempt, exam: models.Exam, org: models.Organization, candidate: models.User,
                      *, evaluated: bool, tz: Optional[str] = None) -> omr_pdf.OmrSheet:
    answers = attempt.answers or {}
    key = attempt.answer_key or {}
    questions: List[omr_pdf.OmrQuestion] = []
    right = wrong = blank = 0
    for number, q in enumerate(attempt.question_data or [], start=1):
        k = key.get(str(q["id"]), {})
        given = answers.get(str(q["id"]))
        answered = scoring.is_answered(given)
        verdict = None
        if evaluated:
            verdict = "blank" if not answered else "correct" if scoring.is_correct(q["type"], k.get("correct", []), given) else "wrong"
            right += verdict == "correct"
            wrong += verdict == "wrong"
            blank += verdict == "blank"
        if q["type"] == Q_SHORT:
            questions.append(omr_pdf.OmrQuestion(
                number, "short_text", text=str(given or ""), verdict=verdict,
                correct_text=" | ".join(str(a) for a in k.get("correct", [])) if evaluated else None))
            continue
        options = list(q.get("options") or [])
        questions.append(omr_pdf.OmrQuestion(
            number, q["type"], labels_for(q["type"], len(options)), _indexes(options, _given(given)),
            _indexes(options, k.get("correct", [])) if evaluated else None, verdict=verdict))

    summary = None
    if evaluated:
        score, max_score, _ = scoring.score_objective(key, answers)
        if attempt.score is not None and attempt.max_score:        # final figures include any coding marks
            score, max_score = attempt.score, attempt.max_score
        pct = scoring.percentage(score, max_score)
        passed = attempt.passed if attempt.passed is not None else pct >= float(exam.pass_percentage or 0)
        summary = {"score": round(float(score), 2), "max": round(float(max_score), 2), "percentage": round(float(pct), 2),
                   "correct": right, "wrong": wrong, "blank": blank, "result": "PASS" if passed else "FAIL"}

    when = _stamp(attempt.started_at, tz)
    return omr_pdf.OmrSheet(
        institute=institute_name(exam, org), note=(exam.omr_note or "").strip(), test_title=exam.title, questions=questions,
        test_code=_pretty_code(exam.code), candidate_name=candidate.full_name or "", email=candidate.email or "", phone=candidate.phone or "",
        extras=candidate_extras(exam, attempt), date_text=when["date"], time_text=when["time"],
        duration_text=f"{exam.duration_minutes} minutes", attempt_ref=f"Attempt {attempt.id}",
        set_letter=attempt.paper_set or "", set_letters=_sets_text(exam), evaluated=evaluated, summary=summary,
        generated_text=_generated(tz))


def blank_sheets(exam: models.Exam, org: models.Organization, questions: List[models.Question], *,
                 set_letter: Optional[str] = None, tz: Optional[str] = None) -> List[omr_pdf.OmrSheet]:
    """Printable empty sheets: one per set when the test has sets (or just the one asked for), else a single sheet."""
    n_sets = int(exam.question_sets or 1)
    wanted = [scoring.set_index(set_letter)] if set_letter else (list(range(n_sets)) if n_sets > 1 else [None])
    sheets = []
    for index in wanted:
        if index is None:
            data, _ = scoring.build_attempt_questions(questions, per_attempt=exam.questions_per_attempt, shuffle_questions=False, shuffle_options=False)
        else:
            data, _ = scoring.build_set_paper(questions, exam_id=exam.id, index=index, per_attempt=exam.questions_per_attempt, shuffle_options=bool(exam.shuffle_options))
        qs = []
        for number, q in enumerate(data, start=1):
            if q["type"] == Q_SHORT:
                qs.append(omr_pdf.OmrQuestion(number, "short_text"))
            else:
                qs.append(omr_pdf.OmrQuestion(number, q["type"], labels_for(q["type"], len(q["options"]))))
        sheets.append(omr_pdf.OmrSheet(
            institute=institute_name(exam, org), note=(exam.omr_note or "").strip(), test_title=exam.title, questions=qs,
            test_code=_pretty_code(exam.code), duration_text=f"{exam.duration_minutes} minutes",
            extras=[(str(f.get("label") or f.get("key")), "") for f in (exam.candidate_fields or []) if f.get("key")],
            set_letter=scoring.set_letter(index) if index is not None and n_sets > 1 else "", set_letters=_sets_text(exam),
            blank=True, generated_text=_generated(tz)))
    return sheets


def _pretty_code(code: Optional[str]) -> str:
    code = code or ""
    return f"{code[:4]}-{code[4:]}" if len(code) == 8 else code


def _generated(tz: Optional[str]) -> str:
    s = _stamp(utcnow(), tz)
    return f"Generated {s['date']} {s['time']}"


def safe_filename(text: str, fallback: str = "omr") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip("-.")[:60]
    return cleaned or fallback


# ---------------------------------------------------------------------------
# the live sheet in the exam room
# ---------------------------------------------------------------------------
def live_header(attempt: models.Attempt, exam: models.Exam, org: models.Organization, candidate: models.User) -> Dict[str, Any]:
    """Everything the on-screen OMR header shows. (The date is formatted by the browser in the candidate's own time zone.)"""
    return {
        "enabled": bool(exam.omr_enabled),
        "institute": institute_name(exam, org), "note": (exam.omr_note or "").strip(), "test_title": exam.title,
        "test_code": _pretty_code(exam.code), "duration_minutes": exam.duration_minutes,
        "started_at": attempt.started_at, "paper_set": attempt.paper_set, "sets": _sets_text(exam),
        "candidate": {"name": candidate.full_name, "email": candidate.email, "phone": candidate.phone,
                      "fields": [{"label": lbl, "value": val} for lbl, val in candidate_extras(exam, attempt)]},
        "attempt_ref": f"Attempt {attempt.id}",
    }
