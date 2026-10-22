"""Scoring is the most correctness-critical path: test every question type and the shuffling guarantees."""
import random
from types import SimpleNamespace as NS

from app import scoring


def q(id, type="single", options=("A", "B", "C", "D"), correct=(1,), marks=1, negative=0, position=0, section=None):
    return NS(id=id, question_type=type, options=list(options), correct=list(correct), marks=marks, negative_marks=negative,
              position=position, section=section, difficulty="medium", question_text=f"Q{id}", explanation="because")


def test_single_correct_wrong_and_unanswered():
    key = {"1": {"type": "single", "correct": ["B"], "marks": 2, "negative": 0.5}}
    assert scoring.score_objective(key, {"1": "B"})[0] == 2
    assert scoring.score_objective(key, {"1": "C"})[0] == 0          # wrong answer: -0.5 clamps at zero
    assert scoring.score_objective(key, {})[0] == 0
    assert scoring.score_objective(key, {"1": "  b "})[0] == 2        # case / whitespace insensitive


def test_negative_marking_applies_only_to_answered_wrong():
    key = {"1": {"type": "single", "correct": ["B"], "marks": 1, "negative": 1},
           "2": {"type": "single", "correct": ["B"], "marks": 1, "negative": 1},
           "3": {"type": "single", "correct": ["B"], "marks": 1, "negative": 1}}
    score, max_score, _ = scoring.score_objective(key, {"1": "B", "2": "A"})   # 3 is skipped
    assert (score, max_score) == (0, 3)        # +1 -1 +0
    score, _, _ = scoring.score_objective(key, {"1": "B", "2": "B", "3": "A"})
    assert score == 1                          # +1 +1 -1


def test_total_never_goes_below_zero():
    key = {"1": {"type": "single", "correct": ["B"], "marks": 1, "negative": 5}}
    assert scoring.score_objective(key, {"1": "A"})[0] == 0


def test_multiple_requires_exact_set():
    key = {"1": {"type": "multiple", "correct": ["2", "3"], "marks": 2, "negative": 1}}
    assert scoring.score_objective(key, {"1": ["3", "2"]})[0] == 2
    assert scoring.score_objective(key, {"1": ["2"]})[0] == 0          # partial is not enough
    assert scoring.score_objective(key, {"1": ["2", "3", "4"]})[0] == 0
    assert scoring.score_objective(key, {"1": ["2", "2", "3"]})[0] == 0  # duplicate padding is rejected


def test_short_text_accepts_any_listed_answer_case_insensitively():
    key = {"1": {"type": "short_text", "correct": ["Paris", "paris, france"], "marks": 1, "negative": 0}}
    assert scoring.score_objective(key, {"1": "  PARIS "})[0] == 1
    assert scoring.score_objective(key, {"1": "Paris, France"})[0] == 1
    assert scoring.score_objective(key, {"1": "London"})[0] == 0


def test_true_false():
    key = {"1": {"type": "true_false", "correct": ["True"], "marks": 1, "negative": 0}}
    assert scoring.score_objective(key, {"1": "true"})[0] == 1
    assert scoring.score_objective(key, {"1": "False"})[0] == 0


def test_answers_to_unassigned_questions_are_ignored():
    key = {"1": {"type": "single", "correct": ["B"], "marks": 1, "negative": 0}}
    score, max_score, breakdown = scoring.score_objective(key, {"1": "B", "999": "anything"})
    assert (score, max_score, len(breakdown)) == (1, 1, 1)


def test_wrong_type_of_answer_does_not_crash_or_score():
    key = {"1": {"type": "single", "correct": ["B"], "marks": 1, "negative": 0}}
    assert scoring.score_objective(key, {"1": ["B"]})[0] == 0   # a list for a single-answer question


def test_percentage():
    assert scoring.percentage(5, 10) == 50
    assert scoring.percentage(0, 0) == 0


def test_shuffling_never_breaks_grading():
    """Whatever order options are shown in, the text of the right answer still scores."""
    questions = [q(i, options=("red", "green", "blue", "gold"), correct=(2,)) for i in range(1, 30)]
    data, key = scoring.build_attempt_questions(questions, per_attempt=None, shuffle_questions=True, shuffle_options=True, rng=random.Random(7))
    assert {d["id"] for d in data} == set(range(1, 30))
    orders = {tuple(d["options"]) for d in data}
    assert len(orders) > 1                                  # options really were shuffled
    answers = {str(d["id"]): "blue" for d in data}
    assert scoring.score_objective(key, answers)[0] == 29


def test_answer_key_never_in_candidate_payload():
    data, key = scoring.build_attempt_questions([q(1)], per_attempt=None, shuffle_questions=False, shuffle_options=False)
    flat = str(data)
    assert "correct" not in flat and "explanation" not in flat and "negative" not in flat
    assert key["1"]["correct"] == ["B"]


def test_per_attempt_sampling_and_authored_order_kept_when_not_shuffling():
    questions = [q(i, position=i) for i in range(1, 21)]
    data, key = scoring.build_attempt_questions(questions, per_attempt=5, shuffle_questions=False, shuffle_options=False, rng=random.Random(1))
    ids = [d["id"] for d in data]
    assert len(ids) == 5 and ids == sorted(ids) and len(key) == 5


def test_options_not_shuffled_when_disabled_and_not_applied_to_short_text():
    data, _ = scoring.build_attempt_questions([q(1, options=("a", "b", "c", "d"))], per_attempt=None, shuffle_questions=False, shuffle_options=False)
    assert data[0]["options"] == ["a", "b", "c", "d"]
    st = q(2, type="short_text", options=(), correct=("x",))
    data, key = scoring.build_attempt_questions([st], per_attempt=None, shuffle_questions=False, shuffle_options=True)
    assert data[0]["options"] == [] and key["2"]["correct"] == ["x"]
