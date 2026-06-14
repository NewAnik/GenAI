"""Additive indices/constraints to support the WhatsApp bot.

Run AFTER `alembic stamp head` against the existing, already-populated database.
Adds:
  - index on conversation_sessions.whatsapp_number (hot lookup path on every webhook call)
  - unique constraint on product_embeddings.product_id (enables a true ON CONFLICT upsert
    in the embeddings job; the source schema defines no PK/unique key on this table)

Revision ID: 0001
Revises:
Create Date: 2026-06-07

"""
from alembic import op
import sqlalchemy as sa  # noqa: F401 -- part of alembic's standard migration template

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_conversation_sessions_whatsapp_number",
        "conversation_sessions",
        ["whatsapp_number"],
        unique=False,
        if_not_exists=True,
    )
    op.create_unique_constraint(
        "uq_product_embeddings_product_id",
        "product_embeddings",
        ["product_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_product_embeddings_product_id", "product_embeddings", type_="unique")
    op.drop_index("ix_conversation_sessions_whatsapp_number", table_name="conversation_sessions")
