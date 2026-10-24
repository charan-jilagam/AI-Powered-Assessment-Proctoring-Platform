"""Self-serve plan purchases with Razorpay.

Flow: POST /billing/order (server creates the order from OUR price list - the browser never sets an amount) ->
Razorpay Checkout in the browser -> POST /billing/verify (signature check) activates the plan. The webhook is the
safety net for browsers that close before /verify; both paths are idempotent.
"""
import json
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app import audit, auth, mailer, models, razorpay_client, serializers
from app.constants import ORG_ACTIVE, ORG_SUSPENDED
from app.database import get_db
from app.errors import ApiError, bad_request, not_found
from app.config import settings
from app.mongo import Session, update
from app.timeutil import as_utc, utcnow

router = APIRouter(prefix="/billing", tags=["billing"])
MONTH_CHOICES = (1, 3, 6, 12)


def payment_out(p: models.Payment, plans: dict) -> dict:
    plan = plans.get(p.plan_id)
    return {"id": p.id, "order_id": p.order_id, "payment_id": p.payment_id, "plan": plan.name if plan else None, "months": p.months,
            "amount": p.amount / 100, "currency": p.currency, "status": p.status, "paid_at": p.paid_at, "period_end": p.period_end,
            "created_at": p.created_at}


@router.get("")
def billing_overview(user: models.User = Depends(auth.require_org_admin), org: models.Organization = Depends(auth.get_current_org),
                     db: Session = Depends(get_db)):
    plans = db.query(models.Plan).filter(models.Plan.is_active.is_(True)).order_by(models.Plan.sort_order).all()
    by_id = {p.id: p for p in plans}
    payments = db.query(models.Payment).filter(models.Payment.org_id == org.id).order_by(models.Payment.id.desc()).limit(25).all()
    return {
        "enabled": settings.razorpay_enabled,
        "plans": [serializers.plan_out(p) for p in plans if p.is_public and p.price_monthly > 0],
        "month_choices": list(MONTH_CHOICES),
        "payments": [payment_out(p, by_id) for p in payments],
    }


class OrderIn(BaseModel):
    plan_code: str = Field(min_length=1, max_length=40)
    months: int = 1


@router.post("/order")
def create_order(body: OrderIn, request: Request, user: models.User = Depends(auth.require_org_admin),
                 org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    if body.months not in MONTH_CHOICES:
        raise bad_request("Choose 1, 3, 6 or 12 months")
    if org.status == ORG_SUSPENDED:
        raise ApiError(403, "This organization is suspended. Contact support.", "org_suspended")
    plan = db.query(models.Plan).filter(models.Plan.code == body.plan_code, models.Plan.is_active.is_(True), models.Plan.is_public.is_(True)).first()
    if plan is None or plan.price_monthly <= 0:
        raise not_found("Plan")
    amount = int(round(plan.price_monthly * body.months * 100))
    order = razorpay_client.create_order(amount, plan.currency, f"orv-{org.id}-{int(utcnow().timestamp())}",
                                         {"org_id": str(org.id), "plan": plan.code, "months": str(body.months)})
    db.add(models.Payment(org_id=org.id, plan_id=plan.id, user_id=user.id, order_id=order["id"], receipt=order.get("receipt"),
                          amount=amount, currency=plan.currency, months=body.months))
    audit.log_event(db, "BILLING_ORDER_CREATED", user=user, entity_type="organization", entity_id=org.id,
                    details=f"{plan.code} x{body.months} {amount / 100:.2f} {plan.currency}", ip=auth.client_ip(request))
    db.commit()
    return {"key_id": settings.razorpay_key_id, "order_id": order["id"], "amount": amount, "currency": plan.currency,
            "plan": plan.name, "months": body.months, "name": "ORVEXA", "description": f"{plan.name} plan - {body.months} month(s)",
            "prefill": {"name": user.full_name, "email": user.email}}


def activate(db: Session, payment: models.Payment, payment_id: Optional[str], method: Optional[str] = None) -> bool:
    """Mark a payment paid and extend the subscription. Idempotent: returns False if it was already applied."""
    claimed = db.execute(
        update(models.Payment)
        .where(models.Payment.id == payment.id, models.Payment.status != "paid")
        .values(status="paid", payment_id=payment_id, method=method, paid_at=utcnow(), error=None)
    ).rowcount
    db.refresh(payment)
    if not claimed:
        return False
    org = db.get(models.Organization, payment.org_id)
    plan = db.get(models.Plan, payment.plan_id)
    now = utcnow()
    current_end = as_utc(org.subscription_ends_at) if org.subscription_ends_at else None
    # Renewing the same plan stacks on the remaining time; switching plans starts today.
    start = current_end if (current_end and current_end > now and org.plan_id == plan.id and org.status == ORG_ACTIVE) else now
    end = start + timedelta(days=30 * payment.months)
    payment.period_start, payment.period_end = start, end
    if org.status != ORG_SUSPENDED:
        org.status = ORG_ACTIVE
    org.plan_id, org.subscription_ends_at = plan.id, end
    audit.log_event(db, "BILLING_PAYMENT_CAPTURED", actor_email="razorpay", org_id=org.id, entity_type="organization", entity_id=org.id,
                    details=f"{plan.code} x{payment.months} {payment.amount / 100:.2f} {payment.currency} {payment_id}")
    payer = db.get(models.User, payment.user_id) if payment.user_id else None
    to = (payer.email if payer else None) or org.contact_email
    if to:
        mailer.queue_email(db, to, f"Payment received - {plan.name} plan", mailer.render(
            "Payment received", [f"Thanks! Your {plan.name} plan is active until {end:%d %b %Y}.",
                                 f"Amount: {payment.amount / 100:.2f} {payment.currency}. Reference: {payment_id}."],
            cta_label="Open ORVEXA", cta_url=f"{settings.frontend_url}/app/billing", org_name=org.name), org_id=org.id)
    return True


class VerifyIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/verify")
def verify(body: VerifyIn, request: Request, user: models.User = Depends(auth.require_org_admin),
           org: models.Organization = Depends(auth.get_current_org), db: Session = Depends(get_db)):
    payment = db.query(models.Payment).filter(models.Payment.order_id == body.razorpay_order_id, models.Payment.org_id == org.id).first()
    if payment is None:
        raise not_found("Order")
    if not razorpay_client.verify_checkout(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        payment.status = payment.status if payment.status == "paid" else "failed"
        payment.error = "signature mismatch"
        audit.log_event(db, "BILLING_SIGNATURE_INVALID", user=user, entity_type="organization", entity_id=org.id, ip=auth.client_ip(request))
        db.commit()
        raise ApiError(400, "Payment could not be verified. If money was deducted it will be reconciled automatically.", "bad_signature")
    activate(db, payment, body.razorpay_payment_id)
    db.commit()
    return {"status": "paid", "subscription_ends_at": db.get(models.Organization, org.id).subscription_ends_at}


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not razorpay_client.verify_webhook(raw, request.headers.get("X-Razorpay-Signature", "")):
        raise ApiError(400, "Bad signature", "bad_signature")
    try:
        event = json.loads(raw)
        kind = event.get("event", "")
        entity = event["payload"]["payment"]["entity"]
    except (ValueError, KeyError, TypeError):
        return {"status": "ignored"}
    payment = db.query(models.Payment).filter(models.Payment.order_id == entity.get("order_id")).first()
    if payment is None:
        return {"status": "unknown_order"}
    if kind in ("payment.captured", "order.paid"):
        activate(db, payment, entity.get("id"), entity.get("method"))
    elif kind == "payment.failed" and payment.status != "paid":
        payment.status, payment.error = "failed", (entity.get("error_description") or "payment failed")[:200]
    db.commit()
    return {"status": "ok"}
