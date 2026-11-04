"""AI proctoring over the whole camera frame: phones, extra people, head pose, frame fusion, model loading.

The real MediaPipe / YOLO models are NOT needed here: the decision logic is pure, and the model plumbing is replaced by
fakes. (A smoke test against real weights is at the bottom; it only runs when the weight files are present.)
"""
import base64
import math
import os

import pytest

from app import proctoring as P
from app.routers import candidate as cand


class Pt:
    def __init__(self, x=0.5, y=0.5, z=0.0):
        self.x, self.y, self.z = x, y, z


def neutral():
    """478 landmarks of a face looking straight at the camera with a closed mouth: eyes centred, nose between the cheeks."""
    pts = [Pt() for _ in range(478)]
    pts[33].x, pts[133].x, pts[362].x, pts[263].x = 0.30, 0.40, 0.60, 0.70
    pts[234].x, pts[454].x, pts[1].x = 0.20, 0.80, 0.50
    for i in P.LEFT_IRIS:
        pts[i].x = 0.35
    for i in P.RIGHT_IRIS:
        pts[i].x = 0.65
    return pts


def det(name, conf, box):
    return {"name": name, "conf": conf, "box": box}


def codes(findings):
    return [f["code"] for f in findings]


# ------------------------------------------------------------------ tiles cover the ENTIRE frame
@pytest.mark.parametrize("w, h", [(960, 540), (1280, 720), (960, 934), (640, 480)])
def test_tiles_cover_the_whole_frame_edge_to_edge(w, h):
    tiles = P.tile_windows(w, h)
    assert len(tiles) == 4
    covered = [[False] * 20 for _ in range(20)]       # a 20x20 grid of probe points across the frame
    for gy in range(20):
        for gx in range(20):
            px, py = (gx + 0.5) * w / 20, (gy + 0.5) * h / 20
            covered[gy][gx] = any(x1 <= px < x2 and y1 <= py < y2 for x1, y1, x2, y2 in tiles)
    assert all(all(row) for row in covered)
    assert min(t[0] for t in tiles) == 0 and min(t[1] for t in tiles) == 0
    assert max(t[2] for t in tiles) == w and max(t[3] for t in tiles) == h
    left, right = tiles[0], tiles[1]
    assert right[0] < left[2]                          # neighbouring tiles overlap, so a phone on a seam is whole in one of them


# ------------------------------------------------------------------ filtering: phones get a deliberately LOW bar
def test_phone_is_accepted_at_a_low_confidence_but_other_things_are_not():
    big = (0.2, 0.2, 0.3, 0.4)
    kept = P.select_detections([
        det("cell phone", 0.31, big),       # phones are small and half hidden by a hand: low bar
        det("cell phone", 0.25, big),       # still too weak
        det("person", 0.40, (0.1, 0.1, 0.6, 0.9)),   # a person needs more than that
        det("person", 0.46, (0.1, 0.1, 0.6, 0.9)),
        det("book", 0.45, big),
        det("book", 0.55, big),
    ])
    assert [(d["name"], d["conf"]) for d in kept] == [("cell phone", 0.31), ("person", 0.46), ("book", 0.55)]


def test_tiny_specks_and_irrelevant_classes_are_ignored():
    assert P.select_detections([det("cell phone", 0.9, (0.5, 0.5, 0.505, 0.505))]) == []       # a few pixels
    assert P.select_detections([det("keyboard", 0.95, (0.1, 0.5, 0.9, 0.9)), det("mouse", 0.95, (0.5, 0.5, 0.6, 0.6)),
                                det("tie", 0.95, (0.4, 0.4, 0.5, 0.7))]) == []                   # own keyboard/mouse are not alarms


def test_a_phone_that_the_model_also_calls_a_remote_stays_a_phone():
    box = (0.40, 0.50, 0.50, 0.70)
    out = P.dedupe_detections([det("remote", 0.60, box), det("cell phone", 0.35, (0.41, 0.51, 0.51, 0.71))])
    assert [d["name"] for d in out] == ["cell phone"]


def test_overlapping_duplicate_person_boxes_collapse_to_one():
    out = P.dedupe_detections([det("person", 0.9, (0.1, 0.1, 0.6, 0.95)), det("person", 0.6, (0.12, 0.12, 0.6, 0.95))])
    assert len(out) == 1 and out[0]["conf"] == 0.9


# ------------------------------------------------------------------ merging the full-frame pass with the tile pass
def test_a_cut_off_piece_of_the_candidate_found_on_a_tile_is_not_a_second_person():
    full = [det("person", 0.90, (0.20, 0.25, 1.00, 1.00))]
    tiled = [det("person", 0.85, (0.38, 0.28, 0.93, 0.62)), det("person", 0.85, (0.23, 0.44, 0.62, 0.99))]
    assert len(P.merge_passes(full, tiled)) == 1


def test_a_small_far_person_that_only_a_tile_can_see_is_found():
    full = [det("person", 0.90, (0.20, 0.25, 0.70, 1.00))]
    tiled = [det("person", 0.72, (0.80, 0.40, 0.88, 0.70))]
    merged = P.merge_passes(full, tiled)
    assert len(merged) == 2


def test_weak_tile_only_people_are_rejected_because_zoom_makes_blurry_backgrounds_look_like_people():
    assert len(P.merge_passes([det("person", 0.9, (0.2, 0.3, 0.7, 1.0))], [det("person", 0.56, (0.80, 0.40, 0.95, 0.80))])) == 1


def test_a_phone_seen_by_the_full_frame_and_a_tile_is_one_phone():
    full = [det("cell phone", 0.40, (0.40, 0.50, 0.46, 0.62))]
    tiled = [det("cell phone", 0.55, (0.405, 0.505, 0.462, 0.625))]
    assert len(P.merge_passes(full, tiled)) == 1


# ------------------------------------------------------------------ counting people
def test_people_counting():
    me = (0.25, 0.20, 0.75, 1.00)
    my_face = (0.42, 0.25, 0.58, 0.50)
    other = (0.78, 0.30, 0.98, 1.00)
    other_face = (0.82, 0.32, 0.94, 0.50)
    assert P.count_people([me], [my_face]) == 1                            # one person, one face
    assert P.count_people([me], []) == 1                                   # face turned away: still a person
    assert P.count_people([], [my_face]) == 1                              # body cut off by the frame, face seen
    assert P.count_people([me, other], [my_face]) == 2                     # someone without a visible face
    assert P.count_people([me, other], [my_face, other_face]) == 2         # faces are not counted twice
    assert P.count_people([me], [my_face, (0.60, 0.30, 0.70, 0.45)]) == 2  # two heads inside one merged box
    assert P.count_people([me], [my_face, (0.01, 0.30, 0.10, 0.45)]) == 2  # a face with no body box at the edge
    assert P.count_people([], []) == 0


# ------------------------------------------------------------------ fusing one frame into findings
def face(box, landmarks=None, blend=None):
    return {"box": box, "landmarks": landmarks if landmarks is not None else neutral(), "blend": blend or {}}


ME = (0.25, 0.20, 0.75, 1.00)
MY_FACE = (0.42, 0.25, 0.58, 0.50)


def test_a_lone_candidate_raises_nothing():
    out = P.build_findings([face(MY_FACE)], [det("person", 0.9, ME)])
    assert out["findings"] == [] and out["face_count"] == 1 and out["person_count"] == 1


def test_someone_behind_the_candidate_with_no_visible_face_is_a_second_person():
    out = P.build_findings([face(MY_FACE)], [det("person", 0.9, ME), det("person", 0.7, (0.78, 0.30, 0.98, 1.0))])
    assert codes(out["findings"]) == ["MULTIPLE_PERSONS"] and out["person_count"] == 2


def test_two_visible_faces_are_reported_as_multiple_faces_not_double_reported():
    out = P.build_findings([face(MY_FACE), face((0.80, 0.30, 0.95, 0.5))], [det("person", 0.9, ME), det("person", 0.8, (0.76, 0.28, 0.99, 1.0))])
    assert codes(out["findings"]) == ["MULTIPLE_FACES"]


def test_body_in_view_but_no_face_is_no_face_with_an_explanation():
    out = P.build_findings([], [det("person", 0.9, ME)])
    assert codes(out["findings"]) == ["NO_FACE"] and "face is not visible" in out["findings"][0]["detail"]


def test_empty_room_is_no_face():
    out = P.build_findings([], [])
    assert codes(out["findings"]) == ["NO_FACE"] and out["findings"][0]["detail"] == "No face visible"


def test_phone_is_its_own_finding_with_the_confidence():
    out = P.build_findings([face(MY_FACE)], [det("person", 0.9, ME), det("cell phone", 0.42, (0.60, 0.60, 0.66, 0.74))])
    assert codes(out["findings"]) == ["PHONE_DETECTED"] and "42%" in out["findings"][0]["detail"] and out["phone_count"] == 1


def test_two_phones_are_counted_and_a_book_is_a_separate_prohibited_object():
    out = P.build_findings([face(MY_FACE)], [det("cell phone", 0.5, (0.1, 0.5, 0.15, 0.62)), det("cell phone", 0.4, (0.8, 0.5, 0.85, 0.62)),
                                              det("book", 0.7, (0.4, 0.8, 0.6, 0.95))])
    assert sorted(codes(out["findings"])) == ["PHONE_DETECTED", "PROHIBITED_OBJECT"]
    assert "2 mobile phones" in out["findings"][0]["detail"] or "2 mobile phones" in out["findings"][1]["detail"]
    assert out["phone_count"] == 2


def test_the_largest_face_is_the_candidate_not_whichever_came_first():
    looking_away = neutral()
    for i in P.LEFT_IRIS:
        looking_away[i].x = 0.30
    for i in P.RIGHT_IRIS:
        looking_away[i].x = 0.60
    big_ok = face(MY_FACE)
    small_background = face((0.85, 0.3, 0.90, 0.38), landmarks=looking_away)
    assert "LOOKING_AWAY" not in codes(P.build_findings([small_background, big_ok], None)["findings"])


def test_when_the_object_model_is_unavailable_people_are_still_counted_from_faces():
    out = P.build_findings([face(MY_FACE), face((0.8, 0.3, 0.95, 0.5))], None)
    assert codes(out["findings"]) == ["MULTIPLE_FACES"] and out["person_count"] == 2


def test_when_the_face_model_is_unavailable_people_come_from_the_object_model():
    assert codes(P.build_findings(None, [det("person", 0.9, ME), det("person", 0.8, (0.78, 0.3, 0.98, 1.0))])["findings"]) == ["MULTIPLE_PERSONS"]
    assert codes(P.build_findings(None, [])["findings"]) == ["NO_FACE"]            # nobody there at all
    assert P.build_findings(None, [det("person", 0.9, ME)])["findings"] == []      # one person, nothing to say


# ------------------------------------------------------------------ head pose from 3-D landmarks
def posed(yaw=0.0, pitch=0.0, aspect=1.0):
    """A synthetic face turned by `yaw` and tipped by `pitch` (chin down = positive), as MediaPipe would report it:
    x / z normalised by frame width, y by height, z growing away from the camera."""
    pts = neutral()
    cy, cp, sy, sp = math.cos(math.radians(yaw)), math.cos(math.radians(pitch)), math.sin(math.radians(yaw)), math.sin(math.radians(pitch))

    def place(i, x, y, z):
        x, z = x * cy + z * sy, -x * sy + z * cy          # yaw about the vertical axis
        y, z = y * cp - z * sp, y * sp + z * cp           # pitch about the horizontal axis
        pts[i].x, pts[i].y, pts[i].z = 0.5 + x / aspect, 0.5 + y, z / aspect

    place(P.CHEEK_LEFT, -0.25, 0, 0); place(P.CHEEK_RIGHT, 0.25, 0, 0); place(P.FACE_TOP, 0, -0.30, 0); place(P.FACE_CHIN, 0, 0.30, 0)
    return pts


def test_a_neutral_posed_face_raises_no_findings_at_all():
    assert P.interpret_landmarks(posed()) == []


def test_a_face_looking_straight_at_the_camera_has_no_pose_angle():
    yaw, pitch = P.head_pose_from_landmarks(posed(), 1.0)
    assert abs(yaw) < 0.5 and abs(pitch) < 0.5


@pytest.mark.parametrize("deg", [15, 30, 45])
def test_pitch_down_is_positive_and_accurate(deg):
    assert P.head_pose_from_landmarks(posed(pitch=deg))[1] == pytest.approx(deg, abs=0.5)
    assert P.head_pose_from_landmarks(posed(pitch=-deg))[1] == pytest.approx(-deg, abs=0.5)


@pytest.mark.parametrize("deg", [20, 40])
def test_yaw_is_measured_either_way(deg):
    assert abs(P.head_pose_from_landmarks(posed(yaw=deg))[0]) == pytest.approx(deg, abs=0.5)
    assert abs(P.head_pose_from_landmarks(posed(yaw=-deg))[0]) == pytest.approx(deg, abs=0.5)


def test_pose_does_not_depend_on_the_frame_shape():
    assert P.head_pose_from_landmarks(posed(pitch=35, aspect=16 / 9), 16 / 9)[1] == pytest.approx(35, abs=0.5)
    assert P.head_pose_from_landmarks(posed(yaw=30, aspect=16 / 9), 16 / 9)[0] == pytest.approx(-30, abs=0.5) or \
        P.head_pose_from_landmarks(posed(yaw=30, aspect=16 / 9), 16 / 9)[0] == pytest.approx(30, abs=0.5)


def test_pose_is_unavailable_without_depth_or_for_a_face_facing_away():
    class NoZ:
        def __init__(self):
            self.x = self.y = 0.5
    assert P.head_pose_from_landmarks([NoZ() for _ in range(478)]) is None
    assert P.head_pose_from_landmarks([]) is None
    assert P.head_pose_from_landmarks(posed(yaw=180)) is None


def test_looking_down_at_a_phone_or_the_desk_is_caught():
    assert codes(P.interpret_landmarks(posed(pitch=35))) == ["LOOKING_DOWN"]
    assert P.interpret_landmarks(posed(pitch=10)) == []                              # reading the lower part of the screen is fine
    assert "LOOKING_DOWN" in codes(P.interpret_landmarks(posed(pitch=16), {"eyeLookDownLeft": 0.8, "eyeLookDownRight": 0.7}))   # head AND eyes down
    assert "LOOKING_DOWN" not in codes(P.interpret_landmarks(posed(pitch=16), {"eyeLookDownLeft": 0.2, "eyeLookDownRight": 0.2}))
    flat = neutral()                                                      # no depth information at all: the eyes alone decide, more strictly
    assert "LOOKING_DOWN" in codes(P.interpret_landmarks(flat, {"eyeLookDownLeft": 0.9, "eyeLookDownRight": 0.9}))
    assert "LOOKING_DOWN" not in codes(P.interpret_landmarks(flat, {"eyeLookDownLeft": 0.62, "eyeLookDownRight": 0.62}))


def test_a_strongly_turned_head_is_caught_even_when_the_nose_does_not_move():
    assert codes(P.interpret_landmarks(posed(yaw=45))) == ["HEAD_TURNED"]
    assert P.interpret_landmarks(posed(yaw=15)) == []


def test_looking_up_is_looking_away():
    out = P.interpret_landmarks(posed(pitch=-35))
    assert codes(out) == ["LOOKING_AWAY"] and "up" in out[0]["detail"]


# ------------------------------------------------------------------ speaking: normalised by face size, steadier with blendshapes
def mouth(open_amount, face_height):
    pts = neutral()
    pts[P.FACE_TOP].y, pts[P.FACE_CHIN].y = 0.5 - face_height / 2, 0.5 + face_height / 2
    for i in P.UPPER_LIP:
        pts[i].y = 0.5
    for i in P.LOWER_LIP:
        pts[i].y = 0.5 + open_amount
    pts[291].y = 0.5
    return pts


def test_a_relaxed_mouth_on_a_big_close_face_is_not_speaking():
    # absolute gap 0.06 would have tripped the old fixed 0.05 threshold; relative to a 0.6-tall face it is only 10 %
    assert P.interpret_landmarks(mouth(0.06, 0.6)) == []
    assert codes(P.interpret_landmarks(mouth(0.12, 0.6))) == ["LIP_MOVEMENT"]


def test_a_small_far_face_with_an_open_mouth_is_still_caught():
    assert codes(P.interpret_landmarks(mouth(0.03, 0.15))) == ["LIP_MOVEMENT"]    # the old absolute threshold would have missed this


def test_jaw_open_blendshape_decides_when_available():
    assert codes(P.interpret_landmarks(mouth(0.0, 0.5), {"jawOpen": 0.6})) == ["LIP_MOVEMENT"]
    assert P.interpret_landmarks(mouth(0.3, 0.5), {"jawOpen": 0.05}) == []


# ------------------------------------------------------------------ blocked camera
def test_blocked_camera_detection():
    assert P.covered_reason(5, 3) and "black" in P.covered_reason(5, 3)
    assert P.covered_reason(120, 2) and "blocked" in P.covered_reason(120, 2)       # a hand / paper over the lens: bright but flat
    assert P.covered_reason(110, 45) is None                                        # a real scene


# ------------------------------------------------------------------ debouncing in the API layer
def run(code_frames, code="PHONE_DETECTED"):
    state, out = {}, []
    for seen in code_frames:
        out.append(cand.debounce(state, {code} if seen else set()).get(code))
    return out


def test_a_flickering_phone_is_confirmed_even_though_it_never_shows_twice_in_a_row():
    assert run([1, 0, 1]) == [False, None, True]


def test_consecutive_rules_are_unchanged_for_gaze():
    assert run([1, 0, 1, 1, 1], "LOOKING_AWAY") == [False, None, False, False, True]


def test_one_stray_sighting_never_confirms_and_old_sightings_age_out_of_the_window():
    assert run([1, 0, 0, 0, 1]) == [False, None, None, None, False]


def test_a_confirmed_event_starts_counting_again_instead_of_firing_every_frame():
    assert run([1, 1, 1, 1, 1, 1]) == [False, True, False, True, False, True]


def test_state_stays_small():
    state = {}
    for seen in [1, 1, 0, 0, 0, 0, 0]:
        cand.debounce(state, {"PHONE_DETECTED"} if seen else set())
    assert state["hist"] == {} and state["streaks"] == {}


# ------------------------------------------------------------------ analyze_frame end to end with fake models
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def data_url(img, quality=80):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


@pytest.fixture()
def scene():
    rng = np.random.default_rng(1)
    return (rng.normal(110, 30, (540, 960, 3))).clip(0, 255).astype("uint8")


@pytest.fixture()
def live(monkeypatch):
    """A 'loaded' AI stack whose two models are fakes."""
    monkeypatch.setitem(P._state, "loaded", True)
    monkeypatch.setitem(P._state, "error", None)
    monkeypatch.setitem(P._state, "cv2", cv2)
    monkeypatch.setitem(P._state, "np", np)
    monkeypatch.setitem(P._state, "landmarker", object())
    monkeypatch.setitem(P._state, "yolo", object())
    box = {"faces": [face(MY_FACE)], "dets": [det("person", 0.9, ME)]}
    monkeypatch.setattr(P, "_detect_faces", lambda rgb: box["faces"])
    monkeypatch.setattr(P, "_detect_objects", lambda img: box["dets"])
    return box


def test_a_phone_anywhere_in_the_frame_is_reported_with_boxed_evidence(live, scene):
    live["dets"] = [det("person", 0.9, ME), det("cell phone", 0.41, (0.88, 0.80, 0.93, 0.92))]     # bottom-right corner, far from the face
    out = P.analyze_frame(data_url(scene))
    assert out["available"] and codes(out["findings"]) == ["PHONE_DETECTED"] and out["phone_count"] == 1
    assert any(b["kind"] == "phone" and b["x"] > 0.8 for b in out["boxes"])
    evidence = out["evidence_image"]
    assert evidence and evidence.startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(evidence.split(",", 1)[1])
    assert len(raw) <= 400_000
    drawn = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert drawn.shape[:2] == scene.shape[:2]
    corner = drawn[int(0.80 * 540) - 3:int(0.80 * 540) + 3, int(0.88 * 960):int(0.93 * 960)]
    assert (corner[..., 2].astype(int) - corner[..., 1].astype(int)).max() > 80       # the red phone box was drawn on the frame


def test_a_second_person_at_the_edge_of_the_frame_is_reported(live, scene):
    live["dets"] = [det("person", 0.9, ME), det("person", 0.7, (0.92, 0.25, 1.0, 1.0))]            # half out of frame, far right
    out = P.analyze_frame(data_url(scene))
    assert codes(out["findings"]) == ["MULTIPLE_PERSONS"] and out["person_count"] == 2 and out["evidence_image"]
    assert sum(1 for b in out["boxes"] if b["kind"] == "person") == 2


def test_a_quiet_frame_has_no_findings_and_no_evidence(live, scene):
    out = P.analyze_frame(data_url(scene))
    assert out["findings"] == [] and out["evidence_image"] is None and out["person_count"] == 1


def test_a_blocked_camera_is_reported_without_running_the_models(live, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("models must not run on a blocked camera")
    monkeypatch.setattr(P, "_detect_faces", boom)
    monkeypatch.setattr(P, "_detect_objects", boom)
    black = np.zeros((540, 960, 3), dtype="uint8")
    assert codes(P.analyze_frame(data_url(black))["findings"]) == ["CAMERA_COVERED"]
    flat = np.full((540, 960, 3), 140, dtype="uint8")
    assert codes(P.analyze_frame(data_url(flat))["findings"]) == ["CAMERA_COVERED"]


def test_a_failing_face_model_does_not_hide_a_phone(live, scene, monkeypatch):
    def broken(rgb):
        raise RuntimeError("landmarker crashed")
    monkeypatch.setattr(P, "_detect_faces", broken)
    live["dets"] = [det("person", 0.9, ME), det("cell phone", 0.6, (0.6, 0.6, 0.7, 0.8))]
    out = P.analyze_frame(data_url(scene))
    assert "PHONE_DETECTED" in codes(out["findings"])


def test_without_the_face_model_phones_and_people_are_still_detected(live, scene, monkeypatch):
    monkeypatch.setitem(P._state, "landmarker", None)
    live["dets"] = [det("person", 0.9, ME), det("person", 0.8, (0.76, 0.28, 0.99, 1.0)), det("cell phone", 0.5, (0.1, 0.5, 0.16, 0.65))]
    out = P.analyze_frame(data_url(scene))
    assert sorted(codes(out["findings"])) == ["MULTIPLE_PERSONS", "PHONE_DETECTED"]


def test_very_large_frames_are_scaled_down_but_never_cropped(live, scene, monkeypatch):
    seen = {}
    monkeypatch.setattr(P, "_detect_objects", lambda img: seen.setdefault("shape", img.shape) and [])
    big = cv2.resize(scene, (2560, 1440), interpolation=cv2.INTER_LINEAR)
    P.analyze_frame(data_url(big))
    h, w = seen["shape"][:2]
    assert max(h, w) == P.MAX_ANALYSIS_SIDE and w / h == pytest.approx(16 / 9, abs=0.01)


# ------------------------------------------------------------------ model plumbing with fake models: coordinate mapping
class FakeTensor(list):
    """Quacks like the tensors ultralytics returns: .tolist()."""

    def tolist(self):
        return list(self)


def yolo_result(items):
    boxes = type("Boxes", (), {})()
    boxes.xyxyn = FakeTensor([i[2] for i in items])
    boxes.conf = FakeTensor([i[1] for i in items])
    boxes.cls = FakeTensor([i[0] for i in items])
    return type("Result", (), {"boxes": boxes})()


class FakeYolo:
    """names like COCO; call 1 = the full frame, call 2 = the batch of tiles."""
    names = {0: "person", 67: "cell phone", 73: "book"}

    def __init__(self, full, per_tile):
        self.full, self.per_tile, self.calls = full, per_tile, []

    def predict(self, images, imgsz, **kw):
        self.calls.append((len(images), imgsz))
        if len(self.calls) == 1:
            return [yolo_result(self.full)]
        return [yolo_result(self.per_tile.get(i, [])) for i in range(len(images))]


def test_a_phone_found_on_a_tile_is_mapped_back_to_the_right_place_in_the_full_frame(monkeypatch, scene):
    monkeypatch.setitem(P._state, "yolo", FakeYolo(full=[(0, 0.9, (0.2, 0.2, 0.7, 1.0))], per_tile={1: [(67, 0.5, (0.5, 0.5, 0.6, 0.7))]}))
    monkeypatch.setitem(P._state, "yolo_classes", [0, 67])
    monkeypatch.setattr(P, "TILED_DETECTION", True)
    h, w = scene.shape[:2]
    x1, y1, x2, y2 = P.tile_windows(w, h)[1]                                  # the top-right tile
    out = {d["name"]: d for d in P._detect_objects(scene)}
    px1, py1, px2, py2 = out["cell phone"]["box"]
    assert (px1, py1, px2, py2) == pytest.approx(((x1 + 0.5 * (x2 - x1)) / w, (y1 + 0.5 * (y2 - y1)) / h, (x1 + 0.6 * (x2 - x1)) / w, (y1 + 0.7 * (y2 - y1)) / h))
    assert px1 == pytest.approx(0.6875, abs=0.001)                                    # right-hand side of the frame ...
    assert py1 == pytest.approx(0.3130, abs=0.001) and py2 < 0.5                      # ... in the upper half
    model = P._state["yolo"]
    assert model.calls == [(1, P.DETECT_IMGSZ), (4, P.TILE_IMGSZ)]            # one full-frame pass + one batched pass over four tiles


def test_tiling_can_be_switched_off_for_small_hosts(monkeypatch, scene):
    monkeypatch.setitem(P._state, "yolo", FakeYolo(full=[(67, 0.5, (0.1, 0.5, 0.2, 0.7))], per_tile={}))
    monkeypatch.setitem(P._state, "yolo_classes", [0, 67])
    monkeypatch.setattr(P, "TILED_DETECTION", False)
    assert [d["name"] for d in P._detect_objects(scene)] == ["cell phone"] and len(P._state["yolo"].calls) == 1


def test_small_frames_are_not_tiled(monkeypatch):
    monkeypatch.setitem(P._state, "yolo", FakeYolo(full=[], per_tile={}))
    monkeypatch.setitem(P._state, "yolo_classes", [0, 67])
    monkeypatch.setattr(P, "TILED_DETECTION", True)
    P._detect_objects(np.zeros((240, 320, 3), dtype="uint8"))
    assert len(P._state["yolo"].calls) == 1


def landmarks_in(box):
    """478 points whose bounding box is `box` (all that face_box() looks at)."""
    x1, y1, x2, y2 = box
    pts = [Pt((x1 + x2) / 2, (y1 + y2) / 2) for _ in range(478)]
    pts[0].x, pts[0].y, pts[1].x, pts[1].y = x1, y1, x2, y2
    return pts


class FakeLandmarker:
    """detect() call 1 = the full frame, then one call per tile, answered from `script`."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def detect(self, image):
        self.calls.append(image.data.shape)
        faces = self.script.get(len(self.calls) - 1, [])
        blend = [[type("C", (), {"category_name": "jawOpen", "score": 0.1})()] for _ in faces]
        return type("D", (), {"face_landmarks": [landmarks_in(b) for b in faces], "face_blendshapes": blend})()


def fake_mp():
    return type("MP", (), {"Image": lambda image_format, data: type("I", (), {"data": data})(), "ImageFormat": type("F", (), {"SRGB": 1})})


def test_faces_are_searched_on_tiles_and_mapped_back_without_double_counting(monkeypatch, scene):
    h, w = scene.shape[:2]
    tiles = P.tile_windows(w, h)
    tx1, ty1, tx2, ty2 = tiles[1]
    candidate_full = (0.40, 0.20, 0.60, 0.55)                                   # the candidate, seen on the full frame
    far_in_tile = (0.62, 0.30, 0.74, 0.62)                                      # a small face (72x108 px) at the right, in tile-local coordinates
    # the top-left tile sees only a cut-off half of the candidate's own face (a would-be false 'second face')
    script = {0: [candidate_full], 1: [(0.60, 0.30, 1.0, 0.95)], 2: [far_in_tile]}
    monkeypatch.setitem(P._state, "landmarker", FakeLandmarker(script))
    monkeypatch.setitem(P._state, "np", np)
    monkeypatch.setitem(P._state, "mp", fake_mp())
    monkeypatch.setattr(P, "TILED_DETECTION", True)
    faces = P._detect_faces(scene)
    assert len(P._state["landmarker"].calls) == 5                               # full frame + 4 tiles
    assert len(faces) == 2
    far = max(faces, key=lambda f: f["box"][0])["box"]
    assert far == pytest.approx(((tx1 + 0.62 * (tx2 - tx1)) / w, (ty1 + 0.30 * (ty2 - ty1)) / h, (tx1 + 0.74 * (tx2 - tx1)) / w, (ty1 + 0.62 * (ty2 - ty1)) / h))
    assert all(f["blend"] == {"jawOpen": pytest.approx(0.1)} for f in faces)


def test_an_ordinary_small_face_is_not_rejected_for_the_frames_aspect_ratio(monkeypatch, scene):
    h, w = scene.shape[:2]                       # 960x540: a 70x90 px face is only 0.44 wide-to-tall in fractions of the frame
    tx1, ty1, tx2, ty2 = P.tile_windows(w, h)[2]
    tw, th = tx2 - tx1, ty2 - ty1
    local = (100 / tw, 100 / th, 170 / tw, 190 / th)                                  # 70 x 90 px inside the bottom-left tile
    monkeypatch.setitem(P._state, "landmarker", FakeLandmarker({0: [(0.40, 0.10, 0.60, 0.45)], 3: [local]}))
    monkeypatch.setitem(P._state, "np", np)
    monkeypatch.setitem(P._state, "mp", fake_mp())
    monkeypatch.setattr(P, "TILED_DETECTION", True)
    assert len(P._detect_faces(scene)) == 2


def test_face_search_ignores_tiny_or_oddly_shaped_boxes_found_on_tiles(monkeypatch, scene):
    script = {0: [(0.40, 0.20, 0.60, 0.55)], 1: [(0.10, 0.10, 0.11, 0.11)], 2: [(0.1, 0.1, 0.9, 0.2)]}   # a speck, then a wide strip
    monkeypatch.setitem(P._state, "landmarker", FakeLandmarker(script))
    monkeypatch.setitem(P._state, "np", np)
    monkeypatch.setitem(P._state, "mp", fake_mp())
    monkeypatch.setattr(P, "TILED_DETECTION", True)
    assert len(P._detect_faces(scene)) == 1


# ------------------------------------------------------------------ model files + loading
def test_nothing_is_downloaded_under_test(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_download", lambda *a, **k: pytest.fail("tests must never reach for the network"))
    with pytest.raises(FileNotFoundError):
        P._ensure_file(str(tmp_path / "model.task"), "https://example.invalid/model.task")


def test_a_missing_model_is_downloaded_once_outside_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(P.settings, "env", "development")
    got = []
    monkeypatch.setattr(P, "_download", lambda url, dest, **k: got.append((url, dest)) or open(dest, "wb").write(b"x"))
    target = str(tmp_path / "m.task")
    P._ensure_file(target, "https://example.invalid/m.task")
    P._ensure_file(target, "https://example.invalid/m.task")          # already there now
    assert got == [("https://example.invalid/m.task", target)]


def test_download_is_atomic_and_rejects_truncated_files(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"\0" * 200_000)
    dest = tmp_path / "out" / "model.bin"
    P._download(src.as_uri(), str(dest))
    assert dest.stat().st_size == 200_000
    tiny = tmp_path / "tiny.bin"
    tiny.write_bytes(b"oops")
    with pytest.raises(RuntimeError):
        P._download(tiny.as_uri(), str(tmp_path / "out" / "never.bin"))
    assert not (tmp_path / "out" / "never.bin").exists() and not list((tmp_path / "out").glob("*.part"))


def test_only_stock_yolo_weights_are_auto_downloaded():
    assert P._yolo_url("/x/yolov8s.pt").endswith("/yolov8s.pt")
    assert P._yolo_url("/x/yolo11n.pt").endswith("/yolo11n.pt")
    assert P._yolo_url("/x/my-custom-model.pt") is None


def fresh_state():
    return {"loaded": False, "error": None, "landmarker": None, "yolo": None, "cv2": None, "np": None, "mp": None,
            "landmarker_error": None, "yolo_error": None, "yolo_classes": None, "attempted_at": None}


def test_one_model_failing_to_load_leaves_the_other_working(monkeypatch):
    monkeypatch.setattr(P, "_state", fresh_state())
    monkeypatch.setattr(P, "_load_landmarker", lambda: (_ for _ in ()).throw(RuntimeError("face model blocked")))
    monkeypatch.setattr(P, "_load_yolo", lambda: P._state.update(yolo=object()))
    P._load()
    st = P.status()
    assert st["available"] is True and st["face_analysis"] is False and st["person_detection"] is True and "blocked" in st["face_error"]


def test_both_models_failing_reports_why(monkeypatch):
    monkeypatch.setattr(P, "_state", fresh_state())
    monkeypatch.setattr(P, "_load_landmarker", lambda: (_ for _ in ()).throw(RuntimeError("no face model")))
    monkeypatch.setattr(P, "_load_yolo", lambda: (_ for _ in ()).throw(RuntimeError("no yolo")))
    P._load()
    assert P._state["error"] == "no face model; no yolo" and P.status()["available"] is False


def test_a_failed_load_is_retried_later_instead_of_staying_dead_until_restart(monkeypatch):
    monkeypatch.setattr(P, "_state", fresh_state())
    attempts = []
    monkeypatch.setattr(P, "_load_landmarker", lambda: attempts.append("face") or (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(P, "_load_yolo", lambda: attempts.append("yolo") or (_ for _ in ()).throw(RuntimeError("offline")))
    P._ensure_loaded()
    P._ensure_loaded()                                                # too soon: no second attempt
    assert attempts == ["face", "yolo"]
    P._state["attempted_at"] -= P.RETRY_AFTER_SECONDS + 1
    P._ensure_loaded()
    assert attempts == ["face", "yolo", "face", "yolo"]


def test_a_non_coco_model_is_refused_with_a_clear_reason(monkeypatch):
    class Fake:
        names = {0: "cat", 1: "dog"}
    ultralytics = pytest.importorskip("ultralytics")
    monkeypatch.setattr(ultralytics, "YOLO", lambda path: Fake())
    monkeypatch.setattr(P, "_ensure_file", lambda *a, **k: None)
    monkeypatch.setattr(P, "_state", fresh_state())
    with pytest.raises(RuntimeError, match="not a COCO model"):
        P._load_yolo()


# ------------------------------------------------------------------ smoke test against REAL weights (skipped when absent)
@pytest.mark.skipif(not os.path.exists(P.YOLO_MODEL_PATH), reason="YOLO weights not installed")
def test_real_yolo_runs_over_the_whole_frame(scene, monkeypatch):
    pytest.importorskip("ultralytics")
    monkeypatch.setattr(P, "_state", fresh_state())
    P._load()
    if P._state["yolo"] is None:
        pytest.skip(f"YOLO could not load: {P._state['yolo_error']}")
    out = P._detect_objects(cv2.resize(scene, (960, 540)))
    assert isinstance(out, list) and all(d["name"] in P.WANTED_CLASSES and all(0 <= v <= 1 for v in d["box"]) for d in out)


def test_health_reports_each_model_and_never_triggers_a_load(env, monkeypatch):
    monkeypatch.setattr(P, "_state", fresh_state())
    body = env.client.get("/health/ready").json()["ai_proctoring"]
    assert body["loaded"] is False and body["face_model"] is False and body["object_model"] is False
    assert P._state["loaded"] is False                                   # a health check must never block on loading models
    monkeypatch.setitem(P._state, "landmarker", object())
    monkeypatch.setitem(P._state, "yolo_error", "weights missing")
    body = env.client.get("/health/ready").json()["ai_proctoring"]
    assert body["face_model"] is True and body["object_model"] is False and body["object_error"] == "weights missing"
