from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RecommendationLog


class RecommendationLogRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def log(self, session_id: int, recommendation_json: dict) -> RecommendationLog:
        row = RecommendationLog(session_id=session_id, recommendation_json=recommendation_json)
        self._session.add(row)
        await self._session.flush()
        return row
