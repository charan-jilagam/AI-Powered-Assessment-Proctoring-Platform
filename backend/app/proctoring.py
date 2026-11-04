"""Server-side AI proctoring over the WHOLE camera frame.

What it looks at (nothing is cropped or masked - every pixel of the frame is analysed):
  * mobile phones and other prohibited objects  - YOLO on the full frame, plus an overlapping tile pass so a phone
    that is only a few dozen pixels wide (held low, on the desk, partly hidden by a hand) is still found
  * people                                      - YOLO `person` boxes fused with MediaPipe face landmarks (faces are
    searched on the full frame and on tiles), so someone standing behind the candidate, sitting at the edge of the
    frame, turned away or only partly visible is counted, not just a second frontal face
  * face presence, gaze, head turn / head down, speaking - MediaPipe face landmarks and blendshapes
  * blocked or dark camera

Heavy libraries (OpenCV, MediaPipe, YOLO) are imported lazily on the first frame, never at import time, so the API
starts fast, tests run without them, and a deployment without the AI extras degrades to "AI unavailable" instead of
crashing. The two models load independently: if the face model cannot be fetched, phone/person detection still works,
and vice versa. All decision logic (`build_findings`, `count_people`, `interpret_landmarks`, ...) is pure and unit-tested;
the model plumbing (`_detect_faces`, `_detect_objects`) is thin.

Models are downloaded on first use if they are missing (set AI_MODEL_AUTODOWNLOAD=false to disable, or run
`python -m app.proctoring download-models` at build time - the Dockerfile does this when WITH_AI=true).
"""
import base64
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.config import settings

log = logging.getLogger("orvexa.ai")


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in ("1", "true", "yes", "on")


_BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
FACE_MODEL_PATH = os.getenv("FACE_MODEL_PATH", os.path.join(_BACKEND_DIR, "face_landmarker.task"))
FACE_MODEL_URL = os.getenv(
    "FACE_MODEL_URL",
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
)
YOLO_ASSET_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/"
_YOLO_STOCK_NAME = re.compile(r"^yolo(v8|11)[nsmlx]\.pt$")


def _resolve_yolo_path() -> str:
    explicit = os.getenv("YOLO_MODEL_PATH")
    if explicit:
        return explicit
    for name in ("yolov8s.pt", "yolov8n.pt"):  # prefer the stronger model, accept an already-installed nano
        candidate = os.path.join(_BACKEND_DIR, name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(_BACKEND_DIR, "yolov8s.pt")


YOLO_MODEL_PATH = _resolve_yolo_path()
AUTODOWNLOAD = _env_bool("AI_MODEL_AUTODOWNLOAD", True)
RETRY_AFTER_SECONDS = 300           # after a failed load, try again this much later instead of staying dead until restart

# Detection tuning. Phones are small and are often half hidden by a hand, so they use a deliberately LOW confidence;
# the server then requires repeated sightings (see routers/candidate.py) before it records anything.
# Both passes run at 640, the scale YOLOv8 was trained at. Running the whole frame at a larger size looks tempting for
# small objects but makes people who sit close to the camera LESS recognisable (measured: one person fell from 0.91 to
# 0.39 confidence at 960), so small objects are handled by the tile pass instead, which zooms in ~1.6x at native scale.
DETECT_IMGSZ = _env_int("AI_DETECT_IMGSZ", 640)
TILE_IMGSZ = _env_int("AI_TILE_IMGSZ", 640)
TILED_DETECTION = _env_bool("AI_TILED_DETECTION", True)
MAX_ANALYSIS_SIDE = 1280            # larger frames are scaled down to this (cheap safety valve, keeps aspect ratio)
YOLO_FLOOR_CONF = 0.20              # what the model returns; each class is then filtered by its own threshold below
PHONE_CONFIDENCE = _env_float("AI_PHONE_CONFIDENCE", 0.30)
PERSON_CONFIDENCE = _env_float("AI_PERSON_CONFIDENCE", 0.45)
TILE_PERSON_CONFIDENCE = 0.65       # a person found ONLY on a tile must be more certain: zooming in also makes blurry
                                    # backgrounds look like people (measured 0.56 on a blurred crowd, 0.7+ on a real far person)
OBJECT_CONFIDENCE = _env_float("AI_OBJECT_CONFIDENCE", 0.50)
MIN_PHONE_AREA = 0.0003             # fraction of the frame (about 20x25 px on a 960x540 frame)
MIN_PERSON_AREA = 0.02
MIN_OBJECT_AREA = 0.002
TILE_GRID = (2, 2)
TILE_OVERLAP = 0.25
MIN_TILED_WIDTH = 640               # tiling a small frame adds cost but no extra detail

PHONE_LABEL = "cell phone"
PERSON_LABEL = "person"
# Other COCO classes treated as prohibited. Keyboards and mice are deliberately NOT here: an external webcam sits on
# the monitor and sees the candidate's own keyboard and mouse, so flagging them only produced false alarms.
PROHIBITED_OBJECTS = {
    "book": "Book detected",
    "laptop": "Second laptop detected",
    "tv": "Extra screen detected",
    "remote": "Remote / device detected",
}
WANTED_CLASSES = {PHONE_LABEL, PERSON_LABEL, *PROHIBITED_OBJECTS}

# MediaPipe face-mesh landmark indices
LEFT_IRIS = [474, 475, 476, 477]
RIGHT_IRIS = [469, 470, 471, 472]
UPPER_LIP = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291]
LOWER_LIP = [146, 91, 181, 84, 17, 314, 405, 321, 375, 291]
FACE_TOP, FACE_CHIN, CHEEK_LEFT, CHEEK_RIGHT = 10, 152, 234, 454

GAZE_LEFT_THRESHOLD = 0.35
GAZE_RIGHT_THRESHOLD = 0.65
LIP_OPEN_THRESHOLD = 0.05           # legacy: lip gap in image units, used only when face height / blendshapes are unavailable
LIP_OPEN_FACE_RATIO = 0.12          # lip gap as a share of face height (independent of how far the candidate sits)
JAW_OPEN_SCORE = 0.35               # blendshape score for "mouth clearly open"
HEAD_YAW_LOW, HEAD_YAW_HIGH = 0.30, 0.70
YAW_TURN_DEG = _env_float("AI_YAW_TURN_DEG", 35.0)
PITCH_DOWN_DEG = _env_float("AI_PITCH_DOWN_DEG", 25.0)      # head tipped down this far = looking at lap / desk / phone
PITCH_DOWN_ASSISTED_DEG = 14.0      # ... or this far when the eyes are also looking down
PITCH_UP_DEG = -25.0
EYES_DOWN_SCORE = 0.60
DARK_FRAME_MEAN = 18.0
FLAT_FRAME_STD = 7.0                # a hand / paper / lens cap over the camera leaves almost no detail

_lock = threading.Lock()            # guards model loading and the (non thread-safe) MediaPipe task object
_yolo_lock = threading.Lock()       # ultralytics predictors are not thread-safe either
_state: Dict[str, Any] = {
    "loaded": False, "error": None, "landmarker": None, "yolo": None, "cv2": None, "np": None, "mp": None,
    "landmarker_error": None, "yolo_error": None, "yolo_classes": None, "attempted_at": None,
}

Box = Tuple[float, float, float, float]   # x1, y1, x2, y2 as fractions of the frame (0..1)


# ---------------------------------------------------------------------------
# geometry helpers (pure)
# ---------------------------------------------------------------------------
def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _intersection(a: Box, b: Box) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def iou(a: Box, b: Box) -> float:
    inter = _intersection(a, b)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def covered_share(inner: Box, outer: Box) -> float:
    """How much of `inner` lies inside `outer` (0..1). Unlike IoU this ignores how big `outer` is."""
    a = _area(inner)
    return _intersection(inner, outer) / a if a > 0 else 0.0


def _center_inside(point_box: Box, outer: Box) -> bool:
    cx, cy = (point_box[0] + point_box[2]) / 2, (point_box[1] + point_box[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def tile_windows(width: int, height: int, grid: Tuple[int, int] = TILE_GRID, overlap: float = TILE_OVERLAP) -> List[Tuple[int, int, int, int]]:
    """Overlapping tiles (x1, y1, x2, y2 in pixels) that together cover the ENTIRE frame, edge to edge."""
    cols, rows = grid
    tile_w = min(width, int(round(width / cols * (1 + overlap))))
    tile_h = min(height, int(round(height / rows * (1 + overlap))))
    step_x = (width - tile_w) / (cols - 1) if cols > 1 else 0
    step_y = (height - tile_h) / (rows - 1) if rows > 1 else 0
    out = []
    for r in range(rows):
        for c in range(cols):
            x1, y1 = int(round(c * step_x)), int(round(r * step_y))
            out.append((x1, y1, min(width, x1 + tile_w), min(height, y1 + tile_h)))
    return out


def kind_of(name: str) -> str:
    return "phone" if name == PHONE_LABEL else "person" if name == PERSON_LABEL else "object"


# ---------------------------------------------------------------------------
# detections (pure): filter, merge full-frame + tile passes, count people
# ---------------------------------------------------------------------------
def select_detections(raw: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep detections of the classes we care about that clear their own confidence and minimum-size bar."""
    keep = []
    for d in raw:
        name = d["name"]
        if name == PERSON_LABEL:
            threshold, min_area = PERSON_CONFIDENCE, MIN_PERSON_AREA
        elif name == PHONE_LABEL:
            threshold, min_area = PHONE_CONFIDENCE, MIN_PHONE_AREA
        elif name in PROHIBITED_OBJECTS:
            threshold, min_area = OBJECT_CONFIDENCE, MIN_OBJECT_AREA
        else:
            continue
        if d["conf"] >= threshold and _area(d["box"]) >= min_area:
            keep.append(d)
    return keep


def dedupe_detections(dets: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicates. People are de-duplicated among themselves; every other object competes class-agnostically
    (a phone that the model also labelled 'remote' stays a phone)."""
    people = sorted((d for d in dets if d["name"] == PERSON_LABEL), key=lambda d: -d["conf"])
    others = sorted((d for d in dets if d["name"] != PERSON_LABEL), key=lambda d: (d["name"] != PHONE_LABEL, -d["conf"]))
    out: List[Dict[str, Any]] = []
    for group, limit in ((people, 0.65), (others, 0.5)):
        kept: List[Dict[str, Any]] = []
        for d in group:
            if all(iou(d["box"], k["box"]) < limit for k in kept):
                kept.append(d)
        out.extend(kept)
    return out


def merge_passes(full: Sequence[Dict[str, Any]], tiled: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combine the full-frame pass with the tile pass without double counting.

    A tile only sees part of a large object, so a person box from a tile that sits inside (or heavily overlaps) a person
    already found on the full frame is that same person cut in half - it must never become a second person."""
    merged = list(full)
    for d in sorted(tiled, key=lambda x: -x["conf"]):
        if d["name"] == PERSON_LABEL:
            if d["conf"] < TILE_PERSON_CONFIDENCE:
                continue
            known = [m["box"] for m in merged if m["name"] == PERSON_LABEL]
            if any(covered_share(d["box"], k) >= 0.5 or iou(d["box"], k) >= 0.3 for k in known):
                continue
        merged.append(d)
    return dedupe_detections(merged)


def count_people(person_boxes: Sequence[Box], face_boxes: Sequence[Box]) -> int:
    """Distinct people in view. A face that sits inside a person box belongs to that person; two faces inside one box
    are two people (the model sometimes merges people who sit close together); a face with no body box counts too
    (body cut off by the frame edge)."""
    free = list(face_boxes)
    total = 0
    for person in person_boxes:
        mine = [f for f in free if _center_inside(f, person)]
        for f in mine:
            free.remove(f)
        total += max(1, len(mine))
    return total + len(free)


def object_findings(dets: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    phones = [d for d in dets if d["name"] == PHONE_LABEL]
    if phones:
        best = int(round(max(p["conf"] for p in phones) * 100))
        what = "Mobile phone" if len(phones) == 1 else f"{len(phones)} mobile phones"
        out.append({"code": "PHONE_DETECTED", "detail": f"{what} detected (confidence {best}%)"})
    names = sorted({d["name"] for d in dets if d["name"] in PROHIBITED_OBJECTS})
    if names:
        out.append({"code": "PROHIBITED_OBJECT", "detail": "; ".join(PROHIBITED_OBJECTS[n] for n in names)})
    return out


# ---------------------------------------------------------------------------
# face landmarks (pure)
# ---------------------------------------------------------------------------
def face_box(landmarks) -> Box:
    xs = [p.x for p in landmarks]
    ys = [p.y for p in landmarks]
    return (max(0.0, min(xs)), max(0.0, min(ys)), min(1.0, max(xs)), min(1.0, max(ys)))


def head_pose_from_landmarks(landmarks, aspect: float = 1.0) -> Optional[Tuple[float, float]]:
    """(yaw, pitch) in degrees from the 3-D landmarks. Pitch > 0 means the chin is down. None without usable depth.

    The face plane is spanned by the cheek-to-cheek and forehead-to-chin vectors; its outward normal tells where the
    head points. Image y grows downward and MediaPipe z grows away from the camera, so a face that looks straight at
    the camera has its normal along -z. x and z are scaled by the frame aspect so the three axes share one unit."""
    try:
        def pt(i):
            p = landmarks[i]
            return (p.x * aspect, p.y, p.z * aspect)
        left, right, top, chin = pt(CHEEK_LEFT), pt(CHEEK_RIGHT), pt(FACE_TOP), pt(FACE_CHIN)
    except (IndexError, AttributeError, TypeError):
        return None
    u = (right[0] - left[0], right[1] - left[1], right[2] - left[2])    # across the face
    v = (chin[0] - top[0], chin[1] - top[1], chin[2] - top[2])          # down the face
    mx, my, mz = v[1] * u[2] - v[2] * u[1], v[2] * u[0] - v[0] * u[2], v[0] * u[1] - v[1] * u[0]
    if not all(math.isfinite(c) for c in (mx, my, mz)) or mz >= 0:
        return None
    return math.degrees(math.atan2(mx, -mz)), math.degrees(math.atan2(my, -mz))


def interpret_landmarks(landmarks, blendshapes: Optional[Dict[str, float]] = None, aspect: Optional[float] = None) -> List[Dict[str, Any]]:
    """Turn one face's 478 landmarks (objects with .x/.y[/.z] in 0..1) into proctoring findings.

    `blendshapes` (name -> score) and `aspect` (frame width / height) are optional; without them the function behaves
    as a landmark-only check."""
    findings: List[Dict[str, Any]] = []
    try:
        left_ratio = (_mean(landmarks[i].x for i in LEFT_IRIS) - landmarks[33].x) / ((landmarks[133].x - landmarks[33].x) or 1e-4)
        right_ratio = (_mean(landmarks[i].x for i in RIGHT_IRIS) - landmarks[362].x) / ((landmarks[263].x - landmarks[362].x) or 1e-4)
        gaze = (left_ratio + right_ratio) / 2
        if gaze < GAZE_LEFT_THRESHOLD:
            findings.append({"code": "LOOKING_AWAY", "detail": "Eyes looking left"})
        elif gaze > GAZE_RIGHT_THRESHOLD:
            findings.append({"code": "LOOKING_AWAY", "detail": "Eyes looking right"})
    except (IndexError, AttributeError, ZeroDivisionError):
        pass

    pose = head_pose_from_landmarks(landmarks, aspect or 1.0)
    turned = False
    try:  # head yaw: where the nose tip sits between the two cheeks
        span = (landmarks[CHEEK_RIGHT].x - landmarks[CHEEK_LEFT].x) or 1e-4
        yaw = (landmarks[1].x - landmarks[CHEEK_LEFT].x) / span
        if yaw < HEAD_YAW_LOW or yaw > HEAD_YAW_HIGH:
            turned = True
            findings.append({"code": "HEAD_TURNED", "detail": "Head turned to the " + ("left" if yaw < HEAD_YAW_LOW else "right")})
    except (IndexError, AttributeError, ZeroDivisionError):
        pass
    if pose is not None and not turned and abs(pose[0]) >= YAW_TURN_DEG:
        findings.append({"code": "HEAD_TURNED", "detail": f"Head turned about {abs(pose[0]):.0f} degrees"})

    # looking down / up: head pitch (and the eyes, when blendshapes are available)
    blend = blendshapes or {}
    eyes_down = _mean([blend.get("eyeLookDownLeft", 0.0), blend.get("eyeLookDownRight", 0.0)]) if blend else 0.0
    pitch = pose[1] if pose is not None else None
    if pitch is not None and (pitch >= PITCH_DOWN_DEG or (pitch >= PITCH_DOWN_ASSISTED_DEG and eyes_down >= EYES_DOWN_SCORE)):
        findings.append({"code": "LOOKING_DOWN", "detail": f"Head tilted down about {pitch:.0f} degrees"})
    elif pitch is None and eyes_down >= EYES_DOWN_SCORE + 0.1:
        findings.append({"code": "LOOKING_DOWN", "detail": "Eyes looking down"})
    elif pitch is not None and pitch <= PITCH_UP_DEG:
        findings.append({"code": "LOOKING_AWAY", "detail": f"Head tilted up about {abs(pitch):.0f} degrees"})

    try:
        if "jawOpen" in blend:
            if blend["jawOpen"] >= JAW_OPEN_SCORE:
                findings.append({"code": "LIP_MOVEMENT", "detail": "Mouth open - possible speaking"})
        else:
            gap = abs(_mean(landmarks[i].y for i in LOWER_LIP) - _mean(landmarks[i].y for i in UPPER_LIP))
            face_height = abs(landmarks[FACE_CHIN].y - landmarks[FACE_TOP].y)
            opened = gap / face_height > LIP_OPEN_FACE_RATIO if face_height > 0.05 else gap > LIP_OPEN_THRESHOLD
            if opened:
                findings.append({"code": "LIP_MOVEMENT", "detail": "Mouth open - possible speaking"})
    except (IndexError, AttributeError):
        pass
    return findings


def covered_reason(mean: float, std: float) -> Optional[str]:
    """Why a frame looks like a blocked camera (black, or flat with no detail), or None if it looks like a real scene."""
    if mean < DARK_FRAME_MEAN:
        return "Camera view is black or covered"
    if std < FLAT_FRAME_STD:
        return "Camera view is blocked (no detail visible)"
    return None


def build_findings(faces: Optional[Sequence[Dict[str, Any]]], dets: Optional[Sequence[Dict[str, Any]]], aspect: float = 1.0) -> Dict[str, Any]:
    """Fuse the face and object/person results of ONE frame into findings.

    `faces`: [{"landmarks", "box", "blend"?}] or None when face analysis did not run.
    `dets`:  filtered detections or None when object detection did not run."""
    findings: List[Dict[str, Any]] = []
    person_boxes = [d["box"] for d in dets if d["name"] == PERSON_LABEL] if dets is not None else None
    face_count = len(faces) if faces is not None else None
    if faces is not None and person_boxes is not None:
        people: Optional[int] = count_people(person_boxes, [f["box"] for f in faces])
    elif person_boxes is not None:
        people = len(person_boxes)
    else:
        people = face_count

    if faces is not None:
        if not faces:
            body = bool(person_boxes)
            findings.append({"code": "NO_FACE", "detail": "A person is in view but their face is not visible (looking away, head down or face covered)" if body else "No face visible",
                             "body_visible": body})
    elif people == 0:
        findings.append({"code": "NO_FACE", "detail": "No person visible"})

    if face_count is not None and face_count >= 2:
        findings.append({"code": "MULTIPLE_FACES", "detail": f"{face_count} faces visible"})
    elif people is not None and people >= 2:
        findings.append({"code": "MULTIPLE_PERSONS", "detail": f"{people} people visible in the camera view"})

    if faces:
        main = max(faces, key=lambda f: _area(f["box"]))   # the candidate is the biggest face, not whichever came first
        findings.extend(interpret_landmarks(main["landmarks"], main.get("blend"), aspect))
    if dets:
        findings.extend(object_findings(dets))
    return {"findings": findings, "face_count": face_count or 0, "person_count": people or 0,
            "phone_count": sum(1 for d in (dets or []) if d["name"] == PHONE_LABEL)}


# ---------------------------------------------------------------------------
# model files + loading
# ---------------------------------------------------------------------------
def _download(url: str, dest: str, timeout: int = 180) -> None:
    folder = os.path.dirname(dest) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".part")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, os.fdopen(fd, "wb") as out:  # honours HTTPS_PROXY
            shutil.copyfileobj(resp, out)
        if os.path.getsize(tmp) < 100_000:
            raise RuntimeError(f"download from {url} looks truncated")
        os.chmod(tmp, 0o644)               # mkstemp makes it 0600; the server may run as a different user than the build
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _ensure_file(path: str, url: Optional[str]) -> None:
    if os.path.exists(path):
        return
    if not (AUTODOWNLOAD and url) or settings.env == "test":   # tests / CI must never reach for the network
        raise FileNotFoundError(f"model missing: {path}")
    log.info("downloading %s", url)
    _download(url, path)


def _yolo_url(path: str) -> Optional[str]:
    name = os.path.basename(path)
    return YOLO_ASSET_URL + name if _YOLO_STOCK_NAME.match(name) else None


def ensure_models() -> Dict[str, str]:
    """Download any missing model file. Used at image-build time; raises nothing, reports per model."""
    report = {}
    for label, path, url in (("face", FACE_MODEL_PATH, FACE_MODEL_URL), ("yolo", YOLO_MODEL_PATH, _yolo_url(YOLO_MODEL_PATH))):
        try:
            _ensure_file(path, url)
            report[label] = "ok"
        except Exception as exc:  # noqa: BLE001
            report[label] = f"failed: {exc}"
    return report


def _load_landmarker() -> None:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    _ensure_file(FACE_MODEL_PATH, FACE_MODEL_URL)
    options = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=FACE_MODEL_PATH),
        output_face_blendshapes=True,                 # jawOpen / eyeLookDown scores: far steadier than raw landmark gaps
        output_facial_transformation_matrixes=False,
        num_faces=6,                                  # was 3: a crowded room must still be counted
        min_face_detection_confidence=0.3,            # was the 0.5 default: small / turned / partly hidden faces count
        min_face_presence_confidence=0.3,
    )
    _state.update(landmarker=vision.FaceLandmarker.create_from_options(options), mp=mp)


def _load_yolo() -> None:
    from ultralytics import YOLO

    _ensure_file(YOLO_MODEL_PATH, _yolo_url(YOLO_MODEL_PATH))
    model = YOLO(YOLO_MODEL_PATH)
    names = getattr(model, "names", {}) or {}
    classes = [int(i) for i, n in names.items() if n in WANTED_CLASSES]
    if PHONE_LABEL not in names.values() or PERSON_LABEL not in names.values():
        raise RuntimeError(f"{os.path.basename(YOLO_MODEL_PATH)} is not a COCO model (no 'cell phone' / 'person' class)")
    _state.update(yolo=model, yolo_classes=classes)


def _load() -> None:
    """Import and build the models once. A failure is remembered (and retried later), never repeated on every frame."""
    with _lock:
        if _state["loaded"]:
            return
        _state.update(loaded=True, attempted_at=time.time(), error=None, landmarker_error=None, yolo_error=None)
        try:
            import cv2
            import numpy as np
            _state.update(cv2=cv2, np=np)
        except Exception as exc:  # noqa: BLE001 - OpenCV / numpy not installed
            _state["error"] = str(exc)
            log.warning("AI proctoring unavailable: %s", exc)
            return
        for key, loader in (("landmarker_error", _load_landmarker), ("yolo_error", _load_yolo)):
            try:
                loader()
            except Exception as exc:  # noqa: BLE001 - missing lib, missing model, blocked download
                _state[key] = str(exc)
                log.warning("AI component unavailable (%s): %s", key.replace("_error", ""), exc)
        if _state["landmarker"] is None and _state["yolo"] is None:
            _state["error"] = "; ".join(e for e in (_state["landmarker_error"], _state["yolo_error"]) if e) or "no AI model could be loaded"


def _ensure_loaded() -> None:
    with _lock:
        due = (_state["loaded"] and _state["error"] is not None and _state.get("attempted_at")
               and time.time() - _state["attempted_at"] > RETRY_AFTER_SECONDS)
        if due:
            _state["loaded"] = False
    if not _state["loaded"]:
        _load()


def warm_up_async() -> None:
    """Load (and if needed download) the models in the background at start-up so the first candidate is not the one waiting."""
    if settings.ai_proctoring_enabled:
        threading.Thread(target=_ensure_loaded, name="ai-warmup", daemon=True).start()


def status() -> Dict[str, Any]:
    if not settings.ai_proctoring_enabled:
        return {"available": False, "reason": "disabled by configuration"}
    _ensure_loaded()
    return {
        "available": _state["error"] is None,
        "reason": _state["error"],
        "object_detection": _state["yolo"] is not None,
        "phone_detection": _state["yolo"] is not None,
        "person_detection": _state["yolo"] is not None,
        "face_analysis": _state["landmarker"] is not None,
        "face_error": _state["landmarker_error"],
        "object_error": _state["yolo_error"],
        "tiled_detection": TILED_DETECTION,
    }


# ---------------------------------------------------------------------------
# model plumbing (thin; replaced by fakes in tests)
# ---------------------------------------------------------------------------
def _decode(data_url: str):
    cv2, np = _state["cv2"], _state["np"]
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    raw = base64.b64decode(data_url)
    return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)


def _faces_in(rgb, offset: Tuple[int, int] = (0, 0), full_size: Optional[Tuple[int, int]] = None) -> List[Dict[str, Any]]:
    """Run the face model on an RGB array. With `offset`/`full_size` the boxes are mapped back to full-frame fractions."""
    np, mp = _state["np"], _state["mp"]
    height, width = rgb.shape[:2]
    full_w, full_h = full_size or (width, height)
    with _lock:
        detection = _state["landmarker"].detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    blends = detection.face_blendshapes or []
    faces = []
    for i, landmarks in enumerate(detection.face_landmarks or []):
        box = face_box(landmarks)
        faces.append({
            "landmarks": landmarks,
            "box": ((box[0] * width + offset[0]) / full_w, (box[1] * height + offset[1]) / full_h,
                    (box[2] * width + offset[0]) / full_w, (box[3] * height + offset[1]) / full_h),
            "blend": {c.category_name: float(c.score) for c in blends[i]} if i < len(blends) else {},
        })
    return faces


def _detect_faces(rgb) -> List[Dict[str, Any]]:
    """Faces anywhere in the frame: the full frame first, then tiles to catch small / far-away faces."""
    height, width = rgb.shape[:2]
    faces = _faces_in(rgb)
    if TILED_DETECTION and width >= MIN_TILED_WIDTH:
        for x1, y1, x2, y2 in tile_windows(width, height):
            for f in _faces_in(rgb[y1:y2, x1:x2], (x1, y1), (width, height)):
                w, h = f["box"][2] - f["box"][0], f["box"][3] - f["box"][1]
                # face-shaped is judged in PIXELS: on a 16:9 frame an ordinary 70x90 px face is only 0.44 wide-to-tall in fractions
                plausible = h > 0 and 0.5 <= (w * width) / (h * height) <= 1.6 and w * h >= 0.0015
                if plausible and all(covered_share(f["box"], k["box"]) < 0.4 for k in faces):   # not a cut-off copy of a known face
                    faces.append(f)
    return faces


def _predict(images, imgsz: int) -> List[List[Dict[str, Any]]]:
    model = _state["yolo"]
    with _yolo_lock:
        results = model.predict(images, imgsz=imgsz, conf=YOLO_FLOOR_CONF, iou=0.6, classes=_state["yolo_classes"], verbose=False)
    names = model.names
    out = []
    for r in results:
        boxes = r.boxes
        coords, confs, classes = boxes.xyxyn.tolist(), boxes.conf.tolist(), boxes.cls.tolist()
        out.append([{"name": names[int(c)], "conf": float(p), "box": tuple(float(v) for v in b)} for b, p, c in zip(coords, confs, classes)])
    return out


def _detect_objects(img) -> List[Dict[str, Any]]:
    """Phones, people and other prohibited objects anywhere in the frame (full-frame pass + tile pass)."""
    height, width = img.shape[:2]
    full = select_detections(_predict([img], DETECT_IMGSZ)[0])
    if not (TILED_DETECTION and width >= MIN_TILED_WIDTH):
        return dedupe_detections(full)
    windows = tile_windows(width, height)
    tiled: List[Dict[str, Any]] = []
    for (x1, y1, x2, y2), found in zip(windows, _predict([img[y1:y2, x1:x2] for x1, y1, x2, y2 in windows], TILE_IMGSZ)):
        for d in select_detections(found):
            bx1, by1, bx2, by2 = d["box"]
            d = dict(d, box=((x1 + bx1 * (x2 - x1)) / width, (y1 + by1 * (y2 - y1)) / height, (x1 + bx2 * (x2 - x1)) / width, (y1 + by2 * (y2 - y1)) / height))
            tiled.append(d)
    return merge_passes(full, tiled)


# ---------------------------------------------------------------------------
# evidence image + HUD boxes
# ---------------------------------------------------------------------------
_COLORS = {"phone": (0, 0, 255), "person": (0, 140, 255), "object": (0, 215, 255), "face": (255, 200, 0)}   # BGR


def hud_boxes(dets: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for d in dets:
        x1, y1, x2, y2 = d["box"]
        kind = kind_of(d["name"])
        out.append({"kind": kind, "label": "Phone" if kind == "phone" else "Person" if kind == "person" else d["name"].title(),
                    "conf": round(d["conf"], 2), "x": round(x1, 4), "y": round(y1, 4), "w": round(x2 - x1, 4), "h": round(y2 - y1, 4)})
    return out


def _annotate(img, dets: Sequence[Dict[str, Any]], faces: Optional[Sequence[Dict[str, Any]]]) -> Optional[str]:
    """JPEG data URL of the frame with every detection boxed, so a reviewer sees exactly what the AI saw."""
    try:
        cv2 = _state["cv2"]
        out = img.copy()
        height, width = out.shape[:2]
        items = [("face", "", f["box"]) for f in faces or []] + [(kind_of(d["name"]), f"{d['name']} {int(d['conf'] * 100)}%", d["box"]) for d in dets]
        for kind, text, (x1, y1, x2, y2) in items:
            p1, p2 = (int(x1 * width), int(y1 * height)), (int(x2 * width), int(y2 * height))
            cv2.rectangle(out, p1, p2, _COLORS[kind], 2 if kind != "face" else 1)
            if text:
                cv2.putText(out, text, (p1[0], max(14, p1[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, _COLORS[kind], 2, cv2.LINE_AA)
        budget = int(settings.max_image_bytes * 0.9)
        for scale in (1.0, 0.75, 0.5):
            frame = out if scale == 1.0 else cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            for quality in (80, 65, 50):
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                if ok and len(buf) <= budget:
                    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    except Exception as exc:  # noqa: BLE001 - evidence is a nice-to-have; the finding itself must still be recorded
        log.warning("could not annotate evidence frame: %s", exc)
    return None


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def analyze_frame(data_url: str, *, detect_objects: bool = True) -> Dict[str, Any]:
    """Analyse one webcam frame. Never raises: problems come back as available=False / empty findings.

    Result: available, face_count, person_count, phone_count, findings [{code, detail}], boxes (HUD overlay, fractions of
    the frame) and evidence_image (annotated JPEG data URL, only when an object/person finding exists)."""
    result: Dict[str, Any] = {"available": False, "face_count": 0, "person_count": 0, "phone_count": 0,
                              "boxes": [], "findings": [], "evidence_image": None}
    if not settings.ai_proctoring_enabled:
        return result
    _ensure_loaded()
    if _state["error"] is not None:
        return result
    result["available"] = True
    try:
        img = _decode(data_url)
        if img is None:
            result["findings"].append({"code": "CAMERA_COVERED", "detail": "Frame could not be decoded"})
            return result
        cv2 = _state["cv2"]
        if max(img.shape[:2]) > MAX_ANALYSIS_SIDE:
            scale = MAX_ANALYSIS_SIDE / max(img.shape[:2])
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        height, width = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        reason = covered_reason(float(gray.mean()), float(gray.std()))
        if reason:
            result["findings"].append({"code": "CAMERA_COVERED", "detail": reason})
            return result

        faces: Optional[List[Dict[str, Any]]] = None
        if _state["landmarker"] is not None:
            try:
                faces = _detect_faces(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            except Exception as exc:  # noqa: BLE001 - one failing model must not blank the other
                log.warning("face analysis failed: %s", exc)
        dets: Optional[List[Dict[str, Any]]] = None
        if detect_objects and _state["yolo"] is not None:
            try:
                dets = _detect_objects(img)
            except Exception as exc:  # noqa: BLE001
                log.warning("object detection failed: %s", exc)

        fused = build_findings(faces, dets, aspect=width / height)
        result.update(face_count=fused["face_count"], person_count=fused["person_count"], phone_count=fused["phone_count"], findings=fused["findings"])
        result["boxes"] = hud_boxes(dets or [])
        if any(f["code"] in ("PHONE_DETECTED", "PROHIBITED_OBJECT", "MULTIPLE_PERSONS", "MULTIPLE_FACES") for f in fused["findings"]):
            result["evidence_image"] = _annotate(img, dets or [], faces)
    except Exception as exc:  # noqa: BLE001 - one bad frame must never break an exam
        log.warning("frame analysis failed: %s", exc)
        result["findings"] = []
    return result


if __name__ == "__main__":  # python -m app.proctoring download-models
    if len(sys.argv) > 1 and sys.argv[1] == "download-models":
        logging.basicConfig(level=logging.INFO)
        report = ensure_models()
        print(report)
        sys.exit(0 if all(v == "ok" for v in report.values()) else 1)
    print("usage: python -m app.proctoring download-models")
