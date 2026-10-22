"""Coding questions on the attempt-scoped API. Judge0 is replaced by a fake that 'runs' source code
according to a marker word in it, so no Docker/network is needed but routing, auth, scoring and
hidden-test secrecy are all exercised. (The real Judge0 integration is NOT tested here.)"""
import pytest

from app import coding, judge0


def _raw(status_id=3, status="Accepted", stdout="", stderr="", compile_output=""):
    return {"status_id": status_id, "status": status, "stdout": stdout, "stderr": stderr,
            "compile_output": compile_output, "message": "", "time": 0.01, "memory": 1024}


def _sum_of(stdin):
    return str(sum(int(x) for x in stdin.split())) + "\n"


class FakeJudge0:
    def __init__(self):
        self.calls = []

    def __call__(self, source_code, language_id, stdins, time_limit_seconds=2.0, memory_limit_mb=256, client=None):
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
            elif "PARTIAL" in source_code:
                out.append(_raw(stdout=_sum_of(stdin) if i % 2 == 0 else "-1\n"))
            else:
                out.append(_raw(stdout=_sum_of(stdin)))
        return out


PY = 71


def sum_problem(points=10, title="Sum of two numbers"):
    return {"title": title, "statement": "Read two integers and print their sum.", "points": points, "test_cases": [
        {"input_data": "1 2\n", "expected_output": "3\n", "is_sample": True},
        {"input_data": "10 20\n", "expected_output": "30\n", "is_sample": True},
        {"input_data": "-5 5\n", "expected_output": "0\n", "is_sample": False},
        {"input_data": "1000 2345\n", "expected_output": "3345\n", "is_sample": False}]}


@pytest.fixture()
def cenv(env, monkeypatch):
    env.fake = FakeJudge0()
    monkeypatch.setattr(judge0, "execute", env.fake)
    return env


def coding_test(env, org, mcq=True, points=10, **kw):
    return env.make_test(org, questions=[env.mcq()] if mcq else [], coding_problems=[sum_problem(points)], **kw)


def start(env, org, test, email=None):
    c = env.candidate(test["code"], email=email)
    c["problem"] = c["state"]["coding_problems"][0]
    return c


def submit(env, c, code="print(1)", lang=PY):
    return env.client.post(f"/attempt/coding/{c['problem']['id']}/submit", headers=c["headers"], json={"language_id": lang, "source_code": code})


# ---------------------------------------------------------------- authoring
def test_create_coding_only_test_and_start_it(cenv):
    org = cenv.make_org()
    test = coding_test(cenv, org, mcq=False)
    c = start(cenv, org, test)
    assert c["state"]["questions"] == [] and len(c["state"]["coding_problems"]) == 1


def test_test_needs_at_least_one_question_or_problem(cenv):
    org = cenv.make_org()
    t = cenv.make_test(org, questions=[], publish=False)
    assert cenv.client.post(f"/tests/{t['id']}/publish", headers=org["headers"]).status_code == 422


def test_reviewers_cannot_author_problems(cenv):
    org = cenv.make_org()
    t = coding_test(cenv, org)
    rev = cenv.add_member(org, "reviewer")["headers"]
    assert cenv.client.post(f"/tests/{t['id']}/coding-problems", headers=rev, json=sum_problem(title="New")).status_code == 403
    assert cenv.client.get(f"/tests/{t['id']}/coding-problems", headers=rev).status_code in (200, 403)


@pytest.mark.parametrize("mutate, fragment", [
    (lambda p: p.update(test_cases=[]), "test case"),
    (lambda p: p.update(points=0), "points"),
    (lambda p: p["test_cases"][0].update(expected_output=""), "expected"),
])
def test_problem_validation(cenv, mutate, fragment):
    org = cenv.make_org()
    t = coding_test(cenv, org)
    bad = sum_problem(title="Bad")
    mutate(bad)
    r = cenv.client.post(f"/tests/{t['id']}/coding-problems", headers=org["headers"], json=bad)
    assert r.status_code in (400, 422)


def test_bulk_import_is_all_or_nothing(cenv):
    org = cenv.make_org()
    t = cenv.make_test(org)
    bad = sum_problem(title="Bad")
    bad["test_cases"] = []
    r = cenv.client.post(f"/tests/{t['id']}/coding-problems/bulk", headers=org["headers"], json={"problems": [sum_problem(title="Good"), bad]})
    assert r.status_code in (400, 422)
    assert cenv.client.get(f"/tests/{t['id']}/coding-problems", headers=org["headers"]).json() == []
    ok = cenv.client.post(f"/tests/{t['id']}/coding-problems/bulk", headers=org["headers"], json={"problems": [sum_problem(title="A"), sum_problem(title="B")]})
    assert ok.status_code == 200 and len(cenv.client.get(f"/tests/{t['id']}/coding-problems", headers=org["headers"]).json()) == 2


def test_add_and_delete_problem(cenv):
    org = cenv.make_org()
    t = cenv.make_test(org)
    p = cenv.client.post(f"/tests/{t['id']}/coding-problems", headers=org["headers"], json=sum_problem()).json()
    assert cenv.client.delete(f"/coding-problems/{p['id']}", headers=org["headers"]).status_code == 200
    assert cenv.client.get(f"/tests/{t['id']}/coding-problems", headers=org["headers"]).json() == []


def test_coding_needs_the_plan_feature_on_existing_tests(cenv):
    org = cenv.make_org(plan="trial", status="trial")
    t = cenv.make_test(org)
    assert cenv.client.post(f"/tests/{t['id']}/coding-problems", headers=org["headers"], json=sum_problem()).status_code == 402


def test_other_orgs_cannot_manage_my_problems(cenv):
    a, b = cenv.make_org("Org A"), cenv.make_org("Org B")
    t = coding_test(cenv, b)
    pid = cenv.client.get(f"/tests/{t['id']}/coding-problems", headers=b["headers"]).json()[0]["id"]
    assert cenv.client.post(f"/tests/{t['id']}/coding-problems", headers=a["headers"], json=sum_problem()).status_code == 404
    assert cenv.client.delete(f"/coding-problems/{pid}", headers=a["headers"]).status_code == 404
    assert cenv.client.get(f"/tests/{t['id']}/coding-submissions", headers=a["headers"]).status_code == 404


# ---------------------------------------------------------------- candidate view
def test_candidate_sees_samples_but_never_hidden_tests(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    blob = str(c["state"]["coding_problems"])
    assert "3345" not in blob and "1000 2345" not in blob and "1 2" in blob


def test_languages_endpoint(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    langs = cenv.client.get("/attempt/coding/languages", headers=c["headers"]).json()
    assert any(l["id"] == PY for l in langs)


def test_a_candidate_cannot_use_another_tests_problem(cenv):
    org = cenv.make_org()
    mine = start(cenv, org, coding_test(cenv, org))
    other = coding_test(cenv, org)
    other_pid = cenv.client.get(f"/tests/{other['id']}/coding-problems", headers=org["headers"]).json()[0]["id"]
    r = cenv.client.post(f"/attempt/coding/{other_pid}/submit", headers=mine["headers"], json={"language_id": PY, "source_code": "x"})
    assert r.status_code == 404


def test_staff_tokens_cannot_run_code(cenv):
    org = cenv.make_org()
    t = coding_test(cenv, org)
    pid = cenv.client.get(f"/tests/{t['id']}/coding-problems", headers=org["headers"]).json()[0]["id"]
    assert cenv.client.post(f"/attempt/coding/{pid}/submit", headers=org["headers"], json={"language_id": PY, "source_code": "x"}).status_code in (401, 403)


# ---------------------------------------------------------------- running + grading
def test_run_uses_only_sample_tests(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    r = cenv.client.post(f"/attempt/coding/{c['problem']['id']}/run", headers=c["headers"], json={"language_id": PY, "source_code": "ok"})
    assert r.status_code == 200 and r.json()["mode"] == "samples" and r.json()["total"] == 2
    assert [s for s in cenv.fake.calls[-1][1]] == ["1 2\n", "10 20\n"]
    assert cenv.client.get(f"/tests/{c['state']['test']['id']}/coding-submissions", headers=org["headers"]).json() == []   # runs are not stored


def test_run_with_custom_input(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    r = cenv.client.post(f"/attempt/coding/{c['problem']['id']}/run", headers=c["headers"], json={"language_id": PY, "source_code": "ok", "custom_input": "7 8\n"})
    assert r.status_code == 200 and r.json()["mode"] == "custom" and "15" in r.json()["stdout"]


def test_submit_accepted_hides_hidden_test_details(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    r = submit(cenv, c, "ok").json()
    assert r["passed"] == 4 and r["total"] == 4 and r["verdict"] == "Accepted"
    assert "3345" not in str(r) and "1000 2345" not in str(r)


@pytest.mark.parametrize("marker, verdict", [("COMPILE_ERROR", "Compilation Error"), ("CRASH", "Runtime Error"), ("TLE", "Time Limit Exceeded"), ("WRONG", "Wrong Answer")])
def test_failure_verdicts(cenv, marker, verdict):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    r = submit(cenv, c, marker).json()
    assert r["passed"] == 0 and verdict.split()[0] in r["verdict"]


def test_judge0_down_gives_a_friendly_503(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    r = submit(cenv, c, "DOWN")
    assert r.status_code == 503 and "connection refused" not in r.text


def test_code_and_language_are_validated(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    assert submit(cenv, c, "").status_code in (400, 422)
    assert submit(cenv, c, "x", lang=99999).status_code in (400, 422)
    assert submit(cenv, c, "x" * 200_000).status_code in (400, 413, 422)


def test_best_submission_counts_and_progress_restores_code(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    submit(cenv, c, "PARTIAL v1")
    good = submit(cenv, c, "ok v2").json()
    worse = submit(cenv, c, "WRONG v3").json()
    assert good["best_passed"] == 4 and worse["best_passed"] == 4
    prog = cenv.client.get("/attempt/coding/progress", headers=c["headers"]).json()[0]
    assert prog["best_passed"] == 4 and prog["attempts"] == 3 and prog["last_source_code"] == "WRONG v3"


def test_progress_is_per_candidate(cenv):
    org = cenv.make_org()
    t = coding_test(cenv, org)
    a, b = start(cenv, org, t, "a@mail.example.com"), start(cenv, org, t, "b@mail.example.com")
    submit(cenv, a, "ok")
    assert cenv.client.get("/attempt/coding/progress", headers=b["headers"]).json() == []


def test_submissions_are_throttled(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    statuses = [submit(cenv, c, f"ok {i}").status_code for i in range(40)]
    assert 429 in statuses and statuses[0] == 200


# ---------------------------------------------------------------- scoring
def test_score_combines_objective_and_coding(cenv):
    org = cenv.make_org()
    t = coding_test(cenv, org, points=10)
    c = start(cenv, org, t)
    submit(cenv, c, "PARTIAL")            # 2 of 4 tests -> 5 of 10 points
    answers = cenv.answer_all_correctly(org, t, c)
    res = cenv.client.post("/attempt/submit", headers=c["headers"], json={"answers": answers}).json()
    assert res["max_score"] == 11 and res["score"] == 6
    report = cenv.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()
    assert report["objective_score"] == 1 and report["coding_score"] == 5 and len(report["coding"]) == 1


def test_full_coding_marks_need_every_test(cenv):
    org = cenv.make_org()
    t = coding_test(cenv, org, mcq=False, points=10)
    c = start(cenv, org, t)
    submit(cenv, c, "PARTIAL")
    assert cenv.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}}).json()["score"] == 5
    d = start(cenv, org, t, "full@mail.example.com")
    submit(cenv, d, "ok")
    assert cenv.client.post("/attempt/submit", headers=d["headers"], json={"answers": {}}).json()["score"] == 10


def test_unattempted_problem_scores_zero_but_counts_in_the_total(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org, mcq=False, points=10))
    res = cenv.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}}).json()
    assert res["score"] == 0 and res["max_score"] == 10


def test_cannot_submit_code_after_finishing(cenv):
    org = cenv.make_org()
    c = start(cenv, org, coding_test(cenv, org))
    cenv.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    assert submit(cenv, c, "ok").status_code in (401, 403, 409)


def test_retake_does_not_inherit_old_code_submissions(cenv):
    org = cenv.make_org()
    t = coding_test(cenv, org, mcq=False)
    first = start(cenv, org, t, "re@mail.example.com")
    submit(cenv, first, "ok")
    cenv.client.post("/attempt/submit", headers=first["headers"], json={"answers": {}})
    cenv.client.post(f"/attempts/{first['attempt_id']}/void", headers=org["headers"])
    second = start(cenv, org, t, "re@mail.example.com")
    assert cenv.client.get("/attempt/coding/progress", headers=second["headers"]).json() == []
    res = cenv.client.post("/attempt/submit", headers=second["headers"], json={"answers": {}}).json()
    assert res["score"] == 0


def test_staff_can_review_submitted_code(cenv):
    org = cenv.make_org()
    t = coding_test(cenv, org)
    c = start(cenv, org, t)
    submit(cenv, c, "print('hello')")
    rows = cenv.client.get(f"/tests/{t['id']}/coding-submissions", headers=org["headers"]).json()
    assert len(rows) == 1 and "hello" in str(rows[0])
