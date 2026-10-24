"""ORVEXA API - multi-tenant assessment & proctoring platform."""
import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import attempt_service, coding, proctoring
from app.config import settings
from app import database
from app.mongo import IntegrityError
from app.database import SessionLocal
from app.limiter import limiter
from app.routers import auth_routes, bank, billing, candidate, invites, org, public, results, superadmin, tests
from app.seed import bootstrap_super_admin, seed_plans

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("orvexa")

VERSION = "2.0.0"


async def _sweeper() -> None:
    """Force-submits attempts whose time ran out even if the candidate's browser is gone."""
    while True:
        await asyncio.sleep(settings.sweeper_interval_seconds)
        try:
            def run() -> int:
                db = SessionLocal()
                try:
                    return attempt_service.sweep_expired(db)
                finally:
                    db.close()

            swept = await asyncio.to_thread(run)
            if swept:
                log.info("sweeper finalised %s expired attempt(s)", swept)
        except Exception:  # noqa: BLE001 - the loop must survive anything
            log.exception("sweeper iteration failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # MongoDB creates databases and collections lazily; this makes sure the indexes (and so the database) exist.
    try:
        database.init_db()
    except Exception:  # noqa: BLE001
        log.exception("could not initialise MongoDB (check MONGODB_URI and Atlas network access)")
    db = SessionLocal()
    try:
        seed_plans(db)
        bootstrap_super_admin(db)
    except Exception:  # noqa: BLE001
        log.exception("startup seeding failed (is MongoDB reachable?)")
    finally:
        db.close()
    task = asyncio.create_task(_sweeper()) if settings.run_sweeper else None
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="ORVEXA API",
    description="Multi-tenant online assessment and AI proctoring platform.",
    version=VERSION,
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,           # bearer tokens in headers, never cookies
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)


STATIC = settings.static_dir if settings.static_dir and os.path.isfile(os.path.join(settings.static_dir, "index.html")) else ""
CSP = ("default-src 'self'; script-src 'self' https://checkout.razorpay.com; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob: https:; media-src 'self' blob:; font-src 'self' data:; "
       "connect-src 'self' https://api.razorpay.com https://lumberjack.razorpay.com https://checkout.razorpay.com; "
       "frame-src https://api.razorpay.com https://checkout.razorpay.com; worker-src 'self' blob:; object-src 'none'; "
       "base-uri 'self'; form-action 'self' https://api.razorpay.com; frame-ancestors 'none'")


@app.middleware("http")
async def request_context(request: Request, call_next):
    if STATIC and (request.scope["path"] == "/api" or request.scope["path"].startswith("/api/")):
        request.scope["path"] = request.scope["path"][4:] or "/"      # the frontend calls /api/*; the routers live at /*
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if STATIC:
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), fullscreen=(self)"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path not in ("/health", "/health/live", "/health/ready"):
        log.info("%s %s -> %s %.0fms rid=%s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - started) * 1000, request_id)
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    return JSONResponse(
        {"detail": exc.detail, "code": getattr(exc, "code", "error")},
        status_code=exc.status_code, headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    problems = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
        problems.append(f"{where}: {err.get('msg', 'invalid')}" if where else err.get("msg", "invalid"))
    return JSONResponse({"detail": "; ".join(problems) or "Invalid request", "code": "validation_error"}, status_code=422)


@app.exception_handler(RateLimitExceeded)
async def rate_limited(_: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": "Too many requests. Please wait a minute and try again.", "code": "rate_limited"}, status_code=429)


@app.exception_handler(IntegrityError)
async def duplicate(_: Request, exc: IntegrityError):
    return JSONResponse({"detail": "That record already exists.", "code": "conflict"}, status_code=409)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Something went wrong on our side. Please try again.", "code": "server_error"}, status_code=500)


@app.get("/")
def root():
    return {"name": "ORVEXA API", "version": VERSION, "status": "online"}


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
@app.get("/health")
def ready():
    db_ok = True
    try:
        database.ping()
    except Exception:  # noqa: BLE001
        db_ok = False
    ai = proctoring._state
    body = {"status": "healthy" if db_ok else "degraded", "database": "connected" if db_ok else "unreachable", "version": VERSION,
            "ai_proctoring": {"enabled": settings.ai_proctoring_enabled, "loaded": ai["loaded"] and ai["error"] is None, "error": ai["error"]}}
    return JSONResponse(body, status_code=200 if db_ok else 503)


for r in (auth_routes.router, public.router, billing.router, superadmin.router, org.router, tests.router, bank.router, invites.router,
          candidate.public_router, candidate.router, results.router, coding.router):
    app.include_router(r)


# ---------------------------------------------------------------------------
# Single-service deployments (Render): serve the built frontend from this process.
# Registered last so every API route wins; unknown GET paths fall back to the SPA.
# ---------------------------------------------------------------------------
if STATIC:
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        root = os.path.realpath(STATIC)
        target = os.path.realpath(os.path.join(root, path))
        if path and target.startswith(root + os.sep) and os.path.isfile(target):
            return FileResponse(target, headers={"Cache-Control": "public, max-age=3600"})
        return FileResponse(os.path.join(root, "index.html"), headers={"Cache-Control": "no-cache"})
