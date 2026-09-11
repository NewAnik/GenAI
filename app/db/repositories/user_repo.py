"""User + address lookups for the storefront auth and checkout flows."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Address, User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_address(self, address_id: int, *, user_id: int) -> Address | None:
        """Fetch an address only if it belongs to the given user (prevents using another
        user's address id at checkout)."""
        result = await self._session.execute(
            select(Address).where(Address.id == address_id, Address.user_id == user_id)
        )
        return result.scalar_one_or_none()
