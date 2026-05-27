"""Add item not found reports

Revision ID: 1d4f7a9c2e86
Revises: 5a7d1e3c9b42
Create Date: 2026-05-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "1d4f7a9c2e86"
down_revision = "5a7d1e3c9b42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "item_not_found_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("order_item_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("picker_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("stock_deducted_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["warehouse_locations.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_items.id"]),
        sa.ForeignKeyConstraint(["picker_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_item_not_found_reports_order_id", "item_not_found_reports", ["order_id"], unique=False)
    op.create_index("ix_item_not_found_reports_order_item_id", "item_not_found_reports", ["order_item_id"], unique=False)
    op.create_index("ix_item_not_found_reports_product_id", "item_not_found_reports", ["product_id"], unique=False)
    op.create_index("ix_item_not_found_reports_warehouse_id", "item_not_found_reports", ["warehouse_id"], unique=False)
    op.create_index("ix_item_not_found_reports_picker_id", "item_not_found_reports", ["picker_id"], unique=False)


def downgrade():
    op.drop_index("ix_item_not_found_reports_picker_id", table_name="item_not_found_reports")
    op.drop_index("ix_item_not_found_reports_warehouse_id", table_name="item_not_found_reports")
    op.drop_index("ix_item_not_found_reports_product_id", table_name="item_not_found_reports")
    op.drop_index("ix_item_not_found_reports_order_item_id", table_name="item_not_found_reports")
    op.drop_index("ix_item_not_found_reports_order_id", table_name="item_not_found_reports")
    op.drop_table("item_not_found_reports")
