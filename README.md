# ProctorAI

**AI-Powered Assessment & Proctoring Platform**

A full-stack technical assessment platform that lets organisations run secure online exams while automatically detecting cheating through two independent layers — browser lockdown and real-time AI monitoring of the candidate's webcam and microphone.

Built with React, FastAPI, and PostgreSQL. Fully containerized, tested, and hardened for production use.

---

## What it does

Companies screening technical candidates need to run exams online, but can't have a human watching every candidate's webcam. ProctorAI solves this: it runs the exam, scores it securely on the server, and simultaneously monitors the candidate for cheating — flagging violations for human review.

If a candidate switches tabs, exits fullscreen, looks away from the screen, has another person appear behind them, pulls out a phone, or starts talking, the system detects it, warns them, and records it in an auditable trail.

---

## Features

### Assessment engine
- Question bank with randomised selection — each candidate receives a different subset of questions
- Answer options shuffled per question, with text-based scoring so shuffling can't break grading
- Server-side scoring (the client is never trusted with grading)
- Server-locked exam sessions: refreshing won't re-roll questions or pause the timer
- Countdown timer with automatic submission when time expires
- Duplicate-submission protection
- **Coding questions**: candidates write and run code in the exam (Python, C++, C, Java, JavaScript); it is executed in a [Judge0](https://github.com/judge0/judge0) sandbox and scored against hidden test cases (see [Coding questions](#coding-questions-judge0))

### Proctoring — Layer 1: Browser security
- Tab-switch detection via the Visibility API
- Fullscreen enforcement with exit detection
- Copy, paste, cut, and right-click blocking
- Keyboard shortcut blocking (Alt, Meta, F11/F12, DevTools)
- Graded violation levels: Level 1 (minor, dismissible warning) and Level 2 (serious, blocking modal)
- Three Level 2 violations automatically terminate the exam, enforced server-side

### Proctoring — Layer 2: AI monitoring
- **Face detection** — verifies a candidate is present; flags multiple faces
- **Gaze tracking** — detects when the candidate looks away from the screen
- **Lip movement detection** — flags possible speaking
- **Object detection** — identifies phones, books, laptops, and other prohibited items
- **Audio monitoring** — voice-frequency analysis to detect talking, tuned to ignore ambient noise

Frames are captured every 1.5 seconds, sent to the backend, analysed, and any violation is logged and surfaced as a live alert.

### Admin console
- Create exams manually or by uploading a CSV question bank
- Ranked candidate results with scores, percentages, and integrity flags
- Detailed violation reports grouped per candidate, with severity badges
- Student management: reset attempts, delete results, remove accounts
- Structured audit log of logins, submissions, terminations, and admin actions

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, Vite, React Router |
| Backend | FastAPI (Python 3.12), Uvicorn |
| Database | PostgreSQL 16, SQLAlchemy ORM |
| Auth | JWT tokens, bcrypt password hashing |
| Computer vision | MediaPipe (face, gaze, lips), YOLOv8 (objects) |
| Audio | Web Audio API — voice-band frequency analysis |
| Code execution | Judge0 CE (optional, sandboxed, via Docker) |
| Infrastructure | Docker, Docker Compose |
| Testing | pytest |

---

## Security & production hardening

This project was deliberately taken beyond "working prototype":

- Secrets (database credentials, JWT signing key) loaded from environment variables, never committed
- Admin accounts cannot be self-registered — created only by existing admins
- Exam sessions locked server-side, preventing question re-rolling and timer pausing
- Submissions validated against the candidate's assigned question set
- Login rate-limited to block brute-force attempts
- Authentication errors deliberately generic ("Invalid email or password") to avoid revealing which field was wrong
- AI analysis is failure-isolated: a bad frame can never crash or interrupt an exam
- Structured audit logging of all security-relevant events

---

## Getting started

### Prerequisites
- Docker Desktop (for the containerised setup), **or**
- Python 3.12+, Node.js 20+, and PostgreSQL 16 (for local development)

### 1. Clone the repository

```bash
git clone https://github.com/gowthamcgowda22-source/AI-Powered-Assessment-Proctoring-Platform.git
cd AI-Powered-Assessment-Proctoring-Platform
```

### 2. Download the AI model files

These are excluded from the repository due to size. Place both in the `backend/` directory:

```bash
# MediaPipe face landmark model
curl -o backend/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task

# YOLOv8 object detection model
curl -o backend/yolov8n.pt https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.pt
```

### 3. Create the environment file

Create `backend/.env`:

```
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/proctoring_db
SECRET_KEY=generate-a-long-random-string-here
```

Generate a secure key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 4a. Run with Docker (recommended)

```bash
docker compose up -d
docker compose exec backend python create_tables.py
docker compose exec backend python create_admin.py
```

Open **http://localhost:5173**

### 4b. Run locally

**Backend:**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
python create_tables.py
uvicorn app.main:app --reload
```

**Frontend** (in a second terminal):
```bash
cd frontend
npm install
npm run dev
```

> **Note:** Docker and the local setup use the same ports. Run one or the other, never both simultaneously.

---

## Running the tests

```bash
cd backend
pytest -v
```

The suite covers password hashing and salting, JWT generation, signup and login flows, access control on protected routes, and exam scoring — including a test verifying that scoring remains correct when answer options are shuffled.

Coding questions are covered by `tests/test_coding.py` (authoring, access control, hidden-test secrecy, scoring, cleanup) and `tests/test_judge0_client.py` (the Judge0 client). They use a fake Judge0, so no Docker is needed.

---

## Coding questions (Judge0)

Exams can contain **coding problems** next to (or instead of) multiple-choice questions. Candidates get an editor
with sample tests, a **Run** button (sample tests or their own input) and a **Submit solution** button (all tests,
including hidden ones). Code runs inside [Judge0](https://github.com/judge0/judge0), a sandboxed execution engine.

**How it fits together**

```
React exam page ──► FastAPI backend ──► Judge0 (judge0-server + judge0-worker, Docker, internal network only)
                        │
                        └── PostgreSQL: coding_problems, coding_test_cases, code_submissions
```

- Judge0 is **not** published to the host; only the backend talks to it. Candidates never see hidden test inputs
  or expected outputs, only pass/fail per hidden test.
- Scoring is server-side. Each problem has a point value; the candidate's **best** submission counts, with partial
  credit rounded down (full points need every test to pass). Coding points are added to the normal exam score, so
  results, rankings and percentages keep working unchanged.
- Code can only be run during an active, in-time exam session, and executions are rate-limited per candidate
  (`CODE_EXEC_PER_MINUTE`, default 15).
- Admins can review every submitted solution (**Dashboard → Coding → Code submissions**) alongside the proctoring
  violations.

**Start Judge0** (optional; the rest of the app works without it, coding questions then report that the execution
service is unavailable):

```bash
# 1. change the two passwords in judge0.conf
# 2. start everything including Judge0
docker compose --profile judge0 up -d
```

Judge0 needs `privileged` containers and, for the 1.13.x series, a **cgroup v1** host. On hosts that default to
cgroup v2 (recent Ubuntu, Docker Desktop/WSL2) it may fail to start; Judge0's release notes recommend adding
`systemd.unified_cgroup_hierarchy=0` to the kernel command line on Ubuntu 22.04. Judge0 is tested on Linux only.
More judging capacity: `docker compose --profile judge0 up -d --scale judge0-worker=3`.

**Adding problems**

- *When creating an exam* (**Create Exam → Coding Problems**), or later from the exam's **Coding** button on the
  dashboard: fill in the form, or **import from JSON**.
- A ready-to-use example with three problems is in `backend/sample_coding_problems.json`. Format:

```json
{
  "problems": [
    {
      "title": "Sum of Two Numbers",
      "statement": "Read two integers from one line and print their sum.",
      "input_format": "optional", "output_format": "optional", "constraints": "optional",
      "points": 10, "time_limit_seconds": 2, "memory_limit_mb": 256,
      "test_cases": [
        { "input_data": "3 4\n", "expected_output": "7\n", "is_sample": true },
        { "input_data": "0 0\n", "expected_output": "0\n", "is_sample": false }
      ]
    }
  ]
}
```

Limits: 0.5-15 s time, 16-256 MB memory, up to 50 test cases per problem. Output is compared ignoring trailing
spaces on a line and trailing blank lines; anything else must match exactly.

**Configuration** (backend environment variables)

| Variable | Default | Meaning |
|----------|---------|---------|
| `JUDGE0_URL` | `http://judge0-server:2358` | Where the backend reaches Judge0 (set in `docker-compose.yml`) |
| `JUDGE0_AUTH_TOKEN` / `JUDGE0_AUTH_HEADER` | empty / `X-Auth-Token` | Only if you enable `AUTHN_TOKEN` in `judge0.conf` |
| `CODE_EXEC_PER_MINUTE` | `15` | Run/Submit calls allowed per candidate per minute |

When running the backend locally (not in Docker), publish Judge0's port yourself and point `JUDGE0_URL` at it
(for example `http://localhost:2358`).

**Notes and limits**

- Language ids are Judge0 CE 1.13.x ids, listed in `backend/app/judge0.py` (`SUPPORTED_LANGUAGES`). Check them
  against `GET /languages` on your Judge0 if you upgrade, and add more there if you like.
- Each test case is a separate Judge0 run (a compiled language compiles once per test), so judging a problem with
  many tests takes a few seconds; add workers if many candidates submit at once.
- The code editor is a plain textarea (no extra dependencies). Copy/paste stays blocked by the proctoring layer.
- Keyboard layouts that type characters with AltGr (for example `{` or `[` on some European layouts) trip the
  existing "Alt key" rule in `ExamPage.jsx`; relax it there if you need to support those layouts.

---

## Known limitations

Deployed AI that affects people's opportunities deserves honesty about its accuracy. These limitations are inherent to the problem, not implementation defects — commercial proctoring systems face the same constraints:

- **Gaze tracking** works well but is not perfectly accurate. True eye-tracking varies with camera angle, lighting, and individual eye shape; high precision would require per-user calibration.
- **Audio detection** distinguishes speech from ambient noise using voice-band frequency analysis, but a whisper and background noise occupy overlapping ranges. Thresholds are a tuned compromise.
- **Lip movement detection** flags an open or moving mouth, but cannot confirm speech from a single frame.

For this reason, AI-detected flags are presented to administrators as **advisory signals for human review**, not as automatic proof of misconduct. The admin interface states this explicitly. Only browser-security violations — which are deterministic — trigger automatic exam termination.

---

## Deployment notes

The backend loads PyTorch, MediaPipe, and YOLOv8, requiring roughly **2 GB of RAM**. Free hosting tiers typically provide 256–512 MB, which is insufficient. Production deployment requires a server with adequate memory.

---

## Licence

MIT