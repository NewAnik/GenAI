from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Org(TimestampMixin, Base):
    __tablename__ = "org"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    industry: Mapped[str | None] = mapped_column(String)
    company_size: Mapped[str | None] = mapped_column(String)
    website: Mapped[str | None] = mapped_column(String)
    gst_number: Mapped[str | None] = mapped_column(String)
    pan_number: Mapped[str | None] = mapped_column(String)
