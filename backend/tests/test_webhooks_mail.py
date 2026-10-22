"""Webhooks (signing, retries, SSRF guard, event routing) and e-mail outbox."""
import hashlib
import hmac
import json

import httpx
import pytest

from app import mailer, models, webhooks
from app.config import settings
from app.database import SessionLocal


class Sink:
    """Stands in for httpx.post and records what the platform would have sent."""

    def __init__(self, status=200, fail=False):
        self.calls, self.status, self.fail = [], status, fail

    def __call__(self, url, content=None, headers=None, timeout=None, follow_redirects=None):
        self.calls.append({"url": url, "body": json.loads(content), "raw": content, "headers": headers, "follow": follow_redirects})
        if self.fail:
            raise httpx.ConnectError("refused")
        return httpx.Response(self.status)


@pytest.fixture()
def hook_env(env, monkeypatch):
    sink = Sink()
    monkeypatch.setattr(webhooks.httpx, "post", sink)
    monkeypatch.setattr(webhooks.time, "sleep", lambda s: None)
    env.sink = sink
    org = env.make_org()
    env.org = org
    return env


def add_hook(env, events=None, url="https://hooks.example.com/in"):
    r = env.client.post("/org/webhooks", headers=env.org["headers"], json={"url": url, "events": events or []})
    assert r.status_code == 201, r.text
    return r.json()


def test_secret_is_revealed_once_then_hidden(hook_env):
    hook = add_hook(hook_env)
    assert hook["secret"].startswith("whsec_")
    listed = hook_env.client.get("/org/webhooks", headers=hook_env.org["headers"]).json()
    assert "secret" not in listed[0] and "secret_hint" in listed[0]


def test_signature_is_verifiable_by_the_receiver(hook_env):
    hook = add_hook(hook_env, ["attempt.submitted"])
    test = hook_env.make_test(hook_env.org)
    c = hook_env.candidate(test["code"])
    hook_env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    call = hook_env.sink.calls[-1]
    sig = call["headers"]["X-ProctorAI-Signature"]
    ts, mac = [p.split("=", 1)[1] for p in sig.split(",")]
    expected = hmac.new(hook["secret"].encode(), f"{ts}.".encode() + call["raw"], hashlib.sha256).hexdigest()
    assert hmac.compare_digest(mac, expected)
    assert call["headers"]["X-ProctorAI-Event"] == "attempt.submitted" and call["follow"] is False
    assert call["body"]["data"]["attempt_id"] == c["attempt_id"]


def test_only_subscribed_events_are_delivered(hook_env):
    add_hook(hook_env, ["attempt.terminated"])
    test = hook_env.make_test(hook_env.org)
    c = hook_env.candidate(test["code"])
    hook_env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    assert hook_env.sink.calls == []


def test_empty_event_list_means_everything(hook_env):
    add_hook(hook_env)
    test = hook_env.make_test(hook_env.org)
    c = hook_env.candidate(test["code"])
    hook_env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    assert {x["body"]["event"] for x in hook_env.sink.calls} >= {"test.published", "attempt.started", "attempt.submitted"}


def test_hooks_never_fire_across_organizations(hook_env):
    add_hook(hook_env)
    other = hook_env.make_org("Other Org")
    test = hook_env.make_test(other)
    c = hook_env.candidate(test["code"])
    hook_env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}})
    assert hook_env.sink.calls == []


def test_delivery_log_records_success_and_failure(hook_env):
    hook = add_hook(hook_env)
    hook_env.client.post(f"/org/webhooks/{hook['id']}/test", headers=hook_env.org["headers"])
    hook_env.sink.status = 500
    hook_env.client.post(f"/org/webhooks/{hook['id']}/test", headers=hook_env.org["headers"])
    rows = hook_env.client.get(f"/org/webhooks/{hook['id']}/deliveries", headers=hook_env.org["headers"]).json()["items"]
    assert [r["success"] for r in rows] == [False, True] and rows[0]["error"] == "HTTP 500"


def test_network_failure_is_logged_and_does_not_break_the_request(hook_env):
    hook_env.sink.fail = True
    hook = add_hook(hook_env)
    test = hook_env.make_test(hook_env.org)                              # publishing triggers an event
    c = hook_env.candidate(test["code"])
    assert hook_env.client.post("/attempt/submit", headers=c["headers"], json={"answers": {}}).status_code == 200
    rows = hook_env.client.get(f"/org/webhooks/{hook['id']}/deliveries", headers=hook_env.org["headers"]).json()["items"]
    assert rows and all(r["success"] is False and "refused" in r["error"] for r in rows)


def test_inactive_hooks_are_skipped(hook_env):
    hook = add_hook(hook_env)
    hook_env.client.put(f"/org/webhooks/{hook['id']}", headers=hook_env.org["headers"], json={"url": hook["url"], "events": [], "is_active": False})
    hook_env.make_test(hook_env.org)
    assert hook_env.sink.calls == []


def test_unknown_event_names_are_rejected(hook_env):
    r = hook_env.client.post("/org/webhooks", headers=hook_env.org["headers"], json={"url": "https://hooks.example.com/x", "events": ["nope"]})
    assert r.status_code == 400


# ---------------------------------------------------------------- SSRF guard
@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://localhost/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/x",
                                 "http://192.168.1.1/x", "http://[::1]/x"])
def test_internal_addresses_are_blocked(monkeypatch, url):
    monkeypatch.setattr(settings, "allow_private_webhooks", False)
    assert "private" in (webhooks.check_url(url) or "").lower() or "resolved" in (webhooks.check_url(url) or "").lower()


@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "http://"])
def test_non_http_schemes_are_blocked(url):
    assert webhooks.check_url(url)


def test_https_required_in_production(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_webhooks", False)
    monkeypatch.setattr(settings, "env", "production")
    assert "https" in webhooks.check_url("http://example.com/x")


def test_url_is_rechecked_at_delivery_time(hook_env, monkeypatch):
    hook = add_hook(hook_env)                                           # accepted while private hosts were allowed
    monkeypatch.setattr(settings, "allow_private_webhooks", False)
    monkeypatch.setattr(webhooks, "check_url", lambda url: "Webhook URL points to a private or internal address")
    hook_env.client.post(f"/org/webhooks/{hook['id']}/test", headers=hook_env.org["headers"])
    assert hook_env.sink.calls == []
    row = hook_env.client.get(f"/org/webhooks/{hook['id']}/deliveries", headers=hook_env.org["headers"]).json()["items"][0]
    assert row["success"] is False and "private" in row["error"]


def test_signature_changes_with_body_secret_and_time():
    base = webhooks.sign("s", 100, b"{}")
    assert base != webhooks.sign("s", 100, b"{ }") and base != webhooks.sign("t", 100, b"{}") and base != webhooks.sign("s", 101, b"{}")


# ---------------------------------------------------------------- e-mail
def test_emails_are_recorded_in_the_outbox_even_without_smtp(env):
    org = env.make_org()
    test = env.make_test(org)
    env.client.post(f"/tests/{test['id']}/invites", headers=org["headers"], json={"invitees": [{"email": "kate@mail.example.com", "name": "Kate"}], "send_email": True})
    rows = env.client.get("/superadmin/outbox", headers=env.super).json()["items"]
    invite = next(r for r in rows if r["to_email"] == "kate@mail.example.com")
    assert invite["status"] == "logged" and test["code"] in invite["body_html"] and "invite=" in invite["body_html"]


def test_user_supplied_text_is_html_escaped_in_emails():
    out = mailer.render("Hi <b>x</b>", ['<script>alert(1)</script>'], cta_label="Go", cta_url='https://x.example.com/?a="><img src=x>', org_name="<i>Evil</i>")
    assert "<script>" not in out and "<img" not in out and "<i>Evil" not in out


class FakeSMTP:
    sent, fail = [], False

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise OSError("smtp down")
        FakeSMTP.sent.append(msg)


@pytest.mark.parametrize("fail, status", [(False, "sent"), (True, "failed")])
def test_smtp_delivery_updates_the_outbox_row(env, monkeypatch, fail, status):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], fail
    org = env.make_org()
    test = env.make_test(org)
    env.client.post(f"/tests/{test['id']}/invites", headers=org["headers"], json={"invitees": [{"email": "lee@mail.example.com"}], "send_email": True})
    db = SessionLocal()
    try:
        row = db.query(models.EmailOutbox).filter(models.EmailOutbox.to_email == "lee@mail.example.com").one()
        assert row.status == status
        assert (row.error is None) is (status == "sent")
    finally:
        db.close()
    assert len([m for m in FakeSMTP.sent if m["To"] == "lee@mail.example.com"]) == (0 if fail else 1)


def test_a_rolled_back_transaction_sends_nothing(env, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], False
    db = SessionLocal()
    try:
        mailer.queue_email(db, "ghost@mail.example.com", "Never", "<p>x</p>")
        db.rollback()
    finally:
        db.close()
    assert FakeSMTP.sent == []
