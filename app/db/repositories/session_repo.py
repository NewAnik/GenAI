"""All `conversation_sessions` access funnels through here — the resumability hub that
lets a stateless WhatsApp webhook carry a multi-turn conversation forward in Postgres."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationSession


class SessionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_or_create(self, whatsapp_number: str) -> ConversationSession:
        row = await self._get(whatsapp_number)
        if row is not None:
            return row
        row = ConversationSession(whatsapp_number=whatsapp_number, session_state={})
        self._session.add(row)
        await self._session.flush()
        return row

    async def load_state(self, whatsapp_number: str) -> dict | None:
        row = await self._get(whatsapp_number)
        if row is None or not row.session_state:
            return None
        return dict(row.session_state)

    async def save_state(self, whatsapp_number: str, state: dict) -> None:
        row = await self.get_or_create(whatsapp_number)
        row.session_state = state
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def touch(self, whatsapp_number: str) -> None:
        row = await self.get_or_create(whatsapp_number)
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def _get(self, whatsapp_number: str) -> ConversationSession | None:
        result = await self._session.execute(
            select(ConversationSession).where(ConversationSession.whatsapp_number == whatsapp_number)
        )
        return result.scalar_one_or_none()
