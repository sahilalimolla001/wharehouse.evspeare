from datetime import datetime, timedelta

from sqlalchemy import case

from ..models import Inventory, Order, User, WarehouseLocation
from .time import india_now


ONLINE_PICKER_WINDOW_SECONDS = 45


def pickable_statuses():
    return ["pending", "picking"]


def picker_online_from_request(request):
    return str(request.headers.get("X-Picker-Online") or "").lower() in {"1", "true", "yes", "online"}


def update_picker_presence(user, request):
    if not user or user.role != "picker" or "X-Picker-Online" not in request.headers:
        return False
    user.last_online_at = india_now() if picker_online_from_request(request) else None
    return True


def online_pickers_for_warehouse(warehouse=None):
    cutoff = india_now() - timedelta(seconds=ONLINE_PICKER_WINDOW_SECONDS)
    query = User.query.filter(
        User.role == "picker",
        User.is_active.is_(True),
        User.last_online_at >= cutoff,
    )
    if warehouse:
        query = query.filter(User.warehouses.any(id=warehouse.id))
    return query.order_by(User.full_name).all()


def product_pick_location(product, warehouse_id=None):
    query = (
        Inventory.query.join(WarehouseLocation)
        .filter(
            Inventory.product_id == product.id,
            WarehouseLocation.is_virtual.is_(False),
            WarehouseLocation.is_active.is_(True),
            (Inventory.quantity - Inventory.reserved_quantity) > 0,
        )
    )
    if warehouse_id:
        query = query.filter(WarehouseLocation.warehouse_id == warehouse_id)
    row = (
        query.order_by(
            WarehouseLocation.zone,
            WarehouseLocation.rack,
            WarehouseLocation.shelf,
            WarehouseLocation.bin_code,
        ).first()
    )
    if not row:
        return None
    return {
        "inventory_id": row.id,
        "available_quantity": row.available_quantity,
        "location": {
            "id": row.location.id,
            "barcode": row.location.barcode,
            "full_code": row.location.full_code,
            "zone": row.location.zone,
            "rack": row.location.rack,
            "shelf": row.location.shelf,
            "bin_code": row.location.bin_code,
        },
    }


def order_bin_analysis(order):
    route_bins = []
    rows = []
    ready = True
    for item in order.items:
        location = product_pick_location(item.product, order.warehouse_id)
        available = int(location["available_quantity"]) if location else 0
        remaining = max(int(item.quantity or 0) - int(item.picked_quantity or 0), 0)
        shortage = max(remaining - available, 0)
        if shortage:
            ready = False
        if location and location["location"]["full_code"] not in route_bins:
            route_bins.append(location["location"]["full_code"])
        rows.append(
            {
                "item_id": item.id,
                "sku": item.product.sku,
                "product": item.product.name,
                "quantity": item.quantity,
                "picked_quantity": item.picked_quantity,
                "remaining_quantity": remaining,
                "available_quantity": available,
                "shortage_quantity": shortage,
                "recommended_bin": location,
            }
        )
    return {
        "ready": ready,
        "route_bins": route_bins,
        "items": rows,
    }


def picker_workload(user_id):
    return Order.query.filter(
        Order.assigned_to_id == user_id,
        Order.status.in_(pickable_statuses()),
    ).count()


def auto_assign_order_to_picker(user, warehouse=None):
    if not user or user.role not in {"picker", "packer", "delivery"}:
        return None
    if picker_workload(user.id) > 0:
        return None
    query = Order.query.filter(
        Order.status == "pending",
        Order.assigned_to_id.is_(None),
    )
    if warehouse:
        query = query.filter(Order.warehouse_id == warehouse.id)
    order = query.order_by(priority_rank_expression(), Order.created_at).first()
    if not order:
        return None
    order.assigned_to_id = user.id
    order.status = "picking"
    return order


def priority_rank_expression():
    return case(
        (Order.priority == "urgent", 0),
        (Order.priority == "high", 1),
        else_=2,
    )


def picker_ops_summary(warehouse=None):
    query = Order.query.filter(Order.status.in_(["pending", "picking", "packed"]))
    picker_query = User.query.filter(User.role.in_(["picker", "packer", "delivery"]), User.is_active.is_(True))
    if warehouse:
        query = query.filter(Order.warehouse_id == warehouse.id)
        picker_query = picker_query.filter(User.warehouses.any(id=warehouse.id))
    orders = query.order_by(priority_rank_expression(), Order.created_at).all()
    pickers = picker_query.order_by(User.full_name).all()
    processing_orders = [order for order in orders if order_has_picked_item(order)]
    unassigned_orders = [order for order in orders if not order.assigned_to_id and not order_has_picked_item(order)]
    assigned_orders = [order for order in orders if order.assigned_to_id and not order_has_picked_item(order)]
    active_pickers = []
    for picker in pickers:
        picker_orders = [order for order in orders if order.assigned_to_id == picker.id]
        picker_processing = sum(1 for order in picker_orders if order_has_picked_item(order))
        active_pickers.append(
            {
                "user": picker,
                "live_count": len(picker_orders),
                "processing_count": picker_processing,
                "status": "Processing" if picker_processing else "Available",
            }
        )
    return {
        "orders": orders,
        "unassigned_orders": unassigned_orders,
        "assigned_orders": assigned_orders,
        "processing_orders": processing_orders,
        "active_pickers": active_pickers,
        "live_count": len(orders),
        "unassigned_count": len(unassigned_orders),
        "assigned_count": len(assigned_orders),
        "processing_count": len(processing_orders),
    }


def order_has_picked_item(order):
    return any(int(item.picked_quantity or 0) > 0 for item in order.items)
