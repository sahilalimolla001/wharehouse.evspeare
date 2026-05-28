"""Add warehouse to money transactions

Revision ID: 3f6a2b9c0d14
Revises: 2e5a8b1d4f97
Create Date: 2026-05-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "3f6a2b9c0d14"
down_revision = "2e5a8b1d4f97"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("money_transactions", sa.Column("warehouse_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_money_transactions_warehouse_id"), "money_transactions", ["warehouse_id"], unique=False)
    op.create_foreign_key(
        "fk_money_transactions_warehouse_id_warehouses",
        "money_transactions",
        "warehouses",
        ["warehouse_id"],
        ["id"],
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            update money_transactions
            set warehouse_id = (
                select orders.warehouse_id
                from orders
                where orders.id = money_transactions.order_id
            )
            where money_transactions.order_id is not null
              and money_transactions.warehouse_id is null
            """
        )
    )


def downgrade():
    op.drop_constraint("fk_money_transactions_warehouse_id_warehouses", "money_transactions", type_="foreignkey")
    op.drop_index(op.f("ix_money_transactions_warehouse_id"), table_name="money_transactions")
    op.drop_column("money_transactions", "warehouse_id")
