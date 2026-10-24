"""Multi-tenancy: one client must never be able to read or touch another client's data."""
import pytest

from tests.conftest import PASSWORD


@pytest.fixture()
def two_orgs(env):
    a = env.make_org("Alpha Inc")
    b = env.make_org("Beta Ltd")
    test = env.make_test(b, questions=[env.mcq(), env.mcq("3+3?", ("5", "6", "7", "8"), 1)])
    detail = env.client.get(f"/tests/{test['id']}", headers=b["headers"]).json()
    qid = detail["questions"][0]["id"]
    cand = env.candidate(test["code"])
    env.client.post("/attempt/violations", headers=cand["headers"], json={"code": "COPY_PASTE"})
    env.client.post("/attempt/submit", headers=cand["headers"], json={"answers": {}})
    inv = env.client.post(f"/tests/{test['id']}/invites", headers=b["headers"], json={"invitees": [{"email": "x@mail.example.com"}], "send_email": False}).json()["created"][0]
    bank = env.client.post("/bank/questions", headers=b["headers"], json=env.mcq()).json()
    hr = env.client.post("/org/webhooks", headers=b["headers"], json={"url": "https://hooks.example.com/x", "events": []})
    assert hr.status_code == 201, hr.text
    hook = hr.json()
    kr = env.client.post("/org/api-keys", headers=b["headers"], json={"name": "ci-key"})
    assert kr.status_code == 201, kr.text
    key = kr.json()
    detail_attempt = env.client.get(f"/attempts/{cand['attempt_id']}", headers=b["headers"]).json()
    return dict(a=a, b=b, test=test, qid=qid, cand=cand, inv=inv, bank=bank, hook=hook, key=key, vid=detail_attempt["violations"][0]["id"],
                member=env.add_member(b, "reviewer"))


def probes(x):
    """(method, path, json) - every one of these targets organization B's data."""
    t, aid = x["test"]["id"], x["cand"]["attempt_id"]
    return [
        ("GET", f"/tests/{t}", None), ("PATCH", f"/tests/{t}", {"title": "hijacked"}), ("DELETE", f"/tests/{t}", None),
        ("POST", f"/tests/{t}/publish", None), ("POST", f"/tests/{t}/close", None), ("POST", f"/tests/{t}/duplicate", None),
        ("POST", f"/tests/{t}/archive", None), ("POST", f"/tests/{t}/regenerate-code", None), ("POST", f"/tests/{t}/unpublish", None),
        ("POST", f"/tests/{t}/questions", {"question_type": "single", "question_text": "x", "options": ["a", "b"], "correct": [0]}),
        ("PUT", f"/tests/{t}/questions/{x['qid']}", {"question_type": "single", "question_text": "x", "options": ["a", "b"], "correct": [0]}),
        ("DELETE", f"/tests/{t}/questions/{x['qid']}", None), ("POST", f"/tests/{t}/questions/reorder", {"ids": [x["qid"]]}),
        ("POST", f"/tests/{t}/questions/from-bank", {"question_ids": [x["bank"]["id"]]}),
        ("POST", f"/tests/{t}/questions/{x['qid']}/save-to-bank", None),
        ("GET", f"/tests/{t}/invites", None), ("POST", f"/tests/{t}/invites", {"invitees": [{"email": "n@mail.example.com"}]}),
        ("POST", f"/tests/{t}/invites/{x['inv']['id']}/resend", None), ("DELETE", f"/tests/{t}/invites/{x['inv']['id']}", None),
        ("GET", f"/tests/{t}/attempts", None), ("GET", f"/tests/{t}/live", None), ("GET", f"/tests/{t}/analytics", None),
        ("GET", f"/tests/{t}/export.csv", None), ("GET", f"/tests/{t}/coding-problems", None), ("GET", f"/tests/{t}/coding-submissions", None),
        ("GET", f"/attempts/{aid}", None), ("POST", f"/attempts/{aid}/terminate", {"reason": "x"}), ("POST", f"/attempts/{aid}/extend", {"minutes": 5}),
        ("POST", f"/attempts/{aid}/message", {"body": "hi"}), ("POST", f"/attempts/{aid}/void", None), ("POST", f"/attempts/{aid}/force-submit", None),
        ("POST", f"/attempts/{aid}/review", {"status": "cleared"}), ("PATCH", f"/violations/{x['vid']}", {"status": "dismissed"}),
        ("PUT", f"/bank/questions/{x['bank']['id']}", env_q()), ("DELETE", f"/bank/questions/{x['bank']['id']}", None),
        ("PUT", f"/org/webhooks/{x['hook']['id']}", {"url": "https://hooks.example.com/y", "events": []}), ("DELETE", f"/org/webhooks/{x['hook']['id']}", None),
        ("POST", f"/org/webhooks/{x['hook']['id']}/test", None), ("GET", f"/org/webhooks/{x['hook']['id']}/deliveries", None),
        ("DELETE", f"/org/api-keys/{x['key']['id']}", None),
        ("PATCH", f"/org/team/{x['member']['id']}", {"is_active": False}), ("POST", f"/org/team/{x['member']['id']}/reset-link", None),
        ("PATCH", f"/candidates/{x['cand']['attempt_id']}", {"is_active": False}), ("DELETE", f"/candidates/{x['cand']['attempt_id']}", None),
    ]


def env_q():
    return {"question_type": "single", "question_text": "x", "options": ["a", "b"], "correct": [0]}


def test_org_a_cannot_touch_any_org_b_resource(env, two_orgs):
    a_headers = two_orgs["a"]["headers"]
    leaks = []
    for method, path, body in probes(two_orgs):
        r = env.client.request(method, path, headers=a_headers, json=body) if body is not None else env.client.request(method, path, headers=a_headers)
        if r.status_code not in (404, 403):
            leaks.append((method, path, r.status_code))
    assert leaks == [], f"cross-tenant access allowed: {leaks}"


def test_b_data_is_unchanged_after_a_probing(env, two_orgs):
    for method, path, body in probes(two_orgs):
        env.client.request(method, path, headers=two_orgs["a"]["headers"], json=body) if body is not None else env.client.request(method, path, headers=two_orgs["a"]["headers"])
    t = env.client.get(f"/tests/{two_orgs['test']['id']}", headers=two_orgs["b"]["headers"]).json()
    assert t["title"] == two_orgs["test"]["title"] and t["status"] == "published" and len(t["questions"]) == 2
    assert env.client.get(f"/attempts/{two_orgs['cand']['attempt_id']}", headers=two_orgs["b"]["headers"]).json()["status"] == "submitted"


def test_lists_only_show_own_data(env, two_orgs):
    a = two_orgs["a"]["headers"]
    assert env.client.get("/tests", headers=a).json()["total"] == 0
    assert env.client.get("/candidates", headers=a).json()["total"] == 0
    assert env.client.get("/bank/questions", headers=a).json()["total"] == 0
    assert env.client.get("/review-queue?min_risk=0", headers=a).json()["total"] == 0
    assert env.client.get("/org/team", headers=a).json().__len__() == 1
    assert env.client.get("/org/audit-log", headers=a).json()["total"] > 0
    dash = env.client.get("/org/dashboard", headers=a).json()
    assert dash["tests"]["total"] == 0 and dash["recent_attempts"] == []


def test_org_audit_log_never_contains_other_orgs_events(env, two_orgs):
    entries = env.client.get("/org/audit-log?page_size=200", headers=two_orgs["a"]["headers"]).json()["items"]
    assert all("Beta" not in (e["details"] or "") and "beta" not in e["actor_email"] for e in entries)


def test_evidence_images_are_org_private(env, two_orgs):
    b = two_orgs["b"]
    cand = env.candidate(two_orgs["test"]["code"], start=False)
    env.client.post("/attempt/start", headers=cand["headers"], json={"consent": True})
    tiny = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    env.client.post("/attempt/violations", headers=cand["headers"], json={"code": "TAB_SWITCH", "image": tiny})
    report = env.client.get(f"/attempts/{cand['attempt_id']}", headers=b["headers"]).json()
    sid = next(v["snapshot_id"] for v in report["violations"] if v["snapshot_id"])
    assert env.client.get(f"/evidence/{sid}", headers=b["headers"]).status_code == 200
    assert env.client.get(f"/evidence/{sid}", headers=two_orgs["a"]["headers"]).status_code == 404
    assert env.client.get(f"/evidence/{sid}").status_code == 401


def test_same_candidate_email_in_two_orgs_stays_separate(env):
    a, b = env.make_org("Org A"), env.make_org("Org B")
    ta, tb = env.make_test(a), env.make_test(b)
    ca = env.candidate(ta["code"], email="shared@mail.example.com", name="Alice")
    cb = env.candidate(tb["code"], email="shared@mail.example.com", name="Different Name")
    assert ca["attempt_id"] != cb["attempt_id"]
    assert env.client.get("/candidates", headers=a["headers"]).json()["items"][0]["name"] == "Alice"
    assert env.client.get("/candidates", headers=b["headers"]).json()["items"][0]["name"] == "Different Name"


def test_staff_email_is_unique_platform_wide(env):
    a = env.make_org("Org A")
    b = env.make_org("Org B")
    r = env.client.post("/org/team", headers=b["headers"], json={"full_name": "Dup", "email": a["email"], "role": "admin"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# roles inside an organization
# ---------------------------------------------------------------------------
def test_reviewer_can_monitor_but_not_manage(env):
    org = env.make_org()
    test = env.make_test(org)
    cand = env.candidate(test["code"])
    rev = env.add_member(org, "reviewer")["headers"]
    ok = [("GET", "/tests"), ("GET", f"/tests/{test['id']}"), ("GET", f"/tests/{test['id']}/attempts"), ("GET", f"/tests/{test['id']}/live"),
          ("GET", f"/tests/{test['id']}/analytics"), ("GET", f"/attempts/{cand['attempt_id']}"), ("GET", "/org/dashboard"), ("GET", "/review-queue"),
          ("GET", "/org/team"), ("GET", "/candidates")]
    for method, path in ok:
        assert env.client.request(method, path, headers=rev).status_code == 200, path
    forbidden = [("POST", "/tests", {"title": "x", "duration_minutes": 5, "questions": [env_q()]}), ("POST", f"/tests/{test['id']}/publish", None),
                 ("DELETE", f"/tests/{test['id']}", None), ("PATCH", f"/tests/{test['id']}", {"title": "x"}),
                 ("POST", f"/attempts/{cand['attempt_id']}/void", None), ("POST", "/org/team", {"full_name": "x y", "email": "n@e.example.com", "role": "admin"}),
                 ("PATCH", "/org", {"name": "Renamed"}), ("GET", "/org/audit-log", None), ("GET", "/org/api-keys", None), ("GET", "/org/webhooks", None),
                 ("GET", "/bank/questions", None), ("POST", f"/tests/{test['id']}/invites", {"invitees": [{"email": "n@mail.example.com"}]}),
                 ("DELETE", f"/candidates/{cand['attempt_id']}", None)]
    for method, path, body in forbidden:
        r = env.client.request(method, path, headers=rev, json=body) if body is not None else env.client.request(method, path, headers=rev)
        assert r.status_code == 403, (method, path, r.status_code)


def test_reviewer_never_sees_the_answer_key(env):
    org = env.make_org()
    test = env.make_test(org)
    rev = env.add_member(org, "reviewer")["headers"]
    detail = env.client.get(f"/tests/{test['id']}", headers=rev).json()
    assert detail["questions"][0]["correct"] == [] and detail["questions"][0]["explanation"] is None
    cand = env.candidate(test["code"])
    env.client.post("/attempt/submit", headers=cand["headers"], json={"answers": {}})
    report = env.client.get(f"/attempts/{cand['attempt_id']}", headers=rev).json()
    assert all(q["correct_answer"] is None for q in report["questions"])
    admin_report = env.client.get(f"/attempts/{cand['attempt_id']}", headers=org["headers"]).json()
    assert all(q["correct_answer"] for q in admin_report["questions"])


def test_reviewer_can_act_on_live_attempts(env):
    org = env.make_org()
    test = env.make_test(org)
    cand = env.candidate(test["code"])
    rev = env.add_member(org, "reviewer")["headers"]
    aid = cand["attempt_id"]
    assert env.client.post(f"/attempts/{aid}/message", headers=rev, json={"body": "Please face the camera"}).status_code == 200
    assert env.client.post(f"/attempts/{aid}/extend", headers=rev, json={"minutes": 5}).status_code == 200
    assert env.client.post(f"/attempts/{aid}/terminate", headers=rev, json={"reason": "Cheating"}).status_code == 200


# ---------------------------------------------------------------------------
# team management
# ---------------------------------------------------------------------------
def test_cannot_remove_last_admin_or_self(env):
    org = env.make_org()
    me = env.client.get("/auth/me", headers=org["headers"]).json()["user"]["id"]
    assert env.client.patch(f"/org/team/{me}", headers=org["headers"], json={"is_active": False}).status_code == 400
    assert env.client.patch(f"/org/team/{me}", headers=org["headers"], json={"role": "reviewer"}).status_code == 400
    second = env.add_member(org, "admin")
    assert env.client.patch(f"/org/team/{second['id']}", headers=org["headers"], json={"role": "reviewer"}).status_code == 200
    assert env.client.patch(f"/org/team/{me}", headers=second["headers"], json={"is_active": False}).status_code == 403   # reviewer now


def test_promote_reviewer_to_admin(env):
    org = env.make_org()
    rev = env.add_member(org, "reviewer")
    env.client.patch(f"/org/team/{rev['id']}", headers=org["headers"], json={"role": "admin"})
    # role is read from the database on every request, so the existing token gains the new power immediately
    assert env.client.get("/org/api-keys", headers=rev["headers"]).status_code == 200


# ---------------------------------------------------------------------------
# plan limits
# ---------------------------------------------------------------------------
def _limit(env, org, **limits):
    r = env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"limits_override": limits})
    assert r.status_code == 200, r.text


def test_active_test_limit_blocks_publishing_not_drafting(env):
    org = env.make_org()
    _limit(env, org, max_active_tests=1)
    first = env.make_test(org)
    second = env.make_test(org, publish=False)
    r = env.client.post(f"/tests/{second['id']}/publish", headers=org["headers"])
    assert r.status_code == 402 and r.json()["code"] == "plan_limit"
    env.client.post(f"/tests/{first['id']}/close", headers=org["headers"])              # frees a slot
    assert env.client.post(f"/tests/{second['id']}/publish", headers=org["headers"]).status_code == 200


def test_team_seat_limit(env):
    org = env.make_org()
    _limit(env, org, max_admins=2)
    env.add_member(org, "reviewer")
    r = env.client.post("/org/team", headers=org["headers"], json={"full_name": "Third Person", "email": "third@client.example.com", "role": "reviewer"})
    assert r.status_code == 402


def test_monthly_candidate_allowance_blocks_new_candidates_but_not_resuming(env):
    org = env.make_org()
    _limit(env, org, max_candidates_per_month=1)
    test = env.make_test(org)
    first = env.candidate(test["code"], email="one@mail.example.com")
    r, _ = env.join(test["code"], email="two@mail.example.com")
    assert r.status_code == 402 and r.json()["code"] == "plan_limit"
    resume, _ = env.join(test["code"], email="one@mail.example.com")
    assert resume.status_code == 200 and resume.json()["attempt"]["resumed"] is True


def test_unlimited_plan_has_no_cap(env):
    org = env.make_org(plan="enterprise")
    test = env.make_test(org)
    for i in range(5):
        env.candidate(test["code"], email=f"u{i}@mail.example.com")
    assert env.client.get("/org", headers=org["headers"]).json()["usage"]["candidates_this_month"] == 5


def test_coding_questions_need_the_plan_feature(env):
    org = env.make_org(plan="trial", status="trial")
    problem = {"title": "Sum", "statement": "add", "points": 5, "test_cases": [{"input_data": "1 2", "expected_output": "3"}]}
    r = env.client.post("/tests", headers=org["headers"], json={"title": "T", "duration_minutes": 10, "questions": [], "coding_problems": [problem]})
    assert r.status_code == 402 and r.json()["code"] == "plan_feature"


def test_ai_monitoring_is_switched_off_with_a_warning_on_plans_without_it(env):
    org = env.make_org(plan="starter")
    r = env.client.post("/tests", headers=org["headers"], json={"title": "T", "duration_minutes": 10, "questions": [env_q()], "proctoring": {"ai_monitoring": True}})
    assert r.status_code == 201
    assert r.json()["proctoring"]["ai_monitoring"] is False and r.json()["warnings"]


def test_webhooks_need_the_plan_feature(env):
    org = env.make_org(plan="starter")
    assert env.client.post("/org/webhooks", headers=org["headers"], json={"url": "https://hooks.example.com/x", "events": []}).status_code == 402


def test_usage_endpoint_reports_limits_and_counts(env):
    org = env.make_org(plan="starter")
    env.make_test(org)
    d = env.client.get("/org", headers=org["headers"]).json()
    assert d["limits"]["max_active_tests"] == 5 and d["usage"]["active_tests"] == 1 and d["usage"]["team_seats"] == 1
    assert d["plan"]["code"] == "starter"


def test_dashboard_range_search_and_notifications(env):
    org = env.make_org()
    other = env.make_org()
    test = env.make_test(org, title="Zebra Aptitude")
    env.make_test(other, title="Zebra Secret")
    env.candidate(test["code"])
    d7 = env.client.get("/org/dashboard?range=7", headers=org["headers"]).json()
    d90 = env.client.get("/org/dashboard?range=90", headers=org["headers"]).json()
    assert len(d7["attempts_per_day"]) == 7 and len(d90["attempts_per_day"]) == 90 and "trends" in d7
    assert env.client.get("/org/dashboard?range=5", headers=org["headers"]).status_code == 422 and env.client.get("/org/dashboard?range=45", headers=org["headers"]).status_code == 400
    found = env.client.get("/org/search?q=zebra", headers=org["headers"]).json()
    assert [t["title"] for t in found["tests"]] == ["Zebra Aptitude"]          # never another tenant's test
    assert env.client.get("/org/search?q=z", headers=org["headers"]).json() == {"tests": [], "candidates": []}
    n = env.client.get("/org/notifications", headers=org["headers"]).json()
    assert n["count"] == len(n["items"]) and any(i["kind"] == "live" for i in n["items"])
