"""Add customer support queries

Revision ID: 9f4a2d7c8b16
Revises: 8a7b6c5d4e30
Create Date: 2026-06-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9f4a2d7c8b16"
down_revision = "8a7b6c5d4e30"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_support_queries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=80), nullable=True),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("customer_phone", sa.String(length=30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.Column("assigned_to_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_support_queries_external_id", "customer_support_queries", ["external_id"], unique=True)
    op.create_index("ix_customer_support_queries_customer_phone", "customer_support_queries", ["customer_phone"], unique=False)
    op.create_index("ix_customer_support_queries_status", "customer_support_queries", ["status"], unique=False)


def downgrade():
    op.drop_index("ix_customer_support_queries_status", table_name="customer_support_queries")
    op.drop_index("ix_customer_support_queries_customer_phone", table_name="customer_support_queries")
    op.drop_index("ix_customer_support_queries_external_id", table_name="customer_support_queries")
    op.drop_table("customer_support_queries")
