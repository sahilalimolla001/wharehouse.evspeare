"""add picker codes

Revision ID: 2b6e4d8f9c10
Revises: 8a7c3f2d1e90
Create Date: 2026-05-26 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "2b6e4d8f9c10"
down_revision = "8a7c3f2d1e90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("picker_code", sa.String(length=5), nullable=True))
    op.create_index(op.f("ix_users_picker_code"), "users", ["picker_code"], unique=True)


def downgrade():
    op.drop_index(op.f("ix_users_picker_code"), table_name="users")
    op.drop_column("users", "picker_code")
