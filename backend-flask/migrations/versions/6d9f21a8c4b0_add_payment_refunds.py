"""add payment refunds

Revision ID: 6d9f21a8c4b0
Revises: 4e8a2c1d9b73
Create Date: 2026-05-26 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "6d9f21a8c4b0"
down_revision = "4e8a2c1d9b73"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("refund_number", sa.String(length=80), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("website_order_id", sa.String(length=120), nullable=True),
        sa.Column("request_id", sa.String(length=120), nullable=True),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("customer_phone", sa.String(length=30), nullable=True),
        sa.Column("gateway", sa.String(length=40), nullable=False),
        sa.Column("gateway_payment_id", sa.String(length=120), nullable=True),
        sa.Column("gateway_transaction_id", sa.String(length=120), nullable=True),
        sa.Column("refund_token", sa.String(length=23), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), nullable=True),
        sa.Column("gateway_response", sa.Text(), nullable=True),
        sa.Column("source_payload", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refund_number"),
        sa.UniqueConstraint("request_id"),
        sa.UniqueConstraint("refund_token"),
    )
    op.create_index(op.f("ix_payment_refunds_gateway_payment_id"), "payment_refunds", ["gateway_payment_id"], unique=False)
    op.create_index(op.f("ix_payment_refunds_gateway_transaction_id"), "payment_refunds", ["gateway_transaction_id"], unique=False)
    op.create_index(op.f("ix_payment_refunds_order_id"), "payment_refunds", ["order_id"], unique=False)
    op.create_index(op.f("ix_payment_refunds_refund_number"), "payment_refunds", ["refund_number"], unique=True)
    op.create_index(op.f("ix_payment_refunds_refund_token"), "payment_refunds", ["refund_token"], unique=True)
    op.create_index(op.f("ix_payment_refunds_request_id"), "payment_refunds", ["request_id"], unique=True)
    op.create_index(op.f("ix_payment_refunds_status"), "payment_refunds", ["status"], unique=False)
    op.create_index(op.f("ix_payment_refunds_website_order_id"), "payment_refunds", ["website_order_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_payment_refunds_website_order_id"), table_name="payment_refunds")
    op.drop_index(op.f("ix_payment_refunds_status"), table_name="payment_refunds")
    op.drop_index(op.f("ix_payment_refunds_request_id"), table_name="payment_refunds")
    op.drop_index(op.f("ix_payment_refunds_refund_token"), table_name="payment_refunds")
    op.drop_index(op.f("ix_payment_refunds_refund_number"), table_name="payment_refunds")
    op.drop_index(op.f("ix_payment_refunds_order_id"), table_name="payment_refunds")
    op.drop_index(op.f("ix_payment_refunds_gateway_transaction_id"), table_name="payment_refunds")
    op.drop_index(op.f("ix_payment_refunds_gateway_payment_id"), table_name="payment_refunds")
    op.drop_table("payment_refunds")
