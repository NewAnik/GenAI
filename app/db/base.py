"""Declarative base + shared mixins for SQLAlchemy 2.0 models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """created_at / updated_at columns matching the schema's `timestamp without time zone`."""

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )


class CreatedAtMixin:
    """created_at-only columns, for tables in the schema that lack updated_at."""

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), server_default=func.now()
    )
