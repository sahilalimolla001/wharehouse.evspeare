import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from ..extensions import db
from ..models import Order, OrderItem, Product, User
from ..utils.order_payload import is_fast_delivery_order, order_automation_summary
from ..utils.time import india_now
from .shiprocket import ShiprocketError, dispatch_order_with_shiprocket
from .auth import accessible_warehouses, get_current_user, login_required, role_required, selected_warehouse, user_has_role

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/orders")
@login_required
def orders():
    user = get_current_user()
    warehouse = selected_warehouse(user)
    query = Order.query
    if warehouse:
        query = query.filter(Order.warehouse_id == warehouse.id)
    if not can_manage_all_orders(user):
        query = query.filter(Order.assigned_to_id == user.id)
    orders_list = query.order_by(Order.created_at.desc()).all()
    automation_by_order = {order.id: order_automation_summary(order) for order in orders_list}
    return render_template("orders.html", orders=orders_list, automation_by_order=automation_by_order)


@orders_bp.route("/fast-delivery-orders")
@role_required("manager", "staff")
def fast_delivery_orders():
    user = get_current_user()
    warehouse = selected_warehouse(user)
    fast_delivery_statuses = [
        "pending",
        "picking",
        "packed",
        "dispatched",
        "ready_to_dispatch",
        "dispatch_ready",
        "confirmed",
        "processing",
        "paid",
        "pending_cod",
        "payment_initiated",
    ]
    query = Order.query.filter(Order.status.in_(fast_delivery_statuses))
    if warehouse:
        query = query.filter(Order.warehouse_id == warehouse.id)
    if not can_manage_all_orders(user):
        query = query.filter(Order.assigned_to_id == user.id)
    query = query.filter(
        or_(
            Order.priority == "urgent",
            Order.source_payload.ilike('%"mode":"fast"%'),
            Order.source_payload.ilike("%express%"),
            Order.source_payload.ilike("%Fast delivery%"),
            Order.source_payload.ilike("%fastDelivery%"),
            Order.source_payload.ilike("%fast_delivery%"),
        )
    )
    orders_list = [
        order
        for order in query.order_by(Order.created_at.desc()).limit(2000).all()
        if is_fast_delivery_order(order)
    ]
    automation_by_order = {order.id: order_automation_summary(order) for order in orders_list}
    return render_template("fast_delivery_orders.html", orders=orders_list, automation_by_order=automation_by_order)


@orders_bp.route("/add-order", methods=["GET", "POST"])
@role_required("manager", "staff")
def add_order():
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    warehouse = selected_warehouse()
    warehouses = accessible_warehouses()
    staff_query = User.query.filter(User.role.in_(["staff", "picker", "packer", "delivery"]))
    if warehouse:
        staff_query = staff_query.filter(User.warehouses.any(id=warehouse.id))
    staff = staff_query.order_by(User.full_name).all()

    if request.method == "POST":
        if not warehouse:
            flash("Select a warehouse before creating an order.", "warning")
            return redirect(url_for("orders.add_order"))
        try:
            submitted_items = json.loads(request.form.get("items_json", "") or "null")
        except json.JSONDecodeError:
            flash("Order items format is invalid.", "danger")
            return redirect(url_for("orders.add_order"))
        if submitted_items is None:
            submitted_items = [{"product_id": request.form["product_id"], "quantity": request.form["quantity"]}]
        if not isinstance(submitted_items, list) or not submitted_items:
            flash("At least one order item is required.", "danger")
            return redirect(url_for("orders.add_order"))
        order = Order(
            order_number=request.form.get("order_number", "").strip() or f"ORD-{india_now().strftime('%Y%m%d%H%M%S')}",
            customer_name=request.form.get("customer_name", "").strip(),
            customer_phone=request.form.get("customer_phone", "").strip(),
            customer_address=request.form.get("customer_address", "").strip(),
            priority=request.form.get("priority", "normal"),
            warehouse_id=warehouse.id,
            assigned_to_id=int_or_none(request.form.get("assigned_to_id")),
            created_by_id=get_current_user().id if get_current_user() else None,
        )
        try:
            for item in submitted_items:
                product = Product.query.get_or_404(int(item["product_id"]))
                quantity = int(item["quantity"])
                if quantity <= 0:
                    raise ValueError
                order.items.append(
                    OrderItem(
                        product_id=product.id,
                        quantity=quantity,
                        unit_price=product.selling_price,
                    )
                )
        except (KeyError, TypeError, ValueError):
            flash("Each order item requires a valid product and quantity.", "danger")
            return redirect(url_for("orders.add_order"))
        db.session.add(order)
        db.session.commit()
        flash("Order created.", "success")
        return redirect(url_for("orders.orders"))

    return render_template("add_order.html", products=products, staff=staff, warehouses=warehouses, warehouse=warehouse)


@orders_bp.route("/order/<int:order_id>")
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    if not can_access_order(get_current_user(), order):
        flash("You do not have permission to open that order.", "warning")
        return redirect(url_for("orders.orders"))
    return render_template("order_detail.html", order=order, automation=order_automation_summary(order))


@orders_bp.post("/order/<int:order_id>/status")
@role_required("manager", "staff", "picker", "packer", "delivery")
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    if not can_access_order(get_current_user(), order):
        flash("You do not have permission to update that order.", "warning")
        return redirect(url_for("orders.orders"))
    requested_status = request.form.get("status", order.status)
    if requested_status == "dispatched":
        return dispatch_order(order_id)

    order.status = requested_status
    if order.status == "completed":
        order.completed_at = india_now()
    db.session.commit()
    flash("Order status updated.", "success")
    return redirect(url_for("orders.order_detail", order_id=order.id))


@orders_bp.post("/order/<int:order_id>/dispatch")
@role_required("manager", "staff", "picker", "packer", "delivery")
def dispatch_order(order_id):
    order = Order.query.get_or_404(order_id)
    if not can_access_order(get_current_user(), order):
        flash("You do not have permission to dispatch that order.", "warning")
        return redirect(url_for("orders.orders"))
    if order.status not in {"packed", "dispatched"}:
        flash("Order must be packed before dispatch.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order.id))
    if not all(item.packed_quantity >= item.quantity for item in order.items):
        flash("Pack all order items before dispatch.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order.id))

    if order.external_source == "inbound_customer" or is_fast_delivery_order(order):
        order.status = "dispatched"
        db.session.commit()
        message = "Fast delivery order handed off locally. Shiprocket was not created."
        if order.external_source == "inbound_customer":
            message = "Inbound customer order handed off locally. Shiprocket was not created."
        flash(message, "success")
        return redirect(url_for("orders.order_detail", order_id=order.id))

    try:
        result = dispatch_order_with_shiprocket(order, request.form, user_id=get_current_user().id if get_current_user() else None)
        db.session.commit()
        if result["created"]:
            message = "Shiprocket courier created and order dispatched."
        elif result.get("skipped"):
            message = "Order dispatched. Shiprocket is not configured, so no courier was created."
        else:
            message = "Order dispatched with existing Shiprocket courier."
        flash(message, "success")
    except (ShiprocketError, ValueError) as error:
        db.session.rollback()
        flash(f"Dispatch failed: {error}", "danger")
    return redirect(url_for("orders.order_detail", order_id=order.id))


def int_or_none(value):
    return int(value) if value else None


def can_manage_all_orders(user):
    return user_has_role(user, "manager", "staff")


def can_access_order(user, order):
    warehouse_ids = {warehouse.id for warehouse in accessible_warehouses(user)}
    same_warehouse = not warehouse_ids or order.warehouse_id in warehouse_ids
    return bool(user and same_warehouse and (can_manage_all_orders(user) or order.assigned_to_id == user.id))
