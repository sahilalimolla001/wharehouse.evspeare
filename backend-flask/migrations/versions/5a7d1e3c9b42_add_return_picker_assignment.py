"""Add return picker assignment and online presence

Revision ID: 5a7d1e3c9b42
Revises: 2b6e4d8f9c10
Create Date: 2026-05-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "5a7d1e3c9b42"
down_revision = "2b6e4d8f9c10"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_online_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("customer_return_orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("assigned_to_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_customer_return_orders_assigned_to", "users", ["assigned_to_id"], ["id"])
        batch_op.create_index(batch_op.f("ix_customer_return_orders_assigned_to_id"), ["assigned_to_id"], unique=False)


def downgrade():
    with op.batch_alter_table("customer_return_orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_customer_return_orders_assigned_to_id"))
        batch_op.drop_constraint("fk_customer_return_orders_assigned_to", type_="foreignkey")
        batch_op.drop_column("assigned_to_id")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("last_online_at")
