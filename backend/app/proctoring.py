"""Server-side AI proctoring: face presence, multiple faces, gaze, head pose, lip movement, prohibited objects.

Heavy libraries (OpenCV, MediaPipe, YOLO) are imported lazily on the first frame, never at import time, so the
API starts fast, tests run without them, and a deployment without the AI extras degrades to "AI unavailable"
instead of crashing. The decision logic (`interpret_landmarks`) is pure and unit-tested; the model plumbing is thin.
"""
import base64
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from app.config import settings

log = logging.getLogger("proctorai.ai")

_BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
FACE_MODEL_PATH = os.getenv("FACE_MODEL_PATH", os.path.join(_BACKEND_DIR, "face_landmarker.task"))
YOLO_MODEL_PATH = os.getenv("YOLO_MODEL_PATH", os.path.join(_BACKEND_DIR, "yolov8n.pt"))

# COCO classes treated as prohibited during an exam
PROHIBITED_OBJECTS = {
    "cell phone": "Mobile phone detected",
    "book": "Book detected",
    "laptop": "Second laptop detected",
    "tv": "Extra screen detected",
    "remote": "Remote / device detected",
    "keyboard": "Extra keyboard detected",
    "mouse": "Extra mouse detected",
}
OBJECT_CONFIDENCE = 0.5

# MediaPipe face-mesh landmark indices
LEFT_IRIS = [474, 475, 476, 477]
RIGHT_IRIS = [469, 470, 471, 472]
UPPER_LIP = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291]
LOWER_LIP = [146, 91, 181, 84, 17, 314, 405, 321, 375, 291]

GAZE_LEFT_THRESHOLD = 0.35
GAZE_RIGHT_THRESHOLD = 0.65
LIP_OPEN_THRESHOLD = 0.05
HEAD_YAW_LOW, HEAD_YAW_HIGH = 0.30, 0.70
DARK_FRAME_MEAN = 18.0

_lock = threading.Lock()
_state: Dict[str, Any] = {"loaded": False, "error": None, "landmarker": None, "yolo": None, "cv2": None, "np": None, "mp": None}


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def interpret_landmarks(landmarks) -> List[Dict[str, Any]]:
    """Turn one face's 478 landmarks (objects with .x/.y in 0..1) into proctoring findings."""
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

    try:  # head yaw: where the nose tip sits between the two cheeks
        span = (landmarks[454].x - landmarks[234].x) or 1e-4
        yaw = (landmarks[1].x - landmarks[234].x) / span
        if yaw < HEAD_YAW_LOW or yaw > HEAD_YAW_HIGH:
            findings.append({"code": "HEAD_TURNED", "detail": "Head turned to the " + ("left" if yaw < HEAD_YAW_LOW else "right")})
    except (IndexError, AttributeError, ZeroDivisionError):
        pass

    try:
        gap = abs(_mean(landmarks[i].y for i in LOWER_LIP) - _mean(landmarks[i].y for i in UPPER_LIP))
        if gap > LIP_OPEN_THRESHOLD:
            findings.append({"code": "LIP_MOVEMENT", "detail": "Mouth open - possible speaking"})
    except (IndexError, AttributeError):
        pass
    return findings


def _load() -> None:
    """Import and build the models once. Failure is remembered so we do not retry on every frame."""
    with _lock:
        if _state["loaded"]:
            return
        _state["loaded"] = True
        try:
            import cv2
            import mediapipe as mp
            import numpy as np
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            if not os.path.exists(FACE_MODEL_PATH):
                raise FileNotFoundError(f"face model missing: {FACE_MODEL_PATH}")
            options = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=FACE_MODEL_PATH),
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
                num_faces=3,
            )
            _state.update(landmarker=vision.FaceLandmarker.create_from_options(options), cv2=cv2, np=np, mp=mp)
            try:
                from ultralytics import YOLO
                if os.path.exists(YOLO_MODEL_PATH):
                    _state["yolo"] = YOLO(YOLO_MODEL_PATH)
                else:
                    log.warning("YOLO model not found at %s - object detection disabled", YOLO_MODEL_PATH)
            except Exception as exc:  # noqa: BLE001
                log.warning("Object detection disabled: %s", exc)
        except Exception as exc:  # noqa: BLE001 - missing libs, missing model, bad install
            _state["error"] = str(exc)
            log.warning("AI proctoring unavailable: %s", exc)


def status() -> Dict[str, Any]:
    if not settings.ai_proctoring_enabled:
        return {"available": False, "reason": "disabled by configuration"}
    if not _state["loaded"]:
        _load()
    return {
        "available": _state["error"] is None,
        "reason": _state["error"],
        "object_detection": _state["yolo"] is not None,
    }


def _decode(data_url: str):
    cv2, np = _state["cv2"], _state["np"]
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    raw = base64.b64decode(data_url)
    return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)


def analyze_frame(data_url: str, *, detect_objects: bool = True) -> Dict[str, Any]:
    """Analyse one webcam frame. Never raises: problems come back as available=False / empty findings."""
    result: Dict[str, Any] = {"available": False, "face_count": 0, "findings": []}
    if not settings.ai_proctoring_enabled:
        return result
    if not _state["loaded"]:
        _load()
    if _state["error"] is not None:
        return result
    result["available"] = True
    try:
        img = _decode(data_url)
        if img is None:
            result["findings"].append({"code": "CAMERA_COVERED", "detail": "Frame could not be decoded"})
            return result
        cv2, np, mp = _state["cv2"], _state["np"], _state["mp"]
        if float(np.mean(img)) < DARK_FRAME_MEAN:
            result["findings"].append({"code": "CAMERA_COVERED", "detail": "Camera view is black or covered"})
            return result

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        with _lock:  # the MediaPipe task object is not thread-safe
            detection = _state["landmarker"].detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        faces = detection.face_landmarks or []
        result["face_count"] = len(faces)
        if not faces:
            result["findings"].append({"code": "NO_FACE", "detail": "No face visible"})
        else:
            if len(faces) > 1:
                result["findings"].append({"code": "MULTIPLE_FACES", "detail": f"{len(faces)} faces visible"})
            result["findings"].extend(interpret_landmarks(faces[0]))

        if detect_objects and _state["yolo"] is not None:
            seen = set()
            for r in _state["yolo"](img, verbose=False):
                for box in r.boxes:
                    name = _state["yolo"].names[int(box.cls[0])]
                    if name in PROHIBITED_OBJECTS and float(box.conf[0]) >= OBJECT_CONFIDENCE and name not in seen:
                        seen.add(name)
                        result["findings"].append({"code": "PROHIBITED_OBJECT", "detail": PROHIBITED_OBJECTS[name]})
    except Exception as exc:  # noqa: BLE001 - one bad frame must never break an exam
        log.warning("frame analysis failed: %s", exc)
        result["findings"] = []
    return result
