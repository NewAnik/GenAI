"""Add `users.cognito_sub`, the join key between AWS Cognito identities and this table's
profile rows, for the storefront API's Cognito-based auth (see storefront/).

`password_hash` is intentionally left in place, unused by the storefront Lambda — this table
is shared with wrapped-and-more-admin, so dropping columns is out of scope for this revision.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("cognito_sub", sa.Text))
    op.create_unique_constraint("uq_users_cognito_sub", "users", ["cognito_sub"])


def downgrade() -> None:
    op.drop_constraint("uq_users_cognito_sub", "users", type_="unique")
    op.drop_column("users", "cognito_sub")
