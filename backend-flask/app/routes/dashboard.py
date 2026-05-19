from datetime import datetime, time

from flask import Blueprint, render_template
from sqlalchemy import func

from ..extensions import db
from ..models import Inventory, Order, Product, StockIn, StockOut
from .auth import login_required

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    today_start = datetime.combine(datetime.utcnow().date(), time.min)

    products = Product.query.filter_by(is_active=True).all()
    total_products = len(products)
    total_stock_units = sum(product.total_quantity for product in products)
    total_stock_value = sum(product.stock_value for product in products)
    low_stock_items = [product for product in products if product.is_low_stock]
    today_stock_in = db.session.query(func.coalesce(func.sum(StockIn.quantity), 0)).filter(StockIn.received_at >= today_start).scalar()
    today_stock_out = db.session.query(func.coalesce(func.sum(StockOut.quantity), 0)).filter(StockOut.dispatched_at >= today_start).scalar()
    pending_orders = Order.query.filter(Order.status.in_(["pending", "picking", "packed"])).count()
    completed_orders = Order.query.filter_by(status="completed").count()

    top_selling_rows = (
        db.session.query(Product.name, Product.sku, func.coalesce(func.sum(StockOut.quantity), 0).label("sold_qty"))
        .join(StockOut, StockOut.product_id == Product.id)
        .group_by(Product.id)
        .order_by(func.sum(StockOut.quantity).desc())
        .limit(5)
        .all()
    )

    recent_inventory = Inventory.query.order_by(Inventory.updated_at.desc()).limit(8).all()

    return render_template(
        "dashboard.html",
        total_products=total_products,
        total_stock_units=total_stock_units,
        total_stock_value=total_stock_value,
        low_stock_items=low_stock_items,
        today_stock_in=today_stock_in,
        today_stock_out=today_stock_out,
        pending_orders=pending_orders,
        completed_orders=completed_orders,
        top_selling_rows=top_selling_rows,
        recent_inventory=recent_inventory,
    )
