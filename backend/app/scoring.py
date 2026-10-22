"""Pure scoring logic - no database, no web. This is the most correctness-critical code in the product.

Options are shuffled per candidate, so answers are always compared by option TEXT, never by position.
"""
import random
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.constants import Q_MULTIPLE, Q_SHORT, Q_SINGLE, Q_TRUE_FALSE


def norm(text: Any) -> str:
    return " ".join(str(text).strip().lower().split())


def build_attempt_questions(
    questions: Iterable[Any],
    *,
    per_attempt: Optional[int],
    shuffle_questions: bool,
    shuffle_options: bool,
    rng: Optional[random.Random] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Pick and arrange the questions one candidate will see.

    Returns (question_data, answer_key). question_data is safe to send to the browser;
    answer_key stays on the server.
    """
    rng = rng or random.Random()
    pool = list(questions)
    if per_attempt and per_attempt < len(pool):
        pool = rng.sample(pool, per_attempt)
        pool.sort(key=lambda q: (q.position, q.id))  # keep authored order unless shuffling below
    if shuffle_questions:
        rng.shuffle(pool)

    question_data: List[Dict[str, Any]] = []
    answer_key: Dict[str, Dict[str, Any]] = {}
    for q in pool:
        options = list(q.options or [])
        if q.question_type in (Q_SINGLE, Q_MULTIPLE) and shuffle_options:
            rng.shuffle(options)
        if q.question_type == Q_SHORT:
            correct_texts = [str(a) for a in (q.correct or [])]
        else:
            original = list(q.options or [])
            correct_texts = [original[i] for i in (q.correct or []) if 0 <= i < len(original)]
        question_data.append({
            "id": q.id,
            "type": q.question_type,
            "text": q.question_text,
            "options": options,
            "marks": q.marks,
            "section": q.section,
            "difficulty": q.difficulty,
        })
        answer_key[str(q.id)] = {
            "type": q.question_type,
            "correct": correct_texts,
            "marks": q.marks,
            "negative": q.negative_marks,
            "explanation": q.explanation,
        }
    return question_data, answer_key


def is_answered(answer: Any) -> bool:
    if answer is None:
        return False
    if isinstance(answer, (list, tuple, set)):
        return len(answer) > 0
    return bool(str(answer).strip())


def is_correct(qtype: str, correct: List[str], answer: Any) -> bool:
    if not is_answered(answer):
        return False
    if qtype in (Q_SINGLE, Q_TRUE_FALSE):
        if isinstance(answer, (list, tuple)):
            return False
        return bool(correct) and norm(answer) == norm(correct[0])
    if qtype == Q_MULTIPLE:
        given = answer if isinstance(answer, (list, tuple, set)) else [answer]
        return {norm(a) for a in given} == {norm(c) for c in correct} and len(given) == len(set(norm(a) for a in given))
    if qtype == Q_SHORT:
        if isinstance(answer, (list, tuple)):
            return False
        return norm(answer) in {norm(c) for c in correct}
    return False


def score_objective(
    answer_key: Dict[str, Dict[str, Any]], answers: Dict[str, Any]
) -> Tuple[float, float, List[Dict[str, Any]]]:
    """(score, max_score, per-question breakdown). Only questions in the key count - extras are ignored."""
    total = 0.0
    max_score = 0.0
    breakdown: List[Dict[str, Any]] = []
    for qid, key in answer_key.items():
        marks = float(key.get("marks", 1))
        max_score += marks
        answer = answers.get(qid, answers.get(int(qid)) if qid.isdigit() else None)
        answered = is_answered(answer)
        correct = is_correct(key["type"], key["correct"], answer)
        if correct:
            awarded = marks
        elif answered:
            awarded = -float(key.get("negative", 0))
        else:
            awarded = 0.0
        total += awarded
        breakdown.append({
            "question_id": int(qid),
            "answered": answered,
            "correct": correct,
            "awarded": round(awarded, 2),
            "marks": marks,
        })
    return round(max(total, 0.0), 2), round(max_score, 2), breakdown


def percentage(score: float, max_score: float) -> float:
    return round(score / max_score * 100, 2) if max_score else 0.0
