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


@finance_bp.route("/warehouse-transactions")
@role_required("manager", "staff")
def warehouse_transactions():
    warehouses = accessible_warehouses()
    allowed_ids = {warehouse.id for warehouse in warehouses}
    requested_warehouse_id = request.args.get("warehouse_id", "").strip()
    selected_id = int(requested_warehouse_id) if requested_warehouse_id.isdigit() and int(requested_warehouse_id) in allowed_ids else None

    base_query = MoneyTransaction.query
    if allowed_ids:
        base_query = base_query.filter(MoneyTransaction.warehouse_id.in_(allowed_ids))
    else:
        base_query = base_query.filter(MoneyTransaction.id == -1)
    if selected_id:
        base_query = base_query.filter(MoneyTransaction.warehouse_id == selected_id)

    all_transactions = base_query.all()
    transactions = base_query.order_by(MoneyTransaction.created_at.desc(), MoneyTransaction.id.desc()).limit(500).all()
    totals = build_warehouse_transaction_totals(all_transactions, warehouses)
    summary = {
        "cash": sum(row["cash"] for row in totals),
        "online": sum(row["online"] for row in totals),
        "other": sum(row["other"] for row in totals),
        "refunds": sum(row["refunds"] for row in totals),
        "settlements": sum(row["settlements"] for row in totals),
        "net": sum(row["net"] for row in totals),
    }
    return render_template(
        "warehouse_transactions.html",
        transactions=transactions,
        warehouses=warehouses,
        selected_id=selected_id,
        totals=totals,
        summary=summary,
    )


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


def build_warehouse_transaction_totals(transactions, warehouses):
    warehouse_by_id = {warehouse.id: warehouse for warehouse in warehouses}
    rows = {
        warehouse.id: {
            "warehouse": warehouse,
            "cash": 0.0,
            "online": 0.0,
            "other": 0.0,
            "refunds": 0.0,
            "settlements": 0.0,
            "credits": 0,
            "debits": 0,
            "count": 0,
        }
        for warehouse in warehouses
    }
    if any(transaction.warehouse_id is None for transaction in transactions):
        rows[None] = {
            "warehouse": None,
            "cash": 0.0,
            "online": 0.0,
            "other": 0.0,
            "refunds": 0.0,
            "settlements": 0.0,
            "credits": 0,
            "debits": 0,
            "count": 0,
        }

    for transaction in transactions:
        warehouse_id = transaction.warehouse_id if transaction.warehouse_id in warehouse_by_id else None
        if warehouse_id not in rows:
            continue
        row = rows[warehouse_id]
        amount = float(transaction.amount or 0)
        gateway = (transaction.gateway or "").lower()
        transaction_type = (transaction.transaction_type or "").lower()
        direction = (transaction.direction or "").lower()
        row["count"] += 1
        if direction == "credit":
            row["credits"] += amount
            if gateway in {"cod", "cash", "cash_on_delivery"}:
                row["cash"] += amount
            elif gateway in {"razorpay", "online", "card", "upi", "netbanking", "wallet", "bank_transfer"}:
                row["online"] += amount
            else:
                row["other"] += amount
        elif direction == "debit":
            row["debits"] += amount
            if transaction_type == "cash_settlement":
                row["settlements"] += amount
            else:
                row["refunds"] += amount

    result = []
    for row in rows.values():
        row["net"] = row["credits"] - row["debits"]
        result.append(row)
    return sorted(result, key=lambda row: (row["warehouse"].code if row["warehouse"] else "ZZZ"))
