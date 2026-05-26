"""add finance tracking and user page permissions

Revision ID: 8a7c3f2d1e90
Revises: 6d9f21a8c4b0
Create Date: 2026-05-26 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "8a7c3f2d1e90"
down_revision = "6d9f21a8c4b0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("page_permissions", sa.Text(), nullable=True))
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invoice_number", sa.String(length=80), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("invoice_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("customer_phone", sa.String(length=30), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_number"),
    )
    op.create_index(op.f("ix_invoices_invoice_number"), "invoices", ["invoice_number"], unique=True)
    op.create_index(op.f("ix_invoices_invoice_type"), "invoices", ["invoice_type"], unique=False)
    op.create_index(op.f("ix_invoices_order_id"), "invoices", ["order_id"], unique=False)
    op.create_index(op.f("ix_invoices_status"), "invoices", ["status"], unique=False)
    op.create_table(
        "money_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_number", sa.String(length=80), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("refund_id", sa.Integer(), nullable=True),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("transaction_type", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("gateway", sa.String(length=40), nullable=True),
        sa.Column("reference", sa.String(length=160), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=True),
        sa.Column("customer_phone", sa.String(length=30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["refund_id"], ["payment_refunds.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_number"),
    )
    op.create_index(op.f("ix_money_transactions_invoice_id"), "money_transactions", ["invoice_id"], unique=False)
    op.create_index(op.f("ix_money_transactions_order_id"), "money_transactions", ["order_id"], unique=False)
    op.create_index(op.f("ix_money_transactions_reference"), "money_transactions", ["reference"], unique=False)
    op.create_index(op.f("ix_money_transactions_refund_id"), "money_transactions", ["refund_id"], unique=False)
    op.create_index(op.f("ix_money_transactions_status"), "money_transactions", ["status"], unique=False)
    op.create_index(op.f("ix_money_transactions_transaction_number"), "money_transactions", ["transaction_number"], unique=True)
    op.create_index(op.f("ix_money_transactions_transaction_type"), "money_transactions", ["transaction_type"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_money_transactions_transaction_type"), table_name="money_transactions")
    op.drop_index(op.f("ix_money_transactions_transaction_number"), table_name="money_transactions")
    op.drop_index(op.f("ix_money_transactions_status"), table_name="money_transactions")
    op.drop_index(op.f("ix_money_transactions_refund_id"), table_name="money_transactions")
    op.drop_index(op.f("ix_money_transactions_reference"), table_name="money_transactions")
    op.drop_index(op.f("ix_money_transactions_order_id"), table_name="money_transactions")
    op.drop_index(op.f("ix_money_transactions_invoice_id"), table_name="money_transactions")
    op.drop_table("money_transactions")
    op.drop_index(op.f("ix_invoices_status"), table_name="invoices")
    op.drop_index(op.f("ix_invoices_order_id"), table_name="invoices")
    op.drop_index(op.f("ix_invoices_invoice_type"), table_name="invoices")
    op.drop_index(op.f("ix_invoices_invoice_number"), table_name="invoices")
    op.drop_table("invoices")
    op.drop_column("users", "page_permissions")
