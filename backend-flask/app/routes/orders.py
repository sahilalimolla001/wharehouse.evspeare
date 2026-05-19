from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Order, OrderItem, Product, User
from .auth import get_current_user, login_required, role_required, user_has_role

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/orders")
@login_required
def orders():
    user = get_current_user()
    query = Order.query
    if not can_manage_all_orders(user):
        query = query.filter(Order.assigned_to_id == user.id)
    orders_list = query.order_by(Order.created_at.desc()).all()
    return render_template("orders.html", orders=orders_list)


@orders_bp.route("/add-order", methods=["GET", "POST"])
@role_required("manager", "staff")
def add_order():
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    staff = User.query.filter(User.role.in_(["staff", "picker", "packer", "delivery"])).order_by(User.full_name).all()

    if request.method == "POST":
        product_id = int(request.form["product_id"])
        product = Product.query.get_or_404(product_id)
        quantity = int(request.form["quantity"])
        order = Order(
            order_number=request.form.get("order_number", "").strip() or f"ORD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            customer_name=request.form.get("customer_name", "").strip(),
            customer_phone=request.form.get("customer_phone", "").strip(),
            customer_address=request.form.get("customer_address", "").strip(),
            priority=request.form.get("priority", "normal"),
            assigned_to_id=int_or_none(request.form.get("assigned_to_id")),
            created_by_id=get_current_user().id if get_current_user() else None,
        )
        order.items.append(
            OrderItem(
                product_id=product.id,
                quantity=quantity,
                unit_price=product.selling_price,
            )
        )
        db.session.add(order)
        db.session.commit()
        flash("Order created.", "success")
        return redirect(url_for("orders.orders"))

    return render_template("add_order.html", products=products, staff=staff)


@orders_bp.route("/order/<int:order_id>")
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    if not can_access_order(get_current_user(), order):
        flash("You do not have permission to open that order.", "warning")
        return redirect(url_for("orders.orders"))
    return render_template("order_detail.html", order=order)


@orders_bp.post("/order/<int:order_id>/status")
@role_required("manager", "staff", "picker", "packer", "delivery")
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    if not can_access_order(get_current_user(), order):
        flash("You do not have permission to update that order.", "warning")
        return redirect(url_for("orders.orders"))
    order.status = request.form.get("status", order.status)
    if order.status == "completed":
        order.completed_at = datetime.utcnow()
    db.session.commit()
    flash("Order status updated.", "success")
    return redirect(url_for("orders.order_detail", order_id=order.id))


def int_or_none(value):
    return int(value) if value else None


def can_manage_all_orders(user):
    return user_has_role(user, "manager", "staff")


def can_access_order(user, order):
    return bool(user and (can_manage_all_orders(user) or order.assigned_to_id == user.id))
