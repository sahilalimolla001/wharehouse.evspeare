"""Add Shiprocket courier fields

Revision ID: a9c4f0d2b8e1
Revises: 7f2a1e9b4c31
Create Date: 2026-05-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a9c4f0d2b8e1"
down_revision = "7f2a1e9b4c31"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("courier_provider", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("courier_order_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("courier_shipment_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("courier_awb", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("courier_status", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("courier_response", sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f("ix_orders_courier_order_id"), ["courier_order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_orders_courier_shipment_id"), ["courier_shipment_id"], unique=False)


def downgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_orders_courier_shipment_id"))
        batch_op.drop_index(batch_op.f("ix_orders_courier_order_id"))
        batch_op.drop_column("courier_response")
        batch_op.drop_column("courier_status")
        batch_op.drop_column("courier_awb")
        batch_op.drop_column("courier_shipment_id")
        batch_op.drop_column("courier_order_id")
        batch_op.drop_column("courier_provider")
