"""Add user warehouse mapping

Revision ID: 0c9d3e7a4b21
Revises: f2b8c4d9a012
Create Date: 2026-05-25 00:00:00.000000

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "0c9d3e7a4b21"
down_revision = "f2b8c4d9a012"
branch_labels = None
depends_on = None


DEFAULT_WAREHOUSE_CODE = "kol-136-wh-01"


def upgrade():
    now = datetime.utcnow()
    op.create_table(
        "user_warehouses",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("user_id", "warehouse_id"),
    )

    connection = op.get_bind()
    warehouse_id = connection.execute(sa.text("select id from warehouses where code = :code"), {"code": DEFAULT_WAREHOUSE_CODE}).scalar()
    user_ids = [row[0] for row in connection.execute(sa.text("select id from users")).all()]
    if warehouse_id:
        op.bulk_insert(
            sa.table(
                "user_warehouses",
                sa.column("user_id", sa.Integer),
                sa.column("warehouse_id", sa.Integer),
                sa.column("created_at", sa.DateTime),
            ),
            [{"user_id": user_id, "warehouse_id": warehouse_id, "created_at": now} for user_id in user_ids],
        )

    op.drop_constraint("warehouse_locations_barcode_key", "warehouse_locations", type_="unique")
    rows = connection.execute(sa.text("select id, zone, rack, shelf, bin_code, is_virtual from warehouse_locations")).mappings().all()
    for row in rows:
        if row["is_virtual"]:
            continue
        barcode = f"LOC:{row['zone']}-{row['rack']}-{row['shelf']}-{row['bin_code']}"
        connection.execute(sa.text("update warehouse_locations set barcode = :barcode where id = :id"), {"barcode": barcode, "id": row["id"]})


def downgrade():
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            select wl.id, w.code, wl.zone, wl.rack, wl.shelf, wl.bin_code, wl.is_virtual
            from warehouse_locations wl
            join warehouses w on w.id = wl.warehouse_id
            """
        )
    ).mappings().all()
    for row in rows:
        if row["is_virtual"]:
            continue
        barcode = f"LOC:{row['code']}-{row['zone']}-{row['rack']}-{row['shelf']}-{row['bin_code']}"
        connection.execute(sa.text("update warehouse_locations set barcode = :barcode where id = :id"), {"barcode": barcode, "id": row["id"]})

    op.create_unique_constraint("warehouse_locations_barcode_key", "warehouse_locations", ["barcode"])
    op.drop_table("user_warehouses")
