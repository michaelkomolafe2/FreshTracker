"""Add alert state and waste tracking.

Revision ID: 20260725_02
Revises: 20260725_01
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa


revision = "20260725_02"
down_revision = "20260725_01"
branch_labels = None
depends_on = None


waste_action = sa.Enum(
    "used",
    "wasted",
    name="waste_action",
    create_constraint=True,
)


def upgrade():
    with op.batch_alter_table("inventory_items") as batch:
        batch.add_column(
            sa.Column(
                "alert_sent",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )

    op.create_table(
        "waste_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", waste_action, nullable=False),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["item_id"], ["inventory_items.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_waste_logs_user_logged_at",
        "waste_logs",
        ["user_id", "logged_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_waste_logs_user_logged_at", table_name="waste_logs")
    op.drop_table("waste_logs")
    waste_action.drop(op.get_bind(), checkfirst=True)

    with op.batch_alter_table("inventory_items") as batch:
        batch.drop_column("alert_sent")
