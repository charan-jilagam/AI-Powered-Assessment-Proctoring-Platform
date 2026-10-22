"""ProctorAI API - multi-tenant assessment & proctoring platform."""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import attempt_service, coding, proctoring
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.limiter import limiter
from app.routers import auth_routes, bank, candidate, invites, org, public, results, superadmin, tests
from app.seed import bootstrap_super_admin, seed_plans

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("proctorai")

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
    # Production schema is managed by Alembic (`alembic upgrade head`); dev/test auto-create for convenience.
    if not settings.is_production:
        Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_plans(db)
        bootstrap_super_admin(db)
    except Exception:  # noqa: BLE001
        log.exception("startup seeding failed (has the database been migrated?)")
    finally:
        db.close()
    task = asyncio.create_task(_sweeper()) if settings.run_sweeper else None
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="ProctorAI API",
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


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
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


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Something went wrong on our side. Please try again.", "code": "server_error"}, status_code=500)


@app.get("/")
def root():
    return {"name": "ProctorAI API", "version": VERSION, "status": "online"}


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
@app.get("/health")
def ready():
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    ai = proctoring._state
    body = {"status": "healthy" if db_ok else "degraded", "database": "connected" if db_ok else "unreachable", "version": VERSION,
            "ai_proctoring": {"enabled": settings.ai_proctoring_enabled, "loaded": ai["loaded"] and ai["error"] is None, "error": ai["error"]}}
    return JSONResponse(body, status_code=200 if db_ok else 503)


for r in (auth_routes.router, public.router, superadmin.router, org.router, tests.router, bank.router, invites.router,
          candidate.public_router, candidate.router, results.router, coding.router):
    app.include_router(r)
