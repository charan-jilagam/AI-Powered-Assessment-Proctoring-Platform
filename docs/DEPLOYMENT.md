# Deploying ORVEXA on Render (one service, MongoDB Atlas, Cloudinary, Razorpay)

ORVEXA ships as a single Docker image: the API serves the built React app, and the browser calls `/api/*` on the same origin (no CORS setup).

## 1. MongoDB Atlas
1. Cluster -> **Network Access**: allow Render. Render's outbound IPs change, so the simple choice is `0.0.0.0/0` (protected by your password) or use Atlas private networking.
2. **Database Access**: create a user with read/write on the `orvexa` database. Rotate any password that was ever shared in chat or committed.
3. Nothing to create by hand: Atlas creates the database lazily. On first start (or `python manage.py init-db`) the app creates the `orvexa` database, all collections and indexes, and seeds the plans.

## 2. Create the service
New -> **Blueprint** -> pick this repo (it reads `render.yaml`). Fill the prompts (see `.env.example` for what each means):

| Variable | Value |
|---|---|
| `MONGODB_URI` | your Atlas connection string |
| `JWT_SECRET` | 64+ random characters (`python -c "import secrets; print(secrets.token_urlsafe(64))"`) |
| `JWT_EXPIRE` | `7d` (staff sign-in lifetime) |
| `FRONTEND_URL`, `CORS_ORIGINS` | `https://<your-service>.onrender.com` (or your custom domain) |
| `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD` | first platform owner, created on first start |
| `CLOUDINARY_URL` | `cloudinary://API_KEY:API_SECRET@CLOUD_NAME` |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | from Razorpay Dashboard -> API keys (use `rzp_test_` first) |
| `RAZORPAY_WEBHOOK_SECRET` | the secret you set on the webhook below |
| `BREVO_API_KEY` **or** `RESEND_API_KEY` (or `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`) + `MAIL_FROM` | **required for e-mail verification** (see section 2b) |
| `CODE_RUNNER`, `JUDGE0_URL` | optional; see section 2c |

Use at least the **Starter** plan: free services sleep, which stops the background sweeper that closes expired exams. Keep `WEB_CONCURRENCY=1` unless you also set `REDIS_URL` (rate limits are per process).

## 2b. E-mail (needed for verification)
Staff must verify their e-mail before creating tests, and candidates enter a 6-digit e-mailed code before joining a test. Both are on by default, so **mail must work in production**.
- Render's free tier blocks SMTP ports. Use an HTTPS provider: create a free **Brevo** account (set `BREVO_API_KEY`) or **Resend** (`RESEND_API_KEY`), verify your sender address/domain there, and set `MAIL_FROM` to it (for example `ORVEXA <no-reply@yourdomain.com>`).
- Check **Platform console -> Overview**: a red banner appears while e-mail is not configured. `/api/health/ready` also reports it.
- If mail is down, you (the platform owner) can open an organization and press **Mark verified** next to an admin, or run `python manage.py verify-email --email admin@client.com`. Existing admins created before this release are shown as "Not verified" until they verify or you mark them.
- Not recommended, but possible: `STAFF_EMAIL_VERIFICATION=false` / `CANDIDATE_EMAIL_VERIFICATION=false` switch the checks off.
- When creating an organization, enter its **Allowed e-mail domains** (for example `sconexsoft.com`). Admins and team members must then use those domains; the optional candidate lock restricts test-takers too.

## 2c. Coding questions: which languages run
- **Built-in runner (default, no extra service):** candidates can use every language whose compiler is installed in the image. Choose the set at build time with the Docker build arg `LANGS` (`none`, `standard` = default, `full`). Render: set `LANGS` as an environment variable on a Docker service (build args are read from env vars of the same name). `/api/health/ready` -> `code_runner` lists what is actually available.
- **Judge0 (recommended for high-stakes exams):** set `JUDGE0_URL` (and `JUDGE0_EXTRA_HEADERS` for RapidAPI). The IDE then offers all Judge0 languages (about 60). `CODE_RUNNER=auto` picks Judge0 when `JUDGE0_URL` is set.
- The built-in runner executes candidate code as an unprivileged user with CPU/memory/process limits, but it is **not a full sandbox** (no network isolation). Use Judge0 on separate infrastructure when the exam matters.

## 3. Razorpay webhook
Dashboard -> Webhooks -> add `https://<your-service>/api/billing/webhook`, event `payment.captured` (and `payment.failed`), same secret as `RAZORPAY_WEBHOOK_SECRET`. The browser flow activates plans immediately; the webhook is the safety net if a tab closes mid-payment.

## 4. Verify
- `https://<your-service>/api/health` -> `{"status":"healthy","database":"connected",...}`
- Sign in as the super admin, create an organization, sign in as its admin, open **Plan & usage** and make a Razorpay test payment.
- From the Render shell: `python manage.py init-db` prints the database name and collections.

## Local development
```
cp .env.example backend/.env      # fill MONGODB_URI etc.
cd backend && pip install -r requirements.txt -r requirements-dev.txt && python -m pytest -q
uvicorn app.main:app --reload      # API on :8000
cd ../frontend && npm ci && npm run dev   # UI on :5173, /api proxied to :8000
```
Coding questions run on Judge0 (`JUDGE0_URL`) or, otherwise, on whatever compilers are installed on your machine (`CODE_RUNNER=local`). With no mail configured in development, verification links and codes are shown on screen instead of being e-mailed.
