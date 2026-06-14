"""Verification of Meta's `X-Hub-Signature-256` webhook signature header."""
from __future__ import annotations

import hashlib
import hmac


def verify_signature(payload: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Constant-time HMAC-SHA256 comparison of the raw request body against the header.

    `signature_header` looks like `sha256=<hex-digest>`. Returns False (never raises) on
    any malformed input so callers can simply branch on the boolean.
    """
    if not signature_header or not app_secret:
        return False
    try:
        algo, _, provided_digest = signature_header.partition("=")
    except ValueError:
        return False
    if algo != "sha256" or not provided_digest:
        return False

    expected_digest = hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_digest, provided_digest)
