"""Add Shiprocket webhook events

Revision ID: b71d5e90f2c4
Revises: a9c4f0d2b8e1
Create Date: 2026-05-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b71d5e90f2c4"
down_revision = "a9c4f0d2b8e1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shiprocket_webhook_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=True),
        sa.Column("shiprocket_order_id", sa.String(length=120), nullable=True),
        sa.Column("shipment_id", sa.String(length=120), nullable=True),
        sa.Column("awb", sa.String(length=120), nullable=True),
        sa.Column("current_status", sa.String(length=120), nullable=True),
        sa.Column("previous_status", sa.String(length=120), nullable=True),
        sa.Column("status_code", sa.String(length=80), nullable=True),
        sa.Column("courier_name", sa.String(length=160), nullable=True),
        sa.Column("location", sa.String(length=180), nullable=True),
        sa.Column("event_time", sa.DateTime(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("headers_json", sa.Text(), nullable=True),
        sa.Column("received_ip", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("shiprocket_webhook_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_shiprocket_webhook_events_awb"), ["awb"], unique=False)
        batch_op.create_index(batch_op.f("ix_shiprocket_webhook_events_current_status"), ["current_status"], unique=False)
        batch_op.create_index(batch_op.f("ix_shiprocket_webhook_events_order_id"), ["order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_shiprocket_webhook_events_shiprocket_order_id"), ["shiprocket_order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_shiprocket_webhook_events_shipment_id"), ["shipment_id"], unique=False)


def downgrade():
    with op.batch_alter_table("shiprocket_webhook_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_shiprocket_webhook_events_shipment_id"))
        batch_op.drop_index(batch_op.f("ix_shiprocket_webhook_events_shiprocket_order_id"))
        batch_op.drop_index(batch_op.f("ix_shiprocket_webhook_events_order_id"))
        batch_op.drop_index(batch_op.f("ix_shiprocket_webhook_events_current_status"))
        batch_op.drop_index(batch_op.f("ix_shiprocket_webhook_events_awb"))
    op.drop_table("shiprocket_webhook_events")
