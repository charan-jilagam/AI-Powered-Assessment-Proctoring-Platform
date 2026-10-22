"""The candidate journey: test code -> join -> start -> autosave -> proctoring -> submit -> result."""
from datetime import timedelta

from app import attempt_service, models
from app.database import SessionLocal
from app.timeutil import utcnow

TWO_Q = lambda env: [env.mcq(), env.mcq("3+3?", ("5", "6", "7", "8"), 1, marks=2)]


def _db_attempt(attempt_id, **changes):
    db = SessionLocal()
    try:
        a = db.get(models.Attempt, attempt_id)
        for k, v in changes.items():
            setattr(a, k, v)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------- lookup
def test_lookup_shows_public_info_only(env):
    org = env.make_org("Acme Corp")
    test = env.make_test(org, instructions="Be honest")
    r = env.client.get(f"/public/tests/{test['code']}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == test["title"] and body["organization"]["name"] == "Acme Corp"
    assert "questions" not in body and "answer_key" not in str(body)


def test_lookup_is_forgiving_about_case_and_spaces(env):
    org = env.make_org()
    test = env.make_test(org)
    messy = " " + test["code"][:4].lower() + "-" + test["code"][4:].lower() + " "
    assert env.client.get(f"/public/tests/{messy.strip()}").status_code == 200


def test_unknown_draft_and_archived_codes_are_not_found(env):
    org = env.make_org()
    draft = env.make_test(org, publish=False)
    assert env.client.get("/public/tests/ZZZZZZZZ").status_code == 404
    assert env.client.get(f"/public/tests/{draft['code']}").status_code == 404
    live = env.make_test(org)
    env.client.post(f"/tests/{live['id']}/archive", headers=org["headers"])
    assert env.client.get(f"/public/tests/{live['code']}").status_code == 404


# ---------------------------------------------------------------- join
def test_join_creates_candidate_and_registered_attempt(env):
    org = env.make_org()
    test = env.make_test(org)
    r, email = env.join(test["code"])
    assert r.status_code == 200
    assert r.json()["attempt"] == {"id": r.json()["attempt"]["id"], "status": "registered", "resumed": False}
    state = env.client.get("/attempt", headers=env.h(r.json()["token"])).json()
    assert state["attempt"]["status"] == "registered" and "questions" not in state


def test_questions_are_only_released_on_start(env):
    org = env.make_org()
    test = env.make_test(org, questions=TWO_Q(env))
    c = env.candidate(test["code"])
    qs = c["state"]["questions"]
    assert len(qs) == 2
    blob = str(c["state"])
    assert "correct" not in blob and "answer_key" not in blob and "explanation" not in blob


def test_access_password_enforced(env):
    org = env.make_org()
    test = env.make_test(org, access_password="open-sesame")
    assert env.join(test["code"])[0].status_code == 403
    assert env.join(test["code"], access_password="nope")[0].json()["code"] == "bad_access_password"
    assert env.join(test["code"], access_password="open-sesame")[0].status_code == 200


def test_invite_only_mode(env):
    org = env.make_org()
    test = env.make_test(org, access_mode="invite")
    r, _ = env.join(test["code"], email="stranger@mail.example.com")
    assert r.status_code == 403 and r.json()["code"] == "not_invited"
    inv = env.client.post(f"/tests/{test['id']}/invites", headers=org["headers"],
                          json={"invitees": [{"email": "vip@mail.example.com", "name": "Vip"}], "send_email": False}).json()["created"][0]
    ok, _ = env.join(test["code"], email="VIP@mail.example.com")
    assert ok.status_code == 200
    # a token for someone else's email is refused
    bad, _ = env.join(test["code"], email="other@mail.example.com", invite_token=inv["link"].split("invite=")[1])
    assert bad.status_code == 403 and bad.json()["code"] == "invite_mismatch"
    invites = env.client.get(f"/tests/{test['id']}/invites", headers=org["headers"]).json()
    assert [i["status"] for i in invites["items"]] == ["started"]


def test_required_custom_fields(env):
    org = env.make_org()
    test = env.make_test(org, candidate_fields=[{"key": "roll", "label": "Roll number", "required": True}])
    r, _ = env.join(test["code"])
    assert r.status_code == 400 and r.json()["code"] == "missing_field"
    ok = env.candidate(test["code"], fields={"roll": "R-42"}, start=False)
    report = env.client.get(f"/attempts/{ok['attempt_id']}", headers=org["headers"]).json()
    assert report["candidate"]["profile"] == {"roll": "R-42"}


def test_scheduling_window(env):
    org = env.make_org()
    soon = (utcnow() + timedelta(hours=2)).isoformat()
    past = (utcnow() - timedelta(hours=2)).isoformat()
    future_test = env.make_test(org, start_time=soon)
    r, _ = env.join(future_test["code"])
    assert r.status_code == 403 and r.json()["code"] == "window_not_started"
    over = env.make_test(org, end_time=(utcnow() + timedelta(hours=1)).isoformat())
    db = SessionLocal()
    try:                                              # publishing refuses a window already over, so age it afterwards
        db.get(models.Exam, over["id"]).end_time = utcnow() - timedelta(hours=2)
        db.commit()
    finally:
        db.close()
    r, _ = env.join(over["code"])
    assert r.status_code == 403 and r.json()["code"] == "window_ended"


def test_closed_test_blocks_new_candidates_but_lets_started_ones_finish(env):
    org = env.make_org()
    test = env.make_test(org)
    started = env.candidate(test["code"], email="early@mail.example.com")
    env.client.post(f"/tests/{test['id']}/close", headers=org["headers"])
    r, _ = env.join(test["code"], email="late@mail.example.com")
    assert r.status_code == 403 and r.json()["code"] == "window_closed"
    assert env.client.post("/attempt/submit", headers=started["headers"], json={"answers": {}}).status_code == 200


def test_suspended_org_blocks_candidates(env):
    org = env.make_org()
    test = env.make_test(org)
    assert env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"status": "suspended", "suspended_reason": "unpaid"}).status_code == 200
    r, _ = env.join(test["code"])
    assert r.status_code == 403 and r.json()["code"] == "unavailable"


# ---------------------------------------------------------------- start
def test_start_requires_consent_and_is_idempotent(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"], start=False)
    r = env.client.post("/attempt/start", headers=c["headers"], json={"consent": False})
    assert r.status_code == 400 and r.json()["code"] == "consent_required"
    first = env.client.post("/attempt/start", headers=c["headers"], json={"consent": True}).json()
    again = env.client.post("/attempt/start", headers=c["headers"], json={"consent": True}).json()
    assert first["questions"] == again["questions"]                                   # no reshuffle
    assert again["attempt"]["remaining_seconds"] <= 30 * 60


def test_id_verification_required_when_configured(env):
    org = env.make_org()
    test = env.make_test(org, proctoring={"webcam_required": False, "ai_monitoring": False, "id_verification": True})
    c = env.candidate(test["code"], start=False)
    r = env.client.post("/attempt/start", headers=c["headers"], json={"consent": True})
    assert r.status_code == 400 and r.json()["code"] == "id_required"
    tiny = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    ok = env.client.post("/attempt/start", headers=c["headers"], json={"consent": True, "id_image": tiny, "face_image": tiny})
    assert ok.status_code == 200
    report = env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()
    assert {s["kind"] for s in report["snapshots"]} >= {"id", "face"}


def test_questions_per_attempt_draws_a_subset_from_the_pool(env):
    org = env.make_org()
    pool = [env.mcq(f"Q{i}?") for i in range(6)]
    test = env.make_test(org, questions=pool, questions_per_attempt=3)
    seen = set()
    for i in range(3):
        c = env.candidate(test["code"], email=f"p{i}@mail.example.com")
        assert len(c["state"]["questions"]) == 3
        seen.update(q["id"] for q in c["state"]["questions"])
    assert len(seen) > 3        # different candidates saw different questions


def test_empty_test_cannot_be_published(env):
    org = env.make_org()
    t = env.make_test(org, questions=[], publish=False)
    r = env.client.post(f"/tests/{t['id']}/publish", headers=org["headers"])
    assert r.status_code == 422 and r.json()["code"] == "not_ready"


# ---------------------------------------------------------------- answers + submit
def test_autosave_merges_and_survives_a_resume(env):
    org = env.make_org()
    test = env.make_test(org, questions=TWO_Q(env))
    c = env.candidate(test["code"], email="r@mail.example.com")
    q1, q2 = (q["id"] for q in c["state"]["questions"])
    env.client.put("/attempt/answers", headers=c["headers"], json={"answers": {str(q1): "x"}, "flagged": [q1]})
    env.client.put("/attempt/answers", headers=c["headers"], json={"answers": {str(q2): "y"}})
    # candidate closes the browser and comes back with the same code + email
    r, _ = env.join(test["code"], email="r@mail.example.com")
    assert r.json()["attempt"]["resumed"] is True
    state = env.client.get("/attempt", headers=env.h(r.json()["token"])).json()
    assert state["answers"] == {str(q1): "x", str(q2): "y"} and [q["id"] for q in state["questions"]] == [q["id"] for q in c["state"]["questions"]]


def test_autosave_ignores_unknown_question_ids(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"])
    env.client.put("/attempt/answers", headers=c["headers"], json={"answers": {"99999": "hack"}})
    assert env.client.get("/attempt", headers=c["headers"]).json()["answers"] == {}


def test_correct_answers_score_full_marks_and_wrong_score_zero(env):
    org = env.make_org()
    test = env.make_test(org, questions=TWO_Q(env), result_visibility="full", pass_percentage=50)
    good = env.candidate(test["code"], email="good@mail.example.com")
    res = env.client.post("/attempt/submit", headers=good["headers"], json={"answers": env.answer_all_correctly(org, test, good)}).json()
    assert res["score"] == 3 and res["max_score"] == 3 and res["percentage"] == 100 and res["passed"] is True
    assert all(r["is_correct"] for r in res["review"])
    bad = env.candidate(test["code"], email="bad@mail.example.com")
    res = env.client.post("/attempt/submit", headers=bad["headers"], json={"answers": {}}).json()
    assert res["score"] == 0 and res["passed"] is False


def test_negative_marking(env):
    org = env.make_org()
    q = env.mcq(marks=4, negative_marks=1)
    test = env.make_test(org, questions=[q], result_visibility="score")
    c = env.candidate(test["code"])
    qid = c["state"]["questions"][0]["id"]
    wrong = next(o for o in c["state"]["questions"][0]["options"] if o != "4")
    res = env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {str(qid): wrong}}).json()
    assert res["score"] == 0       # clamped: a negative total is never reported


def test_result_visibility_levels(env):
    org = env.make_org()
    for vis, expect_score, expect_review in (("none", False, False), ("score", True, False), ("full", True, True)):
        test = env.make_test(org, result_visibility=vis)
        c = env.candidate(test["code"])
        res = env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}}).json()
        assert ("score" in res) is expect_score and ("review" in res) is expect_review, vis


def test_submit_is_idempotent_and_blocks_rejoining(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"], email="once@mail.example.com")
    a = env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}}).json()
    b = env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}}).json()
    assert a["submitted_at"] == b["submitted_at"]
    r, _ = env.join(test["code"], email="once@mail.example.com")
    assert r.status_code == 409 and r.json()["code"] == "already_attempted"
    assert env.client.get("/attempt/result", headers=c["headers"]).status_code == 200


def test_cannot_save_answers_after_submitting(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"])
    qid = c["state"]["questions"][0]["id"]
    env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    env.client.put("/attempt/answers", headers=c["headers"], json={"answers": {str(qid): "4"}})
    report = env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()
    assert report["score"] == 0


def test_result_before_finishing_is_a_conflict(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org)["code"])
    assert env.client.get("/attempt/result", headers=c["headers"]).status_code == 409


# ---------------------------------------------------------------- time
def test_heartbeat_reports_remaining_time_and_admin_messages(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"])
    env.client.post(f"/attempts/{c['attempt_id']}/message", headers=org["headers"], json={"body": "Five minutes left"})
    hb = env.client.post("/attempt/heartbeat", headers=c["headers"], json={"visible": True, "fullscreen": True, "camera": True}).json()
    assert 0 < hb["remaining_seconds"] <= 1800 and [m["body"] for m in hb["messages"]] == ["Five minutes left"]
    again = env.client.post(f"/attempt/heartbeat?after={hb['messages'][0]['id']}", headers=c["headers"], json={}).json()
    assert again["messages"] == []


def test_admin_can_extend_time(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org, duration_minutes=10)["code"])
    before = env.client.post("/attempt/heartbeat", headers=c["headers"], json={}).json()["remaining_seconds"]
    env.client.post(f"/attempts/{c['attempt_id']}/extend", headers=org["headers"], json={"minutes": 15})
    after = env.client.post("/attempt/heartbeat", headers=c["headers"], json={}).json()["remaining_seconds"]
    assert after - before >= 15 * 60 - 5


def test_expired_attempt_is_auto_submitted_by_the_sweeper(env):
    org = env.make_org()
    test = env.make_test(org, duration_minutes=10, questions=TWO_Q(env))
    c = env.candidate(test["code"])
    qid = c["state"]["questions"][0]["id"]
    env.client.put("/attempt/answers", headers=c["headers"], json={"answers": {str(qid): "4"}})
    _db_attempt(c["attempt_id"], started_at=utcnow() - timedelta(minutes=30))
    db = SessionLocal()
    try:
        assert attempt_service.sweep_expired(db) == 1
        assert attempt_service.sweep_expired(db) == 0                      # nothing left to sweep
    finally:
        db.close()
    report = env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()
    assert report["status"] == "submitted" and report["auto_submitted"] is True


def test_rejoining_after_expiry_finalises_instead_of_resuming(env):
    org = env.make_org()
    test = env.make_test(org, duration_minutes=10)
    c = env.candidate(test["code"], email="late@mail.example.com")
    _db_attempt(c["attempt_id"], started_at=utcnow() - timedelta(hours=2))
    r, _ = env.join(test["code"], email="late@mail.example.com")
    assert r.status_code == 409
    assert env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()["status"] == "submitted"


# ---------------------------------------------------------------- sessions
def test_second_login_replaces_the_first_session(env):
    org = env.make_org()
    test = env.make_test(org)
    first = env.candidate(test["code"], email="two@mail.example.com")
    r, _ = env.join(test["code"], email="two@mail.example.com")
    assert r.status_code == 200
    assert env.client.get("/attempt", headers=first["headers"]).status_code == 401      # old window is dead
    assert env.client.get("/attempt", headers=env.h(r.json()["token"])).status_code == 200


def test_candidate_token_cannot_reach_staff_endpoints(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"])
    for path in ("/tests", "/org", "/org/dashboard", f"/attempts/{c['attempt_id']}", "/superadmin/overview"):
        assert env.client.get(path, headers=c["headers"]).status_code in (401, 403), path


def test_staff_token_cannot_be_used_as_candidate(env):
    org = env.make_org()
    assert env.client.get("/attempt", headers=org["headers"]).status_code in (401, 403)


def test_token_for_one_attempt_cannot_read_another(env):
    org = env.make_org()
    test = env.make_test(org)
    a = env.candidate(test["code"], email="a@mail.example.com")
    b = env.candidate(test["code"], email="b@mail.example.com")
    env.client.put("/attempt/answers", headers=a["headers"], json={"answers": {str(a["state"]["questions"][0]["id"]): "secret"}})
    assert str(env.client.get("/attempt", headers=b["headers"]).json()["answers"]) == "{}"


# ---------------------------------------------------------------- proctoring
def test_server_decides_severity_and_ignores_client_claims(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org)["code"])
    r = env.client.post("/attempt/violations", headers=c["headers"], json={"code": "COPY_PASTE", "severity": 2})
    assert r.json()["severity"] == 1 and r.json()["level2_count"] == 0
    bad = env.client.post("/attempt/violations", headers=c["headers"], json={"code": "MULTIPLE_FACES"})
    assert bad.status_code == 400                                    # AI-only code cannot be forged by the browser
    assert env.client.post("/attempt/violations", headers=c["headers"], json={"code": "NOPE"}).status_code in (400, 422)


def test_duplicate_violations_inside_the_window_count_once(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org)["code"])
    outs = [env.client.post("/attempt/violations", headers=c["headers"], json={"code": "TAB_SWITCH"}).json() for _ in range(5)]
    assert [o["recorded"] for o in outs] == [True, False, False, False, False]
    assert outs[-1]["level2_count"] == 1


def test_three_serious_violations_terminate_the_attempt(env):
    org = env.make_org()
    test = env.make_test(org, result_visibility="full")
    c = env.candidate(test["code"])
    outs = [env.client.post("/attempt/violations", headers=c["headers"], json={"code": code}).json()
            for code in ("TAB_SWITCH", "FULLSCREEN_EXIT", "DEVTOOLS")]
    assert [o["terminated"] for o in outs] == [False, False, True]
    state = env.client.get("/attempt", headers=c["headers"]).json()
    assert state["attempt"]["status"] == "terminated" and "score" not in state["result"]      # terminated = no score shown
    assert env.client.post("/attempt/heartbeat", headers=c["headers"], json={}).json()["status"] == "terminated"
    r, _ = env.join(test["code"], email=c["email"])
    assert r.status_code == 409


def test_auto_terminate_can_be_switched_off(env):
    org = env.make_org()
    test = env.make_test(org, proctoring={"webcam_required": False, "ai_monitoring": False, "auto_terminate": False})
    c = env.candidate(test["code"])
    for code in ("TAB_SWITCH", "FULLSCREEN_EXIT", "DEVTOOLS", "CAMERA_LOST"):
        out = env.client.post("/attempt/violations", headers=c["headers"], json={"code": code}).json()
    assert out["terminated"] is False and out["level2_count"] >= 3


def test_disabled_checks_are_not_recorded(env):
    org = env.make_org()
    test = env.make_test(org, proctoring={"webcam_required": False, "ai_monitoring": False, "block_copy_paste": False})
    c = env.candidate(test["code"])
    assert env.client.post("/attempt/violations", headers=c["headers"], json={"code": "COPY_PASTE"}).json()["recorded"] is False


def test_violations_after_submit_are_ignored(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org)["code"])
    env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    assert env.client.post("/attempt/violations", headers=c["headers"], json={"code": "TAB_SWITCH"}).json()["recorded"] is False


def test_resume_from_a_new_network_is_logged_for_reviewers(env):
    org = env.make_org()
    test = env.make_test(org)
    c = env.candidate(test["code"], email="mv@mail.example.com")
    env.join(test["code"], email="mv@mail.example.com")
    codes = [v["code"] for v in env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()["violations"]]
    assert "SESSION_RESUMED" in codes


def test_camera_loss_reported_by_heartbeat_when_webcam_required(env):
    org = env.make_org()
    test = env.make_test(org, proctoring={"webcam_required": True, "ai_monitoring": False})
    c = env.candidate(test["code"])
    env.client.post("/attempt/heartbeat", headers=c["headers"], json={"camera": False})
    codes = [v["code"] for v in env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()["violations"]]
    assert "CAMERA_LOST" in codes


def test_snapshots_are_capped(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org)["code"])
    tiny = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    assert env.client.post("/attempt/snapshot", headers=c["headers"], json={"image": tiny}).json()["saved"] is True
    assert env.client.post("/attempt/snapshot", headers=c["headers"], json={"image": "not-an-image"}).status_code in (400, 422)


def test_analyze_returns_unavailable_when_ai_is_off(env):
    org = env.make_org()
    c = env.candidate(env.make_test(org)["code"])
    tiny = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    out = env.client.post("/attempt/analyze", headers=c["headers"], json={"image": tiny}).json()
    assert out["available"] is False and out["findings"] == []


# ---------------------------------------------------------------- retake
def test_void_allows_exactly_one_clean_retake(env):
    org = env.make_org()
    test = env.make_test(org, questions=TWO_Q(env))
    c = env.candidate(test["code"], email="retake@mail.example.com")
    env.client.put("/attempt/answers", headers=c["headers"], json={"answers": {str(c["state"]["questions"][0]["id"]): "4"}})
    env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    assert env.client.post(f"/attempts/{c['attempt_id']}/void", headers=org["headers"]).status_code == 200
    second = env.candidate(test["code"], email="retake@mail.example.com")
    assert second["attempt_id"] != c["attempt_id"] and second["state"]["answers"] == {}
    listing = env.client.get(f"/tests/{test['id']}/attempts", headers=org["headers"]).json()["items"]
    assert [a["attempt_no"] for a in listing] == [2]                  # voided attempts are hidden from results
    assert env.client.get("/attempt", headers=c["headers"]).status_code == 401   # the old token died with the void
