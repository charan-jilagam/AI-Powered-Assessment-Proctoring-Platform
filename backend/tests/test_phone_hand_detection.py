"""Phones that are spoken into, held in a hand or only partly visible.

Real models are not needed: the decision logic is pure and the YOLO call is replaced by a fake.
"""
import numpy as np
import pytest

from app import proctoring as P
from app.routers import candidate as cand

ASPECT = 16 / 9


def det(name, conf, box, **kw):
    return {"name": name, "conf": conf, "box": box, **kw}


def person(wrists=(), ears=True, nose=True, back_turned=False, box=(0.3, 0.1, 0.7, 1.0)):
    """A COCO-17 keypoint person facing the camera in the middle of a 16:9 frame (head ~0.09 of the frame wide)."""
    kp = [(0.0, 0.0, 0.0)] * 17
    conf = 0.2 if back_turned else 0.9
    kp[P.KP_NOSE] = (0.50, 0.30, conf if nose else 0.0)
    kp[P.KP_LEYE], kp[P.KP_REYE] = (0.52, 0.27, conf), (0.48, 0.27, conf)
    kp[P.KP_LEAR], kp[P.KP_REAR] = (0.55, 0.29, 0.9 if ears else 0.0), (0.45, 0.29, 0.9 if ears else 0.0)
    kp[P.KP_LSHO], kp[P.KP_RSHO] = (0.60, 0.55, 0.9), (0.40, 0.55, 0.9)
    for index, xy in zip((P.KP_LWRI, P.KP_RWRI), wrists + (None,) * (2 - len(wrists))):
        if xy is not None:
            kp[index] = (xy[0], xy[1], 0.9)
    return {"box": box, "conf": 0.9, "kp": kp}


AT_EAR = (0.575, 0.30)      # just outside the left ear
ON_KEYBOARD = (0.55, 0.95)
ABOVE_HEAD = (0.55, 0.05)


# ------------------------------------------------------------------ weak phone sightings
def test_weak_phones_are_flagged_and_edge_phones_are_not():
    kept = P.select_detections([
        det("cell phone", 0.40, (0.1, 0.1, 0.2, 0.3)),
        det("cell phone", 0.15, (0.1, 0.1, 0.2, 0.3)),
        det("cell phone", 0.20, (0.9, 0.4, 1.0, 0.6)),      # cut by the right-hand frame edge: partly out of view
        det("cell phone", 0.08, (0.1, 0.1, 0.2, 0.3)),      # below even the weak bar
    ])
    assert [(d["conf"], bool(d.get("weak"))) for d in kept] == [(0.40, False), (0.15, True), (0.20, False)]


def test_a_weak_phone_floating_in_the_room_is_ignored_but_one_beside_a_hand_is_kept():
    zones = P.hand_zones([person(wrists=(AT_EAR,))], ASPECT)
    near = det("cell phone", 0.14, (0.57, 0.25, 0.61, 0.33), weak=True)
    far = det("cell phone", 0.14, (0.05, 0.60, 0.09, 0.70), weak=True)
    strong = det("cell phone", 0.60, (0.05, 0.60, 0.09, 0.70))
    out = P.resolve_weak_phones([near, far, strong], zones)
    assert {d["box"][0] for d in out} == {0.57, 0.05}
    assert [d.get("via") for d in out if d["box"][0] == 0.57] == ["context"]
    assert all("weak" not in d for d in out) and len(out) == 2 and far not in out


def test_a_weak_phone_beside_the_head_counts_even_without_pose():
    faces = [{"box": (0.45, 0.2, 0.55, 0.4)}]
    zones = P.head_zones(faces, ASPECT)
    assert P.resolve_weak_phones([det("cell phone", 0.13, (0.57, 0.28, 0.61, 0.36), weak=True)], zones)
    assert not P.resolve_weak_phones([det("cell phone", 0.13, (0.85, 0.28, 0.89, 0.36), weak=True)], zones)


def test_unresolved_weak_phones_never_raise_an_alert():
    assert P.object_findings([det("cell phone", 0.15, (0.1, 0.1, 0.2, 0.3), weak=True)]) == []
    out = P.object_findings([det("cell phone", 0.15, (0.1, 0.1, 0.2, 0.3), via="context")])
    assert out[0]["code"] == "PHONE_DETECTED" and "held in hand or partly hidden" in out[0]["detail"]
    assert "partly hidden" not in P.object_findings([det("cell phone", 0.70, (0.1, 0.1, 0.2, 0.3))])[0]["detail"]


# ------------------------------------------------------------------ hand zones
def test_hand_zone_is_centred_on_the_wrist_and_scales_with_the_head():
    zones = P.hand_zones([person(wrists=(AT_EAR,))], ASPECT)
    assert len(zones) == 1
    x1, y1, x2, y2 = zones[0]["box"]
    assert (x1 + x2) / 2 == pytest.approx(AT_EAR[0]) and (y1 + y2) / 2 == pytest.approx(AT_EAR[1])
    assert (x2 - x1) * ASPECT == pytest.approx(y2 - y1)         # square in pixels, not in fractions
    close = person(wrists=(AT_EAR,))
    for i in (P.KP_LEAR, P.KP_REAR):                              # a head half as wide gives a smaller zone
        x, y, c = close["kp"][i]
        close["kp"][i] = (0.5 + (x - 0.5) / 2, y, c)
    assert P.hand_zones([close], ASPECT)[0]["box"][2] - P.hand_zones([close], ASPECT)[0]["box"][0] < x2 - x1


def test_hidden_wrists_make_no_zone():
    assert P.hand_zones([person()], ASPECT) == []


# ------------------------------------------------------------------ hand raised to the ear
def test_hand_at_the_ear_is_a_call_posture():
    got = P.call_posture(person(wrists=(AT_EAR,)), ASPECT)
    assert got and got["distance"] <= P.EAR_REACH_HEADS


@pytest.mark.parametrize("wrist", [ON_KEYBOARD, ABOVE_HEAD, (0.9, 0.30)])
def test_hands_elsewhere_are_not_a_call(wrist):
    assert P.call_posture(person(wrists=(wrist,)), ASPECT) is None


def test_no_wrist_no_call():
    assert P.call_posture(person(), ASPECT) is None


def test_a_person_with_their_back_to_the_camera_is_not_judged():
    assert P.call_posture(person(wrists=(AT_EAR,), back_turned=True), ASPECT) is None


def test_either_hand_counts():
    assert P.call_posture(person(wrists=(None, (0.425, 0.30))), ASPECT)


def test_profile_view_with_one_ear_hidden_still_works():
    p = person(wrists=(AT_EAR,))
    p["kp"][P.KP_REAR] = (0.45, 0.29, 0.0)
    assert P.call_posture(p, ASPECT)


# ------------------------------------------------------------------ fusion
def codes(out):
    return [f["code"] for f in out["findings"] if f["code"] != "NO_FACE"]    # these frames have no face model; ignore that alert


def test_hand_at_ear_reports_a_suspected_call_and_notes_speaking():
    quiet = P.build_findings(None, [], ASPECT, pose=[person(wrists=(AT_EAR,))])
    call = [f for f in quiet["findings"] if f["code"] == "PHONE_CALL_SUSPECTED"]
    assert codes(quiet) == ["PHONE_CALL_SUSPECTED"] and call[0]["speaking"] is False
    assert "possible phone call" in call[0]["detail"] and "speaking" not in call[0]["detail"]


def test_a_moving_mouth_makes_it_a_speaking_call():
    from tests.test_proctoring_detection import mouth                      # landmarks with the mouth open

    faces = [{"landmarks": mouth(0.3, 0.9), "box": (0.4, 0.2, 0.6, 0.45), "blend": {"jawOpen": 0.8}}]
    out = P.build_findings(faces, [], ASPECT, pose=[person(wrists=(AT_EAR,))])
    call = [f for f in out["findings"] if f["code"] == "PHONE_CALL_SUSPECTED"][0]
    assert call["speaking"] is True and "while speaking" in call["detail"]


def test_a_phone_found_next_to_the_hand_is_reported_once_as_a_phone():
    phone = det("cell phone", 0.40, (0.57, 0.25, 0.61, 0.33))
    out = P.build_findings(None, [phone], ASPECT, pose=[person(wrists=(AT_EAR,))])
    assert codes(out) == ["PHONE_DETECTED"]


def test_no_pose_means_no_call_finding():
    assert codes(P.build_findings(None, [], ASPECT)) == [] and codes(P.build_findings(None, [], ASPECT, pose=[])) == []


# ------------------------------------------------------------------ confirmation rules in the API layer
def run(frames, speaking_frames=None):
    state, out = {}, []
    for i, seen in enumerate(frames):
        f = {"code": "PHONE_CALL_SUSPECTED", "speaking": bool(speaking_frames and speaking_frames[i])}
        present = cand.apply_exam_policy([f], {}) if seen else {}
        confirmed = cand.debounce(state, set(present))
        out.append(next(iter(confirmed.values())) if confirmed else None)
    return out


def test_a_hand_at_the_ear_alone_must_persist_before_it_is_recorded():
    assert run([1, 1, 1]) == [False, False, False]
    assert run([1, 1, 1, 1]) == [False, False, False, True]
    assert run([1, 0, 0, 1, 0, 0, 1]) == [False, None, None, False, None, None, False]      # scratching an ear now and then is fine


def test_a_hand_at_the_ear_while_speaking_is_recorded_quickly():
    assert run([1, 1], [1, 1]) == [False, True]
    assert run([1, 0, 1], [1, 0, 1]) == [False, None, True]


def test_the_call_finding_exists_in_the_catalog_and_is_not_client_reportable():
    from app.constants import CLIENT_REPORTABLE, VIOLATION_CATALOG

    assert VIOLATION_CATALOG["PHONE_CALL_SUSPECTED"][1] == "ai"
    assert "PHONE_CALL_SUSPECTED" not in CLIENT_REPORTABLE


def test_competitive_mode_does_not_excuse_a_phone_call():
    present = cand.apply_exam_policy([{"code": "PHONE_CALL_SUSPECTED", "speaking": False}], {"competitive_exam": True})
    assert "PHONE_CALL_SUSPECTED" in present


# ------------------------------------------------------------------ the zoomed look at hands
class FakeTensor(list):
    def tolist(self):
        return list(self)


def result(items):
    boxes = type("Boxes", (), {})()
    boxes.xyxyn, boxes.conf, boxes.cls = (FakeTensor([i[k] for i in items]) for k in (2, 1, 0))
    return type("Result", (), {"boxes": boxes})()


class ZoomYolo:
    """full frame and tiles see nothing; the enlarged crop (imgsz 416) sees a phone filling its centre."""
    names = {0: "person", 67: "cell phone"}

    def __init__(self, zoom_conf=0.40):
        self.calls, self.zoom_conf = [], zoom_conf

    def predict(self, images, imgsz, **kw):
        self.calls.append((len(images), imgsz))
        if imgsz == P.ZOOM_IMGSZ:
            return [result([(67, self.zoom_conf, (0.3, 0.3, 0.7, 0.7))]) for _ in images]
        return [result([]) for _ in images]


@pytest.fixture
def frame():
    return np.zeros((540, 960, 3), dtype="uint8")


@pytest.fixture(autouse=True)
def _yolo_classes(monkeypatch):
    monkeypatch.setitem(P._state, "yolo_classes", [0, 67])
    monkeypatch.setattr(P, "HAND_ZOOM", True)
    monkeypatch.setattr(P, "TILED_DETECTION", False)


def test_a_phone_only_visible_when_zoomed_in_is_found_and_mapped_back(monkeypatch, frame):
    monkeypatch.setitem(P._state, "yolo", ZoomYolo())
    zones = P.hand_zones([person(wrists=(AT_EAR,))], ASPECT)
    out = P._detect_objects(frame, [person(wrists=(AT_EAR,))])
    phones = [d for d in out if d["name"] == "cell phone"]
    assert len(phones) == 1 and phones[0]["via"] == "zoom"
    zx1, zy1, zx2, zy2 = zones[0]["box"]
    px1, py1, px2, py2 = phones[0]["box"]
    assert zx1 <= px1 < px2 <= zx2 and zy1 <= py1 < py2 <= zy2                   # inside the hand zone, in frame coordinates
    assert px1 == pytest.approx(zx1 + 0.3 * (zx2 - zx1), abs=0.003)


def test_without_hands_or_faces_there_is_nothing_to_zoom_into(monkeypatch, frame):
    monkeypatch.setitem(P._state, "yolo", ZoomYolo())
    assert P._detect_objects(frame, [], []) == []
    assert all(imgsz != P.ZOOM_IMGSZ for _, imgsz in P._state["yolo"].calls)


def test_the_zoom_pass_can_be_switched_off(monkeypatch, frame):
    monkeypatch.setitem(P._state, "yolo", ZoomYolo())
    monkeypatch.setattr(P, "HAND_ZOOM", False)
    assert P._detect_objects(frame, [person(wrists=(AT_EAR,))]) == []


def test_a_zoomed_phone_below_the_zoom_bar_is_dropped(monkeypatch, frame):
    monkeypatch.setitem(P._state, "yolo", ZoomYolo(zoom_conf=0.10))
    assert P._detect_objects(frame, [person(wrists=(AT_EAR,))]) == []


def test_a_phone_seen_by_both_passes_is_not_counted_twice(monkeypatch, frame):
    class Both(ZoomYolo):
        def predict(self, images, imgsz, **kw):
            if imgsz == P.ZOOM_IMGSZ:
                return super().predict(images, imgsz)
            self.calls.append((len(images), imgsz))
            zx1, zy1, zx2, zy2 = P.hand_zones([person(wrists=(AT_EAR,))], ASPECT)[0]["box"]
            box = (zx1 + 0.3 * (zx2 - zx1), zy1 + 0.3 * (zy2 - zy1), zx1 + 0.7 * (zx2 - zx1), zy1 + 0.7 * (zy2 - zy1))
            return [result([(67, 0.5, box)])]
    monkeypatch.setitem(P._state, "yolo", Both())
    out = P._detect_objects(frame, [person(wrists=(AT_EAR,))])
    assert len([d for d in out if d["name"] == "cell phone"]) == 1
