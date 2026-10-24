"""Minimal Razorpay client (REST over httpx): create an order, verify signatures. No SDK needed.

Amounts are in the smallest currency unit (paise for INR). Signatures are HMAC-SHA256 hex digests:
checkout:  HMAC(key_secret, f"{order_id}|{payment_id}")      webhook: HMAC(webhook_secret, raw_body)
"""
import hashlib
import hmac
from typing import Any, Dict

import httpx

from app.config import settings
from app.errors import ApiError

API = "https://api.razorpay.com/v1"


def _sign(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_checkout(order_id: str, payment_id: str, signature: str) -> bool:
    if not (settings.razorpay_key_secret and order_id and payment_id and signature):
        return False
    return hmac.compare_digest(_sign(settings.razorpay_key_secret, f"{order_id}|{payment_id}".encode()), signature)


def verify_webhook(raw_body: bytes, signature: str) -> bool:
    if not (settings.razorpay_webhook_secret and signature):
        return False
    return hmac.compare_digest(_sign(settings.razorpay_webhook_secret, raw_body), signature)


def create_order(amount: int, currency: str, receipt: str, notes: Dict[str, Any]) -> Dict[str, Any]:
    if not settings.razorpay_enabled:
        raise ApiError(503, "Online payments are not configured yet", "payments_disabled")
    try:
        resp = httpx.post(f"{API}/orders", auth=(settings.razorpay_key_id, settings.razorpay_key_secret), timeout=15.0,
                          json={"amount": amount, "currency": currency, "receipt": receipt[:40], "notes": notes})
    except httpx.HTTPError:
        raise ApiError(502, "Could not reach the payment provider. Please try again.", "payments_unreachable")
    if resp.status_code != 200:
        raise ApiError(502, "The payment provider rejected the request. Please try again or contact support.", "payments_error")
    return resp.json()
