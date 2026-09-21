"""Calls Resend's REST API directly via stdlib urllib — same choice as
wrapped-and-more/functions/api/enquiry.js's bare `fetch` (no SDK, nothing to bundle), just Python's
equivalent. This is the one function in this package that touches the network."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


def send_email(api_key: str, payload: dict) -> bool:
    request = urllib.request.Request(
        _RESEND_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Without an explicit UA, urllib sends "Python-urllib/3.x" — a signature Cloudflare's
            # WAF in front of api.resend.com blocks outright (a plain-text "error code: 1010" body,
            # not one of Resend's own JSON error responses) before the request reaches Resend at all.
            "User-Agent": "wrapped-and-more-notifications/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        logger.error("resend_rejected status=%s body=%s", exc.code, exc.read())
        return False
    except urllib.error.URLError as exc:
        logger.error("resend_unreachable reason=%s", exc.reason)
        return False
