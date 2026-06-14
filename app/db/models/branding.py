from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LogoAsset(Base):
    __tablename__ = "logo_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("org.id"))
    file_url: Mapped[str | None] = mapped_column(Text)
    file_type: Mapped[str | None] = mapped_column(String)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), server_default=func.now())


class BrandingRequest(Base):
    __tablename__ = "branding_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"))
    logo_asset_id: Mapped[int | None] = mapped_column(ForeignKey("logo_assets.id"))
    branding_type: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), server_default=func.now())

    logo_asset: Mapped["LogoAsset | None"] = relationship()
