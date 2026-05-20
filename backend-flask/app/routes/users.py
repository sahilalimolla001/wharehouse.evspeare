from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import User
from ..utils.google_sheets import auto_sync_current_stock_sheet
from ..utils.google_storage import test_storage_connection
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


@users_bp.post("/settings/test-google-storage")
@role_required("admin")
def test_google_storage_settings():
    try:
        result = test_storage_connection()
        flash(f"Google Cloud Storage connected: {result['bucket']}", "success")
    except Exception as error:
        flash(f"Google Cloud Storage test failed: {error}", "danger")
    return redirect(url_for("users.settings"))


@users_bp.post("/settings/test-google-sheet")
@role_required("admin")
def test_google_sheet_settings():
    result = auto_sync_current_stock_sheet("settings_test")
    category = "success" if result.get("ok") else "warning" if result.get("skipped") else "danger"
    flash(result.get("message", "Google Sheet test finished."), category)
    return redirect(url_for("users.settings"))
