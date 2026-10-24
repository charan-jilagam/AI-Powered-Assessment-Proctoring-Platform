# Known gaps — be honest before going live

**Not implemented**
- Live pair-programming / interview room with audio-video, SQL-database and mock-API sandboxes, multi-file (React / Node) projects, Monaco-grade autocomplete (the editor is a plain textarea with line numbers and auto-indent).
- Keystroke-level code playback: reviewers can replay the sequence of *submitted* versions with changed lines highlighted, not every keystroke.
- Plagiarism matching against public web repositories. Similarity is checked only between candidates of the same test and is a screening aid, not proof.
- Vendor-specific ATS connectors (Greenhouse, Lever, Workday). Signed webhooks and API keys exist; the mapping is left to the receiver.
- Invoices/GST receipts, recurring auto-debit subscriptions, refunds and coupon codes. Razorpay one-time payments extend a plan by 1/3/6/12 months; the super admin can still assign plans manually.
- SSO/SAML/OIDC, MFA for staff.
- Native mobile apps; secure-browser/lockdown software (this is a web proctor).
- Live human proctoring video streaming; recordings are periodic snapshots only.

**Implemented but not verified in this build environment**
- AI proctoring with real MediaPipe/YOLO models and real webcams. Only landmark math and debouncing are unit-tested; head-turn and gaze thresholds are untuned and need calibration on real footage.
- Real SMTP delivery (messages are verified to reach the outbox/SMTP client in tests).
- Real Judge0 execution (tests use a fake).
- **MongoDB Atlas.** All 283 tests run against `mongomock`, an in-memory fake; the code was never run against a real MongoDB server from the build environment. Run `python manage.py init-db` once against Atlas to prove connectivity, indexes and seeding.
- **Razorpay.** Order creation, checkout-signature and webhook-signature logic are unit-tested with the HTTP call mocked. No real test payment was made, and the Checkout popup under the production CSP was not exercised.
- **Cloudinary.** Upload/read/delete are tested with a fake SDK; signed-URL reads of `authenticated` assets were not exercised against a real account.
- The root `Dockerfile` and `render.yaml` were not built or deployed (no Docker daemon here); the same app was run with `STATIC_DIR` set to confirm `/api/*`, SPA fallback and the CSP header.
- Browser behaviour beyond a Chromium smoke test: Safari/Firefox, mobile layouts, accessibility audit, load testing.

**Product notes**
- Candidate sessions rely on in-browser signals, which determined users can circumvent; treat risk scores as evidence for human review, not proof.
- Evidence images go to Cloudinary when configured; otherwise to local disk, which Render wipes on every deploy.
- MongoDB has no multi-document transactions here: a failure between two writes in one request can leave partial data (unique indexes and atomic status claims protect the important invariants).
- Rate limits are per process unless `REDIS_URL` is set.
