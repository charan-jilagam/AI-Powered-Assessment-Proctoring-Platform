from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

# Per-IP limits. Set REDIS_URL so the counters are shared between API workers/containers.
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url or "memory://")
