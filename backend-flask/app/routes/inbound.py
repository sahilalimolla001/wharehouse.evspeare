from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Invoice, MoneyTransaction, Order
from .auth import role_required, selected_warehouse


inbound_bp = Blueprint("inbound", __name__)


@inbound_bp.route("/inbound-customers")
@role_required("manager", "staff")
def customers():
    warehouse = selected_warehouse()
    query = Order.query.filter_by(external_source="inbound_customer")
    if warehouse:
        query = query.filter_by(warehouse_id=warehouse.id)
    orders = query.order_by(Order.created_at.desc()).limit(500).all()
    transactions = (
        MoneyTransaction.query.filter_by(transaction_type="inbound_payment")
        .order_by(MoneyTransaction.created_at.desc())
        .limit(500)
        .all()
    )
    payment_by_order = {row.order_id: row for row in transactions}
    invoices = {
        invoice.order_id: invoice
        for invoice in Invoice.query.filter(Invoice.order_id.in_([order.id for order in orders] or [-1]), Invoice.invoice_type == "sale").all()
    }
    total = sum(float(invoice.amount or 0) for invoice in invoices.values())
    paid = sum(float(row.amount or 0) for row in transactions if row.status in {"paid", "captured", "collected"})
    return render_template(
        "inbound_customers.html",
        orders=orders,
        invoices=invoices,
        payment_by_order=payment_by_order,
        total=total,
        paid=paid,
    )


@inbound_bp.post("/inbound-customers/order/<int:order_id>/payment")
@role_required("manager", "staff")
def update_payment(order_id):
    order = Order.query.filter_by(id=order_id, external_source="inbound_customer").first_or_404()
    payment = (
        MoneyTransaction.query.filter_by(order_id=order.id, transaction_type="inbound_payment")
        .order_by(MoneyTransaction.id.desc())
        .first()
    )
    if not payment:
        flash("Payment record not found.", "warning")
        return redirect(url_for("inbound.customers"))
    payment.status = request.form.get("status", "pending").strip().lower()
    payment.reference = request.form.get("reference", "").strip()[:160]
    payment.notes = request.form.get("notes", "").strip()[:2000]
    db.session.commit()
    flash(f"Payment updated for {order.order_number}.", "success")
    return redirect(url_for("inbound.customers"))


@inbound_bp.get("/inbound-customers/invoice/<int:invoice_id>/download")
@role_required("manager", "staff")
def download_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    if not invoice.order or invoice.order.external_source != "inbound_customer":
        return Response("Invoice not found", status=404)
    html = render_template("inbound_invoice_download.html", invoice=invoice, order=invoice.order)
    response = Response(html, mimetype="text/html")
    response.headers["Content-Disposition"] = f'attachment; filename="{invoice.invoice_number}.html"'
    return response
