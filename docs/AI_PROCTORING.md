# AI proctoring

Optional (needs the `WITH_AI=true` image, or `pip install -r backend/requirements-ai.txt`). Without it the platform runs normally and AI analysis is reported as "unavailable". Findings are **evidence for a human reviewer**: by default AI findings never end a test (`ai_can_terminate` is off).

## What it watches

The browser sends one frame every `analysis_interval_seconds` (default 3 s, minimum 2 s). The server analyses it, and only records a violation after the finding repeats, so a single odd frame is never a violation.

| Code | Raised when | Severity | Confirmed after |
|---|---|---|---|
| `PHONE_DETECTED` | a mobile phone anywhere in the frame (confidence ≥ 0.30) | serious | 2 sightings within 4 frames |
| `MULTIPLE_PERSONS` | two or more people, including someone turned away, at the edge of the frame, partly out of it, or too small/far for a face to be found | serious | 2 within 4 frames |
| `MULTIPLE_FACES` | two or more faces | serious | 2 within 4 frames |
| `PROHIBITED_OBJECT` | a book, second laptop, extra screen or remote | serious | 2 within 4 frames |
| `NO_FACE` | no face found (the detail says whether a body is still in view) | serious | 2 in a row |
| `CAMERA_COVERED` | black frame, or a flat featureless one (hand / paper over the lens) | serious | 2 in a row |
| `LOOKING_DOWN` | head tipped down ≥ 25° (≥ 14° if the eyes also look down): phone in the lap, notes on the desk | minor | 3 in a row |
| `LOOKING_AWAY` | eyes far left/right, or head tipped up ≥ 25° | minor | 3 in a row |
| `HEAD_TURNED` | head turned (nose position, or ≥ 35° from the 3-D pose) | minor | 3 in a row |
| `LIP_MOVEMENT` | mouth clearly open (jaw blendshape; falls back to lip gap relative to face height) | minor | 3 in a row |

**Competitive-exam mode** (Settings → Proctoring → *Competitive exam*, needs AI monitoring): candidates do rough work on paper, so `LOOKING_DOWN` is never recorded, and a face that disappears while the person's body is still in view (head bent over the desk) must last about 6 checks in a row (~18 s at the default interval) instead of 2 before `NO_FACE` is recorded. Phones, extra people, a covered camera, turning away or nobody being in view are judged exactly as before.

Phones and people use a *sliding window* ("2 of the last 4 frames") rather than "2 in a row", because a phone half-hidden by a hand drops out of every other frame. Voice is detected in the browser from the microphone (adaptive to the room's noise level) when the test requires a microphone.

## The whole camera is analysed, never a region

- The browser asks the camera for its **wide 16:9 view** (1280×720 ideal) and sends the **entire frame** at 960 px wide. The preview shows the same uncropped frame (`object-fit: contain`), with corner marks on the true edges.
- On the server nothing is masked or cropped. Objects and people are searched on the full frame **and** on four overlapping tiles that together cover the frame edge to edge (a ~1.6× zoom, to find a small phone on the desk or a person far in the background). Faces are searched the same way.
- People are counted by fusing YOLO `person` boxes with face detections, so a person with no visible face still counts, and a face is never counted twice.
- When a phone or extra person is found, the stored evidence image is the frame **with every detection boxed**. The candidate's preview shows the same boxes live, so they can see and fix what was flagged.

## Setup

| Setting | Default | Meaning |
|---|---|---|
| `AI_PROCTORING_ENABLED` | `true` | master switch |
| `AI_MODEL_AUTODOWNLOAD` | `true` | download missing model files on first use (never done under `APP_ENV=test`) |
| `FACE_MODEL_PATH` / `FACE_MODEL_URL` | `backend/face_landmarker.task` / Google's MediaPipe URL | face model |
| `YOLO_MODEL_PATH` | `backend/yolov8s.pt` (an existing `yolov8n.pt` is also accepted) | any COCO YOLOv8 / YOLO11 weights |
| `AI_TILED_DETECTION` | `true` | the tile pass; turn **off** on small hosts (see cost) |
| `AI_PHONE_CONFIDENCE` | `0.30` | lower = more phones found, more false alarms |
| `AI_PERSON_CONFIDENCE` / `AI_OBJECT_CONFIDENCE` | `0.45` / `0.50` | |
| `AI_DETECT_IMGSZ` / `AI_TILE_IMGSZ` | `640` | keep at 640 (see below) |
| `AI_PITCH_DOWN_DEG` / `AI_YAW_TURN_DEG` | `25` / `35` | head-pose limits |

With `WITH_AI=true` the Dockerfile downloads both models at build time and the app also loads them in the background at start-up. `GET /health/ready` reports whether AI loaded. The two models load independently: if one cannot be fetched, the other still works (and `status()` says which is missing). A failed load is retried every 5 minutes.

`python -m app.proctoring download-models` fetches the models by hand.

## Cost (measured)

On a 2-vCPU CPU-only machine, one 960×540 frame with `yolov8s`: **~150 ms** without the tile pass, **~700 ms** with it (decode + detection + boxing; the face model was not part of this measurement). At the default 3 s interval that is roughly 5 % / 25 % of that machine's time per concurrently-testing candidate. Size the host for your concurrency, or set `AI_TILED_DETECTION=false` / use `yolov8n.pt` to cut it. Only the tile pass can find small, far-away phones, so turning it off trades recall for CPU.

`AI_DETECT_IMGSZ` stays at 640 on purpose: YOLOv8 was trained at that scale, and running the whole frame larger made a close-up person *less* recognisable (measured 0.91 → 0.39 confidence at 960). Small objects are handled by the tiles instead.

## What it does not do (yet)

- **No calibration on real exam footage.** Thresholds are sensible starting points, not tuned values. Record a few real sessions and adjust the table above.
- **COCO has no class for earbuds, headphones, smartwatches, notes held in a hand or a phone with the screen off.** Those need a custom-trained model (point `YOLO_MODEL_PATH` at it; the class names must still include `person` and `cell phone`).
- **No identity verification** (matching the candidate to an ID photo). It needs a face-recognition model and a privacy/consent decision, so it was left out.
- **No liveness check:** a photo or video held up to the camera is not detected.
- **A second screen or device outside the camera's view is invisible to any camera-based check.**
