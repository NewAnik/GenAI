"""Website transactional order flow: persistent cart, reusable addresses, and additive
buyer/shipping/payment columns on the existing `orders` table.

All changes are additive and nullable so they apply cleanly to the already-populated
production database.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-02

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "addresses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("address_type", sa.String),
        sa.Column("recipient_name", sa.String),
        sa.Column("phone", sa.String),
        sa.Column("line1", sa.Text),
        sa.Column("line2", sa.Text),
        sa.Column("city", sa.String),
        sa.Column("state", sa.String),
        sa.Column("pincode", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), server_default=sa.func.now()),
    )

    op.create_table(
        "carts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("status", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), server_default=sa.func.now()),
    )
    # One active cart lookup per user is the hot path (every cart request).
    op.create_index("ix_carts_user_id", "carts", ["user_id"], unique=False)

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cart_id", sa.Integer, sa.ForeignKey("carts.id")),
        sa.Column("variant_id", sa.Integer, sa.ForeignKey("product_variants.id")),
        sa.Column("quantity", sa.Integer),
        sa.Column("unit_price_snapshot", sa.Numeric),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now()),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"], unique=False)

    op.add_column("orders", sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")))
    op.add_column(
        "orders", sa.Column("shipping_address_id", sa.Integer, sa.ForeignKey("addresses.id"))
    )
    op.add_column("orders", sa.Column("payment_status", sa.String))
    op.create_index("ix_orders_user_id", "orders", ["user_id"], unique=False)

    op.add_column(
        "order_items",
        sa.Column("variant_id", sa.Integer, sa.ForeignKey("product_variants.id")),
    )


def downgrade() -> None:
    op.drop_column("order_items", "variant_id")

    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_column("orders", "payment_status")
    op.drop_column("orders", "shipping_address_id")
    op.drop_column("orders", "user_id")

    op.drop_index("ix_cart_items_cart_id", table_name="cart_items")
    op.drop_table("cart_items")
    op.drop_index("ix_carts_user_id", table_name="carts")
    op.drop_table("carts")
    op.drop_table("addresses")
