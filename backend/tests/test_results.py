"""What organisers see: results, ranking, analytics, export, live monitor, review workflow, privacy."""
import csv
import io

TINY = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def finish(env, org, test, email, name="Cand", correct=True, **join_extra):
    c = env.candidate(test["code"], email=email, name=name, **join_extra)
    answers = env.answer_all_correctly(org, test, c) if correct else {}
    env.client.post("/attempt/submit", headers=c["headers"], json={"answers": answers})
    return c


def two_q(env):
    return [env.mcq(), env.mcq("3+3?", ("5", "6", "7", "8"), 1, marks=3)]


def test_results_are_ranked_by_score(env):
    org = env.make_org()
    test = env.make_test(org, questions=two_q(env))
    finish(env, org, test, "zed@mail.example.com", "Zed", correct=False)
    finish(env, org, test, "amy@mail.example.com", "Amy", correct=True)
    items = env.client.get(f"/tests/{test['id']}/attempts?sort=score", headers=org["headers"]).json()["items"]
    assert [i["candidate"]["name"] for i in items] == ["Amy", "Zed"]
    assert [i["rank"] for i in items] == [1, 2]
    assert items[0]["passed"] is True and items[1]["passed"] is False


def test_filters_search_and_pagination(env):
    org = env.make_org()
    test = env.make_test(org)
    for i in range(5):
        finish(env, org, test, f"c{i}@mail.example.com", f"Person {i}")
    base = f"/tests/{test['id']}/attempts"
    assert env.client.get(base + "?q=person 3", headers=org["headers"]).json()["total"] == 1
    page = env.client.get(base + "?page=2&page_size=2", headers=org["headers"]).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    assert env.client.get(base + "?status=terminated", headers=org["headers"]).json()["total"] == 0


def test_analytics_summary_histogram_and_question_stats(env):
    org = env.make_org()
    test = env.make_test(org, questions=two_q(env))
    finish(env, org, test, "a@mail.example.com", correct=True)
    finish(env, org, test, "b@mail.example.com", correct=False)
    d = env.client.get(f"/tests/{test['id']}/analytics", headers=org["headers"]).json()
    s = d["summary"]
    assert s["submitted"] == 2 and s["highest_percentage"] == 100 and s["lowest_percentage"] == 0 and s["average_percentage"] == 50 and s["pass_rate"] == 50
    assert sum(b["count"] for b in d["histogram"]) == 2 and d["histogram"][0]["count"] == 1 and d["histogram"][9]["count"] == 1
    assert all(q["shown"] == 2 and q["correct"] == 1 and q["correct_rate"] == 50 for q in d["question_stats"])
    assert d["leaderboard"][0]["percentage"] == 100


def test_analytics_on_an_empty_test_does_not_crash(env):
    org = env.make_org()
    test = env.make_test(org)
    d = env.client.get(f"/tests/{test['id']}/analytics", headers=org["headers"]).json()
    assert d["summary"]["submitted"] == 0 and d["summary"]["average_percentage"] is None and d["question_stats"] == []


def test_csv_export_content_and_formula_injection_guard(env):
    org = env.make_org()
    test = env.make_test(org)
    finish(env, org, test, "evil@mail.example.com", name="=HYPERLINK(\"http://x\",\"hi\")")
    finish(env, org, test, "plus@mail.example.com", name="+cmd|' /C calc'!A0")
    r = env.client.get(f"/tests/{test['id']}/export.csv", headers=org["headers"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    header, body = rows[0], rows[1:]
    assert "Name" in header and "Risk score" in header and len(body) == 2
    names = [row[header.index("Name")] for row in body]
    assert all(n[0] in ("'", "\t", " ") or n[0] not in "=+-@" for n in names), names


def test_csv_export_includes_custom_fields(env):
    org = env.make_org()
    test = env.make_test(org, candidate_fields=[{"key": "roll", "label": "Roll number", "required": True}])
    finish(env, org, test, "r@mail.example.com", fields={"roll": "R-77"})
    text = env.client.get(f"/tests/{test['id']}/export.csv", headers=org["headers"]).text
    assert "Roll number" in text and "R-77" in text


def test_live_monitor_lists_active_lobby_and_flags_risk(env):
    org = env.make_org()
    test = env.make_test(org)
    env.candidate(test["code"], email="lobby@mail.example.com", start=False)
    live = env.candidate(test["code"], email="live@mail.example.com")
    env.client.post("/attempt/heartbeat", headers=live["headers"], json={"visible": True})
    env.client.post("/attempt/violations", headers=live["headers"], json={"code": "TAB_SWITCH"})
    d = env.client.get(f"/tests/{test['id']}/live", headers=org["headers"]).json()
    assert d["summary"]["in_progress"] == 1 and d["summary"]["in_lobby"] == 1
    row = next(i for i in d["items"] if i["status"] == "in_progress")
    assert row["online"] is True and row["violation_count"] == 1 and row["risk_score"] > 0


# ---------------------------------------------------------------- staff actions
def test_terminate_force_submit_and_state_guards(env):
    org = env.make_org()
    test = env.make_test(org)
    a = env.candidate(test["code"], email="a@mail.example.com")
    b = env.candidate(test["code"], email="b@mail.example.com")
    assert env.client.post(f"/attempts/{a['attempt_id']}/terminate", headers=org["headers"], json={"reason": "Phone seen"}).json()["status"] == "terminated"
    assert env.client.post(f"/attempts/{b['attempt_id']}/force-submit", headers=org["headers"]).json()["status"] == "submitted"
    assert env.client.post(f"/attempts/{a['attempt_id']}/terminate", headers=org["headers"], json={"reason": "again"}).status_code == 409
    assert env.client.post(f"/attempts/{b['attempt_id']}/message", headers=org["headers"], json={"body": "late"}).status_code == 409
    assert env.client.get("/attempt", headers=a["headers"]).json()["result"]["terminated_reason"] == "Phone seen"


def test_review_workflow_changes_final_result(env):
    org = env.make_org()
    test = env.make_test(org)
    c = finish(env, org, test, "x@mail.example.com")
    r = env.client.post(f"/attempts/{c['attempt_id']}/review", headers=org["headers"], json={"status": "disqualified", "note": "Proxy test taker"})
    assert r.status_code == 200 and r.json()["review_status"] == "disqualified"
    report = env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()
    assert report["review"]["status"] == "disqualified" and report["review"]["note"] == "Proxy test taker"
    row = env.client.get(f"/tests/{test['id']}/attempts", headers=org["headers"]).json()["items"][0]
    assert row.get("final_result") == r.json()["final_result"] and row["final_result"] != "pass"


def test_cannot_review_an_unfinished_attempt(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org)["code"])
    assert env.client.post(f"/attempts/{c['attempt_id']}/review", headers=org["headers"], json={"status": "cleared"}).status_code == 409


def test_dismissing_a_violation_lowers_risk_and_confirm_restores_it(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"])
    env.client.post("/attempt/violations", headers=c["headers"], json={"code": "TAB_SWITCH"})
    env.client.post("/attempt/violations", headers=c["headers"], json={"code": "DEVTOOLS"})
    env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    vios = env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()["violations"]
    tab = next(v for v in vios if v["code"] == "TAB_SWITCH")
    full = env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()["risk_score"]
    out = env.client.patch(f"/violations/{tab['id']}", headers=org["headers"], json={"status": "dismissed"}).json()
    assert out["risk_score"] == full - 6
    assert env.client.patch(f"/violations/{tab['id']}", headers=org["headers"], json={"status": "confirmed"}).json()["risk_score"] == full


def test_review_queue_surfaces_risky_pending_attempts_only(env):
    org = env.make_org()
    test = env.make_test(org)
    risky = env.candidate(test["code"], email="risky@mail.example.com")
    for code in ("TAB_SWITCH", "DEVTOOLS"):
        env.client.post("/attempt/violations", headers=risky["headers"], json={"code": code})
    env.client.post("/attempt/submit", headers=risky["headers"], json={"answers": {}})
    finish(env, org, test, "clean@mail.example.com")
    q = env.client.get("/review-queue?min_risk=10", headers=org["headers"]).json()
    assert q["total"] == 1 and q["items"][0]["candidate"]["email"] == "risky@mail.example.com"
    env.client.post(f"/attempts/{risky['attempt_id']}/review", headers=org["headers"], json={"status": "cleared"})
    assert env.client.get("/review-queue?min_risk=10", headers=org["headers"]).json()["total"] == 0


def test_evidence_image_is_served_with_safe_headers(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org)["code"])
    env.client.post("/attempt/violations", headers=c["headers"], json={"code": "TAB_SWITCH", "image": TINY})
    report = env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()
    sid = next(v["snapshot_id"] for v in report["violations"])
    r = env.client.get(f"/evidence/{sid}", headers=org["headers"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and "no-store" in r.headers["cache-control"]


def test_a_bad_evidence_image_does_not_lose_the_violation(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org)["code"])
    out = env.client.post("/attempt/violations", headers=c["headers"], json={"code": "TAB_SWITCH", "image": "data:image/png;base64,AAAA"}).json()
    assert out["recorded"] is True


# ---------------------------------------------------------------- candidates + privacy
def test_block_candidate_stops_them_joining_and_their_live_session(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"], email="b@mail.example.com")
    cid = env.client.get("/candidates", headers=org["headers"]).json()["items"][0]["id"]
    assert env.client.patch(f"/candidates/{cid}", headers=org["headers"], json={"is_active": False}).status_code == 200
    r, _ = env.join(test["code"], email="b@mail.example.com")
    assert r.status_code == 403 and r.json()["code"] == "blocked"
    assert env.client.get("/attempt", headers=c["headers"]).status_code in (401, 403)
    env.client.patch(f"/candidates/{cid}", headers=org["headers"], json={"is_active": True})
    assert env.join(test["code"], email="b@mail.example.com")[0].status_code == 200


def test_erasure_destroys_personal_data_but_keeps_anonymous_scores(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"], email="gone@mail.example.com", name="Real Name")
    env.client.post("/attempt/violations", headers=c["headers"], json={"code": "TAB_SWITCH", "image": TINY})
    env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    sid = next(v["snapshot_id"] for v in env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()["violations"])
    cid = env.client.get("/candidates", headers=org["headers"]).json()["items"][0]["id"]
    assert env.client.delete(f"/candidates/{cid}", headers=org["headers"]).status_code == 200
    assert env.client.get(f"/evidence/{sid}", headers=org["headers"]).status_code == 404
    row = env.client.get(f"/tests/{test['id']}/attempts", headers=org["headers"]).json()["items"][0]
    assert row["candidate"]["name"] == "Erased candidate" and "gone@" not in str(row)
    assert env.client.get("/candidates?q=gone", headers=org["headers"]).json()["total"] == 0


def test_candidate_endpoints_enforce_org_by_candidate_id(env):
    a, b = env.make_org("Org A"), env.make_org("Org B")
    tb = env.make_test(b)
    env.candidate(tb["code"])
    cid = env.client.get("/candidates", headers=b["headers"]).json()["items"][0]["id"]
    assert env.client.patch(f"/candidates/{cid}", headers=a["headers"], json={"is_active": False}).status_code == 404
    assert env.client.delete(f"/candidates/{cid}", headers=a["headers"]).status_code == 404
    assert env.client.get("/candidates", headers=b["headers"]).json()["items"][0]["is_active"] is True


def test_staff_user_cannot_be_blocked_via_the_candidate_endpoint(env):
    org = env.make_org()
    rev = env.add_member(org, "reviewer")
    assert env.client.patch(f"/candidates/{rev['id']}", headers=org["headers"], json={"is_active": False}).status_code == 404
    assert env.client.delete(f"/candidates/{rev['id']}", headers=org["headers"]).status_code == 404
