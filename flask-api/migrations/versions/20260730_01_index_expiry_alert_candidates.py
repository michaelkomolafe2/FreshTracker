"""Index inventory items for the nightly expiry alert scan.

Revision ID: 20260730_01
Revises: 20260725_02
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa


revision = "20260730_01"
down_revision = "20260725_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_inventory_items_expiry_alert_candidates",
        "inventory_items",
        ["expiry_date"],
        unique=False,
        postgresql_where=sa.text(
            "alert_sent = false AND status = 'active'"
        ),
        sqlite_where=sa.text(
            "alert_sent = false AND status = 'active'"
        ),
    )


def downgrade():
    op.drop_index(
        "ix_inventory_items_expiry_alert_candidates",
        table_name="inventory_items",
    )
