"""Tests for exam scoring logic — the most critical correctness path."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def score_answers(questions, submitted_answers):
    """
    Mirror of the backend scoring logic: compare submitted answer TEXT
    against the correct answer TEXT. This is what makes shuffled options
    score correctly.
    """
    score = 0
    for q in questions:
        correct_text = {
            "A": q["option_a"], "B": q["option_b"],
            "C": q["option_c"], "D": q["option_d"],
        }[q["correct_answer"]]

        submitted = submitted_answers.get(q["id"])
        if submitted and submitted.strip() == correct_text.strip():
            score += 1
    return score


# A small question set for testing
QUESTIONS = [
    {"id": 1, "option_a": "3", "option_b": "4", "option_c": "5", "option_d": "6", "correct_answer": "B"},  # correct = "4"
    {"id": 2, "option_a": "10", "option_b": "12", "option_c": "14", "option_d": "16", "correct_answer": "B"},  # correct = "12"
    {"id": 3, "option_a": "London", "option_b": "Paris", "option_c": "Rome", "option_d": "Berlin", "correct_answer": "B"},  # correct = "Paris"
]


def test_all_correct():
    """Answering all questions correctly gives a perfect score."""
    answers = {1: "4", 2: "12", 3: "Paris"}
    assert score_answers(QUESTIONS, answers) == 3


def test_all_wrong():
    """Answering all wrong gives zero."""
    answers = {1: "3", 2: "10", 3: "London"}
    assert score_answers(QUESTIONS, answers) == 0


def test_partial_score():
    """Partial correct answers score correctly."""
    answers = {1: "4", 2: "10", 3: "Paris"}  # 2 correct, 1 wrong
    assert score_answers(QUESTIONS, answers) == 2


def test_scoring_by_text_survives_shuffle():
    """
    The key test: even if options were shuffled so the correct answer
    moved to a different letter, scoring by TEXT still works.
    The student submits the TEXT '4', which is correct regardless of
    which letter position it appeared in.
    """
    answers = {1: "4"}  # correct text, no matter what letter it was shown as
    assert score_answers([QUESTIONS[0]], answers) == 1


def test_unanswered_questions_not_counted():
    """Skipped questions don't add to the score."""
    answers = {1: "4"}  # only answered question 1
    assert score_answers(QUESTIONS, answers) == 1