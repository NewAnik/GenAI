"""Staff-user lookups for Cognito identity resolution and provisioning."""
from __future__ import annotations

from db.models.users import User

STAFF_ROLES = ("super_admin", "admin", "ops", "sales")
OWNER_ROLES = ("super_admin", "admin")


class UserRepository:
    def get_by_cognito_sub(self, cognito_sub: str) -> User | None:
        return User.get_or_none(User.cognito_sub == cognito_sub)

    def get_by_id(self, user_id: int) -> User | None:
        return User.get_or_none(User.id == user_id)
