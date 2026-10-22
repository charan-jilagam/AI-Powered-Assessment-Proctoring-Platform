"""Outbound webhooks: signed (HMAC-SHA256), retried, logged, and guarded against SSRF."""
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
from typing import Any, Dict
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app import models
from app.background import after_commit, inline
from app.config import settings

log = logging.getLogger("proctorai.webhooks")

EVENTS = (
    "attempt.started", "attempt.submitted", "attempt.terminated", "attempt.reviewed",
    "test.published", "test.closed", "candidate.invited",
)


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(24)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def check_url(url: str) -> str | None:
    """Return an error message when the URL must not be called, else None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "Webhook URL must start with http:// or https://"
    if settings.is_production and parsed.scheme != "https" and not settings.allow_private_webhooks:
        return "Webhook URL must use https in production"
    if settings.allow_private_webhooks:
        return None
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return "Webhook host could not be resolved"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "Webhook URL points to a private or internal address"
    return None


def emit(db: Session, org_id: int, event: str, payload: Dict[str, Any]) -> None:
    """Queue `event` for every active webhook of the organization that subscribes to it."""
    hooks = db.query(models.Webhook).filter(models.Webhook.org_id == org_id, models.Webhook.is_active.is_(True)).all()
    for hook in hooks:
        if hook.events and event not in hook.events:
            continue
        delivery = models.WebhookDelivery(
            org_id=org_id, webhook_id=hook.id, event=event, payload={"event": event, "data": payload}
        )
        db.add(delivery)
        db.flush()
        after_commit(db, deliver, delivery.id)


def deliver(delivery_id: int) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        delivery = db.get(models.WebhookDelivery, delivery_id)
        hook = db.get(models.Webhook, delivery.webhook_id) if delivery else None
        if delivery is None or hook is None:
            return
        problem = check_url(hook.url)
        if problem:
            delivery.error, delivery.success = problem, False
            db.commit()
            return
        body = json.dumps(delivery.payload, default=str).encode()
        for attempt in range(1, 4):
            timestamp = int(time.time())
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "ProctorAI-Webhooks/1.0",
                "X-ProctorAI-Event": delivery.event,
                "X-ProctorAI-Signature": sign(hook.secret, timestamp, body),
            }
            delivery.attempts = attempt
            try:
                resp = httpx.post(hook.url, content=body, headers=headers, timeout=6, follow_redirects=False)
                delivery.status_code = resp.status_code
                delivery.success = 200 <= resp.status_code < 300
                delivery.error = None if delivery.success else f"HTTP {resp.status_code}"
            except httpx.HTTPError as exc:
                delivery.success, delivery.error = False, str(exc)[:290]
            db.commit()
            if delivery.success or inline():
                break
            time.sleep(2 ** attempt)  # 2s, 4s between tries
    finally:
        db.close()
