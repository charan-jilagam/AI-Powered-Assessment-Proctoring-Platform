"""
API tests for coding questions. Judge0 is replaced by a fake that "runs" source
code according to a marker word in it, so the tests need neither Docker nor a
network, but still exercise routing, auth, scoring, hiding of hidden tests, etc.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app import auth, coding, judge0, models

app.state.limiter.enabled = False  # signup/login rate limit is irrelevant here

PYTHON = 71
PASSWORD_HASH = auth.hash_password("pw123456")  # bcrypt is slow on purpose; hash once, not per test


# ---------------------------------------------------------------------------
# fake Judge0
# ---------------------------------------------------------------------------
def _raw(status_id=3, status="Accepted", stdout="", stderr="", compile_output=""):
    return {"status_id": status_id, "status": status, "stdout": stdout, "stderr": stderr,
            "compile_output": compile_output, "message": "", "time": 0.01, "memory": 1024}


def _sum_of(stdin: str) -> str:
    return str(sum(int(x) for x in stdin.split())) + "\n"


class FakeJudge0:
    """Behaviour is chosen by a marker word inside the submitted source code."""

    def __init__(self):
        self.calls = []   # (source_code, [stdins]) per execute() call

    def __call__(self, source_code, language_id, stdins, time_limit_seconds=2.0,
                 memory_limit_mb=256, client=None):
        self.calls.append((source_code, list(stdins)))
        if "DOWN" in source_code:
            raise judge0.Judge0Error("connection refused")
        out = []
        for i, stdin in enumerate(stdins):
            if "COMPILE_ERROR" in source_code:
                out.append(_raw(6, "Compilation Error", compile_output="error: boom"))
            elif "CRASH" in source_code:
                out.append(_raw(11, "Runtime Error (NZEC)", stderr="Traceback ..."))
            elif "TLE" in source_code:
                out.append(_raw(5, "Time Limit Exceeded"))
            elif "WRONG" in source_code:
                out.append(_raw(stdout="-1\n"))
            elif "PARTIAL" in source_code:  # even-numbered tests right, odd-numbered wrong
                out.append(_raw(stdout=_sum_of(stdin) if i % 2 == 0 else "-1\n"))
            else:
                out.append(_raw(stdout=_sum_of(stdin)))
        return out


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
class Env:
    pass


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    coding.reset_throttle()

    fake = FakeJudge0()
    monkeypatch.setattr(judge0, "execute", fake)

    e = Env()
    e.Session = Session
    e.client = TestClient(app)
    e.fake = fake

    def make_user(email, role):
        db = Session()
        user = models.User(full_name=email.split("@")[0], email=email,
                           hashed_password=PASSWORD_HASH, role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        uid = user.id
        db.close()
        token = auth.create_access_token({"sub": str(uid), "role": role})
        return uid, {"Authorization": f"Bearer {token}"}

    e.admin_id, e.admin = make_user("admin@test.com", "admin")
    e.student_id, e.student = make_user("student@test.com", "student")
    e.student2_id, e.student2 = make_user("student2@test.com", "student")
    yield e

    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


def sum_problem(points=10, title="Sum of two numbers"):
    return {
        "title": title,
        "statement": "Read two integers and print their sum.",
        "points": points,
        "test_cases": [
            {"input_data": "1 2\n", "expected_output": "3\n", "is_sample": True},
            {"input_data": "10 20\n", "expected_output": "30\n", "is_sample": True},
            {"input_data": "-5 5\n", "expected_output": "0\n", "is_sample": False},
            {"input_data": "1000 2345\n", "expected_output": "3345\n", "is_sample": False},
        ],
    }


MCQ = {"question_text": "2+2?", "option_a": "3", "option_b": "4", "option_c": "5", "option_d": "6",
       "correct_answer": "B"}


def create_exam(e, problems=(), questions=(), title="Mixed exam", minutes=30):
    r = e.client.post("/exams/create", headers=e.admin, json={
        "title": title, "description": "d", "duration_minutes": minutes,
        "questions": list(questions), "coding_problems": list(problems),
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def start_exam(e, exam_id, headers=None):
    r = e.client.get(f"/exams/{exam_id}", headers=headers or e.student)
    assert r.status_code == 200, r.text
    return r.json()


def problem_id_of(e, exam_id):
    r = e.client.get(f"/exams/{exam_id}/coding-problems", headers=e.admin)
    return r.json()[0]["id"]


def run_url(exam_id, pid):
    return f"/exams/{exam_id}/coding-problems/{pid}/run"


def submit_url(exam_id, pid):
    return f"/exams/{exam_id}/coding-problems/{pid}/submit"


def count(e, model):
    db = e.Session()
    try:
        return db.query(model).count()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# authoring
# ---------------------------------------------------------------------------
def test_create_coding_only_exam(env):
    r = env.client.post("/exams/create", headers=env.admin, json={
        "title": "Coding round", "duration_minutes": 45, "questions": [], "coding_problems": [sum_problem()],
    })
    assert r.status_code == 200
    assert r.json()["coding_problem_count"] == 1 and r.json()["question_count"] == 0


def test_exam_needs_at_least_one_question_or_problem(env):
    r = env.client.post("/exams/create", headers=env.admin,
                        json={"title": "Empty", "duration_minutes": 5, "questions": [], "coding_problems": []})
    assert r.status_code == 400


def test_students_cannot_author_problems(env):
    exam_id = create_exam(env, questions=[MCQ])
    r = env.client.post(f"/exams/{exam_id}/coding-problems", headers=env.student, json=sum_problem())
    assert r.status_code == 403
    assert env.client.get(f"/exams/{exam_id}/coding-problems", headers=env.student).status_code == 403
    assert env.client.get(f"/exams/{exam_id}/coding-submissions", headers=env.student).status_code == 403


@pytest.mark.parametrize("mutate,fragment", [
    (lambda p: p.update(test_cases=[]), "at least one test case"),
    (lambda p: p["test_cases"][0].update(expected_output="  "), "empty expected output"),
    (lambda p: p.update(title="  "), "title"),
    (lambda p: p.update(points=0), "points"),
    (lambda p: p.update(time_limit_seconds=99), "time limit"),
    (lambda p: p.update(memory_limit_mb=512), "memory limit"),
])
def test_problem_validation(env, mutate, fragment):
    exam_id = create_exam(env, questions=[MCQ])
    p = sum_problem()
    mutate(p)
    r = env.client.post(f"/exams/{exam_id}/coding-problems", headers=env.admin, json=p)
    assert r.status_code == 400 and fragment in r.json()["detail"]


def test_bulk_import_is_all_or_nothing(env):
    exam_id = create_exam(env, questions=[MCQ])
    bad = sum_problem(title="Bad")
    bad["test_cases"] = []
    r = env.client.post(f"/exams/{exam_id}/coding-problems/bulk", headers=env.admin,
                        json={"problems": [sum_problem(title="Good"), bad]})
    assert r.status_code == 400
    assert count(env, models.CodingProblem) == 0

    r = env.client.post(f"/exams/{exam_id}/coding-problems/bulk", headers=env.admin,
                        json={"problems": [sum_problem(title="A"), sum_problem(title="B")]})
    assert r.status_code == 200 and r.json()["count"] == 2


def test_add_and_delete_problem_on_existing_exam(env):
    exam_id = create_exam(env, questions=[MCQ])
    r = env.client.post(f"/exams/{exam_id}/coding-problems", headers=env.admin, json=sum_problem())
    assert r.status_code == 200
    pid = r.json()["id"]
    assert len(r.json()["test_cases"]) == 4

    assert env.client.delete(f"/coding-problems/{pid}", headers=env.admin).status_code == 200
    assert count(env, models.CodingProblem) == 0 and count(env, models.TestCase) == 0


def test_unknown_exam_404(env):
    r = env.client.post("/exams/999/coding-problems", headers=env.admin, json=sum_problem())
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# what candidates can see
# ---------------------------------------------------------------------------
def test_candidate_sees_samples_but_never_hidden_tests(env):
    exam_id = create_exam(env, problems=[sum_problem()], questions=[MCQ])
    data = start_exam(env, exam_id)

    problem = data["coding_problems"][0]
    assert [s["input"] for s in problem["samples"]] == ["1 2\n", "10 20\n"]
    assert problem["hidden_test_count"] == 2
    blob = json.dumps(data)
    assert "3345" not in blob and "2345" not in blob   # hidden expected output / input


def test_coding_only_exam_can_be_started(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    data = start_exam(env, exam_id)
    assert data["questions"] == [] and len(data["coding_problems"]) == 1


def test_available_exams_report_coding_count(env):
    create_exam(env, problems=[sum_problem(), sum_problem(title="Two")])
    r = env.client.get("/exams/available", headers=env.student)
    assert r.json()[0]["coding_problem_count"] == 2


def test_languages_endpoint(env):
    r = env.client.get("/coding/languages", headers=env.student)
    assert r.status_code == 200
    assert {l["id"] for l in r.json()} == set(judge0.SUPPORTED_LANGUAGES)


# ---------------------------------------------------------------------------
# run (practice)
# ---------------------------------------------------------------------------
def test_run_uses_only_sample_tests(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)

    r = env.client.post(run_url(exam_id, pid), headers=env.student,
                        json={"language_id": PYTHON, "source_code": "print(sum(map(int,input().split())))"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "samples" and body["passed"] == 2 and body["total"] == 2
    assert env.fake.calls[-1][1] == ["1 2\n", "10 20\n"]      # hidden inputs never executed on 'run'
    assert count(env, models.CodeSubmission) == 0             # runs are not stored


def test_run_with_custom_input(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    r = env.client.post(run_url(exam_id, pid), headers=env.student,
                        json={"language_id": PYTHON, "source_code": "x", "custom_input": "4 5"})
    assert r.status_code == 200
    assert r.json()["mode"] == "custom" and r.json()["stdout"] == "9\n"


# ---------------------------------------------------------------------------
# submit (graded)
# ---------------------------------------------------------------------------
def test_submit_accepted_hides_hidden_details(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)

    r = env.client.post(submit_url(exam_id, pid), headers=env.student,
                        json={"language_id": PYTHON, "source_code": "ok"})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "Accepted" and body["passed"] == 4 and body["total"] == 4
    assert [c["label"] for c in body["cases"]] == ["Sample 1", "Sample 2", "Hidden 1", "Hidden 2"]
    for case in body["cases"]:
        if not case["is_sample"]:
            assert not {"input", "expected_output", "actual_output"} & case.keys()
    assert "3345" not in json.dumps(body) and "2345" not in json.dumps(body)
    assert count(env, models.CodeSubmission) == 1


@pytest.mark.parametrize("marker,verdict", [
    ("WRONG", "Wrong Answer"),
    ("COMPILE_ERROR", "Compilation Error"),
    ("CRASH", "Runtime Error"),
    ("TLE", "Time Limit Exceeded"),
])
def test_submit_failure_verdicts(env, marker, verdict):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    r = env.client.post(submit_url(exam_id, pid), headers=env.student,
                        json={"language_id": PYTHON, "source_code": marker})
    assert r.status_code == 200
    assert r.json()["verdict"] == verdict and r.json()["passed"] == 0
    if marker == "COMPILE_ERROR":
        assert "boom" in r.json()["compile_output"]


def test_best_submission_counts_and_progress_restores_code(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    url = submit_url(exam_id, pid)

    env.client.post(url, headers=env.student, json={"language_id": PYTHON, "source_code": "PARTIAL"})
    best = env.client.post(url, headers=env.student, json={"language_id": PYTHON, "source_code": "ok"}).json()
    assert best["best_passed"] == 4
    after_worse = env.client.post(url, headers=env.student, json={"language_id": PYTHON, "source_code": "WRONG"}).json()
    assert after_worse["passed"] == 0 and after_worse["best_passed"] == 4   # a worse retry can't lower the best

    progress = env.client.get(f"/exams/{exam_id}/coding-progress", headers=env.student).json()
    assert len(progress) == 1
    assert progress[0]["best_passed"] == 4 and progress[0]["attempts"] == 3
    assert progress[0]["last_source_code"] == "WRONG"       # editor restores the *latest* code


def test_progress_is_per_student(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "ok"})
    assert env.client.get(f"/exams/{exam_id}/coding-progress", headers=env.student2).json() == []


# ---------------------------------------------------------------------------
# scoring into the exam result
# ---------------------------------------------------------------------------
def test_exam_score_combines_mcq_and_coding(env):
    exam_id = create_exam(env, problems=[sum_problem(points=10)], questions=[MCQ])
    pid = problem_id_of(env, exam_id)
    data = start_exam(env, exam_id)
    qid = data["questions"][0]["id"]

    # PARTIAL passes tests 0 and 2 of 4 -> floor(10 * 2 / 4) = 5 points
    env.client.post(submit_url(exam_id, pid), headers=env.student,
                    json={"language_id": PYTHON, "source_code": "PARTIAL"})
    r = env.client.post(f"/exams/{exam_id}/submit", headers=env.student, json={"answers": {str(qid): "4"}})
    assert r.status_code == 200
    assert r.json()["score"] == 1 + 5
    assert r.json()["total_questions"] == 1 + 10


def test_full_coding_marks_need_every_test(env):
    exam_id = create_exam(env, problems=[sum_problem(points=10)])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "ok"})
    r = env.client.post(f"/exams/{exam_id}/submit", headers=env.student, json={"answers": {}})
    assert (r.json()["score"], r.json()["total_questions"]) == (10, 10)


def test_unattempted_coding_problem_scores_zero_but_counts_in_total(env):
    exam_id = create_exam(env, problems=[sum_problem(points=10)], questions=[MCQ])
    data = start_exam(env, exam_id)
    qid = data["questions"][0]["id"]
    r = env.client.post(f"/exams/{exam_id}/submit", headers=env.student, json={"answers": {str(qid): "4"}})
    assert (r.json()["score"], r.json()["total_questions"]) == (1, 11)


def test_admin_results_show_combined_score(env):
    exam_id = create_exam(env, problems=[sum_problem(points=10)])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "ok"})
    env.client.post(f"/exams/{exam_id}/submit", headers=env.student, json={"answers": {}})
    results = env.client.get(f"/exams/{exam_id}/results", headers=env.admin).json()["results"]
    assert results[0]["score"] == 10 and results[0]["percentage"] == 100


# ---------------------------------------------------------------------------
# access control / abuse
# ---------------------------------------------------------------------------
def test_cannot_run_before_starting_exam(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    r = env.client.post(run_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "x"})
    assert r.status_code == 400
    assert env.fake.calls == []


def test_cannot_run_after_termination_or_submission(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    env.client.post(f"/exams/{exam_id}/terminate", headers=env.student)
    r = env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "ok"})
    assert r.status_code == 403

    exam2 = create_exam(env, problems=[sum_problem()], title="Second")
    pid2 = problem_id_of(env, exam2)
    start_exam(env, exam2, env.student2)
    env.client.post(f"/exams/{exam2}/submit", headers=env.student2, json={"answers": {}})
    r = env.client.post(submit_url(exam2, pid2), headers=env.student2, json={"language_id": PYTHON, "source_code": "ok"})
    assert r.status_code == 403


def test_cannot_submit_code_after_time_is_up(env):
    exam_id = create_exam(env, problems=[sum_problem()], minutes=10)
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)

    db = env.Session()
    session = db.query(models.ExamSession).first()
    session.started_at = datetime.now(timezone.utc) - timedelta(minutes=15)   # 10 min exam, 15 min ago
    db.commit()
    db.close()

    r = env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "ok"})
    assert r.status_code == 400 and "Time is up" in r.json()["detail"]


def test_problem_from_another_exam_is_rejected(env):
    exam1 = create_exam(env, problems=[sum_problem()], title="One")
    exam2 = create_exam(env, problems=[sum_problem()], title="Two")
    start_exam(env, exam1)
    other_pid = problem_id_of(env, exam2)
    r = env.client.post(submit_url(exam1, other_pid), headers=env.student, json={"language_id": PYTHON, "source_code": "ok"})
    assert r.status_code == 404


def test_rejects_unsupported_language_and_bad_source(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    url = submit_url(exam_id, pid)
    assert env.client.post(url, headers=env.student, json={"language_id": 9999, "source_code": "ok"}).status_code == 400
    assert env.client.post(url, headers=env.student, json={"language_id": PYTHON, "source_code": "   "}).status_code == 400
    huge = "x" * (coding.MAX_SOURCE_CHARS + 1)
    assert env.client.post(url, headers=env.student, json={"language_id": PYTHON, "source_code": huge}).status_code == 400
    assert env.fake.calls == []


def test_judge0_down_returns_503_and_stores_nothing(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    r = env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "DOWN"})
    assert r.status_code == 503
    assert "connection refused" not in r.text            # internals aren't leaked to the browser
    assert count(env, models.CodeSubmission) == 0


def test_per_user_throttle(env, monkeypatch):
    monkeypatch.setattr(coding, "EXEC_PER_MINUTE", 2)
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    start_exam(env, exam_id, env.student2)
    body = {"language_id": PYTHON, "source_code": "ok"}

    assert env.client.post(run_url(exam_id, pid), headers=env.student, json=body).status_code == 200
    assert env.client.post(run_url(exam_id, pid), headers=env.student, json=body).status_code == 200
    assert env.client.post(run_url(exam_id, pid), headers=env.student, json=body).status_code == 429
    # another candidate (even from the same IP) is unaffected
    assert env.client.post(run_url(exam_id, pid), headers=env.student2, json=body).status_code == 200


# ---------------------------------------------------------------------------
# admin review + cleanup
# ---------------------------------------------------------------------------
def test_admin_can_review_code_submissions(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "my solution"})
    rows = env.client.get(f"/exams/{exam_id}/coding-submissions", headers=env.admin).json()
    assert len(rows) == 1
    assert rows[0]["student_email"] == "student@test.com"
    assert rows[0]["source_code"] == "my solution" and rows[0]["verdict"] == "Accepted"
    assert rows[0]["language"].startswith("Python")


def test_reset_attempt_clears_code_submissions(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "ok"})
    assert count(env, models.CodeSubmission) == 1
    r = env.client.post(f"/admin/students/{env.student_id}/reset-attempt?exam_id={exam_id}", headers=env.admin)
    assert r.status_code == 200
    assert count(env, models.CodeSubmission) == 0


def test_deleting_student_clears_their_code(env):
    exam_id = create_exam(env, problems=[sum_problem()])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "ok"})
    assert env.client.delete(f"/admin/students/{env.student_id}", headers=env.admin).status_code == 200
    assert count(env, models.CodeSubmission) == 0


def test_deleting_exam_removes_all_coding_data(env):
    exam_id = create_exam(env, problems=[sum_problem()], questions=[MCQ])
    pid = problem_id_of(env, exam_id)
    start_exam(env, exam_id)
    env.client.post(submit_url(exam_id, pid), headers=env.student, json={"language_id": PYTHON, "source_code": "ok"})

    assert env.client.delete(f"/exams/{exam_id}", headers=env.admin).status_code == 200
    for model in (models.CodingProblem, models.TestCase, models.CodeSubmission, models.Exam):
        assert count(env, model) == 0, model.__name__
