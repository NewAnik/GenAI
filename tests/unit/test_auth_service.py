"""Unit tests for storefront auth: bcrypt password verification and JWT round-trips."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.services.auth_service import (
    AuthError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def _settings(**overrides) -> Settings:
    base = dict(jwt_secret="unit-test-secret", jwt_algorithm="HS256", jwt_expire_minutes=60)
    base.update(overrides)
    return Settings(**base)


def test_hash_and_verify_password_round_trip():
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"  # never store plaintext
    assert verify_password("s3cret-pw", h) is True


def test_verify_password_rejects_wrong_password():
    h = hash_password("s3cret-pw")
    assert verify_password("wrong", h) is False


def test_verify_password_rejects_empty_or_malformed_hash():
    assert verify_password("anything", None) is False
    assert verify_password("anything", "") is False
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_jwt_round_trip_carries_claims():
    settings = _settings()
    token = create_access_token(settings, user_id=42, org_id=7, role="buyer")
    claims = decode_access_token(settings, token)
    assert claims["sub"] == "42"
    assert claims["org_id"] == 7
    assert claims["role"] == "buyer"


def test_decode_rejects_tampered_token():
    settings = _settings()
    token = create_access_token(settings, user_id=1, org_id=None, role=None)
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(AuthError):
        decode_access_token(settings, tampered)


def test_decode_rejects_token_signed_with_other_secret():
    token = create_access_token(_settings(jwt_secret="secret-a"), user_id=1, org_id=None, role=None)
    with pytest.raises(AuthError):
        decode_access_token(_settings(jwt_secret="secret-b"), token)


def test_decode_rejects_expired_token():
    settings = _settings(jwt_expire_minutes=-1)  # already expired at issuance
    token = create_access_token(settings, user_id=1, org_id=None, role=None)
    with pytest.raises(AuthError):
        decode_access_token(settings, token)
