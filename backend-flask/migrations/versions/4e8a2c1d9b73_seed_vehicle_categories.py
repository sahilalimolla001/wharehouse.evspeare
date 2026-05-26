"""Seed vehicle product categories

Revision ID: 4e8a2c1d9b73
Revises: 9a1f3c7d2e44
Create Date: 2026-05-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


revision = "4e8a2c1d9b73"
down_revision = "9a1f3c7d2e44"
branch_labels = None
depends_on = None


VEHICLE_CATEGORIES = ["E Scooty", "E Rickshaw", "Auto", "Car"]
DEFAULT_CATEGORY = "E Rickshaw"


def upgrade():
    connection = op.get_bind()
    now = datetime.utcnow()
    categories = sa.table(
        "categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    for name in VEHICLE_CATEGORIES:
        exists = connection.execute(sa.text("select id from categories where lower(name) = lower(:name)"), {"name": name}).first()
        if not exists:
            op.bulk_insert(categories, [{"name": name, "description": f"{name} spare parts", "created_at": now, "updated_at": now}])

    default_row = connection.execute(sa.text("select id from categories where lower(name) = lower(:name)"), {"name": DEFAULT_CATEGORY}).first()
    if default_row:
        connection.execute(sa.text("update products set category_id = :category_id"), {"category_id": default_row[0]})


def downgrade():
    connection = op.get_bind()
    for name in VEHICLE_CATEGORIES:
        connection.execute(sa.text("update products set category_id = null where category_id in (select id from categories where name = :name)"), {"name": name})
        connection.execute(sa.text("delete from categories where name = :name"), {"name": name})
