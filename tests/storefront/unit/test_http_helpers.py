"""Unit test for storefront.handlers.common.http.get_header — the case-insensitive header
lookup needed because, unlike HTTP API (v2), API Gateway REST API doesn't normalize header
name casing in the proxy-integration event."""
from __future__ import annotations

from handlers.common.http import get_header


def test_finds_header_regardless_of_casing():
    event = {"headers": {"X-Signature-256": "sha256=abc"}}
    assert get_header(event, "x-signature-256") == "sha256=abc"
    assert get_header(event, "X-SIGNATURE-256") == "sha256=abc"


def test_missing_header_returns_none():
    assert get_header({"headers": {}}, "x-signature-256") is None
    assert get_header({}, "x-signature-256") is None
