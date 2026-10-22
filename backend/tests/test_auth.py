"""Staff authentication: passwords, lockout, reset flow, token revocation, API keys."""
import time

from app import auth, models
from tests.conftest import PASSWORD


def test_password_hashing_handles_long_and_unicode_passwords():
    long_pw = "pässwörd-" * 40            # > 72 bytes would crash plain bcrypt
    hashed = auth.hash_password(long_pw)
    assert auth.verify_password(long_pw, hashed) and not auth.verify_password(long_pw + "x", hashed)
    assert hashed != auth.hash_password(long_pw)       # salted
    assert not auth.verify_password("x", None)


def test_password_policy():
    assert auth.password_problems("short1") and auth.password_problems("onlyletterslong") and auth.password_problems("1234567890123")
    assert auth.password_problems("GoodPassw0rd!") == []


def test_login_success_and_me(env):
    org = env.make_org()
    r = env.client.post("/auth/login", json={"email": org["email"], "password": PASSWORD})
    body = r.json()
    assert r.status_code == 200 and body["user"]["role"] == "admin" and body["organization"]["name"] == org["name"]
    me = env.client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}).json()
    assert me["user"]["email"] == org["email"] and me["organization"]["plan_code"] == "professional"


def test_login_errors_are_generic(env):
    org = env.make_org()
    wrong = env.client.post("/auth/login", json={"email": org["email"], "password": "WrongPass123"})
    unknown = env.client.post("/auth/login", json={"email": "nobody@x.example.com", "password": "WrongPass123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_unauthenticated_and_garbage_tokens_rejected(env):
    assert env.client.get("/auth/me").status_code == 401
    assert env.client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401
    assert env.client.get("/tests").status_code == 401


def test_account_locks_after_repeated_failures_then_correct_password_still_blocked(env, monkeypatch):
    org = env.make_org()
    from app.config import settings
    monkeypatch.setattr(settings, "max_failed_logins", 3)
    for _ in range(3):
        assert env.client.post("/auth/login", json={"email": org["email"], "password": "WrongPass123"}).status_code == 401
    r = env.client.post("/auth/login", json={"email": org["email"], "password": PASSWORD})
    assert r.status_code == 429 and r.json()["code"] == "account_locked"


def test_forgot_password_does_not_reveal_accounts_and_reset_works_once(env):
    org = env.make_org()
    assert env.client.post("/auth/forgot-password", json={"email": "ghost@x.example.com"}).status_code == 200
    assert env.client.post("/auth/forgot-password", json={"email": org["email"]}).status_code == 200
    db = env.db()
    mail = db.query(models.EmailOutbox).filter(models.EmailOutbox.to_email == org["email"], models.EmailOutbox.subject.like("Reset%")).one()
    assert db.query(models.EmailOutbox).filter(models.EmailOutbox.to_email == "ghost@x.example.com").count() == 0
    token = mail.body_html.split("token=")[1].split('"')[0].split("<")[0]
    db.close()

    info = env.client.get(f"/auth/token-info?token={token}").json()
    assert info["email"] == org["email"] and info["purpose"] == "reset"
    new_pw = "BrandNewPass99"
    assert env.client.post("/auth/reset-password", json={"token": token, "new_password": new_pw}).status_code == 200
    assert env.client.post("/auth/reset-password", json={"token": token, "new_password": new_pw}).status_code == 400   # single use
    assert env.client.post("/auth/login", json={"email": org["email"], "password": PASSWORD}).status_code == 401
    assert env.client.post("/auth/login", json={"email": org["email"], "password": new_pw}).status_code == 200


def test_reset_rejects_weak_password_and_bad_token(env):
    assert env.client.post("/auth/reset-password", json={"token": "x" * 30, "new_password": PASSWORD}).status_code == 400
    org = env.make_org()
    token = org["invite_url"].split("token=")[1]
    assert env.client.post("/auth/reset-password", json={"token": token, "new_password": "weak"}).status_code == 400


def test_expired_reset_token_rejected(env):
    org = env.make_org()
    token = org["invite_url"].split("token=")[1]
    db = env.db()
    from datetime import timedelta
    from app.timeutil import utcnow
    row = db.query(models.PasswordToken).first()
    row.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    db.close()
    assert env.client.post("/auth/reset-password", json={"token": token, "new_password": PASSWORD}).status_code == 400


def test_change_password_revokes_other_sessions(env):
    org = env.make_org()
    other_session = org["headers"]
    r = env.client.post("/auth/change-password", headers=other_session, json={"current_password": PASSWORD, "new_password": "AnotherPass123"})
    assert r.status_code == 200
    assert env.client.get("/auth/me", headers=other_session).status_code == 401          # old token dead
    assert env.client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200


def test_change_password_needs_correct_current(env):
    org = env.make_org()
    r = env.client.post("/auth/change-password", headers=org["headers"], json={"current_password": "Nope12345678", "new_password": "AnotherPass123"})
    assert r.status_code == 400


def test_logout_all_revokes_token(env):
    org = env.make_org()
    assert env.client.post("/auth/logout-all", headers=org["headers"]).status_code == 200
    assert env.client.get("/tests", headers=org["headers"]).status_code == 401


def test_deactivated_user_is_locked_out_immediately(env):
    org = env.make_org()
    member = env.add_member(org, "reviewer")
    assert env.client.get("/tests", headers=member["headers"]).status_code == 200
    assert env.client.patch(f"/org/team/{member['id']}", headers=org["headers"], json={"is_active": False}).status_code == 200
    assert env.client.get("/tests", headers=member["headers"]).status_code == 401


def test_api_key_auth_and_plan_gate(env):
    pro = env.make_org(plan="professional")
    r = env.client.post("/org/api-keys", headers=pro["headers"], json={"name": "ATS integration"})
    assert r.status_code == 201
    key = r.json()["key"]
    assert key.startswith("pk_live_")
    listed = env.client.get("/tests", headers={"X-API-Key": key})
    assert listed.status_code == 200
    assert "key" not in env.client.get("/org/api-keys", headers=pro["headers"]).json()[0]       # never shown again
    env.client.delete(f"/org/api-keys/{r.json()['id']}", headers=pro["headers"])
    assert env.client.get("/tests", headers={"X-API-Key": key}).status_code == 401           # revoked

    starter = env.make_org(plan="starter")
    assert env.client.post("/org/api-keys", headers=starter["headers"], json={"name": "nope"}).status_code == 402


def test_candidate_token_cannot_call_staff_endpoints(env):
    org = env.make_org()
    test = env.make_test(org)
    cand = env.candidate(test["code"])
    assert env.client.get("/tests", headers=cand["headers"]).status_code == 403
    assert env.client.get("/org/dashboard", headers=cand["headers"]).status_code == 403
