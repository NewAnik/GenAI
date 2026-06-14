"""Unit tests for HMAC-SHA256 webhook signature verification — must reject anything malformed
or mismatched, in constant time, and never raise."""
from __future__ import annotations

import hashlib
import hmac

from app.whatsapp.signature import verify_signature

_SECRET = "test-app-secret"
_BODY = b'{"object": "whatsapp_business_account"}'


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_signature_accepts_valid_signature():
    header = _sign(_BODY, _SECRET)
    assert verify_signature(_BODY, header, _SECRET) is True


def test_verify_signature_rejects_wrong_secret():
    header = _sign(_BODY, "a-different-secret")
    assert verify_signature(_BODY, header, _SECRET) is False


def test_verify_signature_rejects_tampered_body():
    header = _sign(_BODY, _SECRET)
    assert verify_signature(_BODY + b"tampered", header, _SECRET) is False


def test_verify_signature_rejects_missing_header():
    assert verify_signature(_BODY, None, _SECRET) is False


def test_verify_signature_rejects_wrong_algorithm_prefix():
    digest = hmac.new(_SECRET.encode("utf-8"), _BODY, hashlib.sha256).hexdigest()
    assert verify_signature(_BODY, f"sha1={digest}", _SECRET) is False


def test_verify_signature_rejects_malformed_header():
    assert verify_signature(_BODY, "not-a-valid-header", _SECRET) is False


def test_verify_signature_rejects_when_app_secret_missing():
    header = _sign(_BODY, _SECRET)
    assert verify_signature(_BODY, header, "") is False
