from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from ..extensions import db
from ..models import CustomerReturnOrder, Order
from .auth import role_required


returns_bp = Blueprint("returns", __name__)


@returns_bp.route("/customer-returns", methods=["GET", "POST"])
@role_required("manager", "staff")
def customer_returns():
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
        db.session.add(return_order)
        db.session.commit()
        flash("Customer return order created.", "success")
        return redirect(url_for("returns.customer_returns"))

    returns = CustomerReturnOrder.query.order_by(CustomerReturnOrder.created_at.desc()).limit(200).all()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(100).all()
    return render_template("customer_returns.html", returns=returns, recent_orders=recent_orders)


@returns_bp.post("/customer-returns/<int:return_id>/status")
@role_required("manager", "staff")
def update_customer_return(return_id):
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
    return_order.status = request.form.get("status", return_order.status).strip() or return_order.status
    return_order.refund_status = request.form.get("refund_status", return_order.refund_status).strip() or return_order.refund_status
    if return_order.status in {"received", "approved", "rejected", "refunded"} and not return_order.resolved_at:
        return_order.resolved_at = datetime.utcnow()
    db.session.commit()
    flash("Return order updated.", "success")
    return redirect(url_for("returns.customer_returns"))


def find_original_order(value):
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        order = Order.query.get(int(cleaned))
        if order:
            return order
    return Order.query.filter(or_(Order.order_number == cleaned, Order.external_order_id == cleaned)).first()


def next_return_number():
    return f"RET-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
