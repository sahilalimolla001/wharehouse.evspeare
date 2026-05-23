"""Add return items and virtual bins

Revision ID: e1a7c9b2d604
Revises: d8f4b2c7e901
Create Date: 2026-05-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


revision = "e1a7c9b2d604"
down_revision = "d8f4b2c7e901"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("warehouse_locations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_virtual", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("customer_return_orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("approved_by_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_customer_return_orders_approved_by", "users", ["approved_by_id"], ["id"])

    op.create_table(
        "customer_return_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("return_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("expected_quantity", sa.Integer(), nullable=False),
        sa.Column("picked_quantity", sa.Integer(), nullable=False),
        sa.Column("stocked_quantity", sa.Integer(), nullable=False),
        sa.Column("issue_quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["return_order_id"], ["customer_return_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("customer_return_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_customer_return_items_return_order_id"), ["return_order_id"], unique=False)

    locations = sa.table(
        "warehouse_locations",
        sa.column("zone", sa.String),
        sa.column("rack", sa.String),
        sa.column("shelf", sa.String),
        sa.column("bin_code", sa.String),
        sa.column("barcode", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_virtual", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    connection = op.get_bind()
    now = datetime.utcnow()
    for row in [
        {"zone": "RC", "rack": "DA", "shelf": "Virtual", "bin_code": "01", "barcode": "RC-DA-01"},
        {"zone": "RE", "rack": "01", "shelf": "Virtual", "bin_code": "01", "barcode": "RE-01-01"},
    ]:
        exists = connection.execute(sa.text("select id from warehouse_locations where barcode = :barcode"), {"barcode": row["barcode"]}).first()
        if exists:
            connection.execute(sa.text("update warehouse_locations set is_virtual = :virtual, is_active = :active where barcode = :barcode"), {"virtual": True, "active": True, "barcode": row["barcode"]})
        else:
            op.bulk_insert(locations, [{**row, "is_active": True, "is_virtual": True, "created_at": now, "updated_at": now}])


def downgrade():
    with op.batch_alter_table("customer_return_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_customer_return_items_return_order_id"))
    op.drop_table("customer_return_items")

    with op.batch_alter_table("customer_return_orders", schema=None) as batch_op:
        batch_op.drop_constraint("fk_customer_return_orders_approved_by", type_="foreignkey")
        batch_op.drop_column("approved_by_id")

    with op.batch_alter_table("warehouse_locations", schema=None) as batch_op:
        batch_op.drop_column("is_virtual")
