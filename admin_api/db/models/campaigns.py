from __future__ import annotations

from peewee import CharField, ForeignKeyField, TextField

from db.models.base import BaseModel


class Campaign(BaseModel):
    class Meta:
        table_name = "campaigns"

    campaign_name = CharField(null=True)


class CampaignRecipient(BaseModel):
    class Meta:
        table_name = "campaign_recipients"

    campaign = ForeignKeyField(Campaign, backref="recipients", column_name="campaign_id")
    employee_name = CharField(null=True)
    employee_email = CharField(null=True)
    address = TextField(null=True)
    city = CharField(null=True)
    state = CharField(null=True)
    pincode = CharField(null=True)
