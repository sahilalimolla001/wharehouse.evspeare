from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Inventory, Product, Supplier, Warehouse, WarehouseLocation
from ..utils.barcode import build_location_barcode
from ..utils.customer_website import notify_product_change
from ..utils.google_storage import upload_product_image
from ..utils.google_sheets import auto_sync_current_stock_sheet
from ..utils.sku import normalize_sku
from ..utils.stock import issue_stock, receive_stock
from .auth import get_current_user, login_required, role_required

stock_bp = Blueprint("stock", __name__)


@stock_bp.route("/inventory")
@login_required
def inventory():
    q = request.args.get("q", "").strip()
    warehouse_id = int_or_none(request.args.get("warehouse_id"))
    query = Inventory.query.join(Product).join(WarehouseLocation)
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.code).all()
    if warehouse_id:
        query = query.filter(WarehouseLocation.warehouse_id == warehouse_id)
    if q:
        like = f"%{q}%"
        sku_like = f"%{normalize_sku(q)}%"
        query = query.filter(
            (Product.name.ilike(like))
            | (Product.sku.ilike(like))
            | (Product.sku.ilike(sku_like))
            | (Product.brand.ilike(like))
            | (WarehouseLocation.barcode.ilike(like))
            | (WarehouseLocation.zone.ilike(like))
            | (WarehouseLocation.rack.ilike(like))
            | (WarehouseLocation.shelf.ilike(like))
            | (WarehouseLocation.bin_code.ilike(like))
        )
    rows = query.order_by(Product.name).all()
    return render_template("inventory.html", inventory_rows=rows, q=q, warehouses=warehouses, warehouse_id=warehouse_id)


@stock_bp.route("/stock-in", methods=["GET", "POST"])
@role_required("manager", "staff")
def stock_in():
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    locations = WarehouseLocation.query.join(Warehouse).filter(WarehouseLocation.is_active.is_(True)).order_by(Warehouse.code, WarehouseLocation.zone).all()

    if request.method == "POST":
        try:
            user = get_current_user()
            product = Product.query.get_or_404(int(request.form["product_id"]))
            receive_stock(
                product_id=product.id,
                supplier_id=int_or_none(request.form.get("supplier_id")),
                location_id=int(request.form["location_id"]),
                quantity=int(request.form["quantity"]),
                unit_cost=float(request.form.get("unit_cost") or 0),
                invoice_number=request.form.get("invoice_number", "").strip(),
                received_by_id=user.id if user else None,
                notes=request.form.get("notes", "").strip(),
            )
            uploaded_file = request.files.get("image_file")
            if uploaded_file and uploaded_file.filename:
                product.image_url = upload_product_image(uploaded_file, sku=product.sku)
            db.session.commit()
            sync_result = auto_sync_current_stock_sheet("stock_in")
            push_result = notify_product_change(product, "stock.changed")
            flash("Stock in saved and inventory increased.", "success")
            if not sync_result["ok"] and not sync_result["skipped"]:
                flash(f"Google Sheet auto-sync failed: {sync_result['message']}", "warning")
            flash_customer_push_result(push_result)
            return redirect(url_for("stock.inventory"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")

    return render_template("stock_in.html", products=products, suppliers=suppliers, locations=locations)


@stock_bp.route("/stock-out", methods=["GET", "POST"])
@role_required("manager", "staff")
def stock_out():
    inventory_rows = Inventory.query.join(Product).join(WarehouseLocation).join(Warehouse).filter(Inventory.quantity > 0).order_by(Warehouse.code, Product.name).all()

    if request.method == "POST":
        try:
            user = get_current_user()
            inventory_row = Inventory.query.get_or_404(int(request.form["inventory_id"]))
            issue_stock(
                product_id=inventory_row.product_id,
                location_id=inventory_row.location_id,
                quantity=int(request.form["quantity"]),
                reason=request.form.get("reason", "sale"),
                dispatched_by_id=user.id if user else None,
                notes=request.form.get("notes", "").strip(),
            )
            db.session.commit()
            sync_result = auto_sync_current_stock_sheet("stock_out")
            push_result = notify_product_change(inventory_row.product, "stock.changed")
            flash("Stock out saved and inventory decreased.", "success")
            if not sync_result["ok"] and not sync_result["skipped"]:
                flash(f"Google Sheet auto-sync failed: {sync_result['message']}", "warning")
            flash_customer_push_result(push_result)
            return redirect(url_for("stock.inventory"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")

    return render_template("stock_out.html", inventory_rows=inventory_rows)


@stock_bp.route("/warehouse-locations")
@login_required
def warehouse_locations():
    warehouse_id = int_or_none(request.args.get("warehouse_id"))
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.code).all()
    query = WarehouseLocation.query.join(Warehouse)
    if warehouse_id:
        query = query.filter(WarehouseLocation.warehouse_id == warehouse_id)
    locations = query.order_by(Warehouse.code, WarehouseLocation.zone, WarehouseLocation.rack, WarehouseLocation.shelf).all()
    return render_template("locations.html", locations=locations, warehouses=warehouses, warehouse_id=warehouse_id)


@stock_bp.route("/warehouses")
@login_required
def warehouses():
    rows = Warehouse.query.order_by(Warehouse.code).all()
    return render_template("warehouses.html", warehouses=rows)


@stock_bp.route("/add-warehouse", methods=["GET", "POST"])
@role_required("manager")
def add_warehouse():
    if request.method == "POST":
        warehouse = Warehouse(
            code=request.form.get("code", "").strip().lower(),
            name=request.form.get("name", "").strip(),
            pincode=request.form.get("pincode", "").strip(),
            address=request.form.get("address", "").strip(),
        )
        db.session.add(warehouse)
        db.session.commit()
        flash("Warehouse saved.", "success")
        return redirect(url_for("stock.warehouses"))
    return render_template("add_warehouse.html")


@stock_bp.route("/add-location", methods=["GET", "POST"])
@role_required("manager")
def add_location():
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.code).all()
    if request.method == "POST":
        warehouse = Warehouse.query.get_or_404(int(request.form["warehouse_id"]))
        location = WarehouseLocation(
            warehouse_id=warehouse.id,
            zone=request.form.get("zone", "").strip(),
            rack=request.form.get("rack", "").strip(),
            shelf=request.form.get("shelf", "").strip(),
            bin_code=request.form.get("bin_code", "").strip(),
        )
        location.warehouse = warehouse
        location.barcode = build_location_barcode(location)
        db.session.add(location)
        db.session.commit()
        flash("Warehouse location saved.", "success")
        return redirect(url_for("stock.warehouse_locations"))
    return render_template("add_location.html", warehouses=warehouses)


def int_or_none(value):
    return int(value) if value else None


def flash_customer_push_result(result):
    if result.get("skipped"):
        return
    if result.get("ok"):
        flash("Customer website updated.", "success")
    else:
        flash(result.get("message", "Customer website update failed."), "warning")
