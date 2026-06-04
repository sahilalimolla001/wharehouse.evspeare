from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import CustomerSupportQuery
from ..utils.time import india_now
from .auth import login_required, role_required


support_bp = Blueprint("support", __name__)


@support_bp.route("/support-queries")
@login_required
def support_queries():
    status = request.args.get("status", "open")
    query = CustomerSupportQuery.query
    if status == "resolved":
        query = query.filter_by(status="resolved")
    elif status in {"new", "in_progress"}:
        query = query.filter_by(status=status)
    else:
        query = query.filter(CustomerSupportQuery.status != "resolved")
        status = "open"
    queries = query.order_by(CustomerSupportQuery.created_at.desc(), CustomerSupportQuery.id.desc()).limit(300).all()
    counts = {
        "open": CustomerSupportQuery.query.filter(CustomerSupportQuery.status != "resolved").count(),
        "new": CustomerSupportQuery.query.filter_by(status="new").count(),
        "in_progress": CustomerSupportQuery.query.filter_by(status="in_progress").count(),
        "resolved": CustomerSupportQuery.query.filter_by(status="resolved").count(),
    }
    return render_template("support_queries.html", queries=queries, active_status=status, counts=counts)


@support_bp.post("/support-query/<int:query_id>/status")
@role_required("manager", "staff")
def update_support_query_status(query_id):
    support_query = CustomerSupportQuery.query.get_or_404(query_id)
    status = request.form.get("status", "").strip()
    if status not in {"new", "in_progress", "resolved"}:
        flash("Invalid query status.", "danger")
        return redirect(url_for("support.support_queries"))
    support_query.status = status
    support_query.resolved_at = india_now() if status == "resolved" else None
    db.session.commit()
    flash("Support query updated.", "success")
    return redirect(url_for("support.support_queries", status=request.args.get("status", "open")))
