"""Add coupons

Revision ID: 8a7b6c5d4e30
Revises: 3f6a2b9c0d14
Create Date: 2026-05-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "8a7b6c5d4e30"
down_revision = "3f6a2b9c0d14"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "coupons",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("discount_type", sa.String(length=20), nullable=False),
        sa.Column("discount_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("min_order_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("max_discount_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_coupons_code"), "coupons", ["code"], unique=True)
    op.create_index(op.f("ix_coupons_is_active"), "coupons", ["is_active"], unique=False)

    op.create_table(
        "coupon_redemptions",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("coupon_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("customer_phone", sa.String(length=30), nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=False),
        sa.Column("source_payload", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("coupon_id", "customer_phone", name="uq_coupon_redemption_phone"),
    )
    op.create_index(op.f("ix_coupon_redemptions_coupon_id"), "coupon_redemptions", ["coupon_id"], unique=False)
    op.create_index(op.f("ix_coupon_redemptions_customer_phone"), "coupon_redemptions", ["customer_phone"], unique=False)
    op.create_index(op.f("ix_coupon_redemptions_order_id"), "coupon_redemptions", ["order_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_coupon_redemptions_order_id"), table_name="coupon_redemptions")
    op.drop_index(op.f("ix_coupon_redemptions_customer_phone"), table_name="coupon_redemptions")
    op.drop_index(op.f("ix_coupon_redemptions_coupon_id"), table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")
    op.drop_index(op.f("ix_coupons_is_active"), table_name="coupons")
    op.drop_index(op.f("ix_coupons_code"), table_name="coupons")
    op.drop_table("coupons")
