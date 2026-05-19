import csv
from io import StringIO

from flask import Blueprint, Response, flash, redirect, render_template, url_for
from sqlalchemy import func

from ..extensions import db
from ..models import Inventory, Product, StockIn, StockOut, Supplier
from ..utils.google_sheets import current_stock_sheet_rows, format_google_sheets_error, write_rows_to_sheet
from .auth import role_required

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/reports")
@role_required("manager")
def reports():
    stock_value = sum(product.stock_value for product in Product.query.filter_by(is_active=True).all())
    low_stock = [product for product in Product.query.filter_by(is_active=True).all() if product.is_low_stock]
    supplier_count = Supplier.query.filter_by(is_active=True).count()
    total_stock_in = db.session.query(func.coalesce(func.sum(StockIn.quantity), 0)).scalar()
    total_stock_out = db.session.query(func.coalesce(func.sum(StockOut.quantity), 0)).scalar()
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
    for row in Inventory.query.join(Product).order_by(Product.sku).all():
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
    inventory_rows = Inventory.query.join(Product).order_by(Product.sku).all()
    try:
        result = write_rows_to_sheet(current_stock_sheet_rows(inventory_rows))
        updated_range = result.get("updatedRange", "Google Sheet")
        flash(f"Current stock synced to {updated_range}.", "success")
    except RuntimeError as error:
        flash(str(error), "danger")
    except Exception as error:
        flash(f"Google Sheets export failed: {format_google_sheets_error(error)}", "danger")
    return redirect(url_for("reports.reports"))
