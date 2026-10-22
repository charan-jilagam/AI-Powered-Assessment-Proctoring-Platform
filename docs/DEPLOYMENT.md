# Deployment & operations

## Environment variables
| Variable | Purpose | Default |
|---|---|---|
| `APP_ENV` | `production` disables /docs, enforces Alembic schema, HSTS | `development` |
| `DATABASE_URL` | SQLAlchemy URL (PostgreSQL in production) | — |
| `SECRET_KEY` | JWT signing key (long random; **required** in production) | — |
| `FRONTEND_URL` | Public URL, used in e-mailed links | `http://localhost:5173` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:5173` |
| `SUPERADMIN_EMAIL/PASSWORD/NAME` | Bootstrap the first super admin if none exists | — |
| `SMTP_HOST/PORT/USER/PASSWORD/STARTTLS`, `MAIL_FROM` | Outgoing mail; without SMTP messages stay in the outbox | — |
| `STAFF_TOKEN_MINUTES`, `CANDIDATE_TOKEN_MINUTES` | Token lifetimes | 480 / 720 |
| `MAX_FAILED_LOGINS`, `LOCKOUT_MINUTES` | Login lockout | 5 / 15 |
| `TRIAL_DAYS` | Default trial length | 14 |
| `AI_PROCTORING_ENABLED` | Allow AI analysis (needs `requirements-ai.txt`) | true |
| `EVIDENCE_DIR`, `MAX_IMAGE_BYTES` | Evidence storage and upload size cap | `backend/evidence`, 400000 |
| `REDIS_URL` | Shared rate limiting across workers | — |
| `RUN_SWEEPER`, `SWEEPER_INTERVAL_SECONDS` | Expired-attempt sweeper | true / 60 |
| `ALLOW_PRIVATE_WEBHOOKS` | Allow webhooks to private IPs (dev only) | false |
| `JUDGE0_URL` | Code execution backend | — |

## `manage.py` CLI
`create-superadmin --email [--name] [--password]` · `reset-password --email` · `seed-plans` · `sweep-expired` · `purge-evidence` · `demo-data [--email] [--password]`.

## Go-live checklist
1. Set strong `SECRET_KEY`, `POSTGRES_PASSWORD`, and change the Judge0 passwords in `judge0.conf`. **The original repository shipped a hard-coded secret key and DB password (`admin123`); rotate anything that was ever deployed with them.**
2. Serve over HTTPS; set `FRONTEND_URL` and `CORS_ORIGINS` to the real origin. Cameras and fullscreen require a secure context.
3. Configure SMTP and send a test invitation; check the super-admin outbox.
4. Run `alembic upgrade head` against your PostgreSQL and run the smoke flow (see below).
5. Back up the database and the evidence volume.
6. Build with `WITH_AI=true` only after testing AI proctoring with real cameras and tuning thresholds.

## Smoke flow
Sign in as super admin → create an organization → activate the admin from the link → create and publish a test → open `/t/CODE` in a private window → join, start, answer, submit → check Results and Review.
