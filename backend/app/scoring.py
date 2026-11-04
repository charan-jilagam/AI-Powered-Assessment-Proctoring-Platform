"""Pure scoring logic - no database, no web. This is the most correctness-critical code in the product.

Options are shuffled per candidate, so answers are always compared by option TEXT, never by position.
"""
import random
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.constants import Q_MULTIPLE, Q_SHORT, Q_SINGLE, Q_TRUE_FALSE


def norm(text: Any) -> str:
    return " ".join(str(text).strip().lower().split())


SET_LETTERS = "ABCDEF"


def _materialize(pool: List[Any], arrange_options) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Turn ordered Question rows into (question_data for the browser, answer_key for the server).

    ``arrange_options(question, options)`` may reorder the option list in place."""
    question_data: List[Dict[str, Any]] = []
    answer_key: Dict[str, Dict[str, Any]] = {}
    for q in pool:
        options = list(q.options or [])
        if q.question_type in (Q_SINGLE, Q_MULTIPLE):
            arrange_options(q, options)
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

    def arrange(_q, options):
        if shuffle_options:
            rng.shuffle(options)

    return _materialize(pool, arrange)


# ---------------------------------------------------------------------------
# Fixed question sets (Set A, Set B, ...)
# ---------------------------------------------------------------------------
def set_letter(index: int) -> str:
    return SET_LETTERS[index]


def set_index(letter: str) -> int:
    letter = (letter or "").strip().upper()
    if len(letter) != 1 or letter not in SET_LETTERS:
        raise ValueError(f"Unknown question set '{letter}'")
    return SET_LETTERS.index(letter)


def pick_set(counts: Dict[str, int], n_sets: int) -> int:
    """Index of the set to give the next candidate: the least-used one (ties go to the earlier letter), so the sets
    stay evenly spread no matter how many people join."""
    return min(range(n_sets), key=lambda i: (counts.get(SET_LETTERS[i], 0), i))


def _subset(pool: List[Any], exam_id: int, per_attempt: Optional[int]) -> List[Any]:
    """The same questions for every candidate of the exam (a set is one paper, so it cannot be a per-person draw)."""
    if per_attempt and per_attempt < len(pool):
        chosen = random.Random(f"{exam_id}|subset|{per_attempt}").sample(range(len(pool)), per_attempt)
        return [pool[i] for i in sorted(chosen)]
    return pool


def set_order(pool: List[Any], exam_id: int, index: int) -> List[Any]:
    """Question order of set ``index``. Set A (0) is the authored order. Every other set shuffles the questions
    *inside* each section (section order is kept, as on a printed paper) and is guaranteed to differ from the earlier
    sets whenever the questions allow it. Deterministic: the same exam always yields the same sets."""
    if index == 0:
        return list(pool)
    groups: Dict[str, List[Any]] = {}
    for q in pool:
        groups.setdefault(q.section or "", []).append(q)
    seen = {tuple(q.id for q in pool)}
    order: List[Any] = list(pool)
    for j in range(1, index + 1):
        rng = random.Random(f"{exam_id}|set{j}|order")
        for attempt in range(30):
            order = []
            for items in groups.values():
                part = list(items)
                rng.shuffle(part)
                order.extend(part)
            if tuple(q.id for q in order) not in seen:
                break
        seen.add(tuple(q.id for q in order))
    return order


def build_set_paper(
    questions: Iterable[Any],
    *,
    exam_id: int,
    index: int,
    per_attempt: Optional[int],
    shuffle_options: bool,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """The fixed paper of set ``index``: identical for every candidate who gets that set. Set A keeps the authored
    option order; the other sets also shuffle each question's options when ``shuffle_options`` is on."""
    pool = _subset(list(questions), exam_id, per_attempt)
    ordered = set_order(pool, exam_id, index)

    def arrange(q, options):
        if shuffle_options and index > 0:
            random.Random(f"{exam_id}|set{index}|opt|{q.id}").shuffle(options)

    return _materialize(ordered, arrange)


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
