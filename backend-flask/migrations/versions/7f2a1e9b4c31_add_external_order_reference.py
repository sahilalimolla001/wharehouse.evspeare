"""Add external order reference

Revision ID: 7f2a1e9b4c31
Revises: 3c62c679a853
Create Date: 2026-05-17 21:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "7f2a1e9b4c31"
down_revision = "3c62c679a853"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("external_source", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("external_order_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("source_payload", sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f("ix_orders_external_source"), ["external_source"], unique=False)
        batch_op.create_index(batch_op.f("ix_orders_external_order_id"), ["external_order_id"], unique=False)
        batch_op.create_unique_constraint("uq_order_external_reference", ["external_source", "external_order_id"])


def downgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_constraint("uq_order_external_reference", type_="unique")
        batch_op.drop_index(batch_op.f("ix_orders_external_order_id"))
        batch_op.drop_index(batch_op.f("ix_orders_external_source"))
        batch_op.drop_column("source_payload")
        batch_op.drop_column("external_order_id")
        batch_op.drop_column("external_source")
