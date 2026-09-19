"""resolve_user's DB-backed provisioning behavior (skipped unless TEST_DATABASE_URL is set
— see conftest.py). Cognito is the identity source of truth; this is what backfills the
local `users` row the first time a request from a given `sub` is seen (normally the
PostConfirmation trigger has already done this at signup — this path is defensive)."""
from __future__ import annotations

import pytest

from storefront.services.auth_service import AuthError, resolve_user


def test_resolve_user_returns_existing_user(seed):
    user = resolve_user({"sub": seed["cognito_sub"]})
    assert user.id == seed["user_id"]


def test_resolve_user_provisions_a_new_user_on_first_sight(database):
    user = resolve_user({"sub": "brand-new-sub", "email": "new@example.com"})
    assert user.cognito_sub == "brand-new-sub"
    assert user.email == "new@example.com"
    assert user.role == "customer"

    # Idempotent: resolving the same sub again returns the same row, not a duplicate.
    again = resolve_user({"sub": "brand-new-sub"})
    assert again.id == user.id


def test_resolve_user_rejects_missing_subject_claim(database):
    with pytest.raises(AuthError):
        resolve_user({})


def test_resolve_user_rejects_inactive_user(seed):
    from storefront.db.models import User

    user = User.get_by_id(seed["user_id"])
    user.is_active = False
    user.save()

    with pytest.raises(AuthError):
        resolve_user({"sub": seed["cognito_sub"]})
