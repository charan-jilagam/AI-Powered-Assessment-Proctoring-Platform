# ProctorAI — multi-tenant assessment & proctoring platform

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

**Test authoring (admin):** single / multiple / true-false / short-text questions · sections · negative marking · per-question marks and difficulty · shuffle questions and options · reusable question bank with tags · CSV import · coding problems (Judge0) with hidden test cases · duplicate test · publish/close/archive · regenerate code.

**Access control:** 8-character code and share link `/t/{code}` · optional access password · invite-only mode with per-candidate links · start/end window · max attempts · custom candidate fields · one live session per attempt (a second join ends the first).

**Exam room:** server-authoritative timer · autosave with offline backup · resume after refresh/crash · question navigator, flag-for-review · fullscreen lock · live admin messages · auto-submit on time-out (also when the browser is gone, via the sweeper).

**Proctoring:** tab switch, window blur, fullscreen exit, copy/paste, right-click, shortcuts, devtools, resize, camera/mic loss, voice · webcam snapshots · AI checks (no face, multiple faces, looking away, head turned, lip movement, prohibited objects) with debouncing · severity levels, risk score, optional auto-termination · ID capture · consent.

**Review & results:** per-test results table, ranking, CSV export · attempt report with answers, timeline and evidence images · confirm/dismiss violations · cleared/suspicious/disqualified decisions with notes · void & allow retake · extend time · live monitor · analytics (score distribution, per-question difficulty) · candidate result page (configurable).

**Integrations & ops:** API keys (`X-API-Key`) · HMAC-signed webhooks with SSRF guard · branded candidate pages · e-mail via SMTP · data erasure · evidence retention purge · health endpoints · Alembic migrations · Docker/compose · CI workflow.

## Quick start (local, SQLite)

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./dev.db SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
python manage.py create-superadmin --email you@example.com      # prompts for a password
python manage.py demo-data --password 'ChangeMe12345'           # optional demo org + test, prints the test code
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend && npm install && npm run dev                       # http://localhost:5173, proxies /api → :8000
```

Open `http://localhost:5173`: sign in at `/login`, or enter the test code on the home page.

## Production (Docker)

```bash
cp .env.example .env     # set POSTGRES_PASSWORD, SECRET_KEY, FRONTEND_URL, SUPERADMIN_*, SMTP_*
docker compose up -d --build
```

Production uses PostgreSQL and Alembic (`alembic upgrade head` runs in the backend container). Put it behind HTTPS (TLS terminator/reverse proxy). Set `WITH_AI=true` at build time to include the AI proctoring libraries. See `docs/DEPLOYMENT.md`.

## Tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest -q     # 260 tests
cd frontend && npm run lint && npm run build
```

## Documentation

- `docs/ARCHITECTURE.md` — data model, auth, attempt lifecycle, proctoring pipeline
- `docs/DEPLOYMENT.md` — environment variables, `manage.py` CLI, operations checklist
- `docs/KNOWN_GAPS.md` — what is not built or not verified. **Read this before going live.**
- Interactive API reference at `/docs` (disabled when `APP_ENV=production`)

## Honest status

Verified by automated tests and a browser smoke test: tenancy isolation, roles, plan limits, candidate lifecycle, server-side proctoring rules, results/review, webhooks, mail outbox, and the main staff and candidate screens. **Not verified here:** real AI models on real webcams, real SMTP delivery, a real Judge0 instance, PostgreSQL migrations, the Docker build. **Not implemented:** online payments/billing (plans are assigned manually by the super admin). Details in `docs/KNOWN_GAPS.md`.
