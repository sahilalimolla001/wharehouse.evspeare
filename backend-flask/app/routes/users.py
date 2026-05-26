from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import CustomerReturnOrder, Inventory, Order, Product, User, Warehouse, WarehouseLocation
from ..utils.customer_website import notify_product_change
from ..utils.google_sheets import auto_sync_current_stock_sheet
from ..utils.google_storage import test_storage_connection
from ..utils.picker_ops import picker_ops_summary
from ..utils.shiprocket import ShiprocketError, is_shiprocket_configured, test_shiprocket_connection
from .auth import role_required, selected_warehouse

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
        warehouse_ids = [int(value) for value in request.form.getlist("warehouse_ids") if value.isdigit()]
        if warehouse_ids:
            user.warehouses = Warehouse.query.filter(Warehouse.id.in_(warehouse_ids)).all()
        db.session.add(user)
        db.session.commit()
        flash("Staff user saved.", "success")
        return redirect(url_for("users.users"))

    users_list = User.query.order_by(User.full_name).all()
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.code).all()
    return render_template("users.html", users=users_list, warehouses=warehouses)


@users_bp.post("/users/<int:user_id>/warehouses")
@role_required("admin")
def update_user_warehouses(user_id):
    user = User.query.get_or_404(user_id)
    warehouse_ids = [int(value) for value in request.form.getlist("warehouse_ids") if value.isdigit()]
    user.warehouses = Warehouse.query.filter(Warehouse.id.in_(warehouse_ids)).all() if warehouse_ids else []
    db.session.commit()
    flash("User warehouse mapping updated.", "success")
    return redirect(url_for("users.users"))


@users_bp.route("/settings")
@role_required("admin")
def settings():
    integrations = {
        "database": "Connected" if current_app.config.get("SQLALCHEMY_DATABASE_URI") else "Not configured",
        "google_storage": "Connected" if current_app.config.get("GOOGLE_CLOUD_STORAGE_BUCKET") else "Not configured",
        "google_sheets": "Connected" if current_app.config.get("GOOGLE_APPS_SCRIPT_WEBHOOK_URL") or current_app.config.get("GOOGLE_SHEETS_SPREADSHEET_ID") else "Not configured",
        "customer_website": "Connected" if current_app.config.get("CUSTOMER_PRODUCT_WEBHOOK_URL") else "Feed only",
        "shiprocket": "Connected" if is_shiprocket_configured(current_app.config) else "Not configured",
    }
    return render_template("settings.html", integrations=integrations)


@users_bp.route("/ops-config")
@role_required("admin")
def ops_config():
    rules = {
        "Shift gate": "Enabled",
        "Pick method": "Bin first",
        "Route optimization": "SLA + bin sequence",
        "Wave picking": "5 orders per wave",
        "Tote assignment": "Required",
        "Dispatch checklist": "Bag seal, label, payment/OTP",
        "Shortage flow": "Exception queue",
        "Return flow": "Virtual bin + PV",
        "Customer app": "Express, buy again, stock badges",
        "Shiprocket": "AWB and courier sync",
    }
    readiness = [
        ("Warehouses", Warehouse.query.filter_by(is_active=True).count(), "Active warehouse nodes"),
        ("Locations", WarehouseLocation.query.filter_by(is_active=True).count(), "Pickable bins"),
        ("Inventory rows", Inventory.query.count(), "Stock ledger rows"),
        ("Products", Product.query.filter_by(is_active=True).count(), "Sellable catalogue"),
        ("Open orders", Order.query.filter(Order.status.in_(["pending", "picking", "packed"])).count(), "Needs floor action"),
        ("Returns", CustomerReturnOrder.query.count(), "Customer return records"),
        ("Staff users", User.query.count(), "Login accounts"),
    ]
    integrations = {
        "Customer website": "Connected" if current_app.config.get("CUSTOMER_PRODUCT_WEBHOOK_URL") else "Feed only",
        "Shiprocket": "Connected" if is_shiprocket_configured(current_app.config) else "Not configured",
        "Google Sheets": "Connected" if current_app.config.get("GOOGLE_APPS_SCRIPT_WEBHOOK_URL") or current_app.config.get("GOOGLE_SHEETS_SPREADSHEET_ID") else "Not configured",
        "Storage": "Connected" if current_app.config.get("GOOGLE_CLOUD_STORAGE_BUCKET") else "Not configured",
    }
    return render_template("ops_config.html", rules=rules, readiness=readiness, integrations=integrations)


@users_bp.route("/picker-ops")
@role_required("manager", "staff")
def picker_ops():
    warehouse = selected_warehouse()
    summary = picker_ops_summary(warehouse)
    return render_template("picker_ops.html", warehouse=warehouse, **summary)


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


@users_bp.post("/settings/test-customer-website")
@role_required("admin")
def test_customer_website_settings():
    product = Product.query.filter_by(is_active=True).order_by(Product.updated_at.desc()).first()
    if not product:
        flash("Add at least one active product before testing customer website push.", "warning")
        return redirect(url_for("users.settings"))

    result = notify_product_change(product, "product.test")
    category = "success" if result.get("ok") else "warning" if result.get("skipped") else "danger"
    flash(result.get("message", "Customer website test finished."), category)
    return redirect(url_for("users.settings"))


@users_bp.post("/settings/test-shiprocket")
@role_required("admin")
def test_shiprocket_settings():
    try:
        result = test_shiprocket_connection(current_app.config)
        flash(result["message"], "success")
    except ShiprocketError as error:
        flash(f"Shiprocket test failed: {error}", "danger")
    return redirect(url_for("users.settings"))
