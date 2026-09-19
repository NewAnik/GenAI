"""Unit tests for group-membership checks — pure logic, no DB. See
tests/storefront/integration/test_auth_service.py for resolve_user's DB-backed
provisioning behavior (Cognito replaced password verification entirely, so there's no
hash/JWT round-trip logic left to unit-test here — see the migration plan)."""
from __future__ import annotations

import pytest

from storefront.services.auth_service import ForbiddenError, require_group


def test_require_group_passes_when_user_in_group():
    require_group({"cognito:groups": ["admin"]}, "admin")


def test_require_group_passes_with_any_matching_group():
    require_group({"cognito:groups": ["editor", "admin"]}, "admin", "superadmin")


def test_require_group_raises_when_no_groups_claim():
    with pytest.raises(ForbiddenError):
        require_group({}, "admin")


def test_require_group_raises_when_group_not_in_required_set():
    with pytest.raises(ForbiddenError):
        require_group({"cognito:groups": ["editor"]}, "admin")


def test_require_group_handles_single_string_group_claim():
    # Cognito can emit a single group as a bare string rather than a list.
    require_group({"cognito:groups": "admin"}, "admin")
