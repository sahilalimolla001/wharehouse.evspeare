import json

from ..extensions import db
from ..models import ActivityLog, Inventory, StockIn, StockOut


def log_activity(action, message, user_id=None, entity_type=None, entity_id=None, meta=None):
    entry = ActivityLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        message=message,
        meta_json=json.dumps(meta or {}, separators=(",", ":")),
    )
    db.session.add(entry)
    return entry


def get_or_create_inventory(product_id, location_id):
    inventory = Inventory.query.filter_by(product_id=product_id, location_id=location_id).first()
    if inventory:
        return inventory

    inventory = Inventory(product_id=product_id, location_id=location_id, quantity=0, reserved_quantity=0)
    db.session.add(inventory)
    db.session.flush()
    return inventory


def receive_stock(product_id, location_id, quantity, supplier_id=None, unit_cost=0, invoice_number=None, received_by_id=None, notes=None):
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")

    inventory = get_or_create_inventory(product_id, location_id)
    inventory.quantity += quantity

    entry = StockIn(
        product_id=product_id,
        supplier_id=supplier_id,
        location_id=location_id,
        quantity=quantity,
        unit_cost=unit_cost or 0,
        invoice_number=invoice_number,
        received_by_id=received_by_id,
        notes=notes,
    )
    db.session.add(entry)
    db.session.flush()
    log_activity(
        "stock_in",
        f"Stock in: {quantity} units received",
        user_id=received_by_id,
        entity_type="StockIn",
        entity_id=entry.id,
        meta={"product_id": product_id, "location_id": location_id, "quantity": quantity},
    )
    return entry


def issue_stock(product_id, location_id, quantity, reason="sale", order_id=None, dispatched_by_id=None, notes=None):
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")

    inventory = Inventory.query.filter_by(product_id=product_id, location_id=location_id).first()
    if not inventory or inventory.available_quantity < quantity:
        raise ValueError("Not enough available stock at selected location")

    inventory.quantity -= quantity
    inventory.reserved_quantity = min(inventory.reserved_quantity, inventory.quantity)

    entry = StockOut(
        product_id=product_id,
        location_id=location_id,
        quantity=quantity,
        reason=reason,
        order_id=order_id,
        dispatched_by_id=dispatched_by_id,
        notes=notes,
    )
    db.session.add(entry)
    db.session.flush()
    log_activity(
        "stock_out",
        f"Stock out: {quantity} units issued",
        user_id=dispatched_by_id,
        entity_type="StockOut",
        entity_id=entry.id,
        meta={"product_id": product_id, "location_id": location_id, "quantity": quantity, "reason": reason},
    )
    return entry
