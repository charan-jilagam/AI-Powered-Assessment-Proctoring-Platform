# Architecture

**Stack:** FastAPI + PyMongo + Pydantic 2 (backend; `app/mongo.py` is a small ODM with a SQLAlchemy-like query API and integer ids from an atomic counter) · React 19 + Vite + react-router 7 (frontend) · MongoDB Atlas (tests use mongomock) · Razorpay · Cloudinary · Judge0 for code execution · optional MediaPipe/YOLO for AI proctoring.

## Tenancy
`Organization` → `Plan` (+ `limits_override`, `-1` = unlimited). Every tenant table carries `org_id`; routers resolve the org from the authenticated user (or API key) and never accept an org id from the client. Super admins have `org_id = null` and use `/superadmin/*`. Candidates are `User` rows unique per `(org_id, email)`.

## Authentication
JWT (HS256) with `sub`, `role`, `org`, `tv` (token version, bumped on password change/logout-all). Candidate tokens add `aid` (attempt) and `sn` (session nonce): joining again rotates the nonce and invalidates the earlier session. Passwords: bcrypt, ≥10 chars with a letter and a digit, lockout after repeated failures. API keys `pk_live_…` sent as `X-API-Key`, stored hashed. Reset/invite tokens are single-use and expire.

## Test code login
`POST /public/tests/{code}/join` validates status, window, access password, invite requirement and plan limits, upserts the candidate, creates or resumes the attempt, and returns a candidate token. Codes are 8 characters from an unambiguous alphabet and can be regenerated.

## Attempt lifecycle
`registered → in_progress → submitted | terminated`, or `voided` (admin) allowing a retake with `attempt_no + 1`. The answer key never leaves the server. The timer is server-side: `PUT /attempt/answers` and `POST /attempt/heartbeat` return remaining seconds; finalisation is atomic and idempotent; a background sweeper force-submits expired attempts.

## Proctoring
The client reports only a fixed set of event codes; the server owns severity, de-duplication (8 s), risk scoring and auto-termination (after N level-2 flags). AI findings come from `/attempt/analyze` (image → landmarks/objects), are debounced by streak length, and only count toward termination if the test enables `ai_can_terminate`. Evidence images are stored under `EVIDENCE_DIR` per org and purged by retention policy.

## Side effects
Committed-then-fired: e-mail (stored in an outbox; sent via SMTP when configured) and webhooks (HMAC-SHA256 signature header, up to 3 attempts, SSRF guard that blocks private addresses unless `ALLOW_PRIVATE_WEBHOOKS=true`).

## Frontend layout
`src/pages/{public,super,admin,candidate}`, shared UI in `src/ui`, design tokens (light/dark) in `src/styles`, API clients with separate staff/candidate tokens in `src/lib/api.js`. Routes are lazy-loaded.
