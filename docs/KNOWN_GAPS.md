# Known gaps — be honest before going live

**Not implemented**
- Online billing/payments (Stripe/Razorpay), invoices, self-serve plan upgrades. The super admin assigns plans manually.
- SSO/SAML/OIDC, MFA for staff.
- Native mobile apps; secure-browser/lockdown software (this is a web proctor).
- Live human proctoring video streaming; recordings are periodic snapshots only.

**Implemented but not verified in this build environment**
- AI proctoring with real MediaPipe/YOLO models and real webcams. Only landmark math and debouncing are unit-tested; head-turn and gaze thresholds are untuned and need calibration on real footage.
- Real SMTP delivery (messages are verified to reach the outbox/SMTP client in tests).
- Real Judge0 execution (tests use a fake).
- PostgreSQL migrations and Docker image builds/compose (tested on SQLite; no Docker daemon was available).
- Browser behaviour beyond a Chromium smoke test: Safari/Firefox, mobile layouts, accessibility audit, load testing.

**Product notes**
- Candidate sessions rely on in-browser signals, which determined users can circumvent; treat risk scores as evidence for human review, not proof.
- Evidence images are stored on local disk/volume; use object storage for multi-node deployments.
- Rate limits are per process unless `REDIS_URL` is set.
