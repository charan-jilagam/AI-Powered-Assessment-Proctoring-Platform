"""Importing coding problems from JSON: format reference, validation messages, dry run, all-or-nothing."""
import json

import pytest

from app import coding, judge0
from tests.test_coding import FakeJudge0, sum_problem


def _admin_test(env):
    org = env.make_org()
    test = env.make_test(org, publish=False)
    return org, test


def test_format_reference_is_available_to_org_admins_only(env):
    org, _ = _admin_test(env)
    r = env.client.get("/coding-problems/json-format", headers=org["headers"])
    assert r.status_code == 200
    body = r.json()
    assert {f["field"] for f in body["fields"]} >= {"title", "statement", "test_cases", "test_cases[].input_data", "test_cases[].expected_output", "test_cases[].is_sample"}
    assert env.client.get("/coding-problems/json-format").status_code == 401
    reviewer = env.add_member(org, "reviewer")
    assert env.client.get("/coding-problems/json-format", headers=reviewer["headers"]).status_code == 403


def test_the_example_in_the_reference_imports_cleanly(env):
    org, test = _admin_test(env)
    example = env.client.get("/coding-problems/json-format", headers=org["headers"]).json()["example"]
    r = env.client.post(f"/tests/{test['id']}/coding-problems/import-json", headers=org["headers"], json=example)
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2 and r.json()["problems"][0]["samples"] == 2
    listed = env.client.get(f"/tests/{test['id']}/coding-problems", headers=org["headers"]).json()
    assert [p["title"] for p in listed] == ["Sum of Two Numbers", "Palindrome Check"]
    assert listed[0]["test_cases"][0]["input_data"] == "3 4\n"


def test_dry_run_checks_without_saving(env):
    org, test = _admin_test(env)
    r = env.client.post(f"/tests/{test['id']}/coding-problems/import-json", params={"dry_run": "true"}, headers=org["headers"], json={"problems": [sum_problem()]})
    assert r.status_code == 200 and r.json()["dry_run"] is True and r.json()["count"] == 1
    assert env.client.get(f"/tests/{test['id']}/coding-problems", headers=org["headers"]).json() == []


@pytest.mark.parametrize("shape", ["bare_list", "single_object", "wrapped"])
def test_accepts_wrapped_bare_and_single_shapes(env, shape):
    org, test = _admin_test(env)
    payload = {"wrapped": {"problems": [sum_problem()]}, "bare_list": [sum_problem()], "single_object": sum_problem()}[shape]
    r = env.client.post(f"/tests/{test['id']}/coding-problems/import-json", headers=org["headers"], json=payload)
    assert r.status_code == 200 and r.json()["count"] == 1


def test_friendly_aliases_and_numbers_as_data(env):
    org, test = _admin_test(env)
    payload = {"problems": [{"name": "Double", "description": "Print twice the number.", "testCases": [
        {"input": 4, "output": 8, "sample": True}, {"stdin": "10\n", "stdout": "20\n"}]}]}
    r = env.client.post(f"/tests/{test['id']}/coding-problems/import-json", headers=org["headers"], json=payload)
    assert r.status_code == 200, r.text
    p = env.client.get(f"/tests/{test['id']}/coding-problems", headers=org["headers"]).json()[0]
    assert p["title"] == "Double" and p["test_cases"][0]["input_data"] == "4" and p["test_cases"][0]["expected_output"] == "8" and p["test_cases"][0]["is_sample"] is True


def test_every_mistake_is_listed_with_the_problem_number_and_nothing_is_saved(env):
    org, test = _admin_test(env)
    payload = {"problems": [
        sum_problem(),
        {"title": "No statement", "test_cases": [{"input_data": "", "expected_output": "1"}]},
        {"title": "No cases", "statement": "x"},
        {"title": "Bad limits", "statement": "x", "points": 5000, "test_cases": [{"expected_output": "1"}]},
        {"title": "Empty answer", "statement": "x", "test_cases": [{"input_data": "1", "expected_output": "  "}]},
    ]}
    r = env.client.post(f"/tests/{test['id']}/coding-problems/import-json", headers=org["headers"], json=payload)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "Problem 2" in detail and "Problem 3" in detail and "Problem 4" in detail and "Problem 5" in detail and "Problem 1" not in detail
    assert "No statement" in detail
    assert env.client.get(f"/tests/{test['id']}/coding-problems", headers=org["headers"]).json() == []


@pytest.mark.parametrize("payload,fragment", [
    ({}, "Expected"), ([], "empty"), ({"problems": []}, "empty"), ("just text", "Expected"), ({"problems": ["x"]}, "must be an object"),
])
def test_wrong_shapes_get_a_clear_message(env, payload, fragment):
    org, test = _admin_test(env)
    r = env.client.post(f"/tests/{test['id']}/coding-problems/import-json", headers=org["headers"], json=payload)
    assert r.status_code == 422 and fragment in r.json()["detail"]


def test_import_size_cap(env):
    org, test = _admin_test(env)
    r = env.client.post(f"/tests/{test['id']}/coding-problems/import-json", headers=org["headers"],
                        json={"problems": [sum_problem(title=f"P{i}") for i in range(coding.MAX_IMPORT_PROBLEMS + 1)]})
    assert r.status_code == 422 and "At most" in r.json()["detail"]


def test_import_respects_plan_and_tenancy(env):
    trial = env.make_org(plan="trial", status="trial")          # trial plan has no coding feature
    t = env.make_test(trial, publish=False)
    r = env.client.post(f"/tests/{t['id']}/coding-problems/import-json", headers=trial["headers"], json={"problems": [sum_problem()]})
    assert r.status_code == 402
    a, b = env.make_org(), env.make_org()
    tb = env.make_test(b, publish=False)
    r = env.client.post(f"/tests/{tb['id']}/coding-problems/import-json", headers=a["headers"], json={"problems": [sum_problem()]})
    assert r.status_code == 404


def test_imported_problems_work_for_candidates_and_hide_hidden_cases(env, monkeypatch):
    monkeypatch.setattr(judge0, "execute", FakeJudge0())
    org, test = _admin_test(env)
    env.client.post(f"/tests/{test['id']}/coding-problems/import-json", headers=org["headers"], json={"problems": [sum_problem()]})
    env.client.post(f"/tests/{test['id']}/publish", headers=org["headers"])
    cand = env.candidate(test["code"])
    problem = cand["state"]["coding_problems"][0]
    assert len(problem["samples"]) == 2 and problem["hidden_test_count"] == 2
    assert "-5 5" not in json.dumps(cand["state"])
    r = env.client.post(f"/attempt/coding/{problem['id']}/submit", headers=cand["headers"], json={"language_id": 71, "source_code": "print(sum)"})
    assert r.status_code == 200 and r.json()["verdict"] == "Accepted"
