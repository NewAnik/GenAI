"""Cognito PostConfirmation Lambda trigger: provisions the local `users` profile row the
moment a signup is confirmed, keyed by the new Cognito `sub`. Registered on the User Pool
in infra/cdk/storefront_stack/storefront_stack.py."""
from __future__ import annotations

from db.database import connection
from db.repositories.user_repo import UserRepository


def lambda_handler(event: dict, context=None) -> dict:
    attrs = event.get("request", {}).get("userAttributes", {})
    sub = attrs.get("sub")
    email = attrs.get("email")
    if sub:
        with connection():
            repo = UserRepository()
            if repo.get_by_cognito_sub(sub) is None:
                repo.create_from_cognito(cognito_sub=sub, email=email)
    return event
