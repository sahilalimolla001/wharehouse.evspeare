"""Add order warehouse

Revision ID: 9a1f3c7d2e44
Revises: 0c9d3e7a4b21
Create Date: 2026-05-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9a1f3c7d2e44"
down_revision = "0c9d3e7a4b21"
branch_labels = None
depends_on = None


DEFAULT_WAREHOUSE_CODE = "kol-136-wh-01"


def upgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("warehouse_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_orders_warehouse_id", "warehouses", ["warehouse_id"], ["id"])

    connection = op.get_bind()
    warehouse_id = connection.execute(sa.text("select id from warehouses where code = :code"), {"code": DEFAULT_WAREHOUSE_CODE}).scalar()
    if warehouse_id:
        connection.execute(sa.text("update orders set warehouse_id = :warehouse_id where warehouse_id is null"), {"warehouse_id": warehouse_id})

    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.alter_column("warehouse_id", existing_type=sa.Integer(), nullable=False)


def downgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_constraint("fk_orders_warehouse_id", type_="foreignkey")
        batch_op.drop_column("warehouse_id")
