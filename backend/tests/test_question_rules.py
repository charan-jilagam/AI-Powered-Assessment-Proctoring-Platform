import pytest

from app import exam_service, question_rules


def n(**kw):
    base = {"question_type": "single", "question_text": "Q?", "options": ["a", "b", "c"], "correct": [1]}
    base.update(kw)
    return question_rules.normalize_question(base)


def test_valid_single_normalises():
    out = n(correct=["B"])           # option letter accepted
    assert out["correct"] == [1] and out["marks"] == 1 and out["difficulty"] == "medium"


def test_correct_can_be_option_text():
    assert n(correct=["c"])["correct"] == [2]


@pytest.mark.parametrize("kw,fragment", [
    ({"question_text": "  "}, "required"),
    ({"options": ["a"]}, "between"),
    ({"options": ["a", "a"]}, "different"),
    ({"options": ["a", ""]}, "blank"),
    ({"correct": []}, "at least one correct"),
    ({"correct": [0, 1]}, "exactly one"),
    ({"correct": [9]}, "does not exist"),
    ({"correct": ["zzz"]}, "not one of the options"),
    ({"marks": 0}, "Marks"),
    ({"negative_marks": -1}, "Negative"),
    ({"difficulty": "insane"}, "Difficulty"),
    ({"question_type": "essay"}, "Unknown"),
])
def test_invalid_questions_rejected_with_reason(kw, fragment):
    with pytest.raises(ValueError, match=fragment):
        n(**kw)


def test_multiple_and_true_false_and_short():
    assert n(question_type="multiple", correct=[0, 2, 2])["correct"] == [0, 2]
    tf = n(question_type="true_false", options=[], correct=["False"])
    assert tf["options"] == ["True", "False"] and tf["correct"] == [1]
    st = n(question_type="short_text", options=["junk"], correct=[" Paris ", "", "paris"])
    assert st["options"] == [] and st["correct"] == ["Paris", "paris"]
    with pytest.raises(ValueError):
        n(question_type="short_text", correct=[" "])


def test_tags_are_cleaned_and_capped():
    out = n(tags=[" Math ", "", "Physics"] + [f"t{i}" for i in range(20)])
    assert out["tags"][0] == "math" and len(out["tags"]) == 10


def test_csv_template_roundtrips_through_the_importer():
    good, errors = exam_service.parse_csv(exam_service.csv_template().encode())
    assert errors == [] and len(good) == 4
    assert [g["question_type"] for g in good] == ["single", "multiple", "true_false", "short_text"]
    assert good[1]["correct"] == [0, 1] and good[3]["correct"] == ["Paris", "paris"]


def test_csv_legacy_six_column_format_still_works():
    csv = "Question,Option A,Option B,Option C,Option D,Answer\nWhat is 2+2?,3,4,5,6,B\n"
    good, errors = exam_service.parse_csv(csv.encode())
    assert errors == [] and good[0]["correct"] == [1]


def test_csv_reports_every_bad_row_with_line_numbers():
    csv = "Question,Option A,Option B,Answer\nOk,1,2,A\nBad,1,2,Z\n,1,2,A\n"
    good, errors = exam_service.parse_csv(csv.encode())
    assert len(good) == 1
    assert [e["row"] for e in errors] == [3, 4]


def test_csv_requires_known_columns_and_utf8():
    from app.errors import ApiError
    with pytest.raises(ApiError):
        exam_service.parse_csv(b"foo,bar\n1,2\n")
    with pytest.raises(ApiError):
        exam_service.parse_csv("Question,Answer\nx,y\n".encode("utf-16"))
    with pytest.raises(ApiError):
        exam_service.parse_csv(b"x" * (exam_service.MAX_CSV_BYTES + 1))


def test_csv_with_bom_from_excel():
    csv = "﻿Question,Option A,Option B,Answer\nQ?,x,y,B\n"
    good, errors = exam_service.parse_csv(csv.encode("utf-8"))
    assert errors == [] and good[0]["correct"] == [1]
