"""Shared test setup: an in-memory MongoDB (mongomock), deterministic background jobs, and API builders."""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="orvexa-tests-")
os.environ.update({
    "APP_ENV": "test",
    "MONGODB_URI": "mongomock://",
    "MONGODB_DB": "orvexa_test",
    "SECRET_KEY": "test-secret-key-for-unit-tests-0123456789abcdef",
    "EVIDENCE_DIR": f"{_TMP}/evidence",
    "FRONTEND_URL": "http://frontend.test",
    "BACKGROUND_INLINE": "true",     # run e-mail / webhook side effects synchronously
    "RUN_SWEEPER": "false",
    "ALLOW_PRIVATE_WEBHOOKS": "true",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt  # noqa: E402

_gensalt = bcrypt.gensalt
bcrypt.gensalt = lambda rounds=4, prefix=b"2b": _gensalt(rounds, prefix)  # fast hashing in tests only

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, coding, models  # noqa: E402
from app import mongo  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.limiter import limiter  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_plans  # noqa: E402

limiter.enabled = False
PASSWORD = "CorrectHorse42"


class Env:
    """Everything a test needs: an HTTP client plus helpers to build tenants, tests and candidates."""

    def __init__(self):
        self.client = TestClient(app)
        self._n = 0

    # ---- plumbing -----------------------------------------------------
    def db(self):
        return SessionLocal()

    def uid(self, prefix="x"):
        self._n += 1
        return f"{prefix}{self._n}"

    @staticmethod
    def h(token):
        return {"Authorization": f"Bearer {token}"}

    def login(self, email, password=PASSWORD):
        r = self.client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    # ---- tenants ------------------------------------------------------
    def make_super(self, email="owner@platform.example.com"):
        db = self.db()
        db.add(models.User(full_name="Owner", email=email, hashed_password=auth.hash_password(PASSWORD), role="super_admin"))
        db.commit()
        db.close()
        self.super = self.h(self.login(email))
        return self.super

    def make_org(self, name=None, plan="professional", status="active", **extra):
        if not hasattr(self, "super"):
            self.make_super()
        name = name or self.uid("Org")
        email = f"admin-{name.lower().replace(' ', '')}@client.example.com"
        r = self.client.post("/superadmin/organizations", headers=self.super, json={
            "name": name, "plan_code": plan, "status": status, "admin_name": f"{name} Admin", "admin_email": email,
            "admin_temp_password": PASSWORD, **extra})
        assert r.status_code == 201, r.text
        org = r.json()["organization"]
        token = self.login(email)
        return {"id": org["id"], "name": name, "email": email, "headers": self.h(token), "invite_url": r.json()["admin"]["invite_url"]}

    def add_member(self, org, role="reviewer"):
        email = f"{self.uid(role)}@client.example.com"
        r = self.client.post("/org/team", headers=org["headers"], json={"full_name": "Member", "email": email, "role": role})
        assert r.status_code == 201, r.text
        # activate via the invitation link
        token = r.json()["invite_url"].split("token=")[1]
        assert self.client.post("/auth/reset-password", json={"token": token, "new_password": PASSWORD}).status_code == 200
        return {"email": email, "headers": self.h(self.login(email)), "id": r.json()["id"]}

    # ---- tests --------------------------------------------------------
    def mcq(self, text="2+2?", options=("3", "4", "5", "6"), correct=1, **kw):
        return {"question_type": "single", "question_text": text, "options": list(options), "correct": [correct], **kw}

    def make_test(self, org, questions=None, publish=True, **body):
        payload = {"title": body.pop("title", self.uid("Test")), "duration_minutes": body.pop("duration_minutes", 30),
                   "questions": questions if questions is not None else [self.mcq()],
                   "proctoring": body.pop("proctoring", {"webcam_required": False, "ai_monitoring": False}), **body}
        r = self.client.post("/tests", headers=org["headers"], json=payload)
        assert r.status_code == 201, r.text
        test = r.json()
        if publish:
            p = self.client.post(f"/tests/{test['id']}/publish", headers=org["headers"])
            assert p.status_code == 200, p.text
        return test

    # ---- candidates ---------------------------------------------------
    def join(self, code, email=None, name="Test Candidate", **extra):
        email = email or f"{self.uid('cand')}@mail.example.com"
        return self.client.post(f"/public/tests/{code}/join", json={"full_name": name, "email": email, **extra}), email

    def candidate(self, code, email=None, start=True, **extra):
        r, email = self.join(code, email, **extra)
        assert r.status_code == 200, r.text
        c = {"email": email, "headers": self.h(r.json()["token"]), "attempt_id": r.json()["attempt"]["id"], "token": r.json()["token"]}
        if start:
            s = self.client.post("/attempt/start", headers=c["headers"], json={"consent": True})
            assert s.status_code == 200, s.text
            c["state"] = s.json()
        return c

    def answer_all_correctly(self, org, test, cand):
        """Submit the correct option text for every question the candidate was shown."""
        detail = self.client.get(f"/tests/{test['id']}", headers=org["headers"]).json()
        key = {q["id"]: [q["options"][i] for i in q["correct"]] if q["question_type"] != "short_text" else q["correct"] for q in detail["questions"]}
        answers = {}
        for q in cand["state"]["questions"]:
            correct = key[q["id"]]
            answers[str(q["id"])] = correct if q["type"] == "multiple" else correct[0]
        return answers


@pytest.fixture()
def env():
    mongo.drop_all_data()
    init_db()
    db = SessionLocal()
    seed_plans(db)
    db.close()
    coding.reset_throttle()
    return Env()
