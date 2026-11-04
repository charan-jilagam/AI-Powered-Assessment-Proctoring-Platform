"""Competitive-exam mode (rough work: looking down is allowed) and the per-test on-screen calculator setting."""
import pytest

from app import proctoring
from app.routers import candidate as candidate_router
from tests.test_proctoring_ai import TINY, ai_env, ai_test, recorded  # noqa: F401  (fixtures)


def send(env, c, *findings, body=False):
    items = []
    for code in findings:
        item = {"code": code, "detail": "d"}
        if code == "NO_FACE" and body:
            item["body_visible"] = True
        items.append(item)
    env.frames["next"] = {"available": True, "face_count": 0 if "NO_FACE" in findings else 1, "findings": items}
    return env.client.post("/attempt/analyze", headers=c["headers"], json={"image": TINY}).json()


# ---------------------------------------------------------------- the pure rule
def test_policy_is_a_no_op_for_normal_exams():
    f = [{"code": "LOOKING_DOWN"}, {"code": "NO_FACE", "body_visible": True}, {"code": "PHONE_DETECTED"}]
    assert set(candidate_router.apply_exam_policy(f, {"competitive_exam": False})) == {"LOOKING_DOWN", "NO_FACE", "PHONE_DETECTED"}


def test_competitive_exams_ignore_looking_down_but_nothing_else():
    f = [{"code": "LOOKING_DOWN"}, {"code": "PHONE_DETECTED"}, {"code": "MULTIPLE_PERSONS"}, {"code": "HEAD_TURNED"},
         {"code": "LOOKING_AWAY"}, {"code": "CAMERA_COVERED"}, {"code": "NO_FACE"}]
    out = candidate_router.apply_exam_policy(f, {"competitive_exam": True})
    assert "LOOKING_DOWN" not in out
    assert set(out) == {"PHONE_DETECTED", "MULTIPLE_PERSONS", "HEAD_TURNED", "LOOKING_AWAY", "CAMERA_COVERED", "NO_FACE"}


def test_a_hidden_face_with_the_body_still_in_view_gets_its_own_longer_streak():
    out = candidate_router.apply_exam_policy([{"code": "NO_FACE", "body_visible": True}], {"competitive_exam": True})
    assert list(out) == ["NO_FACE_BODY"] and out["NO_FACE_BODY"]["code"] == "NO_FACE"
    # nobody in view at all is judged as always
    assert list(candidate_router.apply_exam_policy([{"code": "NO_FACE"}], {"competitive_exam": True})) == ["NO_FACE"]


def test_the_detector_tells_whether_a_body_is_still_in_view():
    person = [{"name": "person", "box": (0.2, 0.2, 0.8, 0.9), "conf": 0.9}]
    with_body = proctoring.build_findings([], person)["findings"]
    assert with_body[0]["code"] == "NO_FACE" and with_body[0]["body_visible"] is True
    nobody = proctoring.build_findings([], [])["findings"]
    assert nobody[0]["code"] == "NO_FACE" and nobody[0]["body_visible"] is False


# ---------------------------------------------------------------- through the API
def test_looking_down_is_recorded_in_a_normal_exam(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    for _ in range(3):
        send(ai_env, c, "LOOKING_DOWN")
    assert recorded(ai_env, org, c) == ["LOOKING_DOWN"]


def test_looking_down_is_never_recorded_in_a_competitive_exam(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org, competitive_exam=True)["code"])
    for _ in range(12):
        out = send(ai_env, c, "LOOKING_DOWN")
    assert out["findings"] == [] and recorded(ai_env, org, c) == []


def test_other_violations_still_count_in_a_competitive_exam(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org, competitive_exam=True)["code"])
    send(ai_env, c, "LOOKING_DOWN", "PHONE_DETECTED")
    out = send(ai_env, c, "LOOKING_DOWN", "PHONE_DETECTED")
    assert [f["code"] for f in out["findings"]] == ["PHONE_DETECTED"] and recorded(ai_env, org, c) == ["PHONE_DETECTED"]


def test_a_face_hidden_over_rough_work_needs_about_six_frames(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org, competitive_exam=True)["code"])
    for _ in range(5):
        send(ai_env, c, "NO_FACE", body=True)
    assert recorded(ai_env, org, c) == []
    out = send(ai_env, c, "NO_FACE", body=True)
    assert out["findings"][0]["confirmed"] is True and recorded(ai_env, org, c) == ["NO_FACE"]
    # a quick glance down that ends sooner is never recorded
    c2 = ai_env.candidate(ai_test(ai_env, org, competitive_exam=True)["code"])
    for _ in range(4):
        send(ai_env, c2, "NO_FACE", body=True)
    send(ai_env, c2)
    for _ in range(4):
        send(ai_env, c2, "NO_FACE", body=True)
    assert recorded(ai_env, org, c2) == []


def test_nobody_in_view_is_still_flagged_after_two_frames_in_a_competitive_exam(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org, competitive_exam=True)["code"])
    send(ai_env, c, "NO_FACE", body=False)
    send(ai_env, c, "NO_FACE", body=False)
    assert recorded(ai_env, org, c) == ["NO_FACE"]


def test_the_setting_is_saved_and_shown_to_candidates(env):
    org = env.make_org()
    t = env.make_test(org, proctoring={"webcam_required": True, "ai_monitoring": True, "competitive_exam": True})
    assert t["proctoring"]["competitive_exam"] is True
    assert env.make_test(org)["proctoring"]["competitive_exam"] is False
    public = env.client.get(f"/public/tests/{t['code']}").json()
    assert public["proctoring"]["competitive_exam"] is True
    r = env.client.patch(f"/tests/{t['id']}", headers=org["headers"], json={"proctoring": {"webcam_required": True, "ai_monitoring": True, "competitive_exam": False}})
    assert r.json()["proctoring"]["competitive_exam"] is False


# ---------------------------------------------------------------- calculator
def test_calculator_setting_round_trips_and_reaches_the_candidate(env):
    org = env.make_org()
    off = env.make_test(org)
    assert off["calculator"] == "off" and env.client.get(f"/public/tests/{off['code']}").json()["calculator"] == "off"
    t = env.make_test(org, calculator="scientific")
    assert t["calculator"] == "scientific"
    c = env.candidate(t["code"])
    assert c["state"]["test"]["calculator"] == "scientific"
    r = env.client.patch(f"/tests/{t['id']}", headers=org["headers"], json={"calculator": "basic"})
    assert r.status_code == 200 and r.json()["calculator"] == "basic"
    assert env.client.patch(f"/tests/{t['id']}", headers=org["headers"], json={"calculator": "graphing"}).status_code == 422
    copy = env.client.post(f"/tests/{t['id']}/duplicate", headers=org["headers"]).json()
    assert copy["calculator"] == "basic"


def test_the_sample_aptitude_test_has_camera_ai_competitive_mode_and_a_calculator(env):
    org = env.make_org()
    env.client.post("/tests/samples", headers=org["headers"])
    apt = next(t for t in env.client.get("/tests", headers=org["headers"]).json()["items"] if "OMR" in t["title"])
    detail = env.client.get(f"/tests/{apt['id']}", headers=org["headers"]).json()
    p = detail["proctoring"]
    assert p["webcam_required"] and p["ai_monitoring"] and p["competitive_exam"] and p["fullscreen_required"]
    assert p["ai_can_terminate"] is False                       # AI still only flags for a human to review
    assert detail["calculator"] == "scientific"
    public = env.client.get(f"/public/tests/{apt['code']}").json()
    assert public["proctoring"]["webcam_required"] and public["proctoring"]["ai_monitoring"]
