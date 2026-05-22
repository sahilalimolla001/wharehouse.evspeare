"""Add order package dimensions

Revision ID: c6a2e91d4f35
Revises: b71d5e90f2c4
Create Date: 2026-05-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c6a2e91d4f35"
down_revision = "b71d5e90f2c4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("package_length_cm", sa.Numeric(precision=8, scale=2), nullable=True))
        batch_op.add_column(sa.Column("package_breadth_cm", sa.Numeric(precision=8, scale=2), nullable=True))
        batch_op.add_column(sa.Column("package_height_cm", sa.Numeric(precision=8, scale=2), nullable=True))
        batch_op.add_column(sa.Column("package_weight_kg", sa.Numeric(precision=8, scale=3), nullable=True))


def downgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_column("package_weight_kg")
        batch_op.drop_column("package_height_cm")
        batch_op.drop_column("package_breadth_cm")
        batch_op.drop_column("package_length_cm")
