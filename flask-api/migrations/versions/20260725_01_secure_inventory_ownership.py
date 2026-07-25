"""Create the application schema and isolate inventory by account.

Revision ID: 20260725_01
Revises:
Create Date: 2026-07-25
"""
import hashlib

from alembic import op
import sqlalchemy as sa


revision = "20260725_01"
down_revision = None
branch_labels = None
depends_on = None


def stack_key(name, unit, expiry_date):
    parts = (name.strip().casefold(), unit.strip().casefold(), str(expiry_date))
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def create_users_table():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)


def create_sessions_table():
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("csrf_hash", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=False)


def create_inventory_table():
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("stack_key", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_items_user_stack_status",
        "inventory_items",
        ["user_id", "stack_key", "status"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_items_user_status_expiry",
        "inventory_items",
        ["user_id", "status", "expiry_date"],
        unique=False,
    )


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "users" not in table_names:
        create_users_table()
    if "sessions" not in table_names:
        create_sessions_table()

    if "inventory_items" not in table_names:
        create_inventory_table()
        return

    columns = {column["name"] for column in inspector.get_columns("inventory_items")}
    with op.batch_alter_table("inventory_items") as batch:
        if "user_id" not in columns:
            # Existing unowned rows are deliberately left inaccessible. Guessing
            # an owner would turn a migration into a data-disclosure bug.
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        if "stack_key" not in columns:
            batch.add_column(sa.Column("stack_key", sa.String(length=64), nullable=True))

    if "stack_key" not in columns:
        legacy_items = bind.execute(
            sa.text("SELECT id, name, unit, expiry_date FROM inventory_items")
        ).mappings()
        for item in legacy_items:
            bind.execute(
                sa.text("UPDATE inventory_items SET stack_key = :stack_key WHERE id = :id"),
                {"id": item["id"], "stack_key": stack_key(item["name"], item["unit"], item["expiry_date"])},
            )
        with op.batch_alter_table("inventory_items") as batch:
            batch.alter_column("stack_key", existing_type=sa.String(length=64), nullable=False)

    index_names = {index["name"] for index in sa.inspect(bind).get_indexes("inventory_items")}
    if "ix_inventory_items_user_stack_status" not in index_names:
        op.create_index(
            "ix_inventory_items_user_stack_status",
            "inventory_items",
            ["user_id", "stack_key", "status"],
            unique=False,
        )
    if "ix_inventory_items_user_status_expiry" not in index_names:
        op.create_index(
            "ix_inventory_items_user_status_expiry",
            "inventory_items",
            ["user_id", "status", "expiry_date"],
            unique=False,
        )


def downgrade():
    # This migration preserves user data. Reversing it would require deleting
    # account and inventory records, so there is intentionally no downgrade.
    pass
