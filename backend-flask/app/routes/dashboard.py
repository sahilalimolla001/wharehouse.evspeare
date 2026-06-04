from flask import Blueprint, render_template
from sqlalchemy import func

from ..extensions import db
from ..models import CustomerSupportQuery, Inventory, Order, Product, StockIn, StockOut, WarehouseLocation
from ..utils.order_payload import is_fast_delivery_order, order_automation_summary
from ..utils.time import india_today_start
from .auth import accessible_warehouses, get_current_user, login_required, selected_warehouse, user_has_role

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    today_start = india_today_start()
    user = get_current_user()
    warehouses = accessible_warehouses(user)
    warehouse = selected_warehouse(user)

    products = Product.query.filter_by(is_active=True).all()
    total_products = len(products)
    inventory_query = Inventory.query.join(WarehouseLocation)
    stock_in_query = db.session.query(func.coalesce(func.sum(StockIn.quantity), 0)).join(WarehouseLocation, StockIn.location_id == WarehouseLocation.id).filter(StockIn.received_at >= today_start)
    stock_out_query = db.session.query(func.coalesce(func.sum(StockOut.quantity), 0)).join(WarehouseLocation, StockOut.location_id == WarehouseLocation.id).filter(StockOut.dispatched_at >= today_start)
    if warehouse:
        inventory_query = inventory_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
        stock_in_query = stock_in_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
        stock_out_query = stock_out_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
    inventory_rows = inventory_query.all()
    product_quantities = {}
    for row in inventory_rows:
        product_quantities[row.product_id] = product_quantities.get(row.product_id, 0) + row.quantity
    total_stock_units = sum(product_quantities.values())
    total_stock_value = sum((row.product.purchase_price or 0) * row.quantity for row in inventory_rows)
    low_stock_items = [product for product in products if product_quantities.get(product.id, 0) <= product.minimum_stock]
    today_stock_in = stock_in_query.scalar()
    today_stock_out = stock_out_query.scalar()
    pending_query = Order.query.filter(Order.status.in_(["pending", "picking", "packed"]))
    completed_query = Order.query.filter_by(status="completed")
    if warehouse:
        pending_query = pending_query.filter(Order.warehouse_id == warehouse.id)
        completed_query = completed_query.filter(Order.warehouse_id == warehouse.id)
    pending_orders = pending_query.count()
    completed_orders = completed_query.count()
    active_orders_query = Order.query.filter(Order.status.in_(["pending", "picking", "packed", "dispatched"]))
    if warehouse:
        active_orders_query = active_orders_query.filter(Order.warehouse_id == warehouse.id)
    active_order_summaries = [order_automation_summary(order) for order in active_orders_query.all()]
    express_orders = sum(1 for item in active_order_summaries if item["is_express"])
    auto_discount_orders = sum(1 for item in active_order_summaries if item["auto_discount"] > 0)
    auto_discount_total = sum(item["auto_discount"] for item in active_order_summaries)
    open_support_queries = CustomerSupportQuery.query.filter(CustomerSupportQuery.status != "resolved").count()
    courier_pending_orders = []
    if user_has_role(user, "manager", "staff"):
        courier_pending_query = Order.query.filter(
            Order.status.in_(["packed", "dispatched"]),
            db.or_(Order.external_source.is_(None), Order.external_source != "inbound_customer"),
            db.or_(Order.courier_order_id.is_(None), Order.courier_order_id == ""),
            db.or_(Order.courier_shipment_id.is_(None), Order.courier_shipment_id == ""),
        )
        if warehouse:
            courier_pending_query = courier_pending_query.filter(Order.warehouse_id == warehouse.id)
        courier_pending_orders = [
            order
            for order in courier_pending_query.order_by(Order.updated_at.desc(), Order.created_at.desc()).limit(50).all()
            if not is_fast_delivery_order(order)
        ][:20]

    top_selling_rows = (
        db.session.query(Product.name, Product.sku, func.coalesce(func.sum(StockOut.quantity), 0).label("sold_qty"))
        .join(StockOut, StockOut.product_id == Product.id)
        .join(WarehouseLocation, StockOut.location_id == WarehouseLocation.id)
        .filter(WarehouseLocation.warehouse_id == warehouse.id if warehouse else True)
        .group_by(Product.id)
        .order_by(func.sum(StockOut.quantity).desc())
        .limit(5)
        .all()
    )

    recent_query = Inventory.query.join(WarehouseLocation)
    if warehouse:
        recent_query = recent_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
    recent_inventory = recent_query.order_by(Inventory.updated_at.desc()).limit(8).all()

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
        express_orders=express_orders,
        auto_discount_orders=auto_discount_orders,
        auto_discount_total=auto_discount_total,
        open_support_queries=open_support_queries,
        courier_pending_orders=courier_pending_orders,
        top_selling_rows=top_selling_rows,
        recent_inventory=recent_inventory,
        warehouses=warehouses,
        warehouse=warehouse,
        product_quantities=product_quantities,
    )
