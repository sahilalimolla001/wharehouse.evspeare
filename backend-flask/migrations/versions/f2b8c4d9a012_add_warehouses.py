"""Add warehouses

Revision ID: f2b8c4d9a012
Revises: e1a7c9b2d604
Create Date: 2026-05-25 00:00:00.000000

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "f2b8c4d9a012"
down_revision = "e1a7c9b2d604"
branch_labels = None
depends_on = None


DEFAULT_WAREHOUSE_CODE = "kol-136-wh-01"
DEFAULT_WAREHOUSE_PINCODE = "700136"


def upgrade():
    now = datetime.utcnow()
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("pincode", sa.String(length=12), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    with op.batch_alter_table("warehouses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_warehouses_code"), ["code"], unique=False)

    warehouses = sa.table(
        "warehouses",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("pincode", sa.String),
        sa.column("address", sa.Text),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        warehouses,
        [
            {
                "code": DEFAULT_WAREHOUSE_CODE,
                "name": "Kolkata 700136 Warehouse",
                "pincode": DEFAULT_WAREHOUSE_PINCODE,
                "address": "",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    with op.batch_alter_table("warehouse_locations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("warehouse_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_warehouse_locations_warehouse_id", "warehouses", ["warehouse_id"], ["id"])
        batch_op.drop_constraint("uq_location_path", type_="unique")
        batch_op.create_unique_constraint("uq_location_warehouse_path", ["warehouse_id", "zone", "rack", "shelf", "bin_code"])

    connection = op.get_bind()
    warehouse_id = connection.execute(sa.text("select id from warehouses where code = :code"), {"code": DEFAULT_WAREHOUSE_CODE}).scalar()
    connection.execute(sa.text("update warehouse_locations set warehouse_id = :warehouse_id"), {"warehouse_id": warehouse_id})

    rows = connection.execute(sa.text("select id, zone, rack, shelf, bin_code, is_virtual from warehouse_locations")).mappings().all()
    for row in rows:
        if row["is_virtual"]:
            continue
        barcode = f"LOC:{DEFAULT_WAREHOUSE_CODE}-{row['zone']}-{row['rack']}-{row['shelf']}-{row['bin_code']}"
        connection.execute(sa.text("update warehouse_locations set barcode = :barcode where id = :id"), {"barcode": barcode, "id": row["id"]})

    with op.batch_alter_table("warehouse_locations", schema=None) as batch_op:
        batch_op.alter_column("warehouse_id", existing_type=sa.Integer(), nullable=False)


def downgrade():
    connection = op.get_bind()
    rows = connection.execute(sa.text("select id, zone, rack, shelf, bin_code, is_virtual from warehouse_locations")).mappings().all()
    for row in rows:
        if row["is_virtual"]:
            continue
        barcode = f"LOC:{row['zone']}-{row['rack']}-{row['shelf']}-{row['bin_code']}"
        connection.execute(sa.text("update warehouse_locations set barcode = :barcode where id = :id"), {"barcode": barcode, "id": row["id"]})

    with op.batch_alter_table("warehouse_locations", schema=None) as batch_op:
        batch_op.drop_constraint("uq_location_warehouse_path", type_="unique")
        batch_op.create_unique_constraint("uq_location_path", ["zone", "rack", "shelf", "bin_code"])
        batch_op.drop_constraint("fk_warehouse_locations_warehouse_id", type_="foreignkey")
        batch_op.drop_column("warehouse_id")

    with op.batch_alter_table("warehouses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_warehouses_code"))
    op.drop_table("warehouses")
