"""Add central panel settings

Revision ID: 2e5a8b1d4f97
Revises: 1d4f7a9c2e86
Create Date: 2026-05-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "2e5a8b1d4f97"
down_revision = "1d4f7a9c2e86"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "central_panel_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=80), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_central_panel_settings_section", "central_panel_settings", ["section"], unique=True)


def downgrade():
    op.drop_index("ix_central_panel_settings_section", table_name="central_panel_settings")
    op.drop_table("central_panel_settings")
