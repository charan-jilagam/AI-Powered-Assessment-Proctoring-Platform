# ORVEXA — Assess Smarter. Trust Every Result.

Multi-tenant assessment & AI proctoring platform. Stack: FastAPI + MongoDB (Atlas) · React · Razorpay (INR plans) · Cloudinary (evidence) · deployable on Render as one service.

A SaaS for running proctored online tests. The **platform owner** (super admin) onboards client **organizations**; each organization's **admins** build tests and share an **8-character test code**; **candidates** sign in with only that code, take the test in a locked-down exam room, and admins review scored results with proctoring evidence.

## Roles

| Role | Created by | Can do |
|---|---|---|
| **Super admin** | `manage.py create-superadmin` / `SUPERADMIN_*` env | Create/suspend organizations, assign plans and per-org limit overrides, create org admins (activation link or temp password), manage plans, platform admins, demo requests, e-mail outbox, platform audit log |
| **Admin** (client / subscriber) | Super admin | Everything inside their org: tests, question bank, invites, results, review, team, branding, API keys, webhooks, usage |
| **Reviewer** | Org admin | Read results and evidence, review attempts, no test/team changes |
| **Candidate** | Self, on joining with a code | Take the test; no password, no account |

Data is isolated per organization on every query; see `backend/tests/test_tenancy.py` (44 cross-org probes).

## Feature overview

**Platform (super admin):** organizations with trial/active/suspended/cancelled status · plans (seats, active tests, candidates/month, AI proctoring, coding, API, webhooks, evidence retention) with per-org overrides · platform admins · demo-request leads · e-mail outbox · audit log · platform usage dashboard.

**Test authoring (admin):** single / multiple / true-false / short-text questions · sections · negative marking · per-question marks and difficulty · shuffle questions and options · reusable question bank with tags · CSV import · built-in 36-question starter library (Python, JavaScript, SQL, DSA, CS fundamentals, aptitude) · coding problems with hidden test cases, added by hand **or imported from JSON** (format shown in the app) · 30+ languages (Judge0 or the built-in runner) · two ready-made trial tests per organization · e-mail verification for admins and candidates · per-organization allowed e-mail domains · in-app user guides at `/guide` · duplicate test · publish/close/archive · regenerate code.

**Access control:** 8-character code and share link `/t/{code}` · optional access password · invite-only mode with per-candidate links · start/end window · max attempts · custom candidate fields · one live session per attempt (a second join ends the first).

**Exam room:** server-authoritative timer · autosave with offline backup · resume after refresh/crash · question navigator, flag-for-review · fullscreen lock · live admin messages · auto-submit on time-out (also when the browser is gone, via the sweeper).

**Proctoring:** tab switch, window blur, fullscreen exit, copy/paste, right-click, shortcuts, devtools, resize, camera/mic loss, voice · webcam snapshots · AI checks (no face, multiple faces, looking away, head turned, lip movement, prohibited objects) with debouncing · severity levels, risk score, optional auto-termination · ID capture · consent.

**Candidate experience:** light / dark / match-system theme (light by default) · clear on-screen proctoring alerts (minor notices fade, serious warnings show a strike counter and must be acknowledged) · live camera tile with status · code editor with line numbers, auto-indent and tab support.

**Review & results:** printable professional **PDF report** per attempt (summary, integrity timeline, evidence, code similarity, section scores, answers, reviewer sign-off) · code-submission history replay · **code similarity screening** between candidates of a test · per-test results table, ranking, CSV export · attempt report with answers, timeline and evidence images · confirm/dismiss violations · cleared/suspicious/disqualified decisions with notes · void & allow retake · extend time · live monitor · analytics (score distribution, per-question difficulty) · candidate result page (configurable).

**Integrations & ops:** API keys (`X-API-Key`) · HMAC-signed webhooks with SSRF guard · branded candidate pages · e-mail via SMTP · data erasure · evidence retention purge · health endpoints · Razorpay self-serve plans · Cloudinary evidence storage · global search and notifications · light/dark themes · Docker + `render.yaml`.

## Quick start (local)

You need a MongoDB: a free Atlas cluster or `mongod` on localhost.

```bash
cp .env.example backend/.env          # set MONGODB_URI, JWT_SECRET, SUPERADMIN_*
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py init-db                                        # creates database "orvexa", collections, indexes, plans
python manage.py create-superadmin --email you@example.com      # prompts for a password
python manage.py demo-data --password 'ChangeMe12345'           # optional demo org + test, prints the test code
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend && npm install && npm run dev                       # http://localhost:5173, proxies /api -> :8000
```

## Production (Render)

`render.yaml` + the root `Dockerfile` deploy API and UI as one service. Step-by-step (Atlas network access, env vars, Razorpay webhook): `docs/DEPLOYMENT.md`.

## Tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest -q     # 342 tests (MongoDB faked with mongomock)
cd frontend && npm run lint && npm run build
```

## Documentation

- `docs/ARCHITECTURE.md` — data model, auth, attempt lifecycle, proctoring pipeline
- `docs/DEPLOYMENT.md` — environment variables, `manage.py` CLI, operations checklist
- `docs/KNOWN_GAPS.md` — what is not built or not verified. **Read this before going live.**
- Interactive API reference at `/docs` (disabled when `APP_ENV=production`)

## Honest status

The test suite and browser smoke runs use an in-memory MongoDB fake; real Atlas, Razorpay, Cloudinary and the Docker/Render build are **not verified** from the build environment. See `docs/KNOWN_GAPS.md` before going live.
