from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Supplier
from .auth import role_required

suppliers_bp = Blueprint("suppliers", __name__)


@suppliers_bp.route("/suppliers")
@role_required("manager")
def suppliers():
    suppliers_list = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template("suppliers.html", suppliers=suppliers_list)


@suppliers_bp.route("/add-supplier", methods=["GET", "POST"])
@role_required("manager")
def add_supplier():
    if request.method == "POST":
        supplier = Supplier(
            name=request.form.get("name", "").strip(),
            phone=request.form.get("phone", "").strip(),
            email=request.form.get("email", "").strip(),
            address=request.form.get("address", "").strip(),
            gst_number=request.form.get("gst_number", "").strip(),
            notes=request.form.get("notes", "").strip(),
        )
        db.session.add(supplier)
        db.session.commit()
        flash("Supplier saved.", "success")
        return redirect(url_for("suppliers.suppliers"))
    return render_template("add_supplier.html")
