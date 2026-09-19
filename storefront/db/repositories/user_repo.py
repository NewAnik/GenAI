"""User + address lookups for the storefront checkout flow and Cognito identity provisioning."""
from __future__ import annotations

from db.models import Address, User


class UserRepository:
    def get_by_cognito_sub(self, cognito_sub: str) -> User | None:
        return User.get_or_none(User.cognito_sub == cognito_sub)

    def get_by_id(self, user_id: int) -> User | None:
        return User.get_or_none(User.id == user_id)

    def create_from_cognito(self, *, cognito_sub: str, email: str | None,
                             first_name: str | None = None, last_name: str | None = None) -> User:
        return User.create(
            cognito_sub=cognito_sub, email=email, first_name=first_name, last_name=last_name,
            role="customer", is_active=True,
        )

    def update_name(self, user: User, *, first_name: str, last_name: str) -> User:
        user.first_name = first_name
        user.last_name = last_name
        user.save()
        return user

    def get_address(self, address_id: int, *, user_id: int) -> Address | None:
        """Fetch an address only if it belongs to the given user (prevents using another
        user's address id at checkout)."""
        return Address.get_or_none(Address.id == address_id, Address.user_id == user_id)
