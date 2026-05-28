from flask import Blueprint, render_template, request
from sqlalchemy import func

from ..models import Invoice, MoneyTransaction, Warehouse
from .auth import accessible_warehouses, role_required


finance_bp = Blueprint("finance", __name__)


@finance_bp.route("/money-tracking")
@role_required("manager", "staff")
def money_tracking():
    transactions = MoneyTransaction.query.order_by(MoneyTransaction.created_at.desc()).limit(500).all()
    return render_template("money_tracking.html", transactions=transactions)


@finance_bp.route("/cash-tracker")
@role_required("manager", "staff")
def cash_tracker():
    return render_template("cash_tracker.html")


@finance_bp.route("/cash-settlements")
@role_required("manager", "staff")
def cash_settlements():
    warehouses = accessible_warehouses()
    allowed_ids = {warehouse.id for warehouse in warehouses}
    requested_warehouse_id = request.args.get("warehouse_id", "").strip()
    selected_id = int(requested_warehouse_id) if requested_warehouse_id.isdigit() and int(requested_warehouse_id) in allowed_ids else None

    query = MoneyTransaction.query.filter_by(transaction_type="cash_settlement", direction="debit")
    totals_query = (
        MoneyTransaction.query.with_entities(
            MoneyTransaction.warehouse_id,
            func.coalesce(func.sum(MoneyTransaction.amount), 0).label("total_settled"),
            func.count(MoneyTransaction.id).label("settlement_count"),
            func.max(MoneyTransaction.created_at).label("last_settled_at"),
        )
        .filter_by(transaction_type="cash_settlement", direction="debit")
        .group_by(MoneyTransaction.warehouse_id)
    )
    if allowed_ids:
        query = query.filter(MoneyTransaction.warehouse_id.in_(allowed_ids))
        totals_query = totals_query.filter(MoneyTransaction.warehouse_id.in_(allowed_ids))
    else:
        query = query.filter(MoneyTransaction.id == -1)
        totals_query = totals_query.filter(MoneyTransaction.id == -1)
    if selected_id:
        query = query.filter(MoneyTransaction.warehouse_id == selected_id)

    settlements = query.order_by(MoneyTransaction.created_at.desc(), MoneyTransaction.id.desc()).limit(1000).all()
    totals = {row.warehouse_id: row for row in totals_query.all()}
    total_settled = sum(float(row.amount or 0) for row in settlements)
    warehouse_by_id = {warehouse.id: warehouse for warehouse in warehouses}
    return render_template(
        "cash_settlements.html",
        settlements=settlements,
        warehouses=warehouses,
        warehouse_by_id=warehouse_by_id,
        selected_id=selected_id,
        totals=totals,
        total_settled=total_settled,
    )


@finance_bp.route("/invoices")
@role_required("manager", "staff")
def invoices():
    invoices_list = Invoice.query.order_by(Invoice.issued_at.desc(), Invoice.id.desc()).limit(500).all()
    return render_template("invoices.html", invoices=invoices_list)
