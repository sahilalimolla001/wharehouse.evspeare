from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from ..extensions import db
from ..models import CustomerReturnItem, CustomerReturnOrder, Inventory, Order, WarehouseLocation
from ..utils.picker_ops import online_pickers_for_warehouse
from ..utils.stock import log_activity
from ..utils.time import india_now
from .api import ensure_virtual_return_bins
from .auth import get_current_user, role_required, selected_warehouse


returns_bp = Blueprint("returns", __name__)


@returns_bp.route("/customer-returns", methods=["GET", "POST"])
@role_required("manager", "staff")
def customer_returns():
    ensure_virtual_return_bins()
    db.session.commit()
    if request.method == "POST":
        original_order = find_original_order(request.form.get("order_lookup"))
        return_order = CustomerReturnOrder(
            return_number=request.form.get("return_number", "").strip() or next_return_number(),
            order_id=original_order.id if original_order else None,
            website_order_id=(original_order.external_order_id if original_order else request.form.get("website_order_id", "").strip()) or "",
            customer_name=(request.form.get("customer_name", "").strip() or (original_order.customer_name if original_order else "")),
            customer_phone=(request.form.get("customer_phone", "").strip() or (original_order.customer_phone if original_order else "")),
            reason=request.form.get("reason", "other").strip() or "other",
            status=request.form.get("status", "requested").strip() or "requested",
            refund_status=request.form.get("refund_status", "pending").strip() or "pending",
            notes=request.form.get("notes", "").strip(),
        )
        if not return_order.customer_name:
            flash("Customer name is required.", "warning")
            return redirect(url_for("returns.customer_returns"))
        if original_order:
            for order_item in original_order.items:
                return_order.items.append(
                    CustomerReturnItem(
                        product_id=order_item.product_id,
                        expected_quantity=order_item.quantity,
                    )
                )
        db.session.add(return_order)
        db.session.commit()
        flash("Customer return order created.", "success")
        return redirect(url_for("returns.customer_returns"))

    warehouse = selected_warehouse()
    returns_query = CustomerReturnOrder.query.outerjoin(Order)
    recent_orders_query = Order.query
    if warehouse:
        returns_query = returns_query.filter(or_(CustomerReturnOrder.order_id.is_(None), Order.warehouse_id == warehouse.id))
        recent_orders_query = recent_orders_query.filter(Order.warehouse_id == warehouse.id)
    returns = returns_query.order_by(CustomerReturnOrder.created_at.desc()).limit(200).all()
    recent_orders = recent_orders_query.order_by(Order.created_at.desc()).limit(100).all()
    online_pickers = online_pickers_for_warehouse(warehouse)
    virtual_bins = (
        WarehouseLocation.query.filter_by(is_virtual=True)
        .order_by(WarehouseLocation.zone, WarehouseLocation.rack, WarehouseLocation.bin_code)
        .all()
    )
    virtual_inventory = (
        Inventory.query.join(WarehouseLocation)
        .filter(WarehouseLocation.is_virtual.is_(True), Inventory.quantity > 0)
        .order_by(WarehouseLocation.zone, WarehouseLocation.rack, WarehouseLocation.bin_code)
        .all()
    )
    return render_template(
        "customer_returns.html",
        returns=returns,
        recent_orders=recent_orders,
        online_pickers=online_pickers,
        virtual_bins=virtual_bins,
        virtual_inventory=virtual_inventory,
    )


@returns_bp.post("/customer-returns/<int:return_id>/status")
@role_required("manager", "staff")
def update_customer_return(return_id):
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
    return_order.status = request.form.get("status", return_order.status).strip() or return_order.status
    return_order.refund_status = request.form.get("refund_status", return_order.refund_status).strip() or return_order.refund_status
    if return_order.status in {"received", "rejected", "refunded"} and not return_order.resolved_at:
        return_order.resolved_at = india_now()
    db.session.commit()
    flash("Return order updated.", "success")
    return redirect(url_for("returns.customer_returns"))


@returns_bp.post("/customer-returns/<int:return_id>/approve")
@role_required("manager", "staff")
def approve_customer_return(return_id):
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
    if not return_order.items and return_order.order:
        for order_item in return_order.order.items:
            return_order.items.append(
                CustomerReturnItem(
                    product_id=order_item.product_id,
                    expected_quantity=order_item.quantity,
                )
            )
    if not return_order.items:
        flash("Return approval needs at least one item.", "warning")
        return redirect(url_for("returns.customer_returns"))
    return_order.status = "approved"
    user = get_current_user()
    return_order.approved_by_id = user.id if user else None
    db.session.commit()
    flash("Return approved. Online picker assign karne ke baad picker app mein dikhega.", "success")
    return redirect(url_for("returns.customer_returns"))


@returns_bp.post("/customer-returns/<int:return_id>/assign-picker")
@role_required("manager", "staff")
def assign_customer_return_picker(return_id):
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
    warehouse = selected_warehouse()
    if warehouse and return_order.order and return_order.order.warehouse_id != warehouse.id:
        flash("Return selected warehouse ka nahi hai.", "warning")
        return redirect(url_for("returns.customer_returns"))
    if return_order.status in {"received", "rejected", "refunded"}:
        flash("Completed return picker ko assign nahi ho sakta.", "warning")
        return redirect(url_for("returns.customer_returns"))
    try:
        picker_id = int(request.form.get("picker_id", ""))
    except (TypeError, ValueError):
        picker_id = None
    picker = next((candidate for candidate in online_pickers_for_warehouse(warehouse) if candidate.id == picker_id), None)
    if not picker:
        flash("Selected picker ab online nahi hai. Online picker choose karo.", "danger")
        return redirect(url_for("returns.customer_returns"))
    return_order.assigned_to_id = picker.id
    user = get_current_user()
    log_activity(
        "return_picker_assign",
        f"Assigned {return_order.return_number} to {picker.full_name} / {picker.picker_code or picker.id}",
        user_id=user.id if user else None,
        entity_type="CustomerReturnOrder",
        entity_id=return_order.id,
    )
    db.session.commit()
    flash(f"{return_order.return_number} assigned to Picker ID {picker.picker_code or picker.id}.", "success")
    return redirect(url_for("returns.customer_returns"))


def find_original_order(value):
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    warehouse = selected_warehouse()
    if cleaned.isdigit():
        order = Order.query.get(int(cleaned))
        if order and (not warehouse or order.warehouse_id == warehouse.id):
            return order
    query = Order.query.filter(or_(Order.order_number == cleaned, Order.external_order_id == cleaned))
    if warehouse:
        query = query.filter(Order.warehouse_id == warehouse.id)
    return query.first()


def next_return_number():
    return f"RET-{india_now().strftime('%Y%m%d%H%M%S')}"
