"""Organization e-mail domains, the two trial sample tests, and the language list."""
import pytest

from app import judge0, models, sample_tests
from app.config import settings
from tests.conftest import PASSWORD


# ---------------------------------------------------------------- domains
def _create(env, **extra):
    env.make_super() if not hasattr(env, "super") else None
    body = {"name": "Sconex Soft", "plan_code": "professional", "admin_name": "Sai Kumar", "admin_email": "sai@sconexsoft.com",
            "admin_temp_password": PASSWORD, "install_samples": False, **extra}
    return env.client.post("/superadmin/organizations", headers=env.super, json=body)


def test_organization_can_be_created_with_its_email_domains(env):
    r = _create(env, allowed_domains=["@SconexSoft.com", "sconexsoft.com", "mail.sconexsoft.in"])
    assert r.status_code == 201, r.text
    org = r.json()["organization"]
    assert org["allowed_domains"] == ["sconexsoft.com", "mail.sconexsoft.in"]     # cleaned and de-duplicated
    detail = env.client.get(f"/superadmin/organizations/{org['id']}", headers=env.super).json()
    assert detail["allowed_domains"] == ["sconexsoft.com", "mail.sconexsoft.in"]


def test_first_admin_must_belong_to_the_domain(env):
    r = _create(env, allowed_domains=["acme.com"])
    assert r.status_code == 400 and r.json()["code"] == "email_domain_not_allowed"


def test_team_invites_are_limited_to_the_domain_but_subdomains_count(env):
    r = _create(env, allowed_domains=["sconexsoft.com"])
    assert r.status_code == 201
    admin = {"Authorization": "Bearer " + env.login("sai@sconexsoft.com")}
    env.verify_email("sai@sconexsoft.com")
    bad = env.client.post("/org/team", headers=admin, json={"full_name": "Outsider", "email": "x@gmail.com", "role": "reviewer"})
    assert bad.status_code == 400 and bad.json()["code"] == "email_domain_not_allowed"
    assert env.client.post("/org/team", headers=admin, json={"full_name": "Insider", "email": "ravi@sconexsoft.com", "role": "reviewer"}).status_code == 201
    assert env.client.post("/org/team", headers=admin, json={"full_name": "Dept", "email": "lee@hr.sconexsoft.com", "role": "reviewer"}).status_code == 201
    # a look-alike domain is not a subdomain
    assert env.client.post("/org/team", headers=admin, json={"full_name": "Fake", "email": "z@evilsconexsoft.com", "role": "reviewer"}).status_code == 400


def test_bad_domains_are_rejected(env):
    for bad in ["not a domain", "nodot", "a..b.com", "-x.com"]:
        r = _create(env, name=f"Org {bad}", admin_email="a@x.com", allowed_domains=[bad])
        assert r.status_code == 400 and r.json()["code"] == "bad_domain", bad


def test_owner_can_change_domains_later_and_org_admin_cannot(env):
    org = env.make_org()
    r = env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"allowed_domains": ["client.example.com"], "candidate_domain_lock": True})
    assert r.status_code == 200 and r.json()["allowed_domains"] == ["client.example.com"] and r.json()["candidate_domain_lock"] is True
    # org admins can read the list but PATCH /org ignores attempts to set it
    env.client.patch("/org", headers=org["headers"], json={"allowed_domains": ["evil.com"]})
    assert env.client.get("/org", headers=org["headers"]).json()["allowed_domains"] == ["client.example.com"]
    # lock needs a domain
    other = env.make_org()
    r = env.client.patch(f"/superadmin/organizations/{other['id']}", headers=env.super, json={"candidate_domain_lock": True})
    assert r.status_code == 400 and r.json()["code"] == "no_domains"


def test_candidate_domain_lock_restricts_who_can_join(env):
    org = env.make_org()
    env.client.patch(f"/superadmin/organizations/{org['id']}", headers=env.super, json={"allowed_domains": ["sconexsoft.com"], "candidate_domain_lock": True})
    test = env.make_test(org)
    info = env.client.get(f"/public/tests/{test['code']}").json()
    assert info["email_domains"] == ["sconexsoft.com"]
    r, _ = env.join(test["code"], email="someone@gmail.com")
    assert r.status_code == 403 and r.json()["code"] == "email_domain_not_allowed"
    r, _ = env.join(test["code"], email="priya@sconexsoft.com")
    assert r.status_code == 200
    # org admin can switch the lock off again (it only ever narrows access)
    assert env.client.patch("/org", headers=org["headers"], json={"candidate_domain_lock": False}).status_code == 200
    r, _ = env.join(test["code"], email="someone@gmail.com")
    assert r.status_code == 200


# ---------------------------------------------------------------- sample tests
def test_new_organizations_get_two_published_trial_tests(env):
    env.make_super()
    r = _create(env, install_samples=True, admin_email="sai@sconexsoft.com", allowed_domains=[])
    assert r.status_code == 201
    admin = {"Authorization": "Bearer " + env.login("sai@sconexsoft.com")}
    rows = env.client.get("/tests", headers=admin).json()["items"]
    assert len(rows) == 2 and all(t["is_sample"] and t["status"] == "published" and t["title"].startswith("[Trial]") for t in rows)
    assert sorted(t["coding_problem_count"] for t in rows) == [0, 2]
    # they are real: a candidate can join one
    code = rows[0]["code"]
    assert env.client.get(f"/public/tests/{code}").json()["is_sample"] is True


def test_trial_tests_do_not_use_up_the_active_test_allowance(env):
    org = env.make_org(plan="trial", status="trial")           # trial plan: 2 active tests
    db = env.db()
    admin = db.query(models.User).filter(models.User.email == org["email"]).first()
    organization = db.get(models.Organization, org["id"])
    sample_tests.install(db, organization, admin)
    db.commit()
    db.close()
    usage = env.client.get("/org", headers=org["headers"]).json()["usage"]
    assert usage["active_tests"] == 0 and usage["total_tests"] == 2
    t1, t2 = env.make_test(org, publish=False), env.make_test(org, publish=False)
    assert env.client.post(f"/tests/{t1['id']}/publish", headers=org["headers"]).status_code == 200
    assert env.client.post(f"/tests/{t2['id']}/publish", headers=org["headers"]).status_code == 200


def test_installing_samples_is_idempotent_and_available_on_demand(env):
    org = env.make_org()
    first = env.client.post("/tests/samples", headers=org["headers"])
    assert first.status_code == 201 and len(first.json()["created"]) == 2
    again = env.client.post("/tests/samples", headers=org["headers"])
    assert again.json()["created"] == []
    assert env.client.get("/tests", headers=org["headers"]).json()["total"] == 2


def test_sample_test_content_is_valid_and_scores_correctly(env):
    org = env.make_org()
    env.client.post("/tests/samples", headers=org["headers"])
    rows = env.client.get("/tests", headers=org["headers"]).json()["items"]
    quiz = next(t for t in rows if t["coding_problem_count"] == 0)
    detail = env.client.get(f"/tests/{quiz['id']}", headers=org["headers"]).json()
    assert len(detail["questions"]) == 10 and {q["question_type"] for q in detail["questions"]} == {"single", "multiple", "true_false", "short_text"}
    cand = env.candidate(quiz["code"])
    answers = env.answer_all_correctly(org, quiz, cand)
    done = env.client.post("/attempt/submit", headers=cand["headers"], json={"answers": answers, "flagged": []})
    assert done.status_code == 200, done.text
    assert done.json()["percentage"] == 100


def test_copies_of_a_sample_are_ordinary_tests(env):
    org = env.make_org()
    env.client.post("/tests/samples", headers=org["headers"])
    sample = env.client.get("/tests", headers=org["headers"]).json()["items"][0]
    copy = env.client.post(f"/tests/{sample['id']}/duplicate", headers=org["headers"]).json()
    assert copy["is_sample"] is False


# ---------------------------------------------------------------- languages
def test_language_table_covers_the_judge0_catalogue():
    names = " ".join(judge0.SUPPORTED_LANGUAGES.values())
    for lang in ["Python", "C++", "C (", "Java", "JavaScript", "TypeScript", "C#", "Go", "Rust", "Kotlin", "Swift", "Ruby", "PHP", "Perl", "Lua",
                 "Bash", "R (", "Haskell", "Scala", "Dart", "Fortran", "Pascal", "COBOL", "SQL", "Elixir", "Erlang", "OCaml", "Prolog", "Assembly", "Groovy", "Clojure"]:
        assert lang in names, lang
    assert not set(judge0.SUPPORTED_LANGUAGES) & judge0.NOT_OFFERED_IDS
    assert len(judge0.SUPPORTED_LANGUAGES) >= 55
    assert all(judge0.family_of(n) != "text" for n in judge0.SUPPORTED_LANGUAGES.values())


def test_candidate_language_endpoint_reports_families(cenv_langs):
    env, cand = cenv_langs
    langs = env.client.get("/attempt/coding/languages", headers=cand["headers"]).json()
    by_id = {l["id"]: l for l in langs}
    assert by_id[71]["family"] == "python" and by_id[54]["family"] == "cpp" and by_id[60]["family"] == "go"
    assert len(langs) >= 55


@pytest.fixture()
def cenv_langs(env):
    org = env.make_org()
    test = env.make_test(org)
    return env, env.candidate(test["code"])


def test_live_language_list_from_judge0_is_used_and_cached(monkeypatch):
    calls = []

    class Resp:
        def raise_for_status(self): pass
        def json(self): return [{"id": 71, "name": "Python (3.8.1)"}, {"id": 43, "name": "Plain Text"}, {"id": 300, "name": "Zig (0.13)"}]

    monkeypatch.setattr(judge0, "JUDGE0_FETCH_LANGUAGES", True)
    monkeypatch.setattr(judge0, "CODE_RUNNER", "judge0")
    monkeypatch.setattr(judge0.httpx, "get", lambda *a, **k: (calls.append(1), Resp())[1])
    judge0._lang_cache.update(at=0.0, value=None)
    langs = judge0.get_languages()
    assert langs == {71: "Python (3.8.1)", 300: "Zig (0.13)"}          # Plain Text dropped, unknown language kept
    judge0.get_languages()
    assert len(calls) == 1                                               # cached
    judge0._lang_cache.update(at=0.0, value=None)


def test_unreachable_judge0_falls_back_to_the_static_list(monkeypatch):
    def boom(*a, **k): raise judge0.httpx.ConnectError("down")
    monkeypatch.setattr(judge0, "JUDGE0_FETCH_LANGUAGES", True)
    monkeypatch.setattr(judge0, "CODE_RUNNER", "judge0")
    monkeypatch.setattr(judge0.httpx, "get", boom)
    judge0._lang_cache.update(at=0.0, value=None)
    assert judge0.get_languages() == judge0.SUPPORTED_LANGUAGES
    judge0._lang_cache.update(at=0.0, value=None)
