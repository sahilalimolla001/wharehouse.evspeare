import json
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, url_for
from sqlalchemy import or_

from ..extensions import db
from ..models import Order, PaymentRefund
from ..utils.payu import PayURefundError, initiate_payu_refund, payu_refund_enabled
from ..utils.stock import log_activity
from .auth import get_current_user, role_required, selected_warehouse


refunds_bp = Blueprint("refunds", __name__)


@refunds_bp.route("/payment-refunds")
@role_required("manager", "staff")
def payment_refunds():
    warehouse = selected_warehouse()
    query = PaymentRefund.query.outerjoin(Order)
    if warehouse:
        query = query.filter(or_(PaymentRefund.order_id.is_(None), Order.warehouse_id == warehouse.id))
    refunds = query.order_by(PaymentRefund.created_at.desc()).limit(300).all()
    return render_template("payment_refunds.html", refunds=refunds, payu_ready=payu_refund_enabled())


@refunds_bp.post("/payment-refunds/<int:refund_id>/approve")
@role_required("manager", "staff")
def approve_payment_refund(refund_id):
    refund = PaymentRefund.query.get_or_404(refund_id)
    if refund.status in {"approved", "refunded"}:
        flash("Refund is already approved.", "info")
        return redirect(url_for("refunds.payment_refunds"))
    if refund.gateway != "payu":
        flash("Only PayU refunds can be approved from this panel.", "warning")
        return redirect(url_for("refunds.payment_refunds"))

    try:
        token = ensure_refund_token(refund)
        payload = initiate_payu_refund(mihpayid=refund.gateway_payment_id, token=token, amount=refund.amount)
        refund.status = "approved"
        refund.approved_at = datetime.utcnow()
        user = get_current_user()
        refund.approved_by_id = user.id if user else None
        refund.gateway_response = json.dumps(payload, default=str, separators=(",", ":"))[:20000]
        log_activity(
            "payment_refund_approved",
            f"Approved PayU refund {refund.refund_number}",
            user_id=user.id if user else None,
            entity_type="PaymentRefund",
            entity_id=refund.id,
            meta={"amount": float(refund.amount or 0), "mihpayid": refund.gateway_payment_id},
        )
        db.session.commit()
        flash("PayU refund approved and sent.", "success")
    except (PayURefundError, ValueError) as error:
        db.session.rollback()
        flash(f"Refund approval failed: {error}", "danger")
    return redirect(url_for("refunds.payment_refunds"))


@refunds_bp.post("/payment-refunds/<int:refund_id>/reject")
@role_required("manager", "staff")
def reject_payment_refund(refund_id):
    refund = PaymentRefund.query.get_or_404(refund_id)
    if refund.status not in {"requested", "failed"}:
        flash("Only requested or failed refunds can be rejected.", "warning")
        return redirect(url_for("refunds.payment_refunds"))
    refund.status = "rejected"
    db.session.commit()
    flash("Refund request rejected.", "success")
    return redirect(url_for("refunds.payment_refunds"))


def ensure_refund_token(refund):
    if refund.refund_token:
        return refund.refund_token
    refund.refund_token = f"RF{refund.id}{datetime.utcnow().strftime('%H%M%S%f')}"[:23]
    return refund.refund_token
