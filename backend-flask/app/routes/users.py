from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import User
from .auth import role_required

users_bp = Blueprint("users", __name__)


@users_bp.route("/users", methods=["GET", "POST"])
@role_required("admin")
def users():
    if request.method == "POST":
        user = User(
            full_name=request.form.get("full_name", "").strip(),
            email=request.form.get("email", "").strip().lower(),
            phone=request.form.get("phone", "").strip(),
            role=request.form.get("role", "staff"),
        )
        user.set_password(request.form.get("password", "staff123"))
        db.session.add(user)
        db.session.commit()
        flash("Staff user saved.", "success")
        return redirect(url_for("users.users"))

    users_list = User.query.order_by(User.full_name).all()
    return render_template("users.html", users=users_list)


@users_bp.route("/settings")
@role_required("admin")
def settings():
    integrations = {
        "database": "Connected" if current_app.config.get("SQLALCHEMY_DATABASE_URI") else "Not configured",
        "google_storage": "Connected" if current_app.config.get("GOOGLE_CLOUD_STORAGE_BUCKET") else "Not configured",
        "google_sheets": "Connected" if current_app.config.get("GOOGLE_APPS_SCRIPT_WEBHOOK_URL") or current_app.config.get("GOOGLE_SHEETS_SPREADSHEET_ID") else "Not configured",
    }
    return render_template("settings.html", integrations=integrations)
