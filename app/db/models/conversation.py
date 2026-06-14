"""The two tables that make this a bot project: per-user resumable session state and an
audit trail of every recommendation the bot ever produced."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship


from app.db.base import Base


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String, index=True)
    session_state: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    recommendation_logs: Mapped[list["RecommendationLog"]] = relationship(back_populates="session")


class RecommendationLog(Base):
    __tablename__ = "recommendation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("conversation_sessions.id"))
    recommendation_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), server_default=func.now())

    session: Mapped["ConversationSession | None"] = relationship(back_populates="recommendation_logs")
