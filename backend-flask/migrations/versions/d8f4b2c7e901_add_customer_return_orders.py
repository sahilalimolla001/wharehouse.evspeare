"""Add customer return orders

Revision ID: d8f4b2c7e901
Revises: c6a2e91d4f35
Create Date: 2026-05-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d8f4b2c7e901"
down_revision = "c6a2e91d4f35"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_return_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("return_number", sa.String(length=80), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("website_order_id", sa.String(length=120), nullable=True),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("customer_phone", sa.String(length=30), nullable=True),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("refund_status", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("return_number"),
    )
    with op.batch_alter_table("customer_return_orders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_customer_return_orders_order_id"), ["order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_customer_return_orders_return_number"), ["return_number"], unique=False)
        batch_op.create_index(batch_op.f("ix_customer_return_orders_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_customer_return_orders_website_order_id"), ["website_order_id"], unique=False)


def downgrade():
    with op.batch_alter_table("customer_return_orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_customer_return_orders_website_order_id"))
        batch_op.drop_index(batch_op.f("ix_customer_return_orders_status"))
        batch_op.drop_index(batch_op.f("ix_customer_return_orders_return_number"))
        batch_op.drop_index(batch_op.f("ix_customer_return_orders_order_id"))
    op.drop_table("customer_return_orders")
