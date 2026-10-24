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

Use at least the **Starter** plan: free services sleep, which stops the background sweeper that closes expired exams. Keep `WEB_CONCURRENCY=1` unless you also set `REDIS_URL` (rate limits are per process).

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
Coding questions need Judge0 (`JUDGE0_URL`) or, for development only, `CODE_RUNNER=local`.
