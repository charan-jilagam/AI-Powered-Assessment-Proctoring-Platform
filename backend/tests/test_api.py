"""Tests for the API endpoints using an isolated test database."""
import sys
import os
from app.main import app
# Disable rate limiting during tests
app.state.limiter.enabled = False   
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models
from app.main import app

# ---- Set up an in-memory SQLite test database ----
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def test_signup_creates_student():
    """A new signup creates a student account."""
    response = client.post("/auth/signup", json={
        "full_name": "Test User",
        "email": "newuser@test.com",
        "password": "password123",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "newuser@test.com"
    assert data["role"] == "student"   # public signups are always students


def test_duplicate_email_rejected():
    """Signing up with an already-used email is rejected."""
    client.post("/auth/signup", json={
        "full_name": "First",
        "email": "dupe@test.com",
        "password": "password123",
    })
    response = client.post("/auth/signup", json={
        "full_name": "Second",
        "email": "dupe@test.com",
        "password": "password123",
    })
    assert response.status_code == 400


def test_login_with_correct_credentials():
    """Login succeeds with correct credentials and returns a token."""
    client.post("/auth/signup", json={
        "full_name": "Login User",
        "email": "login@test.com",
        "password": "mypassword",
    })
    response = client.post("/auth/login", json={
        "email": "login@test.com",
        "password": "mypassword",
    })
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_with_wrong_password_fails():
    """Login fails with a wrong password."""
    client.post("/auth/signup", json={
        "full_name": "Wrong Pass",
        "email": "wrongpass@test.com",
        "password": "correctpassword",
    })
    response = client.post("/auth/login", json={
        "email": "wrongpass@test.com",
        "password": "wrongpassword",
    })
    assert response.status_code == 401


def test_protected_route_requires_token():
    """Accessing a protected route without a token is rejected."""
    response = client.get("/exams/available")
    assert response.status_code in (401, 403)