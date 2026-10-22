"""Validation + normalisation for questions, shared by the JSON API, the bank and CSV import."""
from typing import Any, Dict, List

from app.constants import DIFFICULTIES, Q_MULTIPLE, Q_SHORT, Q_SINGLE, Q_TRUE_FALSE, QUESTION_TYPES

MAX_OPTIONS = 8
MIN_OPTIONS = 2


def normalize_question(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a clean dict of question columns or raise ValueError with a human-readable reason."""
    qtype = (data.get("question_type") or Q_SINGLE).strip().lower()
    if qtype not in QUESTION_TYPES:
        raise ValueError(f"Unknown question type '{qtype}'")

    text = (data.get("question_text") or "").strip()
    if not text:
        raise ValueError("Question text is required")
    if len(text) > 5000:
        raise ValueError("Question text is too long (5000 characters max)")

    marks = float(data.get("marks", 1) or 0)
    negative = float(data.get("negative_marks", 0) or 0)
    if not 0 < marks <= 100:
        raise ValueError("Marks must be greater than 0 and at most 100")
    if not 0 <= negative <= 100:
        raise ValueError("Negative marks must be between 0 and 100")

    difficulty = (data.get("difficulty") or "medium").strip().lower()
    if difficulty not in DIFFICULTIES:
        raise ValueError("Difficulty must be easy, medium or hard")

    options: List[str] = [str(o).strip() for o in (data.get("options") or [])]
    correct = list(data.get("correct") or [])

    if qtype == Q_TRUE_FALSE:
        options = ["True", "False"]
        if len(correct) != 1:
            raise ValueError("Pick whether the statement is True or False")
        correct = [_index(correct[0], options)]
    elif qtype in (Q_SINGLE, Q_MULTIPLE):
        if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
            raise ValueError(f"Provide between {MIN_OPTIONS} and {MAX_OPTIONS} options")
        if any(not o for o in options):
            raise ValueError("Options cannot be blank")
        if len({o.lower() for o in options}) != len(options):
            raise ValueError("Options must be different from each other")
        indexes = sorted({_index(c, options) for c in correct})
        if not indexes:
            raise ValueError("Mark at least one correct option")
        if qtype == Q_SINGLE and len(indexes) != 1:
            raise ValueError("A single-answer question needs exactly one correct option")
        correct = indexes
    else:  # short text
        options = []
        answers = [str(c).strip() for c in correct if str(c).strip()]
        if not answers:
            raise ValueError("Provide at least one accepted answer")
        correct = answers

    tags = [str(t).strip().lower() for t in (data.get("tags") or []) if str(t).strip()][:10]
    return {
        "question_type": qtype,
        "question_text": text,
        "options": options,
        "correct": correct,
        "marks": marks,
        "negative_marks": negative,
        "section": (data.get("section") or "").strip()[:80] or None,
        "difficulty": difficulty,
        "tags": tags,
        "explanation": (data.get("explanation") or "").strip() or None,
    }


def _index(value: Any, options: List[str]) -> int:
    """Accept an index (2, "2"), an option letter ("C") or the option text itself."""
    if isinstance(value, int) and not isinstance(value, bool):
        idx = value
    else:
        s = str(value).strip()
        if s.isdigit():
            idx = int(s)
        elif len(s) == 1 and s.upper() in "ABCDEFGH":
            idx = "ABCDEFGH".index(s.upper())
        else:
            lowered = [o.lower() for o in options]
            if s.lower() not in lowered:
                raise ValueError(f"Correct answer '{s}' is not one of the options")
            idx = lowered.index(s.lower())
    if not 0 <= idx < len(options):
        raise ValueError("Correct answer points to an option that does not exist")
    return idx


def question_to_dict(q) -> Dict[str, Any]:
    """Admin-facing representation (includes the answer key)."""
    return {
        "id": q.id,
        "exam_id": q.exam_id,
        "question_type": q.question_type,
        "question_text": q.question_text,
        "options": q.options or [],
        "correct": q.correct or [],
        "marks": q.marks,
        "negative_marks": q.negative_marks,
        "section": q.section,
        "difficulty": q.difficulty,
        "tags": q.tags or [],
        "explanation": q.explanation,
        "position": q.position,
    }
