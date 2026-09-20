"""Cart/order lines can now reference a GiftBox directly (the sellable unit the public catalogue
actually sells) instead of only a ProductVariant. Additive and nullable — `variant_id` stays on
both tables, unused, rather than being dropped in this revision.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cart_items", sa.Column("gift_box_id", sa.Integer, sa.ForeignKey("gift_boxes.id"))
    )
    op.add_column(
        "order_items", sa.Column("gift_box_id", sa.Integer, sa.ForeignKey("gift_boxes.id"))
    )


def downgrade() -> None:
    op.drop_column("order_items", "gift_box_id")
    op.drop_column("cart_items", "gift_box_id")
