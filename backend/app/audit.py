"""Audit trail: every security-relevant action is written to the audit_logs table and to the log stream."""
import json
import logging
from typing import Optional

from app.mongo import Session

from app import models

audit_logger = logging.getLogger("orvexa.audit")


def log_event(
    db: Optional[Session],
    action: str,
    *,
    user: Optional[models.User] = None,
    actor_email: Optional[str] = None,
    org_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    details: str = "",
    ip: Optional[str] = None,
    commit: bool = False,
) -> None:
    """Record an event. By default the row joins the caller's transaction; pass commit=True for stand-alone events."""
    email = actor_email or (user.email if user else "system")
    if org_id is None and user is not None:
        org_id = user.org_id
    audit_logger.info(json.dumps({
        "event": action, "actor": email, "org_id": org_id, "entity": entity_type,
        "entity_id": entity_id, "details": details[:500], "ip": ip,
    }))
    if db is None:
        return
    db.add(models.AuditLog(
        org_id=org_id,
        actor_id=user.id if user else None,
        actor_email=email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details[:2000] if details else None,
        ip_address=ip,
    ))
    if commit:
        db.commit()
