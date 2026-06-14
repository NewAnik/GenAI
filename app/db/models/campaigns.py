from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin


class Campaign(CreatedAtMixin, Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("org.id"))
    campaign_name: Mapped[str | None] = mapped_column(String)
    budget: Mapped[Decimal | None] = mapped_column(Numeric)
    employee_count: Mapped[int | None] = mapped_column(Integer)
    event_type: Mapped[str | None] = mapped_column(String)
    start_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String)

    recipients: Mapped[list["CampaignRecipient"]] = relationship(back_populates="campaign")


class CampaignRecipient(Base):
    __tablename__ = "campaign_recipients"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"))
    employee_name: Mapped[str | None] = mapped_column(String)
    employee_email: Mapped[str | None] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    pincode: Mapped[str | None] = mapped_column(String)

    campaign: Mapped["Campaign | None"] = relationship(back_populates="recipients")
