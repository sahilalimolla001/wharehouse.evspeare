import csv
from io import StringIO

from flask import Blueprint, Response, flash, redirect, render_template, url_for
from sqlalchemy import func

from ..extensions import db
from ..models import Inventory, Product, StockIn, StockOut, Supplier, WarehouseLocation
from ..utils.google_sheets import format_google_sheets_error, sync_google_sheets_workbook
from .auth import role_required, selected_warehouse

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/reports")
@role_required("manager")
def reports():
    warehouse = selected_warehouse()
    products = Product.query.filter_by(is_active=True).all()
    inventory_query = Inventory.query.join(WarehouseLocation)
    stock_in_query = db.session.query(func.coalesce(func.sum(StockIn.quantity), 0)).join(WarehouseLocation, StockIn.location_id == WarehouseLocation.id)
    stock_out_query = db.session.query(func.coalesce(func.sum(StockOut.quantity), 0)).join(WarehouseLocation, StockOut.location_id == WarehouseLocation.id)
    if warehouse:
        inventory_query = inventory_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
        stock_in_query = stock_in_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
        stock_out_query = stock_out_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
    inventory_rows = inventory_query.all()
    product_quantities = {}
    for row in inventory_rows:
        product_quantities[row.product_id] = product_quantities.get(row.product_id, 0) + row.quantity
    stock_value = sum((row.product.purchase_price or 0) * row.quantity for row in inventory_rows)
    low_stock = [product for product in products if product_quantities.get(product.id, 0) <= product.minimum_stock]
    supplier_count = Supplier.query.filter_by(is_active=True).count()
    total_stock_in = stock_in_query.scalar()
    total_stock_out = stock_out_query.scalar()
    return render_template(
        "reports.html",
        stock_value=stock_value,
        low_stock=low_stock,
        supplier_count=supplier_count,
        total_stock_in=total_stock_in,
        total_stock_out=total_stock_out,
    )


@reports_bp.route("/reports/current-stock.csv")
@role_required("manager")
def current_stock_csv():
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["SKU", "Product", "Location", "Quantity", "Reserved", "Available", "Stock Value"])
    warehouse = selected_warehouse()
    query = Inventory.query.join(Product).join(WarehouseLocation)
    if warehouse:
        query = query.filter(WarehouseLocation.warehouse_id == warehouse.id)
    for row in query.order_by(Product.sku).all():
        writer.writerow(
            [
                row.product.sku,
                row.product.name,
                row.location.full_code,
                row.quantity,
                row.reserved_quantity,
                row.available_quantity,
                row.product.purchase_price * row.quantity,
            ]
        )
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=current-stock.csv"},
    )


@reports_bp.post("/reports/export-google-sheet")
@role_required("manager")
def export_google_sheet():
    try:
        result = sync_google_sheets_workbook("manual_export")
        flash(result.get("message", "Google Sheet synced."), "success")
    except RuntimeError as error:
        flash(str(error), "danger")
    except Exception as error:
        flash(f"Google Sheets export failed: {format_google_sheets_error(error)}", "danger")
    return redirect(url_for("reports.reports"))
