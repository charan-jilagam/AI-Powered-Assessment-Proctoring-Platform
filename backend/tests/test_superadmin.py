"""The platform owner console."""
from app import models
from tests.conftest import PASSWORD


def test_only_super_admin_can_use_console(env):
    env.make_super()
    org = env.make_org()
    for path in ("/superadmin/overview", "/superadmin/organizations", "/superadmin/plans", "/superadmin/audit-log"):
        assert env.client.get(path, headers=org["headers"]).status_code == 403, path
        assert env.client.get(path).status_code == 401, path
        assert env.client.get(path, headers=env.super).status_code == 200, path


def test_create_org_with_invite_link_and_first_login(env):
    env.make_super()
    r = env.client.post("/superadmin/organizations", headers=env.super, json={
        "name": "Globex Corporation", "plan_code": "starter", "status": "trial", "trial_days": 10,
        "admin_name": "Hank Scorpio", "admin_email": "Hank@Globex.example.com"})
    assert r.status_code == 201
    body = r.json()
    assert body["organization"]["slug"] == "globex-corporation" and body["organization"]["status"] == "trial"
    assert body["admin"]["email"] == "hank@globex.example.com"                       # normalised
    assert "/accept-invite?token=" in body["admin"]["invite_url"] and body["admin"]["temp_password"] is None
    # invitation e-mail was queued
    db = env.db()
    assert db.query(models.EmailOutbox).filter(models.EmailOutbox.to_email == "hank@globex.example.com").count() == 1
    db.close()
    # the admin activates the account and can sign in
    token = body["admin"]["invite_url"].split("token=")[1]
    assert env.client.post("/auth/reset-password", json={"token": token, "new_password": PASSWORD}).status_code == 200
    assert env.client.post("/auth/login", json={"email": "hank@globex.example.com", "password": PASSWORD}).status_code == 200


def test_create_org_with_temp_password_requires_policy(env):
    env.make_super()
    base = {"name": "Initech", "plan_code": "starter", "admin_name": "Peter G", "admin_email": "peter@initech.example.com", "send_invite": False}
    assert env.client.post("/superadmin/organizations", headers=env.super, json={**base, "admin_temp_password": "short"}).status_code == 400
    r = env.client.post("/superadmin/organizations", headers=env.super, json={**base, "admin_temp_password": PASSWORD})
    assert r.status_code == 201 and r.json()["admin"]["temp_password"] == PASSWORD
    assert r.json()["admin"]["must_change_password"] is True


def test_duplicate_admin_email_and_unknown_plan(env):
    org = env.make_org()
    body = {"name": "Dup", "plan_code": "starter", "admin_name": "Someone", "admin_email": org["email"]}
    assert env.client.post("/superadmin/organizations", headers=env.super, json=body).status_code == 409
    assert env.client.post("/superadmin/organizations", headers=env.super, json={**body, "admin_email": "new@x.example.com", "plan_code": "ghost"}).status_code == 400


def test_slug_collisions_get_suffix(env):
    env.make_super()
    slugs = []
    for i in range(3):
        r = env.client.post("/superadmin/organizations", headers=env.super, json={
            "name": "Same Name", "plan_code": "starter", "admin_name": "A B", "admin_email": f"a{i}@same.example.com"})
        slugs.append(r.json()["organization"]["slug"])
    assert slugs == ["same-name", "same-name-2", "same-name-3"]


def test_suspend_blocks_staff_login_and_candidates_then_reactivate(env):
    org = env.make_org()
    test = env.make_test(org)
    r = env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"status": "suspended", "suspended_reason": "Invoice overdue"})
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    login = env.client.post("/auth/login", json={"email": org["email"], "password": PASSWORD})
    assert login.status_code == 403 and "Invoice overdue" in login.json()["detail"]
    assert env.client.get("/tests", headers=org["headers"]).status_code == 403          # existing token is blocked too
    join, _ = env.join(test["code"])
    assert join.status_code == 403 and "Invoice" not in join.text                      # candidates never see billing details
    assert env.client.get(f"/public/tests/{test['code']}").json()["available"] is False

    env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"status": "active"})
    assert env.client.get("/tests", headers=org["headers"]).status_code == 200
    assert env.join(test["code"])[0].status_code == 200


def test_expired_trial_blocks_until_extended(env):
    from datetime import timedelta
    from app.timeutil import utcnow
    org = env.make_org(status="trial")
    past = (utcnow() - timedelta(days=1)).isoformat()
    env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"trial_ends_at": past})
    assert env.client.get("/tests", headers=org["headers"]).status_code == 403
    future = (utcnow() + timedelta(days=5)).isoformat()
    env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"trial_ends_at": future})
    assert env.client.get("/tests", headers=org["headers"]).status_code == 200


def test_change_plan_and_limit_overrides(env):
    org = env.make_org(plan="starter")
    detail = env.client.get(f"/superadmin/organizations/{org['id']}", headers=env.super).json()
    assert detail["limits"]["max_active_tests"] == 5
    r = env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"limits_override": {"max_active_tests": 50, "api_access": True}})
    assert r.json()["limits"]["max_active_tests"] == 50 and r.json()["limits"]["api_access"] is True
    assert env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"limits_override": {"bogus": 1}}).status_code == 400
    assert env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"limits_override": {"max_admins": "x"}}).status_code == 400
    r = env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"plan_code": "enterprise", "limits_override": {}})
    assert r.json()["plan_code"] == "enterprise" and r.json()["limits"]["max_admins"] == -1


def test_cancel_org_signs_everyone_out(env):
    org = env.make_org()
    assert env.client.delete(f"/superadmin/organizations/{org['id']}", headers=env.super).status_code == 200
    assert env.client.get("/auth/me", headers=org["headers"]).status_code == 401 or env.client.get("/tests", headers=org["headers"]).status_code in (401, 403)
    assert env.client.post("/auth/login", json={"email": org["email"], "password": PASSWORD}).status_code == 403


def test_org_list_filters_and_search(env):
    env.make_org("Alpha Labs", plan="starter")
    env.make_org("Beta Works", plan="professional")
    r = env.client.get("/superadmin/organizations?q=alpha", headers=env.super).json()
    assert r["total"] == 1 and r["items"][0]["name"] == "Alpha Labs"
    assert env.client.get("/superadmin/organizations?plan=professional", headers=env.super).json()["total"] == 1
    assert env.client.get("/superadmin/organizations?status=trial", headers=env.super).json()["total"] == 0


def test_overview_numbers(env):
    org = env.make_org()
    test = env.make_test(org)
    env.candidate(test["code"])
    o = env.client.get("/superadmin/overview", headers=env.super).json()
    assert o["organizations"]["total"] == 1 and o["organizations"]["active"] == 1
    assert o["tests"]["published"] == 1 and o["attempts"]["this_month"] == 1 and o["attempts"]["in_progress_now"] == 1
    assert o["mrr"] == {"USD": 199} and len(o["attempts_last_30_days"]) == 30
    assert o["top_organizations"][0]["attempts"] == 1


def test_plan_crud_and_safe_delete(env):
    env.make_super()
    body = {"code": "custom-1", "name": "Custom", "price_monthly": 10, "max_candidates_per_month": 5}
    r = env.client.post("/superadmin/plans", headers=env.super, json=body)
    assert r.status_code == 201
    pid = r.json()["id"]
    assert env.client.post("/superadmin/plans", headers=env.super, json=body).status_code == 409
    assert env.client.put(f"/superadmin/plans/{pid}", headers=env.super, json={**body, "name": "Renamed"}).json()["name"] == "Renamed"
    org = env.make_org(plan="custom-1")
    r = env.client.delete(f"/superadmin/plans/{pid}", headers=env.super)
    assert r.json()["status"] == "deactivated"                                    # in use -> hidden, not deleted
    other = env.client.post("/superadmin/plans", headers=env.super, json={**body, "code": "custom-2"}).json()["id"]
    assert env.client.delete(f"/superadmin/plans/{other}", headers=env.super).json()["status"] == "deleted"
    public = [p["code"] for p in env.client.get("/public/plans").json()]
    assert "starter" in public and "trial" not in public and "custom-1" not in public


def test_platform_admins(env):
    env.make_super()
    r = env.client.post("/superadmin/platform-admins", headers=env.super, json={"full_name": "Second Owner", "email": "second@platform.example.com"})
    assert r.status_code == 201
    token = r.json()["invite_url"].split("token=")[1]
    env.client.post("/auth/reset-password", json={"token": token, "new_password": PASSWORD})
    second = env.h(env.login("second@platform.example.com"))
    assert env.client.get("/superadmin/overview", headers=second).status_code == 200
    me = env.client.get("/auth/me", headers=env.super).json()["user"]["id"]
    assert env.client.patch(f"/superadmin/platform-admins/{me}", headers=env.super, json={"is_active": False}).status_code == 400   # cannot lock yourself out


def test_reset_link_and_staff_toggle(env):
    org = env.make_org()
    uid = env.client.get(f"/superadmin/organizations/{org['id']}", headers=env.super).json()["users"][0]["id"]
    link = env.client.post(f"/superadmin/organizations/{org['id']}/users/{uid}/reset-link", headers=env.super).json()["reset_url"]
    assert "reset-password?token=" in link
    assert env.client.patch(f"/superadmin/organizations/{org['id']}/users/{uid}", headers=env.super, json={"is_active": False}).json()["is_active"] is False
    assert env.client.post("/auth/login", json={"email": org["email"], "password": PASSWORD}).status_code == 401


def test_demo_request_lifecycle(env):
    env.make_super()
    r = env.client.post("/public/demo-request", json={"name": "Dana", "email": "dana@corp.example.com", "company": "Corp", "message": "Hi"})
    assert r.status_code == 200
    items = env.client.get("/superadmin/demo-requests", headers=env.super).json()["items"]
    assert items[0]["company"] == "Corp" and items[0]["status"] == "new"
    assert env.client.patch(f"/superadmin/demo-requests/{items[0]['id']}", headers=env.super, json={"status": "contacted"}).json()["status"] == "contacted"


def test_audit_log_records_actions_and_filters(env):
    org = env.make_org()
    rows = env.client.get("/superadmin/audit-log", headers=env.super).json()
    actions = {a["action"] for a in rows["items"]}
    assert {"ORG_CREATED", "LOGIN_SUCCESS"} <= actions
    only = env.client.get(f"/superadmin/audit-log?org_id={org['id']}&action=ORG_CREATED", headers=env.super).json()
    assert only["total"] == 1
