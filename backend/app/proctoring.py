import cv2
import numpy as np
import base64
import os
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from ultralytics import YOLO

# Path to the downloaded model
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "face_landmarker.task")

# Set up the face landmarker once (reused across frames)
base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
options = vision.FaceLandmarkerOptions(
    base_options=base_options,
    output_face_blendshapes=False,
    output_facial_transformation_matrixes=False,
    num_faces=2,  # detect up to 2 faces to catch "multiple faces" violation
)
landmarker = vision.FaceLandmarker.create_from_options(options)
# Load YOLOv8 model for object detection
yolo_model = YOLO("yolov8n.pt")

# Objects we consider prohibited during an exam (COCO dataset class names)
PROHIBITED_OBJECTS = {
    "cell phone": "Mobile phone detected",
    "book": "Book detected",
    "laptop": "Secondary laptop detected",
    "tv": "TV/monitor detected",
    "remote": "Remote/device detected",
    "keyboard": "Extra keyboard detected",
    "mouse": "Extra mouse detected",
}

# Landmark indices
LEFT_IRIS = [474, 475, 476, 477]
RIGHT_IRIS = [469, 470, 471, 472]
UPPER_LIP = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291]
LOWER_LIP = [146, 91, 181, 84, 17, 314, 405, 321, 375, 291]
# Track previous lip distance to detect movement over time
_previous_lip_distance = {"value": None}

def decode_image(base64_string: str):
    try:
        if "," in base64_string:
            base64_string = base64_string.split(",")[1]
        img_bytes = base64.b64decode(base64_string)
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"Image decode error: {e}")
        return None


def analyze_frame(base64_image: str) -> dict:
    results = {
        "face_detected": False,
        "multiple_faces": False,
        "looking_away": False,
        "lip_moving": False,
        "face_count": 0,
        "gaze_direction": "unknown",
        "warnings": []
    }

    img = decode_image(base64_image)
    if img is None:
        results["warnings"].append("Could not process image")
        return results

    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_img)

    detection = landmarker.detect(mp_image)

    if not detection.face_landmarks:
        results["warnings"].append("No face detected")
        return results

    face_count = len(detection.face_landmarks)
    results["face_count"] = face_count
    results["face_detected"] = True

    if face_count > 1:
        results["multiple_faces"] = True
        results["warnings"].append(f"Multiple faces detected ({face_count})")

    # Use the first face for gaze + lip analysis
    landmarks = detection.face_landmarks[0]

  # ---- GAZE TRACKING (iris position relative to eye corners) ----
    try:
        # LEFT EYE: corners are landmark 33 (outer) and 133 (inner)
        left_eye_left = landmarks[33].x
        left_eye_right = landmarks[133].x
        left_iris_x = np.mean([landmarks[i].x for i in LEFT_IRIS])

        # RIGHT EYE: corners are landmark 362 (inner) and 263 (outer)
        right_eye_left = landmarks[362].x
        right_eye_right = landmarks[263].x
        right_iris_x = np.mean([landmarks[i].x for i in RIGHT_IRIS])

        # Ratio of iris position within each eye (0 = far left, 1 = far right)
        left_width = left_eye_right - left_eye_left
        right_width = right_eye_right - right_eye_left

        left_ratio = (left_iris_x - left_eye_left) / (left_width + 0.0001)
        right_ratio = (right_iris_x - right_eye_left) / (right_width + 0.0001)
        avg_ratio = (left_ratio + right_ratio) / 2

        # Tighter thresholds catch eye movement, not just head turn
        if avg_ratio < 0.35:
            results["gaze_direction"] = "left"
            results["looking_away"] = True
            results["warnings"].append("Eyes looking away (left)")
        elif avg_ratio > 0.65:
            results["gaze_direction"] = "right"
            results["looking_away"] = True
            results["warnings"].append("Eyes looking away (right)")
        else:
            results["gaze_direction"] = "center"
    except Exception as e:
        print(f"Gaze tracking error: {e}")

    # ---- LIP MOVEMENT DETECTION ----
    try:
        upper_lip_y = np.mean([landmarks[i].y for i in UPPER_LIP])
        lower_lip_y = np.mean([landmarks[i].y for i in LOWER_LIP])
        lip_distance = abs(lower_lip_y - upper_lip_y)

        # Only flag if mouth is clearly open (talking with visible mouth movement)
        if lip_distance > 0.05:  # Adjusted threshold for more sensitivity
            results["lip_moving"] = True
            results["warnings"].append("Lip movement detected - possible speaking")
    except Exception as e:
        print(f"Lip detection error: {e}")
       # ---- OBJECT DETECTION (YOLOv8) ----
    try:
        if yolo_model is None:
            return results
        yolo_results = yolo_model(img, verbose=False)
        for r in yolo_results:
            for box in r.boxes:
                class_id = int(box.cls[0])
                confidence = float(box.conf[0])
                class_name = yolo_model.names[class_id]

                # Only flag prohibited objects with decent confidence
                if class_name in PROHIBITED_OBJECTS and confidence > 0.4:
                    warning = PROHIBITED_OBJECTS[class_name]
                    if warning not in results["warnings"]:
                        results["warnings"].append(warning)
    except Exception as e:
        print(f"Object detection error: {e}")

    return results