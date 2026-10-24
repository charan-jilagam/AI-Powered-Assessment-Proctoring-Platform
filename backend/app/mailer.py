"""E-mail: every message is stored in email_outbox; it is also sent over SMTP when SMTP_HOST is configured."""
import html
import logging
import smtplib
from email.message import EmailMessage
from typing import List, Optional

from app import models
from app.background import after_commit
from app.config import settings
from app.timeutil import utcnow

log = logging.getLogger("orvexa.mail")


def render(
    title: str,
    paragraphs: List[str],
    *,
    cta_label: Optional[str] = None,
    cta_url: Optional[str] = None,
    org_name: Optional[str] = None,
    brand: Optional[str] = None,
) -> str:
    color = brand or "#4F46E5"
    body = "".join(f'<p style="margin:0 0 14px;line-height:1.55;color:#334155">{html.escape(p)}</p>' for p in paragraphs)
    button = ""
    if cta_label and cta_url:
        safe_url = html.escape(cta_url, quote=True)
        button = (
            f'<p style="margin:22px 0"><a href="{safe_url}" style="background:{color};color:#fff;text-decoration:none;'
            f'padding:12px 22px;border-radius:8px;font-weight:600;display:inline-block">{html.escape(cta_label)}</a></p>'
            f'<p style="font-size:12px;color:#64748B">If the button does not work, copy this link:<br>{safe_url}</p>'
        )
    sender = html.escape(org_name or "ORVEXA")
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;padding:24px">'
        f'<h2 style="color:#0F172A;margin:0 0 18px">{html.escape(title)}</h2>{body}{button}'
        f'<hr style="border:none;border-top:1px solid #E2E8F0;margin:26px 0 12px">'
        f'<p style="font-size:12px;color:#94A3B8">Sent by {sender} via ORVEXA</p></div>'
    )


def queue_email(db, to_email: str, subject: str, body_html: str, org_id: Optional[int] = None) -> models.EmailOutbox:
    """Record the e-mail inside the caller's transaction; it is sent once that transaction commits."""
    row = models.EmailOutbox(
        org_id=org_id, to_email=to_email, subject=subject[:255], body_html=body_html,
        status="queued" if settings.smtp_host else "logged",
    )
    db.add(row)
    db.flush()
    if settings.smtp_host:
        after_commit(db, deliver, row.id)
    return row


def deliver(outbox_id: int) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(models.EmailOutbox, outbox_id)
        if row is None or row.status != "queued":
            return
        msg = EmailMessage()
        msg["From"] = settings.mail_from
        msg["To"] = row.to_email
        msg["Subject"] = row.subject
        msg.set_content("This message needs an HTML-capable mail client.")
        msg.add_alternative(row.body_html, subtype="html")
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
            row.status, row.sent_at, row.error = "sent", utcnow(), None
        except Exception as exc:  # noqa: BLE001 - record any transport failure
            log.warning("SMTP delivery failed for outbox %s: %s", outbox_id, exc)
            row.status, row.error = "failed", str(exc)[:290]
        db.commit()
    finally:
        db.close()
