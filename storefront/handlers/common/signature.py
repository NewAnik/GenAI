"""Verification of a payment-gateway webhook's `X-Signature-256` header. Copied (not
imported) from app/whatsapp/signature.py — an 18-line, dependency-free function; duplicating
it is cheaper than coupling this Lambda's import path back to the `app` package layout."""
from __future__ import annotations

import hashlib
import hmac


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    """Constant-time HMAC-SHA256 comparison of the raw request body against the header.

    `signature_header` looks like `sha256=<hex-digest>`. Returns False (never raises) on
    any malformed input so callers can simply branch on the boolean.
    """
    if not signature_header or not secret:
        return False
    algo, _, provided_digest = signature_header.partition("=")
    if algo != "sha256" or not provided_digest:
        return False

    expected_digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_digest, provided_digest)
