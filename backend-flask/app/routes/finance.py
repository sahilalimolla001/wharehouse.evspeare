from flask import Blueprint, render_template

from ..models import Invoice, MoneyTransaction
from .auth import role_required


finance_bp = Blueprint("finance", __name__)


@finance_bp.route("/money-tracking")
@role_required("manager", "staff")
def money_tracking():
    transactions = MoneyTransaction.query.order_by(MoneyTransaction.created_at.desc()).limit(500).all()
    return render_template("money_tracking.html", transactions=transactions)


@finance_bp.route("/invoices")
@role_required("manager", "staff")
def invoices():
    invoices_list = Invoice.query.order_by(Invoice.issued_at.desc(), Invoice.id.desc()).limit(500).all()
    return render_template("invoices.html", invoices=invoices_list)
