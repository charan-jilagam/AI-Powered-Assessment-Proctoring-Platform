"""E-mail verification: org admins must verify before creating tests; candidates must enter an e-mailed code to join."""
import re

import pytest

from app import models
from app.config import settings
from app.email_verification import MAX_ATTEMPTS
from tests.conftest import PASSWORD


def _link_token(env, email, marker="verify-email?token="):
    db = env.db()
    rows = db.query(models.EmailOutbox).filter(models.EmailOutbox.to_email == email.lower()).order_by(models.EmailOutbox.id.desc()).all()
    db.close()
    for row in rows:
        m = re.search(re.escape(marker) + r"([A-Za-z0-9_\-]+)", row.body_html)
        if m:
            return m.group(1)
    raise AssertionError(f"no mail with {marker} for {email}")


# ---------------------------------------------------------------- staff
def test_unverified_admin_cannot_create_tests_until_the_link_is_used(env):
    org = env.make_org(verified=False)
    body = {"title": "Round 1", "duration_minutes": 30, "questions": [env.mcq()]}
    r = env.client.post("/tests", headers=org["headers"], json=body)
    assert r.status_code == 403 and r.json()["code"] == "email_not_verified"
    assert env.client.get("/auth/me", headers=org["headers"]).json()["user"]["email_verified"] is False

    token = _link_token(env, org["email"])
    assert env.client.post("/auth/verify-email", json={"token": token}).status_code == 200
    assert env.client.get("/auth/me", headers=org["headers"]).json()["user"]["email_verified"] is True
    assert env.client.post("/tests", headers=org["headers"], json=body).status_code == 201
    # the link works once
    assert env.client.post("/auth/verify-email", json={"token": token}).status_code == 400


def test_every_authoring_endpoint_is_gated(env):
    org = env.make_org(verified=False)
    h = org["headers"]
    for method, path, payload in [
        ("post", "/tests/1/publish", None), ("post", "/tests/1/duplicate", None),
        ("post", "/tests/1/questions", env.mcq()), ("post", "/tests/1/questions/from-bank", {"question_ids": [1]}),
        ("post", "/tests/1/coding-problems/import-json", {"problems": []}),
    ]:
        r = getattr(env.client, method)(path, headers=h, **({"json": payload} if payload is not None else {}))
        assert r.status_code == 403 and r.json()["code"] == "email_not_verified", (path, r.text)


def test_verification_can_be_resent_and_old_links_die(env):
    org = env.make_org(verified=False)
    first = _link_token(env, org["email"])
    assert env.client.post("/auth/send-verification", headers=org["headers"]).json()["status"] == "sent"
    second = _link_token(env, org["email"])
    assert first != second
    assert env.client.post("/auth/verify-email", json={"token": first}).status_code == 400
    assert env.client.post("/auth/verify-email", json={"token": second}).status_code == 200
    assert env.client.post("/auth/send-verification", headers=org["headers"]).json()["status"] == "already_verified"


def test_verification_tokens_cannot_set_a_password(env):
    org = env.make_org(verified=False)
    token = _link_token(env, org["email"])
    assert env.client.post("/auth/reset-password", json={"token": token, "new_password": "BrandNewPass123"}).status_code == 400
    assert env.client.get("/auth/token-info", params={"token": token}).status_code == 400
    # and reset tokens cannot verify an address
    env.client.post("/auth/forgot-password", json={"email": org["email"]})
    reset = _link_token(env, org["email"], "reset-password?token=")
    assert env.client.post("/auth/verify-email", json={"token": reset}).status_code == 400


def test_platform_owner_can_verify_by_hand(env):
    org = env.make_org(verified=False)
    db = env.db()
    admin_id = db.query(models.User).filter(models.User.email == org["email"]).first().id
    db.close()
    r = env.client.post(f"/superadmin/organizations/{org['id']}/users/{admin_id}/verify-email", headers=env.super)
    assert r.status_code == 200 and r.json()["email_verified"] is True
    assert env.client.post("/tests", headers=org["headers"], json={"title": "T", "duration_minutes": 5, "questions": []}).status_code == 201


def test_team_members_get_a_verification_mail_too(env):
    org = env.make_org()
    r = env.client.post("/org/team", headers=org["headers"], json={"full_name": "New Admin", "email": "new@client.example.com", "role": "admin"})
    assert r.status_code == 201 and r.json()["email_verified"] is False
    assert _link_token(env, "new@client.example.com")


# ---------------------------------------------------------------- candidates
@pytest.fixture()
def verifying(env, monkeypatch):
    monkeypatch.setattr(settings, "candidate_email_verification", True)
    org = env.make_org()
    test = env.make_test(org)
    return env, org, test


def _send(env, test, email, **extra):
    return env.client.post(f"/public/tests/{test['code']}/send-code", json={"email": email, **extra})


def test_joining_needs_the_emailed_code(verifying):
    env, org, test = verifying
    r, email = env.join(test["code"])
    assert r.status_code == 400 and r.json()["code"] == "email_code_required"

    sent = _send(env, test, "Jane@Mail.Example.com")
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    code = sent.json()["dev_code"]                     # no mail transport in tests: the code is echoed (never in production)
    db = env.db()
    mail = db.query(models.EmailOutbox).filter(models.EmailOutbox.to_email == "jane@mail.example.com").first()
    db.close()
    assert code in mail.body_html

    wrong = env.client.post(f"/public/tests/{test['code']}/join", json={"full_name": "Jane", "email": "jane@mail.example.com", "email_code": "000000" if code != "000000" else "111111"})
    assert wrong.status_code == 400 and wrong.json()["code"] == "email_code_wrong"
    ok = env.client.post(f"/public/tests/{test['code']}/join", json={"full_name": "Jane", "email": "jane@mail.example.com", "email_code": code})
    assert ok.status_code == 200
    # the code is single use
    again = env.client.post(f"/public/tests/{test['code']}/join", json={"full_name": "Jane", "email": "jane@mail.example.com", "email_code": code})
    assert again.status_code == 400


def test_code_belongs_to_one_address_and_one_test(verifying):
    env, org, test = verifying
    code = _send(env, test, "a@mail.example.com").json()["dev_code"]
    r = env.client.post(f"/public/tests/{test['code']}/join", json={"full_name": "Eve", "email": "eve@mail.example.com", "email_code": code})
    assert r.status_code == 400
    other = env.make_test(org)
    r = env.client.post(f"/public/tests/{other['code']}/join", json={"full_name": "Al", "email": "a@mail.example.com", "email_code": code})
    assert r.status_code == 400


def test_wrong_guesses_lock_the_code(verifying):
    env, org, test = verifying
    code = _send(env, test, "a@mail.example.com").json()["dev_code"]
    bad = "999999" if code != "999999" else "888888"
    for _ in range(MAX_ATTEMPTS):
        assert env.client.post(f"/public/tests/{test['code']}/join", json={"full_name": "A B", "email": "a@mail.example.com", "email_code": bad}).status_code == 400
    r = env.client.post(f"/public/tests/{test['code']}/join", json={"full_name": "A B", "email": "a@mail.example.com", "email_code": code})
    assert r.status_code == 429 and r.json()["code"] == "email_code_locked"


def test_codes_are_rate_limited_and_expire(verifying, monkeypatch):
    env, org, test = verifying
    assert _send(env, test, "a@mail.example.com").status_code == 200
    r = _send(env, test, "a@mail.example.com")
    assert r.status_code == 429 and r.json()["code"] == "code_cooldown"
    # expire it
    db = env.db()
    from app.timeutil import utcnow
    from datetime import timedelta
    db.query(models.EmailCode).update({"expires_at": utcnow() - timedelta(minutes=1), "created_at": utcnow() - timedelta(minutes=5)})
    db.commit()
    db.close()
    r = env.client.post(f"/public/tests/{test['code']}/join", json={"full_name": "A B", "email": "a@mail.example.com", "email_code": "123456"})
    assert r.status_code == 400 and r.json()["code"] == "email_code_expired"


def test_a_new_code_replaces_the_old_one(verifying):
    env, org, test = verifying
    first = _send(env, test, "a@mail.example.com").json()["dev_code"]
    db = env.db()
    from app.timeutil import utcnow
    from datetime import timedelta
    db.query(models.EmailCode).update({"created_at": utcnow() - timedelta(minutes=5)})
    db.commit()
    db.close()
    second = _send(env, test, "a@mail.example.com").json()["dev_code"]
    if first != second:
        r = env.client.post(f"/public/tests/{test['code']}/join", json={"full_name": "A B", "email": "a@mail.example.com", "email_code": first})
        assert r.status_code == 400
    assert env.client.post(f"/public/tests/{test['code']}/join", json={"full_name": "A B", "email": "a@mail.example.com", "email_code": second}).status_code == 200


def test_invite_only_tests_only_mail_invited_addresses(verifying):
    env, org, _ = verifying
    test = env.make_test(org, access_mode="invite")
    assert _send(env, test, "stranger@mail.example.com").status_code == 403
    r = env.client.post(f"/tests/{test['id']}/invites", headers=org["headers"], json={"invitees": [{"email": "kim@mail.example.com", "name": "Kim"}], "send_email": False})
    assert r.status_code in (200, 201), r.text
    assert _send(env, test, "kim@mail.example.com").status_code == 200


def test_public_info_tells_the_page_to_ask_for_a_code(verifying):
    env, org, test = verifying
    assert env.client.get(f"/public/tests/{test['code']}").json()["requires_email_verification"] is True


def test_production_without_mail_says_so_instead_of_pretending(verifying, monkeypatch):
    env, org, test = verifying
    monkeypatch.setattr(settings, "env", "production")
    r = _send(env, test, "a@mail.example.com")
    assert r.status_code == 503 and r.json()["code"] == "mail_not_configured"
    assert "dev_code" not in r.text
