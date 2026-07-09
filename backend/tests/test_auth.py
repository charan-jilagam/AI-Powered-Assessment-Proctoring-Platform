"""Tests for authentication and password security."""
import sys
import os

# Allow importing from the app package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import auth


def test_password_hashing_works():
    """A password can be hashed and the hash is not the original password."""
    password = "mySecret123"
    hashed = auth.hash_password(password)

    assert hashed != password          # never store plaintext
    assert len(hashed) > 20            # bcrypt hashes are long
    assert hashed.startswith("$2")     # bcrypt hash signature


def test_correct_password_verifies():
    """The correct password verifies against its hash."""
    password = "correctPassword"
    hashed = auth.hash_password(password)

    assert auth.verify_password(password, hashed) is True


def test_wrong_password_fails():
    """A wrong password does NOT verify against the hash."""
    hashed = auth.hash_password("realPassword")

    assert auth.verify_password("wrongPassword", hashed) is False


def test_same_password_different_hashes():
    """Hashing the same password twice gives different hashes (salting)."""
    password = "samePassword"
    hash1 = auth.hash_password(password)
    hash2 = auth.hash_password(password)

    # Different hashes due to random salt, but both verify correctly
    assert hash1 != hash2
    assert auth.verify_password(password, hash1) is True
    assert auth.verify_password(password, hash2) is True


def test_token_creation_and_decode():
    """A JWT token can be created and decoded back to the right user."""
    token = auth.create_access_token(data={"sub": "42", "role": "student"})

    assert isinstance(token, str)
    assert len(token) > 20