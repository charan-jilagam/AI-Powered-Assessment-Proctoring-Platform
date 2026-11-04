"""AI proctoring: landmark interpretation (pure) and how the server debounces and applies AI findings.

The real MediaPipe/YOLO models are NOT exercised here (they are optional extras that need model downloads);
these tests cover the decision logic that sits around them.
"""
import pytest

from app import proctoring
from app.routers import candidate as candidate_router

TINY = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


class P:
    def __init__(self, x=0.5, y=0.5):
        self.x, self.y = x, y


def face(iris_x=None, nose_x=0.5, mouth_open=False):
    """A synthetic 478-point face. Defaults: eyes centred, head straight, mouth closed."""
    pts = [P() for _ in range(478)]
    pts[33].x, pts[133].x, pts[362].x, pts[263].x = 0.30, 0.40, 0.60, 0.70
    pts[234].x, pts[454].x, pts[1].x = 0.20, 0.80, nose_x
    left_x = 0.35 if iris_x is None else 0.30 + 0.10 * iris_x
    right_x = 0.65 if iris_x is None else 0.60 + 0.10 * iris_x
    for i in proctoring.LEFT_IRIS:
        pts[i].x = left_x
    for i in proctoring.RIGHT_IRIS:
        pts[i].x = right_x
    for i in proctoring.UPPER_LIP:
        pts[i].y = 0.50
    for i in proctoring.LOWER_LIP:
        pts[i].y = 0.70 if mouth_open else 0.50
    pts[291].y = 0.50
    return pts


def codes(landmarks):
    return [f["code"] for f in proctoring.interpret_landmarks(landmarks)]


def test_a_neutral_face_has_no_findings():
    assert codes(face()) == []


@pytest.mark.parametrize("iris, expect", [(0.0, "left"), (1.0, "right")])
def test_looking_left_or_right_is_detected(iris, expect):
    out = proctoring.interpret_landmarks(face(iris_x=iris))
    assert [f["code"] for f in out] == ["LOOKING_AWAY"] and expect in out[0]["detail"]


def test_small_eye_movement_is_tolerated():
    assert codes(face(iris_x=0.42)) == [] and codes(face(iris_x=0.58)) == []


@pytest.mark.parametrize("nose_x, side", [(0.24, "left"), (0.76, "right")])
def test_head_turn_is_detected(nose_x, side):
    out = proctoring.interpret_landmarks(face(nose_x=nose_x))
    assert [f["code"] for f in out] == ["HEAD_TURNED"] and side in out[0]["detail"]


def test_open_mouth_is_flagged_as_possible_speaking():
    assert codes(face(mouth_open=True)) == ["LIP_MOVEMENT"]


def test_several_findings_can_co_occur():
    assert set(codes(face(iris_x=0.0, nose_x=0.76, mouth_open=True))) == {"LOOKING_AWAY", "HEAD_TURNED", "LIP_MOVEMENT"}


def test_malformed_landmarks_never_raise():
    assert proctoring.interpret_landmarks([]) == []
    assert proctoring.interpret_landmarks([P()] * 10) == []


def test_analyze_frame_degrades_gracefully_without_the_ai_stack(monkeypatch):
    monkeypatch.setitem(proctoring._state, "loaded", True)
    monkeypatch.setitem(proctoring._state, "error", "not installed")
    out = proctoring.analyze_frame(TINY)
    assert out["available"] is False and out["findings"] == []


# ---------------------------------------------------------------- server-side debouncing
@pytest.fixture()
def ai_env(env, monkeypatch):
    monkeypatch.setattr(candidate_router, "MIN_ANALYZE_GAP_SECONDS", 0)
    frames = {"next": {"available": True, "face_count": 1, "findings": []}}
    monkeypatch.setattr(proctoring, "analyze_frame", lambda image, **kw: frames["next"])
    env.frames = frames
    return env


def ai_test(env, org, **proctoring_cfg):
    return env.make_test(org, proctoring={"webcam_required": True, "ai_monitoring": True, **proctoring_cfg})


def frame(env, c, *findings, faces=1):
    env.frames["next"] = {"available": True, "face_count": faces, "findings": [{"code": c_, "detail": "d"} for c_ in findings]}
    return env.client.post("/attempt/analyze", headers=c["headers"], json={"image": TINY}).json()


def recorded(env, org, c):
    return [v["code"] for v in env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()["violations"]]


def test_a_single_bad_frame_is_not_a_violation(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    out = frame(ai_env, c, "NO_FACE")
    assert out["findings"][0]["confirmed"] is False and recorded(ai_env, org, c) == []


def test_consecutive_bad_frames_become_a_violation(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    frame(ai_env, c, "NO_FACE")
    out = frame(ai_env, c, "NO_FACE")
    assert out["findings"][0]["confirmed"] is True and recorded(ai_env, org, c) == ["NO_FACE"]


def test_a_good_frame_resets_the_streak(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    frame(ai_env, c, "NO_FACE")
    frame(ai_env, c)                     # candidate is back
    frame(ai_env, c, "NO_FACE")
    assert recorded(ai_env, org, c) == []


def test_gaze_needs_a_longer_streak_than_face_loss(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    frame(ai_env, c, "LOOKING_AWAY")
    frame(ai_env, c, "LOOKING_AWAY")
    assert recorded(ai_env, org, c) == []
    frame(ai_env, c, "LOOKING_AWAY")
    assert recorded(ai_env, org, c) == ["LOOKING_AWAY"]


def test_ai_findings_do_not_terminate_by_default(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org, max_level2_violations=1)["code"])
    for _ in range(4):
        out = frame(ai_env, c, "NO_FACE", "MULTIPLE_FACES", faces=2)
    assert out["terminated"] is False and out["level2_count"] == 0
    assert ai_env.client.get("/attempt", headers=c["headers"]).json()["attempt"]["status"] == "in_progress"
    assert set(recorded(ai_env, org, c)) >= {"NO_FACE", "MULTIPLE_FACES"}      # still on record for the human reviewer


def test_ai_findings_terminate_when_the_org_opts_in(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org, max_level2_violations=1, ai_can_terminate=True)["code"])
    frame(ai_env, c, "MULTIPLE_FACES")
    out = frame(ai_env, c, "MULTIPLE_FACES")
    assert out["terminated"] is True
    assert ai_env.client.get("/attempt", headers=c["headers"]).json()["attempt"]["status"] == "terminated"


def test_analyze_is_ignored_when_the_test_has_ai_monitoring_off(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_env.make_test(org, proctoring={"webcam_required": False, "ai_monitoring": False})["code"])
    out = frame(ai_env, c, "NO_FACE")
    assert out["available"] is False and recorded(ai_env, org, c) == []


def test_analyze_is_ignored_on_plans_without_ai(ai_env):
    org = ai_env.make_org(plan="starter")
    c = ai_env.candidate(ai_env.make_test(org)["code"])
    assert frame(ai_env, c, "NO_FACE", "NO_FACE")["available"] is False


def test_analyze_rate_limit_skips_rapid_frames(ai_env, monkeypatch):
    monkeypatch.setattr(candidate_router, "MIN_ANALYZE_GAP_SECONDS", 60)
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    frame(ai_env, c)
    assert frame(ai_env, c, "NO_FACE").get("skipped") is True


def test_a_camera_that_went_dark_is_recorded_with_evidence(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    frame(ai_env, c, "CAMERA_COVERED")
    frame(ai_env, c, "CAMERA_COVERED")
    report = ai_env.client.get(f"/attempts/{c['attempt_id']}", headers=org["headers"]).json()
    v = report["violations"][0]
    assert v["code"] == "CAMERA_COVERED" and v["snapshot_id"] and v["details"].startswith("[ai]")


# ---------------------------------------------------------------- phones, extra people and the whole-frame results
def png(r, g, b):
    """A valid 1x1 PNG of the given colour (so two evidence images can be told apart)."""
    import base64
    import struct
    import zlib

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = b"\x00" + bytes((r, g, b))
    blob = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(blob).decode()


def analyze(env, c, **result):
    """One /attempt/analyze call against a fake AI result. Anything not given defaults to a quiet single-person frame."""
    findings = [{"code": code, "detail": "d"} for code in result.pop("codes", [])]
    env.frames["next"] = {"available": True, "face_count": 1, "person_count": 1, "phone_count": 0, "boxes": [], "findings": findings, **result}
    return env.client.post("/attempt/analyze", headers=c["headers"], json={"image": TINY}).json()


def test_a_phone_that_keeps_dropping_out_of_view_is_still_recorded(ai_env):
    """A phone half hidden by a hand is seen in every other frame; 'two in a row' would let exactly that through."""
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    assert analyze(ai_env, c, codes=["PHONE_DETECTED"])["findings"][0]["confirmed"] is False
    analyze(ai_env, c)                                                   # the hand moved: no phone this frame
    assert recorded(ai_env, org, c) == []
    out = analyze(ai_env, c, codes=["PHONE_DETECTED"])
    assert out["findings"][0]["confirmed"] is True and recorded(ai_env, org, c) == ["PHONE_DETECTED"]


def test_a_single_stray_phone_sighting_is_not_a_violation(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    analyze(ai_env, c, codes=["PHONE_DETECTED"])
    for _ in range(4):
        analyze(ai_env, c)
    assert recorded(ai_env, org, c) == []


def test_the_boxed_frame_is_stored_as_evidence_instead_of_the_raw_frame(ai_env, monkeypatch):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    seen = []
    original = candidate_router.proctor_rules.record_violation
    monkeypatch.setattr(candidate_router.proctor_rules, "record_violation", lambda *a, **kw: seen.append(kw.get("image")) or original(*a, **kw))
    boxed = png(255, 0, 0)
    for _ in range(2):
        analyze(ai_env, c, codes=["PHONE_DETECTED"], evidence_image=boxed)
    assert seen == [boxed] and seen[0] != TINY
    analyze(ai_env, c, codes=["LOOKING_AWAY"])                           # no annotated frame for gaze: the raw frame is used
    analyze(ai_env, c, codes=["LOOKING_AWAY"])
    analyze(ai_env, c, codes=["LOOKING_AWAY"])
    assert seen[-1] == TINY


def test_the_response_reports_what_the_ai_sees_and_every_alert_that_was_recorded(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    boxes = [{"kind": "phone", "label": "Phone", "conf": 0.4, "x": 0.8, "y": 0.7, "w": 0.1, "h": 0.2}]
    both = dict(codes=["PHONE_DETECTED", "MULTIPLE_PERSONS"], person_count=2, phone_count=1, boxes=boxes)
    analyze(ai_env, c, **both)
    out = analyze(ai_env, c, **both)
    assert out["person_count"] == 2 and out["phone_count"] == 1 and out["boxes"] == boxes
    assert {o["code"] for o in out["outcomes"]} == {"PHONE_DETECTED", "MULTIPLE_PERSONS"}     # neither alert is lost
    assert set(recorded(ai_env, org, c)) == {"PHONE_DETECTED", "MULTIPLE_PERSONS"}


def test_the_most_serious_finding_comes_first_so_it_is_the_one_shown_to_the_candidate(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    out = analyze(ai_env, c, codes=["LOOKING_AWAY", "PHONE_DETECTED"])
    assert [f["code"] for f in out["findings"]] == ["PHONE_DETECTED", "LOOKING_AWAY"]


def test_a_phone_and_a_second_person_are_serious_but_do_not_terminate_unless_the_org_opts_in(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org, max_level2_violations=1)["code"])
    for _ in range(3):
        out = analyze(ai_env, c, codes=["PHONE_DETECTED", "MULTIPLE_PERSONS"])
    assert out["terminated"] is False and out["level2_count"] == 0
    assert set(recorded(ai_env, org, c)) >= {"PHONE_DETECTED", "MULTIPLE_PERSONS"}


@pytest.mark.parametrize("code", ["PHONE_DETECTED", "MULTIPLE_PERSONS"])
def test_a_phone_or_a_second_person_ends_the_test_when_the_org_opts_in(ai_env, code):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org, max_level2_violations=1, ai_can_terminate=True)["code"])
    analyze(ai_env, c, codes=[code])
    out = analyze(ai_env, c, codes=[code])
    assert out["terminated"] is True


def test_looking_down_is_a_minor_flag_that_needs_a_sustained_look(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    analyze(ai_env, c, codes=["LOOKING_DOWN"])
    analyze(ai_env, c, codes=["LOOKING_DOWN"])
    assert recorded(ai_env, org, c) == []
    out = analyze(ai_env, c, codes=["LOOKING_DOWN"])
    assert recorded(ai_env, org, c) == ["LOOKING_DOWN"] and out["findings"][0]["severity"] == 1


def test_the_browser_cannot_report_the_ai_codes_itself(ai_env):
    org = ai_env.make_org()
    c = ai_env.candidate(ai_test(ai_env, org)["code"])
    for code in ("PHONE_DETECTED", "MULTIPLE_PERSONS", "LOOKING_DOWN"):
        assert ai_env.client.post("/attempt/violations", headers=c["headers"], json={"code": code}).status_code == 400
