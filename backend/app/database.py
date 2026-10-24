"""Database access: the MongoDB connection, the per-request session and startup helpers."""
from app import mongo
from app.mongo import Session

SessionLocal = Session          # `SessionLocal()` opens a unit of work, as before


def get_db():
    """One session per request, always closed (uncommitted changes are simply dropped)."""
    db = Session()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create collections and indexes. Safe to run on every start; this is what creates the database on Atlas."""
    mongo.ensure_indexes()


def ping() -> None:
    mongo.ping()
