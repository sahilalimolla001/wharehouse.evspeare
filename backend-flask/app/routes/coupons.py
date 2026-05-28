from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Coupon
from ..utils.coupons import money_value, normalize_coupon_code
from .auth import role_required


coupons_bp = Blueprint("coupons", __name__)


@coupons_bp.route("/coupons", methods=["GET", "POST"])
@role_required("manager", "staff")
def coupons():
    if request.method == "POST":
        code = normalize_coupon_code(request.form.get("code"))
        discount_type = request.form.get("discount_type", "fixed").strip().lower()
        if discount_type not in {"fixed", "percent"}:
            discount_type = "fixed"
        if not code:
            flash("Coupon code is required.", "danger")
            return redirect(url_for("coupons.coupons"))
        if Coupon.query.filter_by(code=code).first():
            flash("Coupon code already exists.", "danger")
            return redirect(url_for("coupons.coupons"))
        coupon = Coupon(
            code=code,
            title=request.form.get("title", "").strip()[:120] or code,
            discount_type=discount_type,
            discount_value=money_value(request.form.get("discount_value")),
            min_order_amount=money_value(request.form.get("min_order_amount")),
            max_discount_amount=money_value(request.form.get("max_discount_amount")) if request.form.get("max_discount_amount") else None,
            max_redemptions=int_or_none(request.form.get("max_redemptions")),
            starts_at=parse_datetime(request.form.get("starts_at")),
            expires_at=parse_datetime(request.form.get("expires_at")),
            is_active=bool(request.form.get("is_active")),
            notes=request.form.get("notes", "").strip()[:2000],
        )
        if coupon.discount_value <= 0:
            flash("Discount value must be greater than zero.", "danger")
            return redirect(url_for("coupons.coupons"))
        db.session.add(coupon)
        db.session.commit()
        flash(f"Coupon {coupon.code} created.", "success")
        return redirect(url_for("coupons.coupons"))

    coupons_list = Coupon.query.order_by(Coupon.created_at.desc(), Coupon.id.desc()).all()
    return render_template("coupons.html", coupons=coupons_list)


@coupons_bp.post("/coupons/<int:coupon_id>/toggle")
@role_required("manager", "staff")
def toggle_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.is_active = not coupon.is_active
    db.session.commit()
    flash(f"Coupon {coupon.code} {'activated' if coupon.is_active else 'paused'}.", "success")
    return redirect(url_for("coupons.coupons"))


def int_or_none(value):
    try:
        return int(value) if str(value or "").strip() else None
    except (TypeError, ValueError):
        return None


def parse_datetime(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
