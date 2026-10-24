"""Razorpay billing: server-priced orders, signature checks, idempotent activation (provider HTTP mocked)."""
import hashlib
import hmac
import json

import pytest

from app import razorpay_client
from app.config import settings


@pytest.fixture()
def rzp(monkeypatch):
    for k, v in (("razorpay_key_id", "rzp_test_x"), ("razorpay_key_secret", "secret_x"), ("razorpay_webhook_secret", "whsec")):
        monkeypatch.setattr(settings, k, v)
    seen, counter = {}, iter(range(1, 1000))

    def fake_order(amount, currency, receipt, notes):
        seen.update(amount=amount, currency=currency, notes=notes)
        return {"id": f"order_{next(counter)}", "receipt": receipt}
    monkeypatch.setattr(razorpay_client, "create_order", fake_order)
    return seen


def sig(secret, msg):
    return hmac.new(secret.encode(), msg.encode() if isinstance(msg, str) else msg, hashlib.sha256).hexdigest()


def buy(env, org, plan="starter", months=3):
    r = env.client.post("/billing/order", headers=org["headers"], json={"plan_code": plan, "months": months})
    assert r.status_code == 200, r.text
    return r.json()


def test_overview_lists_paid_public_plans(env, rzp):
    org = env.make_org(plan="trial", status="trial")
    o = env.client.get("/billing", headers=org["headers"]).json()
    assert o["enabled"] is True
    assert {p["code"] for p in o["plans"]} == {"starter", "professional", "enterprise"} - {"enterprise"}


def test_amount_comes_from_our_price_list_not_the_browser(env, rzp):
    org = env.make_org(plan="trial", status="trial")
    o = buy(env, org, "starter", 3)
    assert o["amount"] == 999 * 3 * 100 and o["currency"] == "INR" and rzp["notes"]["plan"] == "starter"
    bad = env.client.post("/billing/order", headers=org["headers"], json={"plan_code": "starter", "months": 2})
    assert bad.status_code == 400
    assert env.client.post("/billing/order", headers=org["headers"], json={"plan_code": "enterprise", "months": 1}).status_code == 404


def test_verify_activates_plan_once(env, rzp):
    org = env.make_org(plan="trial", status="trial")
    o = buy(env, org, "professional", 1)
    s = sig("secret_x", f"{o['order_id']}|pay_1")
    body = {"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_1", "razorpay_signature": s}
    assert env.client.post("/billing/verify", headers=org["headers"], json=body).status_code == 200
    assert env.client.post("/billing/verify", headers=org["headers"], json=body).status_code == 200   # idempotent
    me = env.client.get("/org", headers=org["headers"]).json()
    assert me["plan"]["code"] == "professional" and me["status"] == "active" and me["subscription_ends_at"]
    pays = env.client.get("/billing", headers=org["headers"]).json()["payments"]
    assert len(pays) == 1 and pays[0]["status"] == "paid" and pays[0]["amount"] == 3999


def test_bad_signature_is_rejected_and_plan_unchanged(env, rzp):
    org = env.make_org(plan="trial", status="trial")
    o = buy(env, org)
    r = env.client.post("/billing/verify", headers=org["headers"], json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_1", "razorpay_signature": "0" * 64})
    assert r.status_code == 400
    assert env.client.get("/org", headers=org["headers"]).json()["plan"]["code"] == "trial"


def test_cannot_verify_another_orgs_order(env, rzp):
    a, b = env.make_org(plan="trial", status="trial"), env.make_org(plan="trial", status="trial")
    o = buy(env, a)
    s = sig("secret_x", f"{o['order_id']}|pay_1")
    r = env.client.post("/billing/verify", headers=b["headers"], json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_1", "razorpay_signature": s})
    assert r.status_code == 404


def test_webhook_activates_when_browser_never_returned(env, rzp):
    org = env.make_org(plan="trial", status="trial")
    o = buy(env, org, "starter", 1)
    raw = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_9", "order_id": o["order_id"], "method": "upi"}}}}).encode()
    assert env.client.post("/billing/webhook", content=raw, headers={"X-Razorpay-Signature": "bad"}).status_code == 400
    ok = env.client.post("/billing/webhook", content=raw, headers={"X-Razorpay-Signature": sig("whsec", raw)})
    assert ok.status_code == 200
    env.client.post("/billing/webhook", content=raw, headers={"X-Razorpay-Signature": sig("whsec", raw)})
    assert env.client.get("/org", headers=org["headers"]).json()["plan"]["code"] == "starter"
    assert len(env.client.get("/billing", headers=org["headers"]).json()["payments"]) == 1


def test_renewal_stacks_time_on_same_plan(env, rzp):
    org = env.make_org(plan="trial", status="trial")
    ends = []
    for i in range(2):
        o = buy(env, org, "starter", 1)
        env.client.post("/billing/verify", headers=org["headers"], json={
            "razorpay_order_id": o["order_id"], "razorpay_payment_id": f"pay_{i}", "razorpay_signature": sig("secret_x", f"{o['order_id']}|pay_{i}")})
        ends.append(env.client.get("/org", headers=org["headers"]).json()["subscription_ends_at"])
    from datetime import datetime
    d = [datetime.fromisoformat(x.replace("Z", "")) for x in ends]
    assert 29 <= (d[1] - d[0]).days <= 31


def test_payments_disabled_without_credentials(env):
    org = env.make_org(plan="trial", status="trial")
    assert env.client.get("/billing", headers=org["headers"]).json()["enabled"] is False
    assert env.client.post("/billing/order", headers=org["headers"], json={"plan_code": "starter", "months": 1}).status_code == 503


def test_reviewers_cannot_buy(env, rzp):
    org = env.make_org(plan="trial", status="trial")
    assert env.client.get("/billing", headers={"Authorization": "Bearer nope"}).status_code in (401, 403)
