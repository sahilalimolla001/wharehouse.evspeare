import json
import secrets
from datetime import datetime

from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, Response, current_app, jsonify, redirect, request, session, url_for
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..extensions import db
from ..models import Barcode, CentralPanelSetting, CustomerReturnItem, CustomerReturnOrder, CustomerSupportQuery, Inventory, Invoice, ItemNotFoundReport, MoneyTransaction, Order, OrderItem, PaymentRefund, Product, StockIn, StockOut, User, Warehouse, WarehouseLocation
from ..utils.customer_website import notify_product_change
from ..utils.google_sheets import auto_sync_current_stock_sheet
from ..utils.google_storage import get_storage_client, upload_product_image
from ..utils.coupons import redeem_order_coupon, validate_coupon
from ..utils.finance import ensure_invoice
from ..utils.order_payload import is_fast_delivery_order, order_automation_summary
from ..utils.razorpay import RazorpayRefundError, initiate_razorpay_refund, verify_razorpay_webhook
from ..utils.picker_identity import ensure_picker_code
from ..utils.picker_ops import auto_assign_order_to_picker, order_bin_analysis, picker_online_from_request, pickable_statuses, picker_workload, product_pick_location, update_picker_presence
from ..utils.sku import normalize_sku, sku_lookup_candidates
from ..utils.stock import get_or_create_inventory, issue_stock, log_activity, receive_stock
from ..utils.time import india_iso, india_now, india_timestamp, india_today_start
from .auth import ADMIN_PANEL_PERMISSIONS, PAGE_PERMISSIONS, PICKER_APP_PERMISSIONS, user_has_role, user_page_permissions
from .shiprocket import ShiprocketError, create_shiprocket_return_for_customer_return, ensure_shiprocket_label, dispatch_order_with_shiprocket
from ..utils.shiprocket import cancel_shiprocket_order

api_bp = Blueprint("api", __name__)


def serialize_delivery_order(order):
    payload = {}
    if order.source_payload:
        try:
            payload = json.loads(order.source_payload)
        except (TypeError, ValueError):
            payload = {}
    summary = order_automation_summary(payload)
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
    amounts = payload.get("amounts") if isinstance(payload.get("amounts"), dict) else {}
    billing_address = payload.get("billing_address") or payload.get("billingAddress") or {}
    shipping_address = payload.get("shipping_address") or payload.get("shippingAddress") or {}
    warehouse = order.warehouse

    return {
        "source": "warehouse",
        "external_order_id": str(order.id),
        "order_number": order.order_number,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "customer_address": order.customer_address,
        "billing_address": billing_address,
        "shipping_address": shipping_address,
        "payment_method": order_payment_method(order, payment, payload),
        "payment_status": payment.get("status") or payload.get("paymentStatus") or "",
        "cod_amount": order_cod_amount(order, payment, amounts),
        "total_amount": float(order.total_value or 0),
        "delivery": {
            "mode": summary["delivery_mode"],
            "label": summary["delivery_label"],
            "eta": summary["delivery_eta"],
            "automation": summary["automation"],
        },
        "warehouse": {
            "id": warehouse.id if warehouse else None,
            "code": warehouse.code if warehouse else "",
            "name": warehouse.name if warehouse else "Warehouse",
            "phone": "",
            "address": warehouse.address if warehouse else "",
            "pincode": warehouse.pincode if warehouse else "",
        },
        "items": [
            {
                "sku": item.product.sku if item.product else "",
                "name": item.product.name if item.product else "Item",
                "quantity": item.quantity,
                "unit_price": float(item.unit_price or 0),
                "unit": item.product.unit if item.product else "pcs",
                "image_url": item.product.image_url if item.product else "",
            }
            for item in order.items
        ],
        "raw": payload,
    }


def order_payment_method(order, payment, payload):
    method = order.source_payload and (payment.get("method") or payload.get("paymentMethod"))
    if method:
        return str(method)
    return str(payload.get("payment_method") or "")


def order_cod_amount(order, payment, amounts):
    method = str(payment.get("method") or "").lower()
    if method != "cod":
        return 0
    try:
        return float(payment.get("collectAmount") or amounts.get("total") or order.total_value or 0)
    except (TypeError, ValueError):
        return 0




@api_bp.after_request
def add_api_headers(response):
    origin = request.headers.get("Origin")
    allowed_origins = current_app.config.get("API_ALLOWED_ORIGINS", [])
    if origin and is_allowed_api_origin(origin, allowed_origins):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    elif not origin and not current_app.config.get("IS_PRODUCTION"):
        response.headers["Access-Control-Allow-Origin"] = "*"
    response.vary.add("Origin")
    allowed_headers = ["Authorization", "Content-Type", "X-CSRF-Token", "X-Integration-Key", "X-Picker-Id", "X-Picker-Online", "X-Warehouse-Id"]
    if current_app.config.get("ALLOW_INSECURE_USER_HEADER"):
        allowed_headers.append("X-User-Id")
    response.headers["Access-Control-Allow-Headers"] = ", ".join(allowed_headers)
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return response


def is_allowed_api_origin(origin, allowed_origins):
    if origin in allowed_origins or (not current_app.config.get("IS_PRODUCTION") and not allowed_origins):
        return True
    if current_app.config.get("API_ALLOW_RAILWAY_ORIGINS"):
        hostname = urlparse(origin).hostname or ""
        return hostname.endswith(".up.railway.app")
    return False


@api_bp.route("/health")
def health():
    return jsonify({"ok": True, "service": "warehouse-api"})


def api_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 204
        if not current_api_user():
            return jsonify({"ok": False, "message": "Login required"}), 401
        return view(*args, **kwargs)

    return wrapped


def api_role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if request.method == "OPTIONS":
                return "", 204
            user = current_api_user()
            if not user:
                return jsonify({"ok": False, "message": "Login required"}), 401
            if not user_has_role(user, *roles):
                return jsonify({"ok": False, "message": "Permission denied"}), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator


def picker_permission_required(*permissions):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if request.method == "OPTIONS":
                return "", 204
            user = current_api_user()
            if user and user.role == "picker" and not picker_has_permission(user, *permissions):
                return jsonify({"ok": False, "message": "You are not allowed to access this page."}), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator


def integration_key_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 204
        configured_key = current_app.config.get("INTEGRATION_API_KEY", "")
        if not configured_key:
            return jsonify({"ok": False, "message": "Order import API is not configured"}), 503
        supplied_key = integration_request_key()
        if not supplied_key or not secrets.compare_digest(configured_key, supplied_key):
            return jsonify({"ok": False, "message": "Invalid integration key"}), 401
        return view(*args, **kwargs)

    return wrapped


def integration_key_or_staff_session_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 204
        configured_key = current_app.config.get("INTEGRATION_API_KEY", "")
        supplied_key = integration_request_key()
        if configured_key and supplied_key and secrets.compare_digest(configured_key, supplied_key):
            return view(*args, **kwargs)
        if user_has_role(current_api_user(), "manager", "staff"):
            return view(*args, **kwargs)
        if not configured_key:
            return jsonify({"ok": False, "message": "Order import API is not configured"}), 503
        return jsonify({"ok": False, "message": "Invalid integration key"}), 401

    return wrapped


def support_query_key_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 204
        allowed_keys = [
            current_app.config.get("SUPPORT_QUERY_TOKEN", ""),
            current_app.config.get("INTEGRATION_API_KEY", ""),
        ]
        supplied_key = integration_request_key()
        if supplied_key and any(key and secrets.compare_digest(key, supplied_key) for key in allowed_keys):
            return view(*args, **kwargs)
        if not any(allowed_keys):
            return jsonify({"ok": False, "message": "Support query API is not configured"}), 503
        return jsonify({"ok": False, "message": "Invalid support query token"}), 401

    return wrapped


def integration_request_key():
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get("X-Integration-Key", "").strip()


@api_bp.route("/support-queries", methods=["POST", "OPTIONS"])
@support_query_key_required
def receive_support_query():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or data.get("customer_name") or "").strip()
    phone = "".join(ch for ch in str(data.get("phone") or data.get("customer_phone") or "") if ch.isdigit())[-10:]
    message = str(data.get("message") or data.get("query") or "").strip()
    external_id = str(data.get("id") or data.get("external_id") or "").strip()

    if not name:
        return jsonify({"ok": False, "message": "Customer name is required"}), 400
    if len(phone) != 10:
        return jsonify({"ok": False, "message": "Valid customer phone is required"}), 400
    if len(message) < 5:
        return jsonify({"ok": False, "message": "Support message is required"}), 400

    query = CustomerSupportQuery.query.filter_by(external_id=external_id).first() if external_id else None
    if not query:
        query = CustomerSupportQuery(external_id=external_id or None)
        db.session.add(query)
    query.customer_name = name[:160]
    query.customer_phone = phone
    query.message = message
    query.source = str(data.get("source") or "mobile_app")[:80]
    query.raw_payload_json = json.dumps(data, ensure_ascii=True)
    db.session.commit()

    return jsonify({"ok": True, "id": query.id, "external_id": query.external_id, "status": query.status})


@api_bp.post("/login")
def api_login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(email=data.get("email", "").strip().lower(), is_active=True).first()
    if not user or not user.check_password(data.get("password", "")):
        return jsonify({"ok": False, "message": "Invalid email or password"}), 401
    session.permanent = True
    session["user_id"] = user.id
    session["user_role"] = user.role
    ensure_picker_code(user)
    db.session.commit()
    return jsonify({"ok": True, "user": serialize_user(user), "token": create_api_token(user)})


@api_bp.post("/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@api_bp.get("/me")
@api_login_required
def api_me():
    user = current_api_user()
    ensure_picker_code(user)
    db.session.commit()
    return jsonify({"ok": True, "user": serialize_user(user)})


@api_bp.route("/central-panel/users", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@integration_key_required
def api_central_panel_users():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "GET":
        users = User.query.order_by(User.full_name).all()
        for user in users:
            ensure_picker_code(user)
        db.session.commit()
        return jsonify({"ok": True, "users": [serialize_central_panel_user(user) for user in users]})

    data = request.get_json(silent=True) or {}
    email = (data.get("userId") or data.get("email") or "").strip().lower()
    original_email = (data.get("originalUserId") or data.get("original_email") or email).strip().lower()
    user_id = data.get("id")
    is_new_user = False
    if request.method in {"PUT", "PATCH", "DELETE"}:
        user = User.query.filter_by(id=user_id).first() if str(user_id or "").isdigit() else None
        if not user and original_email:
            user = User.query.filter_by(email=original_email).first()
        if not user:
            return jsonify({"ok": False, "message": "User not found"}), 404
        if request.method == "DELETE":
            db.session.delete(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                return jsonify({"ok": False, "message": "User has linked operations. Set status to blocked instead."}), 409
            return jsonify({"ok": True})
    else:
        password = data.get("password") or ""
        warehouse_id = data.get("warehouseId") or data.get("warehouse_id")
        if not email or not password or not warehouse_id:
            return jsonify({"ok": False, "message": "userId, password and warehouseId are required"}), 400
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email)
            is_new_user = True

    warehouse_id = data.get("warehouseId") or data.get("warehouse_id")
    warehouse = resolve_warehouse(warehouse_id)
    if warehouse_id and not warehouse:
        return jsonify({"ok": False, "message": "Warehouse not found"}), 404
    if request.method == "POST" and not warehouse:
        return jsonify({"ok": False, "message": "Warehouse not found"}), 404

    if email:
        user.email = email
    user.full_name = (data.get("name") or data.get("full_name") or user.full_name or user.email).strip()
    user.phone = (data.get("phone") if "phone" in data else user.phone or "").strip()
    user.role = (data.get("role") or user.role or "picker").strip()
    user.is_active = data.get("status", "active" if user.is_active else "blocked") != "blocked"
    if data.get("password"):
        user.set_password(data["password"])
    if warehouse:
        user.warehouses = [warehouse]
    requested_permissions = data.get("page_permissions") or data.get("permissions") or []
    if isinstance(requested_permissions, list):
        valid_permissions = set(ADMIN_PANEL_PERMISSIONS) | set(PAGE_PERMISSIONS) | set(PICKER_APP_PERMISSIONS)
        user.page_permissions = json.dumps([value for value in requested_permissions if value in valid_permissions])
    ensure_picker_code(user)
    if is_new_user:
        db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "User ID / email already exists"}), 409
    return jsonify({"ok": True, "user": serialize_central_panel_user(user)})


@api_bp.route("/central-panel/warehouses", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_warehouses():
    if request.method == "OPTIONS":
        return "", 204
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.code).all()
    return jsonify({"ok": True, "warehouses": [serialize_warehouse(warehouse) for warehouse in warehouses]})


@api_bp.route("/central-panel/inbound-orders", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_inbound_orders():
    if request.method == "OPTIONS":
        return "", 204
    orders = Order.query.filter_by(external_source="inbound_customer").order_by(Order.created_at.desc()).limit(500).all()
    return jsonify({"ok": True, "orders": [serialize_inbound_order(order) for order in orders]})


@api_bp.route("/central-panel/item-not-found", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_item_not_found():
    if request.method == "OPTIONS":
        return "", 204
    reports = ItemNotFoundReport.query.order_by(ItemNotFoundReport.created_at.desc()).limit(500).all()
    return jsonify({"ok": True, "reports": [serialize_item_not_found_report(report) for report in reports]})


@api_bp.route("/central-panel/cash-settlements", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_cash_settlements():
    if request.method == "OPTIONS":
        return "", 204
    settlements = (
        MoneyTransaction.query.filter_by(transaction_type="cash_settlement", direction="debit")
        .order_by(MoneyTransaction.created_at.desc(), MoneyTransaction.id.desc())
        .limit(1000)
        .all()
    )
    summary_rows = (
        db.session.query(
            MoneyTransaction.warehouse_id,
            func.coalesce(func.sum(MoneyTransaction.amount), 0).label("total_settled"),
            func.count(MoneyTransaction.id).label("settlement_count"),
            func.max(MoneyTransaction.created_at).label("last_settled_at"),
        )
        .filter_by(transaction_type="cash_settlement", direction="debit")
        .group_by(MoneyTransaction.warehouse_id)
        .all()
    )
    warehouses = {warehouse.id: warehouse for warehouse in Warehouse.query.all()}
    summary = [
        {
            "warehouse_id": row.warehouse_id,
            "warehouse": warehouses.get(row.warehouse_id).code if warehouses.get(row.warehouse_id) else "",
            "warehouse_name": warehouses.get(row.warehouse_id).name if warehouses.get(row.warehouse_id) else "",
            "total_settled": float(row.total_settled or 0),
            "settlement_count": int(row.settlement_count or 0),
            "last_settled_at": india_iso(row.last_settled_at),
        }
        for row in summary_rows
    ]
    return jsonify(
        {
            "ok": True,
            "summary": summary,
            "settlements": [serialize_cash_transaction(row) for row in settlements],
        }
    )


@api_bp.route("/central-panel/products", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_products():
    if request.method == "OPTIONS":
        return "", 204
    products = Product.query.filter_by(is_active=True).order_by(Product.name).limit(1000).all()
    return jsonify({"ok": True, "products": [serialize_product(product) for product in products]})


@api_bp.route("/central-panel/orders", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_orders():
    if request.method == "OPTIONS":
        return "", 204
    orders = Order.query.order_by(Order.created_at.desc()).limit(1000).all()
    return jsonify({"ok": True, "orders": [serialize_order(order) for order in orders]})


@api_bp.route("/order-tracking", methods=["GET", "OPTIONS"])
@integration_key_required
def api_order_tracking():
    if request.method == "OPTIONS":
        return "", 204
    order_id = trim_text(request.args.get("orderId") or request.args.get("order_id") or request.args.get("id"), 120)
    awb = trim_text(request.args.get("awb") or request.args.get("awb_number"), 120)
    if not order_id and not awb:
        return jsonify({"ok": False, "message": "orderId or awb is required"}), 400

    query = Order.query
    if order_id:
        query = query.filter(or_(Order.order_number == order_id, Order.external_order_id == order_id))
    if awb:
        query = query.filter(Order.courier_awb == awb)
    order = query.order_by(Order.created_at.desc()).first()
    if not order:
        return jsonify({"ok": False, "message": "Order not found"}), 404

    status = order.status or "pending"
    label = "Order cancelled" if "cancel" in status.lower() else status.replace("_", " ").title()
    return jsonify(
        {
            "ok": True,
            "orderId": order.order_number,
            "order_id": order.order_number,
            "website_order_id": order.external_order_id,
            "status": status,
            "label": label,
            "awb": order.courier_awb or "",
            "awbNumber": order.courier_awb or "",
            "courier": order.courier_provider or "",
            "updatedAt": india_iso(order.updated_at),
            "tracking": {
                "status": status,
                "label": label,
                "awbNumber": order.courier_awb or "",
                "updatedAt": india_iso(order.updated_at),
            },
        }
    )


@api_bp.route("/central-panel/customers", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_customers():
    if request.method == "OPTIONS":
        return "", 204
    customers = {}
    for order in Order.query.order_by(Order.created_at.desc()).all():
        key = (order.customer_phone or order.customer_name or str(order.id)).strip().lower()
        customer = customers.setdefault(
            key,
            {
                "id": key,
                "name": order.customer_name,
                "phone": order.customer_phone or "",
                "status": "active",
                "orders": 0,
                "value": 0.0,
                "created_at": india_iso(order.created_at),
            },
        )
        customer["orders"] += 1
        customer["value"] += float(order.total_value)
    return jsonify({"ok": True, "customers": list(customers.values())})


@api_bp.route("/central-panel/picker-orders", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_picker_orders():
    if request.method == "OPTIONS":
        return "", 204
    orders = (
        Order.query.filter(Order.status.in_(["pending", "picking", "packed", "dispatched"]))
        .order_by(Order.created_at.desc())
        .limit(500)
        .all()
    )
    return jsonify({"ok": True, "orders": [serialize_order(order) for order in orders]})


@api_bp.route("/central-panel/returns", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_returns():
    if request.method == "OPTIONS":
        return "", 204
    returns = CustomerReturnOrder.query.order_by(CustomerReturnOrder.requested_at.desc()).limit(500).all()
    return jsonify({"ok": True, "returns": [serialize_return_order(return_order) for return_order in returns]})


@api_bp.route("/central-panel/inventory", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_inventory():
    if request.method == "OPTIONS":
        return "", 204
    inventory = (
        Inventory.query.join(WarehouseLocation)
        .filter(WarehouseLocation.is_virtual.is_(False), WarehouseLocation.is_active.is_(True))
        .order_by(WarehouseLocation.warehouse_id, WarehouseLocation.zone, WarehouseLocation.rack, WarehouseLocation.bin_code)
        .limit(2000)
        .all()
    )
    return jsonify({"ok": True, "items": [serialize_inventory_item(row) for row in inventory]})


@api_bp.route("/central-panel/settings", methods=["GET", "OPTIONS"])
@integration_key_required
def api_central_panel_settings():
    if request.method == "OPTIONS":
        return "", 204
    settings = CentralPanelSetting.query.order_by(CentralPanelSetting.section).all()
    return jsonify({"ok": True, "settings": [serialize_central_panel_setting(setting) for setting in settings]})


@api_bp.route("/central-panel/update", methods=["POST", "OPTIONS"])
@integration_key_required
def api_central_panel_update():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(silent=True) or {}
    if data.get("type") != "editor":
        return jsonify({"ok": False, "message": "This record is read-only in the central monitoring panel"}), 400
    section = str(data.get("section") or "").strip()
    updates = data.get("updates")
    if not section or not isinstance(updates, dict):
        return jsonify({"ok": False, "message": "Editor section and updates are required"}), 400
    setting = CentralPanelSetting.query.filter_by(section=section).first()
    if not setting:
        setting = CentralPanelSetting(section=section, payload_json="{}")
        db.session.add(setting)
    setting.payload_json = json.dumps(updates)
    db.session.commit()
    return jsonify({"ok": True, "setting": serialize_central_panel_setting(setting)})


@api_bp.get("/dashboard")
@api_login_required
@picker_permission_required("picker_home")
def api_dashboard():
    today_start = india_today_start()
    warehouse = current_api_warehouse()
    products = Product.query.filter_by(is_active=True).all()
    inventory_query = Inventory.query.join(WarehouseLocation)
    stock_in_query = db.session.query(func.coalesce(func.sum(StockIn.quantity), 0)).join(WarehouseLocation, StockIn.location_id == WarehouseLocation.id).filter(StockIn.received_at >= today_start)
    stock_out_query = db.session.query(func.coalesce(func.sum(StockOut.quantity), 0)).join(WarehouseLocation, StockOut.location_id == WarehouseLocation.id).filter(StockOut.dispatched_at >= today_start)
    if warehouse:
        inventory_query = inventory_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
        stock_in_query = stock_in_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
        stock_out_query = stock_out_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
    inventory_rows = inventory_query.all()
    product_quantities = {}
    stock_value = 0
    for row in inventory_rows:
        product_quantities[row.product_id] = product_quantities.get(row.product_id, 0) + row.quantity
        stock_value += float(row.product.purchase_price or 0) * row.quantity
    low_stock = [product for product in products if product_quantities.get(product.id, 0) <= product.minimum_stock]
    top_selling = (
        db.session.query(Product.id, Product.name, Product.sku, func.sum(StockOut.quantity).label("sold_qty"))
        .join(StockOut, StockOut.product_id == Product.id)
        .join(WarehouseLocation, StockOut.location_id == WarehouseLocation.id)
        .filter(WarehouseLocation.warehouse_id == warehouse.id if warehouse else True)
        .group_by(Product.id)
        .order_by(func.sum(StockOut.quantity).desc())
        .limit(5)
        .all()
    )
    return jsonify(
        {
            "total_products": len(products),
            "total_stock_units": sum(product_quantities.values()),
            "total_stock_value": stock_value,
            "low_stock_items": len(low_stock),
            "today_stock_in": stock_in_query.scalar(),
            "today_stock_out": stock_out_query.scalar(),
            "pending_orders": order_count_query(["pending", "picking", "packed"], warehouse).count(),
            "completed_orders": order_count_query(["completed"], warehouse).count(),
            "top_selling_products": [
                {"id": row.id, "name": row.name, "sku": row.sku, "sold_qty": int(row.sold_qty or 0)}
                for row in top_selling
            ],
        }
    )


@api_bp.get("/cash-tracker/summary")
@api_role_required("manager", "staff")
def api_cash_tracker_summary():
    warehouse = current_api_warehouse()
    collected_query = (
        MoneyTransaction.query.join(Order, MoneyTransaction.order_id == Order.id)
        .filter(
            MoneyTransaction.transaction_type == "inbound_payment",
            MoneyTransaction.direction == "credit",
            func.lower(MoneyTransaction.gateway).in_(["cod", "cash", "cash_on_delivery"]),
            func.lower(MoneyTransaction.status).in_(["paid", "captured", "collected", "payment_complete", "complete", "completed"]),
            Order.external_source == "inbound_customer",
        )
    )
    if warehouse:
        collected_query = collected_query.filter(Order.warehouse_id == warehouse.id)
    collected = float(collected_query.with_entities(func.coalesce(func.sum(MoneyTransaction.amount), 0)).scalar() or 0)
    settled_query = db.session.query(func.coalesce(func.sum(MoneyTransaction.amount), 0)).filter(
        MoneyTransaction.transaction_type == "cash_settlement",
        MoneyTransaction.direction == "debit",
    )
    settlements_query = MoneyTransaction.query.filter_by(transaction_type="cash_settlement", direction="debit")
    if warehouse:
        settled_query = settled_query.filter(MoneyTransaction.warehouse_id == warehouse.id)
        settlements_query = settlements_query.filter(MoneyTransaction.warehouse_id == warehouse.id)
    settled = float(settled_query.scalar() or 0)
    recent_payments = collected_query.order_by(MoneyTransaction.updated_at.desc(), MoneyTransaction.id.desc()).limit(12).all()
    recent_settlements = settlements_query.order_by(MoneyTransaction.created_at.desc(), MoneyTransaction.id.desc()).limit(12).all()
    return jsonify(
        {
            "ok": True,
            "currency": "INR",
            "warehouse": serialize_warehouse(warehouse) if warehouse else None,
            "collectedCash": round(collected, 2),
            "settledCash": round(settled, 2),
            "availableCash": round(max(collected - settled, 0), 2),
            "recentPayments": [serialize_cash_transaction(row) for row in recent_payments],
            "recentSettlements": [serialize_cash_transaction(row) for row in recent_settlements],
        }
    )


@api_bp.post("/cash-tracker/settlements")
@api_role_required("manager", "staff")
def api_cash_tracker_settlement():
    data = request.get_json(silent=True) or {}
    try:
        amount = positive_money(data.get("amount"), "amount")
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    summary = api_cash_tracker_summary().get_json()
    available = float(summary.get("availableCash") or 0)
    if amount > available:
        return jsonify({"ok": False, "message": "Settlement amount is greater than available cash"}), 400
    transaction = MoneyTransaction(
        transaction_number=next_transaction_number("CS"),
        warehouse_id=summary_warehouse_id(),
        transaction_type="cash_settlement",
        direction="debit",
        status="settled",
        gateway="bank",
        reference=trim_text(data.get("bank"), 160),
        amount=amount,
        currency="INR",
        notes=trim_text(data.get("notes") or "Cash tracker settlement", 2000),
        payload_json=json.dumps(data, default=str, separators=(",", ":"))[:20000],
    )
    db.session.add(transaction)
    db.session.commit()
    return jsonify({"ok": True, "settlement": serialize_cash_transaction(transaction)})


@api_bp.get("/products")
@api_login_required
def api_products():
    q = request.args.get("q", "").strip()
    barcode = request.args.get("barcode", "").strip()

    if barcode:
        product = find_product(identifier=barcode)
        return jsonify({"products": [serialize_product(product)] if product else []})

    query = Product.query.filter_by(is_active=True)
    if q:
        like = f"%{q}%"
        sku_like = f"%{normalize_sku(q)}%"
        query = query.filter((Product.name.ilike(like)) | (Product.sku.ilike(like)) | (Product.sku.ilike(sku_like)))
    return jsonify({"products": [serialize_product(product) for product in query.order_by(Product.name).limit(50).all()]})


@api_bp.get("/public/products")
def api_public_products():
    q = request.args.get("q", "").strip()
    limit = min(int_or_default(request.args.get("limit"), 100), 200)

    query = Product.query.filter_by(is_active=True)
    if q:
        like = f"%{q}%"
        sku_like = f"%{normalize_sku(q)}%"
        query = query.filter((Product.name.ilike(like)) | (Product.sku.ilike(like)) | (Product.sku.ilike(sku_like)))

    products = query.order_by(Product.name).limit(limit).all()
    response = jsonify(
        {
            "ok": True,
            "count": len(products),
            "updated_at": india_iso(india_now()),
            "products": [serialize_public_product(product) for product in products],
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@api_bp.get("/public/products/<int:product_id>/image")
def api_public_product_image(product_id):
    product = Product.query.filter_by(id=product_id, is_active=True).first_or_404()
    return serve_product_image(product)


@api_bp.get("/inbound/catalog")
@api_login_required
def api_inbound_catalog():
    user = current_api_user()
    if user.role != "inbound_customer":
        return jsonify({"ok": False, "message": "Inbound customer login required"}), 403
    products = Product.query.filter_by(is_active=True).order_by(Product.name).limit(200).all()
    return jsonify(
        {
            "ok": True,
            "discount_percent": 20,
            "products": [
                serialize_inbound_product(product, user.warehouses[0].id)
                for product in products
                if inbound_available_quantity(product, user.warehouses[0].id) > 0
            ],
        }
    )


@api_bp.get("/inbound/orders")
@api_login_required
def api_inbound_orders():
    user = current_api_user()
    if user.role != "inbound_customer":
        return jsonify({"ok": False, "message": "Inbound customer login required"}), 403
    orders = (
        Order.query.filter_by(external_source="inbound_customer", customer_phone=user.phone)
        .order_by(Order.created_at.desc())
        .limit(100)
        .all()
    )
    return jsonify({"ok": True, "orders": [serialize_inbound_order(order) for order in orders]})


@api_bp.post("/inbound/orders")
@api_login_required
def api_create_inbound_order():
    user = current_api_user()
    if user.role != "inbound_customer":
        return jsonify({"ok": False, "message": "Inbound customer login required"}), 403
    data = request.get_json(silent=True) or {}
    if not user.warehouses:
        return jsonify({"ok": False, "message": "Customer is not assigned to a warehouse"}), 409
    try:
        prepared = prepare_inbound_order_payload(data, user)
        order, created = create_order_from_integration(prepared)
        invoice = ensure_invoice(order, "sale", "issued", payload=prepared)
        if created:
            payment = prepared["payment"]
            transaction = MoneyTransaction.query.filter_by(invoice_id=invoice.id, transaction_type="sale").first()
            if transaction:
                transaction.transaction_type = "inbound_payment"
                transaction.status = "pending" if payment["method"] == "cod" else "payment_pending"
                transaction.gateway = payment["method"]
                transaction.warehouse_id = order.warehouse_id
                transaction.reference = payment.get("reference", "")
                transaction.notes = "Inbound customer checkout payment"
                transaction.payload_json = json.dumps(payment, default=str, separators=(",", ":"))[:20000]
        db.session.commit()
        return jsonify({"ok": True, "created": created, "order": serialize_inbound_order(order)}), 201 if created else 200
    except (TypeError, ValueError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.get("/products/<int:product_id>")
@api_login_required
def api_product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    return jsonify({"product": serialize_product(product)})


@api_bp.get("/products/<int:product_id>/image")
@api_login_required
def api_product_image(product_id):
    product = Product.query.get_or_404(product_id)
    return serve_product_image(product)


def serve_product_image(product):
    image_url = (product.image_url or "").strip()
    if not image_url:
        return jsonify({"ok": False, "message": "Product image not found"}), 404

    if image_url.startswith(("http://", "https://", "/")):
        return redirect(image_url)

    if image_url.startswith("gs://"):
        try:
            bucket_name, object_name = parse_gs_url(image_url)
            blob = get_storage_client().bucket(bucket_name).blob(object_name)
            image_bytes = blob.download_as_bytes()
            response = Response(image_bytes, mimetype=blob.content_type or "application/octet-stream")
            response.headers["Cache-Control"] = "private, max-age=300"
            return response
        except Exception as error:
            return jsonify({"ok": False, "message": str(error)}), 404

    return jsonify({"ok": False, "message": "Unsupported product image URL"}), 400


def inbound_available_quantity(product, warehouse_id):
    return max(int(
        db.session.query(func.coalesce(func.sum(Inventory.quantity - Inventory.reserved_quantity), 0))
        .join(WarehouseLocation, Inventory.location_id == WarehouseLocation.id)
        .filter(
            Inventory.product_id == product.id,
            WarehouseLocation.warehouse_id == warehouse_id,
            WarehouseLocation.is_virtual.is_(False),
        )
        .scalar()
        or 0
    ), 0)


def serialize_inbound_product(product, warehouse_id):
    product_data = serialize_public_product(product)
    regular_price = float(product.selling_price or product.purchase_price or 0)
    available_quantity = inbound_available_quantity(product, warehouse_id)
    product_data.update(
        {
            "regular_price": regular_price,
            "inbound_price": round(regular_price * 0.80, 2),
            "discount_percent": 20,
            "available_quantity": available_quantity,
            "in_stock": available_quantity > 0,
        }
    )
    return product_data


def prepare_inbound_order_payload(data, user):
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    if not user.phone:
        raise ValueError("Inbound customer account needs a phone number")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Add at least one product to the cart")
    priced_items = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each cart item must be an object")
        product = find_product_from_payload(item, required=True)
        quantity = positive_int(item.get("quantity"), "quantity")
        available_quantity = inbound_available_quantity(product, user.warehouses[0].id)
        if available_quantity < quantity:
            raise ValueError(f"Only {available_quantity} {product.name} available in your warehouse")
        regular_price = float(product.selling_price or product.purchase_price or 0)
        priced_items.append(
            {
                "product_id": product.id,
                "sku": product.sku,
                "quantity": quantity,
                "regular_price": regular_price,
                "unit_price": round(regular_price * 0.80, 2),
                "discount_percent": 20,
            }
        )
    payment = data.get("payment") if isinstance(data.get("payment"), dict) else {}
    payment_method = trim_text(payment.get("method") or "cod", 20).lower()
    if payment_method not in {"cod", "upi", "bank_transfer", "card"}:
        raise ValueError("Supported payments are COD, UPI, bank transfer or card")
    order_id = trim_text(data.get("order_id") or data.get("orderId"), 120) or f"INB-{india_timestamp()}"
    address = trim_text(data.get("customer_address") or data.get("address"), 2000)
    if not address:
        raise ValueError("Delivery address is required")
    return {
        "source": "inbound_customer",
        "external_order_id": order_id,
        "order_number": order_id,
        "warehouse_id": user.warehouses[0].id,
        "customer_name": user.full_name,
        "customer_phone": user.phone,
        "customer_address": address,
        "priority": "normal",
        "discount": {"type": "inbound_customer", "percent": 20},
        "payment": {
            "method": payment_method,
            "status": "pending",
            "reference": trim_text(payment.get("reference"), 160),
        },
        "customer": {"id": user.id, "email": user.email, "name": user.full_name, "phone": user.phone},
        "items": priced_items,
    }


@api_bp.get("/scan/<path:code>")
@api_login_required
@picker_permission_required("picker_pick", "picker_stock_in", "picker_stock_take", "picker_move_stock", "picker_bins", "picker_returns")
def api_scan(code):
    if request.args.get("type") == "location":
        location = find_location(identifier=code)
        if location:
            return jsonify({"type": "location", "location": serialize_location(location)})
        return jsonify({"type": "unknown", "message": "Bin/location not found"}), 404

    product = find_product(identifier=code)
    if product:
        return jsonify({"type": "product", "product": serialize_product(product)})

    location = find_location(identifier=code)
    if location:
        return jsonify({"type": "location", "location": serialize_location(location)})

    return jsonify({"type": "unknown", "message": "Code not found"}), 404


@api_bp.get("/locations")
@api_login_required
def api_locations():
    warehouse = current_api_warehouse()
    query = WarehouseLocation.query.join(Warehouse).filter(WarehouseLocation.is_active.is_(True))
    if warehouse:
        query = query.filter(WarehouseLocation.warehouse_id == warehouse.id)
    locations = query.order_by(Warehouse.code, WarehouseLocation.zone, WarehouseLocation.rack).all()
    return jsonify({"locations": [serialize_location(location) for location in locations]})


@api_bp.get("/warehouses")
@api_login_required
def api_warehouses():
    warehouses = accessible_api_warehouses()
    return jsonify({"warehouses": [serialize_warehouse(warehouse) for warehouse in warehouses]})


@api_bp.get("/location-inventory/<path:identifier>")
@api_role_required("manager", "staff", "picker", "packer")
@picker_permission_required("picker_pick", "picker_stock_in", "picker_stock_take", "picker_move_stock", "picker_bins")
def api_location_inventory(identifier):
    try:
        location = find_location(identifier=identifier, required=True)
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 404
    rows = (
        Inventory.query.join(Product)
        .filter(Inventory.location_id == location.id, Inventory.quantity > 0, Product.is_active.is_(True))
        .order_by(Product.name, Product.sku)
        .all()
    )
    return jsonify(
        {
            "ok": True,
            "location": serialize_location(location),
            "items": [serialize_inventory_item(row) for row in rows],
        }
    )


@api_bp.post("/integrations/orders")
@integration_key_required
def api_import_order():
    data = request.get_json(silent=True) or {}
    try:
        order, created = create_order_from_integration(data)
        shiprocket = {"created": False, "skipped": True, "message": "Courier creation deferred until dispatch"}
        invoice = ensure_invoice(order, "sale", "issued", payload=data)
        if created:
            redeem_order_coupon(order, data)
        sync_sale_transaction_payment(invoice, data)
        db.session.commit()
        return jsonify({"ok": True, "created": created, "order": serialize_order(order), "shiprocket": shiprocket}), 201 if created else 200
    except (TypeError, ValueError, ShiprocketError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/coupons/validate")
@integration_key_required
def api_validate_coupon():
    data = request.get_json(silent=True) or {}
    try:
        result = validate_coupon(data.get("code"), data.get("customer_phone") or data.get("phone"), data.get("subtotal"))
        return jsonify(
            {
                "ok": True,
                "coupon": {
                    "code": result["code"],
                    "title": result["title"],
                    "discount_type": result["discount_type"],
                    "discount_value": result["discount_value"],
                    "discount": result["discount"],
                    "subtotal": result["subtotal"],
                },
            }
        )
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/integrations/returns")
@integration_key_required
def api_import_return():
    data = request.get_json(silent=True) or {}
    try:
        return_order, created = create_return_from_integration(data)
        shiprocket = create_shiprocket_return_for_customer_return(return_order, user_id=current_api_user_id())
        if return_order.order:
            ensure_invoice(return_order.order, "return", "return_requested", payload=data)
        db.session.commit()
        return jsonify({"ok": True, "created": created, "return_order": serialize_return_order(return_order), "shiprocket": shiprocket}), 201 if created else 200
    except (TypeError, ValueError, ShiprocketError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/integrations/order-cancel")
@integration_key_or_staff_session_required
def api_import_order_cancel():
    data = request.get_json(silent=True) or {}
    try:
        orders = find_orders_for_action(data)
        if not orders:
            return jsonify({"ok": False, "message": "Order not found for cancellation"}), 404
        cancel_stock_orders = []
        shiprocket_cancels = []
        for order in orders:
            shiprocket_cancel = None
            if order.courier_order_id and not order_is_shipped(order):
                shiprocket_cancel = cancel_shiprocket_order([order.courier_order_id], current_app.config)
            cancel_stock_order = create_cancel_stock_in_order(order, data)
            order.status = "cancelled" if not cancel_stock_order else "cancel_requested"
            ensure_invoice(order, "cancel", "cancelled", payload=data)
            if cancel_stock_order:
                cancel_stock_orders.append(cancel_stock_order)
            if shiprocket_cancel:
                shiprocket_cancels.append(shiprocket_cancel)
        primary_order = orders[0]
        refund, created = create_refund_from_cancel(data, primary_order)
        log_activity(
            "order_cancel_request",
            f"Imported cancel request for {data.get('orderId') or data.get('order_id') or primary_order.order_number}",
            entity_type="Order",
            entity_id=primary_order.id,
            meta={
                "refund_id": refund.id if refund else None,
                "refund_created": created,
                "cancelled_order_ids": [order.id for order in orders],
                "cancel_stock_order_ids": [return_order.id for return_order in cancel_stock_orders],
                "shiprocket_cancels": shiprocket_cancels,
            },
        )
        db.session.commit()
        return jsonify(
            {
                "ok": True,
                "order": serialize_order(primary_order),
                "orders": [serialize_order(order) for order in orders],
                "cancelled_order_count": len(orders),
                "refund": serialize_payment_refund(refund) if refund else None,
                "refund_created": created,
                "cancel_stock_order": serialize_return_order(cancel_stock_orders[0]) if cancel_stock_orders else None,
                "cancel_stock_orders": [serialize_return_order(return_order) for return_order in cancel_stock_orders],
                "shiprocket_cancel": shiprocket_cancels[0] if shiprocket_cancels else None,
                "shiprocket_cancels": shiprocket_cancels,
            }
        )
    except (TypeError, ValueError, ShiprocketError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/integrations/refunds/<int:refund_id>/approve")
@api_role_required("manager", "staff")
def api_approve_payment_refund(refund_id):
    refund = PaymentRefund.query.get_or_404(refund_id)
    if refund.status in {"approved", "refunded"}:
        return jsonify({"ok": True, "refund": serialize_payment_refund(refund)})
    try:
        approve_payment_refund(refund)
        db.session.commit()
        return jsonify({"ok": True, "refund": serialize_payment_refund(refund)})
    except (RazorpayRefundError, ValueError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/integrations/razorpay/webhook")
def api_razorpay_webhook():
    raw_body = request.get_data(cache=False)
    if not verify_razorpay_webhook(raw_body, request.headers.get("X-Razorpay-Signature", "")):
        return jsonify({"ok": False, "message": "Invalid Razorpay webhook signature"}), 400
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return jsonify({"ok": False, "message": "Invalid Razorpay webhook payload"}), 400
    event = str(payload.get("event") or "").lower()
    refund_data = (((payload.get("payload") or {}).get("refund") or {}).get("entity") or {})
    refund_id = trim_text(refund_data.get("id"), 120)
    payment_id = trim_text(refund_data.get("payment_id"), 120)
    refund = PaymentRefund.query.filter_by(gateway_transaction_id=refund_id).first() if refund_id else None
    if not refund and payment_id:
        refund = (
            PaymentRefund.query.filter_by(gateway_payment_id=payment_id)
            .filter(PaymentRefund.status.in_(["requested", "approved"]))
            .order_by(PaymentRefund.created_at.desc())
            .first()
        )
    if refund and event in {"refund.processed", "refund.failed"}:
        refund.gateway_transaction_id = refund_id or refund.gateway_transaction_id
        refund.gateway_response = json.dumps(payload, default=str, separators=(",", ":"))[:20000]
        refund.status = "refunded" if event == "refund.processed" else "failed"
        db.session.commit()
    return jsonify({"ok": True})


@api_bp.post("/stock-in")
@api_role_required("manager", "staff", "picker")
@picker_permission_required("picker_stock_in")
def api_stock_in():
    data = request.form if request.form else (request.get_json(silent=True) or {})
    try:
        product = find_product_from_payload(data, required=True)
        location = find_or_create_stock_in_location(data.get("location") or data.get("location_id") or data.get("location_barcode"))
        entry = receive_stock(
            product_id=product.id,
            supplier_id=int_or_none(data.get("supplier_id")),
            location_id=location.id,
            quantity=int(data.get("quantity", 0)),
            unit_cost=float(data.get("unit_cost") or 0),
            invoice_number=data.get("invoice_number"),
            received_by_id=current_api_user_id(),
            notes=data.get("notes"),
        )
        uploaded_file = request.files.get("image_file")
        if uploaded_file and uploaded_file.filename:
            product.image_url = upload_product_image(uploaded_file, sku=product.sku)
        db.session.commit()
        sync_result = auto_sync_current_stock_sheet("api_stock_in")
        push_result = notify_product_change(product, "stock.changed")
        return jsonify({"ok": True, "stock_in": {"id": entry.id}, "product": serialize_product(product), "google_sheet": sync_result, "customer_website": push_result})
    except (RuntimeError, ValueError, TypeError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/stock-out")
@api_role_required("manager", "staff")
def api_stock_out():
    data = request.get_json(silent=True) or {}
    try:
        product = find_product_from_payload(data, required=True)
        location = find_location(required=True, identifier=data.get("location") or data.get("location_id") or data.get("location_barcode"))
        entry = issue_stock(
            product_id=product.id,
            location_id=location.id,
            quantity=int(data.get("quantity", 0)),
            reason=data.get("reason", "sale"),
            order_id=int_or_none(data.get("order_id")),
            dispatched_by_id=current_api_user_id(),
            notes=data.get("notes"),
        )
        db.session.commit()
        sync_result = auto_sync_current_stock_sheet("api_stock_out")
        push_result = notify_product_change(product, "stock.changed")
        return jsonify({"ok": True, "stock_out": {"id": entry.id}, "product": serialize_product(product), "google_sheet": sync_result, "customer_website": push_result})
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/location-update")
@api_role_required("manager", "staff", "picker")
@picker_permission_required("picker_move_stock")
def api_location_update():
    data = request.get_json(silent=True) or {}
    try:
        product = find_product_from_payload(data, required=True)
        from_location = find_location(required=True, identifier=data.get("from_location") or data.get("from_location_id"))
        to_location = find_location(required=True, identifier=data.get("to_location") or data.get("to_location_id"))
        quantity = int(data.get("quantity", 0))
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero")

        source = Inventory.query.filter_by(product_id=product.id, location_id=from_location.id).first()
        if not source or source.available_quantity < quantity:
            raise ValueError("Not enough stock at source location")

        target = get_or_create_inventory(product.id, to_location.id)
        source.quantity -= quantity
        target.quantity += quantity
        log_activity(
            "location_update",
            f"Moved {quantity} units to {to_location.full_code}",
            user_id=current_api_user_id(),
            entity_type="Product",
            entity_id=product.id,
            meta={"from_location_id": from_location.id, "to_location_id": to_location.id, "quantity": quantity},
        )
        db.session.commit()
        sync_result = auto_sync_current_stock_sheet("api_location_update")
        push_result = notify_product_change(product, "stock.changed")
        return jsonify({"ok": True, "product": serialize_product(product), "google_sheet": sync_result, "customer_website": push_result})
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.get("/pick-list")
@api_role_required("manager", "staff", "picker", "packer", "delivery")
@picker_permission_required("picker_pick", "picker_ship")
def api_pick_list():
    user = current_api_user()
    warehouse = current_api_warehouse()
    presence_changed = update_picker_presence(user, request)
    if picker_online_from_request(request):
        assigned = auto_assign_order_to_picker(user, warehouse)
        if assigned:
            log_activity(
                "picker_auto_assign",
                f"Auto assigned {assigned.order_number} to {user.full_name}",
                user_id=user.id,
                entity_type="Order",
                entity_id=assigned.id,
            )
        if assigned or presence_changed:
            db.session.commit()
    elif presence_changed:
        db.session.commit()
    query = Order.query.filter(Order.status.in_(["pending", "picking", "packed", "dispatched"]))
    if warehouse:
        query = query.filter(Order.warehouse_id == warehouse.id)
    if user and not can_manage_all_orders(user):
        query = query.filter(Order.assigned_to_id == user.id)
    orders = query.order_by(Order.priority.desc(), Order.created_at).all()
    return jsonify({"orders": [serialize_order(order) for order in orders]})


@api_bp.get("/returns/pick-list")
@api_role_required("manager", "staff", "picker")
@picker_permission_required("picker_returns")
def api_return_pick_list():
    user = current_api_user()
    warehouse = current_api_warehouse()
    ensure_virtual_return_bins()
    update_picker_presence(user, request)
    db.session.commit()
    query = CustomerReturnOrder.query.filter(CustomerReturnOrder.status.in_(["approved", "return_picking", "return_picked", "inspection"]))
    if user and user.role == "picker":
        query = query.filter(CustomerReturnOrder.assigned_to_id == user.id)
    elif warehouse:
        query = query.outerjoin(Order).filter(or_(CustomerReturnOrder.order_id.is_(None), Order.warehouse_id == warehouse.id))
    returns = query.order_by(CustomerReturnOrder.requested_at, CustomerReturnOrder.id).all()
    return jsonify({"returns": [serialize_return_order(return_order) for return_order in returns]})


@api_bp.post("/returns/<int:return_id>/items/<int:item_id>/pick")
@api_role_required("manager", "staff", "picker")
@picker_permission_required("picker_returns")
def api_return_item_pick(return_id, item_id):
    data = request.get_json(silent=True) or {}
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
    if not can_access_return_order(current_api_user(), return_order):
        return jsonify({"ok": False, "message": "This return is not assigned to you"}), 403
    if return_order.status not in {"approved", "return_picking", "return_picked"}:
        return jsonify({"ok": False, "message": "Return must be approved before picking"}), 400
    item = CustomerReturnItem.query.filter_by(id=item_id, return_order_id=return_order.id).first_or_404()
    try:
        quantity = int(data.get("quantity", item.expected_quantity))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Quantity must be a number"}), 400
    if quantity < 0 or quantity > item.expected_quantity:
        return jsonify({"ok": False, "message": "Picked quantity must be between 0 and return quantity"}), 400

    item.picked_quantity = quantity
    item.status = "picked" if quantity >= item.expected_quantity else "pending"
    return_order.status = "return_picked" if all(row.picked_quantity >= row.expected_quantity for row in return_order.items) else "return_picking"
    log_activity("return_pick", f"Picked return item {item.product.sku}: {quantity}/{item.expected_quantity}", user_id=current_api_user_id(), entity_type="CustomerReturnItem", entity_id=item.id)
    db.session.commit()
    return jsonify({"ok": True, "return_order": serialize_return_order(return_order)})


@api_bp.post("/returns/<int:return_id>/initiate-pv")
@api_role_required("manager", "staff", "picker")
@picker_permission_required("picker_returns")
def api_return_initiate_pv(return_id):
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
    if not can_access_return_order(current_api_user(), return_order):
        return jsonify({"ok": False, "message": "This return is not assigned to you"}), 403
    if not return_order.items or not all(item.picked_quantity >= item.expected_quantity for item in return_order.items):
        return jsonify({"ok": False, "message": "Pick all return items before PV"}), 400
    return_order.status = "inspection"
    log_activity("return_pv", f"PV initiated for {return_order.return_number}", user_id=current_api_user_id(), entity_type="CustomerReturnOrder", entity_id=return_order.id)
    db.session.commit()
    return jsonify({"ok": True, "return_order": serialize_return_order(return_order)})


@api_bp.post("/returns/<int:return_id>/items/<int:item_id>/stock-in")
@api_role_required("manager", "staff", "picker")
@picker_permission_required("picker_returns")
def api_return_item_stock_in(return_id, item_id):
    data = request.get_json(silent=True) or {}
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
    if not can_access_return_order(current_api_user(), return_order):
        return jsonify({"ok": False, "message": "This return is not assigned to you"}), 403
    if return_order.status != "inspection":
        return jsonify({"ok": False, "message": "Initiate PV before stock in"}), 400
    item = CustomerReturnItem.query.filter_by(id=item_id, return_order_id=return_order.id).first_or_404()
    try:
        quantity = int(data.get("quantity", 1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Quantity must be a number"}), 400
    if quantity <= 0 or quantity > item.remaining_stock_in_quantity:
        return jsonify({"ok": False, "message": "Quantity is more than pending picked return quantity"}), 400

    condition = str(data.get("condition") or "no_issue").strip().lower()
    try:
        location = find_location(identifier=data.get("location") or data.get("location_id") or data.get("location_barcode"), required=True)
        if condition == "issue":
            suggested_location = ensure_virtual_return_bins()["customer_return"]
            if not location.is_virtual or location.id != suggested_location.id:
                raise ValueError(f"Product issue stock must go to virtual return bin {suggested_location.barcode}")
            item.issue_quantity += quantity
            item.status = "issue" if item.remaining_stock_in_quantity == 0 else "partial"
            notes = f"Customer return issue stock in: {return_order.return_number}"
        elif condition == "no_issue":
            if location.is_virtual:
                raise ValueError("No-issue stock must go to a normal bin")
            item.stocked_quantity += quantity
            item.status = "stocked" if item.remaining_stock_in_quantity == 0 else "partial"
            notes = f"Customer return no-issue stock in: {return_order.return_number}"
        else:
            raise ValueError("Condition must be issue or no_issue")

        entry = receive_stock(
            product_id=item.product_id,
            location_id=location.id,
            quantity=quantity,
            received_by_id=current_api_user_id(),
            notes=notes,
        )
        if all(row.remaining_stock_in_quantity == 0 for row in return_order.items):
            return_order.status = "received"
            return_order.resolved_at = india_now()
        log_activity("return_stock_in", f"Stocked return item {item.product.sku} to {location.barcode or location.id}", user_id=current_api_user_id(), entity_type="CustomerReturnItem", entity_id=item.id)
        db.session.commit()
        sync_result = auto_sync_current_stock_sheet("customer_return_stock_in")
        push_result = notify_product_change(item.product, "stock.changed")
        return jsonify({"ok": True, "stock_in": {"id": entry.id}, "return_order": serialize_return_order(return_order), "google_sheet": sync_result, "customer_website": push_result})
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/orders/<int:order_id>/status")
@api_role_required("manager", "staff", "picker", "packer", "delivery")
@picker_permission_required("picker_pick")
def api_order_status(order_id):
    data = request.get_json(silent=True) or {}
    order = Order.query.get_or_404(order_id)
    if not can_access_order(current_api_user(), order):
        return jsonify({"ok": False, "message": "Permission denied for this order"}), 403
    allowed = {"pending", "picking", "packed", "dispatched", "completed", "cancelled"}
    status = data.get("status", "").strip().lower()
    if status not in allowed:
        return jsonify({"ok": False, "message": "Invalid order status"}), 400
    if status == "dispatched":
        return dispatch_order_api_response(order, data)
    if status == "picking" and not order.assigned_to_id:
        if current_api_user().role == "picker" and picker_workload(current_api_user_id()) > 0:
            return jsonify({"ok": False, "message": "Complete your active pick before starting another order"}), 409
        order.assigned_to_id = current_api_user_id()
    order.status = status
    if status == "completed":
        order.completed_at = india_now()
    log_activity("order_status", f"Order {order.order_number} marked {status}", user_id=current_api_user_id(), entity_type="Order", entity_id=order.id)
    db.session.commit()
    return jsonify({"ok": True, "order": serialize_order(order)})


@api_bp.post("/orders/<int:order_id>/dispatch")
@api_role_required("manager", "staff", "picker", "packer", "delivery")
@picker_permission_required("picker_ship")
def api_dispatch_order(order_id):
    data = request.get_json(silent=True) or {}
    order = Order.query.get_or_404(order_id)
    if not can_access_order(current_api_user(), order):
        return jsonify({"ok": False, "message": "Permission denied for this order"}), 403
    return dispatch_order_api_response(order, data)


@api_bp.post("/orders/<int:order_id>/label")
@api_role_required("manager", "staff", "picker", "packer", "delivery")
@picker_permission_required("picker_ship")
def api_order_label(order_id):
    data = request.get_json(silent=True) or {}
    order = Order.query.get_or_404(order_id)
    if not can_access_order(current_api_user(), order):
        return jsonify({"ok": False, "message": "Permission denied for this order"}), 403
    if is_fast_delivery_order(order):
        return jsonify(
            {
                "ok": True,
                "label_url": "",
                "order": serialize_order(order),
                "shiprocket": {"created": False, "skipped": True, "message": "Fast delivery orders are handled locally"},
            }
        )
    try:
        result = ensure_shiprocket_label(order, user_id=current_api_user_id(), package_input=data)
        db.session.commit()
        return jsonify({"ok": True, "label_url": result.get("label_url"), "order": serialize_order(order), "shiprocket": result.get("summary")})
    except (ShiprocketError, ValueError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


def dispatch_order_api_response(order, data):
    if order.status not in {"packed", "dispatched"}:
        return jsonify({"ok": False, "message": "Order must be packed before dispatch"}), 400
    if not all(item.packed_quantity >= item.quantity for item in order.items):
        return jsonify({"ok": False, "message": "Pack all order items before dispatch"}), 400
    if is_fast_delivery_order(order):
        order.status = "dispatched"
        db.session.commit()
        return jsonify(
            {
                "ok": True,
                "order": serialize_order(order),
                "shiprocket": {"created": False, "skipped": True, "message": "Fast delivery orders are handled locally"},
                "created_courier_order": False,
            }
        )
    try:
        result = dispatch_order_with_shiprocket(order, data, user_id=current_api_user_id())
        db.session.commit()
        return jsonify(
            {
                "ok": True,
                "order": serialize_order(order),
                "shiprocket": result["summary"],
                "created_courier_order": result["created"],
            }
        )
    except (ShiprocketError, ValueError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/orders/<int:order_id>/items/<int:item_id>/pick")
@api_role_required("manager", "staff", "picker")
@picker_permission_required("picker_pick")
def api_order_item_pick(order_id, item_id):
    data = request.get_json(silent=True) or {}
    order = Order.query.get_or_404(order_id)
    if not can_access_order(current_api_user(), order):
        return jsonify({"ok": False, "message": "Permission denied for this order"}), 403
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()
    try:
        quantity = int(data.get("quantity", item.quantity))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Quantity must be a number"}), 400

    if quantity < 0 or quantity > item.quantity:
        return jsonify({"ok": False, "message": "Picked quantity must be between 0 and ordered quantity"}), 400

    try:
        if not order.assigned_to_id:
            if current_api_user().role == "picker" and picker_workload(current_api_user_id()) > 0:
                return jsonify({"ok": False, "message": "Complete your active pick before picking another order"}), 409
            order.assigned_to_id = current_api_user_id()
        item.picked_quantity = quantity
        if order.status == "pending":
            order.status = "picking"
        if all(order_item.picked_quantity >= order_item.quantity for order_item in order.items):
            order.status = "packed" if data.get("auto_pack") else "picking"

        sync_order_product_pick_stock(
            order,
            item.product_id,
            location_identifier=data.get("location") or data.get("location_id") or data.get("location_barcode"),
        )
        log_activity(
            "item_pick",
            f"Picked {quantity}/{item.quantity} for {item.product.sku}",
            user_id=current_api_user_id(),
            entity_type="OrderItem",
            entity_id=item.id,
        )
        db.session.commit()
        sync_result = auto_sync_current_stock_sheet("order_pick")
        push_result = notify_product_change(item.product, "stock.changed")
        return jsonify({"ok": True, "order": serialize_order(order), "google_sheet": sync_result, "customer_website": push_result})
    except ValueError as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/orders/<int:order_id>/items/<int:item_id>/not-found")
@api_role_required("manager", "staff", "picker")
@picker_permission_required("picker_pick")
def api_order_item_not_found(order_id, item_id):
    data = request.get_json(silent=True) or {}
    user = current_api_user()
    order = Order.query.get_or_404(order_id)
    if not can_access_order(user, order):
        return jsonify({"ok": False, "message": "Permission denied for this order"}), 403
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()
    remaining = max(int(item.quantity or 0) - int(item.picked_quantity or 0), 0)
    if remaining <= 0:
        return jsonify({"ok": False, "message": "This item is already completed"}), 400
    try:
        quantity = positive_int(data.get("quantity") or remaining, "quantity")
        if quantity > remaining:
            raise ValueError("Quantity cannot exceed remaining pick quantity")
        location = find_location(identifier=data.get("location") or data.get("location_id") or data.get("location_barcode"), required=True)
        if location.warehouse_id != order.warehouse_id or location.is_virtual:
            raise ValueError("Select a normal bin from this order warehouse")
        inventory = Inventory.query.filter_by(product_id=item.product_id, location_id=location.id).first()
        stock_deducted = min(quantity, int(inventory.quantity or 0)) if inventory else 0
        if inventory and stock_deducted:
            inventory.quantity -= stock_deducted
            inventory.reserved_quantity = min(inventory.reserved_quantity, inventory.quantity)

        report = ItemNotFoundReport(
            order_id=order.id,
            order_item_id=item.id,
            product_id=item.product_id,
            warehouse_id=order.warehouse_id,
            location_id=location.id,
            picker_id=user.id,
            quantity=quantity,
            stock_deducted_quantity=stock_deducted,
            unit_price=item.unit_price or 0,
            notes=trim_text(data.get("notes") or "Item not found during picking", 1000),
        )
        db.session.add(report)
        item.quantity -= quantity
        if item.packed_quantity > item.quantity:
            item.packed_quantity = item.quantity
        if all(order_item.picked_quantity >= order_item.quantity for order_item in order.items):
            order.status = "packed" if data.get("auto_pack") else "picking"
        revised_total = order.total_value
        for invoice in Invoice.query.filter_by(order_id=order.id).all():
            invoice.amount = revised_total
        for transaction in MoneyTransaction.query.filter_by(order_id=order.id).all():
            transaction.amount = revised_total
        log_activity(
            "item_not_found",
            f"INF {item.product.sku}: removed {quantity} from order, stock adjusted {stock_deducted}",
            user_id=user.id,
            entity_type="ItemNotFoundReport",
            meta={"order_id": order.id, "product_id": item.product_id, "warehouse_id": order.warehouse_id, "location_id": location.id, "quantity": quantity, "stock_deducted_quantity": stock_deducted},
        )
        db.session.commit()
        sync_result = auto_sync_current_stock_sheet("item_not_found")
        push_result = notify_product_change(item.product, "stock.changed")
        return jsonify({"ok": True, "order": serialize_order(order), "report": serialize_item_not_found_report(report), "google_sheet": sync_result, "customer_website": push_result})
    except (TypeError, ValueError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/orders/<int:order_id>/items/<int:item_id>/pack")
@api_role_required("manager", "staff", "picker", "packer")
@picker_permission_required("picker_pick")
def api_order_item_pack(order_id, item_id):
    data = request.get_json(silent=True) or {}
    order = Order.query.get_or_404(order_id)
    if not can_access_order(current_api_user(), order):
        return jsonify({"ok": False, "message": "Permission denied for this order"}), 403
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()
    try:
        quantity = int(data.get("quantity", item.picked_quantity or item.quantity))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Quantity must be a number"}), 400

    if quantity < 0 or quantity > item.quantity:
        return jsonify({"ok": False, "message": "Packed quantity must be between 0 and ordered quantity"}), 400

    item.packed_quantity = quantity
    if all(order_item.packed_quantity >= order_item.quantity for order_item in order.items):
        order.status = "packed"

    log_activity(
        "item_pack",
        f"Packed {quantity}/{item.quantity} for {item.product.sku}",
        user_id=current_api_user_id(),
        entity_type="OrderItem",
        entity_id=item.id,
    )
    db.session.commit()
    return jsonify({"ok": True, "order": serialize_order(order)})


def current_api_user_id():
    user = current_api_user()
    return user.id if user else None


def picker_has_permission(user, *requested):
    if not user or user.role != "picker":
        return True
    allowed = user_page_permissions(user) if user.page_permissions else set(role_permissions("picker"))
    legacy = {
        "picker_home": {"dashboard"},
        "picker_pick": {"orders", "picker_ops", "pick_transfer"},
        "picker_ship": {"shiprocket", "shipping_status"},
        "picker_returns": {"returns"},
        "picker_stock_in": {"stock_in"},
        "picker_stock_take": {"inventory"},
        "picker_move_stock": {"locations"},
        "picker_bins": {"inventory"},
        "picker_tools": {"picker_ops"},
    }
    return any(permission in allowed or bool(legacy.get(permission, set()) & allowed) for permission in requested)


def order_count_query(statuses, warehouse=None):
    query = Order.query.filter(Order.status.in_(statuses))
    if warehouse:
        query = query.filter(Order.warehouse_id == warehouse.id)
    return query


def current_api_user():
    bearer_user = current_bearer_user()
    if bearer_user:
        return bearer_user

    user_id = session.get("user_id")
    if user_id:
        return User.query.filter_by(id=user_id, is_active=True).first()
    if not current_app.config.get("ALLOW_INSECURE_USER_HEADER"):
        return None
    header_user_id = request.headers.get("X-User-Id")
    if header_user_id and header_user_id.isdigit():
        return User.query.filter_by(id=int(header_user_id), is_active=True).first()
    return None


def accessible_api_warehouses(user=None):
    user = user or current_api_user()
    if not user:
        return []
    assigned = [warehouse for warehouse in user.warehouses if warehouse.is_active]
    if assigned:
        return sorted(assigned, key=lambda warehouse: warehouse.code)
    if user.role == "admin":
        return Warehouse.query.filter_by(is_active=True).order_by(Warehouse.code).all()
    return []


def current_api_warehouse():
    warehouses = accessible_api_warehouses()
    if not warehouses:
        return None
    allowed_ids = {warehouse.id for warehouse in warehouses}
    data = request.get_json(silent=True) if request.method in {"POST", "PUT", "PATCH"} else {}
    requested_id = request.headers.get("X-Warehouse-Id") or request.args.get("warehouse_id") or (data or {}).get("warehouse_id") or session.get("warehouse_id")
    try:
        requested_id = int(requested_id) if requested_id else None
    except (TypeError, ValueError):
        requested_id = None
    if requested_id in allowed_ids:
        session["warehouse_id"] = requested_id
        return next(warehouse for warehouse in warehouses if warehouse.id == requested_id)
    warehouse = warehouses[0]
    session["warehouse_id"] = warehouse.id
    return warehouse


def current_bearer_user():
    authorization = request.headers.get("Authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    try:
        data = api_token_serializer().loads(token, salt="warehouse-mobile-api", max_age=api_token_max_age())
    except (BadSignature, SignatureExpired):
        return None
    user_id = data.get("user_id")
    if not user_id:
        return None
    return User.query.filter_by(id=user_id, is_active=True).first()


def create_api_token(user):
    return api_token_serializer().dumps({"user_id": user.id}, salt="warehouse-mobile-api")


def api_token_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def api_token_max_age():
    lifetime = current_app.config.get("PERMANENT_SESSION_LIFETIME")
    if lifetime and hasattr(lifetime, "total_seconds"):
        return int(lifetime.total_seconds())
    return 12 * 60 * 60


def can_manage_all_orders(user):
    return user_has_role(user, "manager", "staff")


def can_access_order(user, order):
    warehouse_ids = {warehouse.id for warehouse in accessible_api_warehouses(user)}
    same_warehouse = not warehouse_ids or order.warehouse_id in warehouse_ids
    return bool(user and same_warehouse and (can_manage_all_orders(user) or order.assigned_to_id in {None, user.id}))


def can_access_return_order(user, return_order):
    if not user:
        return False
    if can_manage_all_orders(user):
        return True
    return user.role == "picker" and return_order.assigned_to_id == user.id


def sync_order_product_pick_stock(order, product_id, location_identifier=None):
    desired_quantity = sum(item.picked_quantity for item in order.items if item.product_id == product_id)
    issued_quantity = (
        db.session.query(func.coalesce(func.sum(StockOut.quantity), 0))
        .filter_by(order_id=order.id, product_id=product_id, reason="order_pick")
        .scalar()
        or 0
    )
    delta = int(desired_quantity) - int(issued_quantity)
    if delta > 0:
        issue_order_pick_stock(order, product_id, delta, location_identifier=location_identifier)
    elif delta < 0:
        restore_order_pick_stock(order, product_id, abs(delta))


def issue_order_pick_stock(order, product_id, quantity, location_identifier=None):
    if location_identifier:
        location = find_location(identifier=location_identifier, required=True)
        if location.is_virtual:
            raise ValueError("Virtual bins cannot be used for order picking")
        inventory = Inventory.query.filter_by(product_id=product_id, location_id=location.id).first()
        if not inventory or inventory.available_quantity < quantity:
            raise ValueError("Not enough available stock in scanned bin for this order item")
        issue_stock(
            product_id=product_id,
            location_id=location.id,
            quantity=quantity,
            reason="order_pick",
            order_id=order.id,
            dispatched_by_id=current_api_user_id(),
            notes=f"Picked for order {order.order_number} from scanned bin",
        )
        return

    remaining = quantity
    warehouse = current_api_warehouse()
    inventory_rows = (
        Inventory.query.join(WarehouseLocation)
        .filter(Inventory.product_id == product_id, WarehouseLocation.is_virtual.is_(False))
        .filter(WarehouseLocation.warehouse_id == warehouse.id if warehouse else True)
        .filter(Inventory.quantity > Inventory.reserved_quantity)
        .order_by(Inventory.quantity.desc(), Inventory.id)
        .all()
    )
    for inventory in inventory_rows:
        if remaining <= 0:
            break
        take = min(remaining, inventory.available_quantity)
        if take <= 0:
            continue
        issue_stock(
            product_id=product_id,
            location_id=inventory.location_id,
            quantity=take,
            reason="order_pick",
            order_id=order.id,
            dispatched_by_id=current_api_user_id(),
            notes=f"Picked for order {order.order_number}",
        )
        remaining -= take
    if remaining > 0:
        raise ValueError("Not enough available stock for this order item")


def restore_order_pick_stock(order, product_id, quantity):
    remaining = quantity
    stock_outs = (
        StockOut.query.filter_by(order_id=order.id, product_id=product_id, reason="order_pick")
        .order_by(StockOut.dispatched_at.desc(), StockOut.id.desc())
        .all()
    )
    for stock_out in stock_outs:
        if remaining <= 0:
            break
        restore_quantity = min(remaining, stock_out.quantity)
        inventory = get_or_create_inventory(product_id, stock_out.location_id)
        inventory.quantity += restore_quantity
        stock_out.quantity -= restore_quantity
        remaining -= restore_quantity
        if stock_out.quantity <= 0:
            db.session.delete(stock_out)
    if remaining > 0:
        raise ValueError("Picked stock restore failed")
    log_activity(
        "order_pick_restore",
        f"Restored {quantity} picked units for order {order.order_number}",
        user_id=current_api_user_id(),
        entity_type="Order",
        entity_id=order.id,
        meta={"product_id": product_id, "quantity": quantity},
    )


def create_order_from_integration(data):
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")

    source = trim_text(data.get("source") or "external", 80).lower()
    external_order_id = trim_text(data.get("external_order_id") or data.get("order_id") or data.get("orderId") or data.get("id"), 120)
    if not external_order_id:
        raise ValueError("external_order_id is required")

    existing = Order.query.filter_by(external_source=source, external_order_id=external_order_id).first()
    if existing:
        apply_fast_delivery_metadata(existing, data)
        return existing, False

    order_number = trim_text(
        data.get("order_number") or data.get("external_order_number") or data.get("orderId") or f"{source.upper()}-{external_order_id}",
        80,
    )
    if not order_number:
        raise ValueError("order_number is required")
    duplicate_order = Order.query.filter_by(order_number=order_number).first()
    if duplicate_order:
        raise ValueError("order_number already exists")

    customer = data.get("customer") or {}
    if customer and not isinstance(customer, dict):
        raise ValueError("customer must be an object")

    customer_name = trim_text(data.get("customer_name") or customer.get("name") or full_name(customer), 160)
    if not customer_name:
        raise ValueError("customer_name is required")

    automation = order_automation_summary(data)
    priority = trim_text(data.get("priority") or ("urgent" if automation["is_express"] else "normal"), 20).lower()
    if priority not in {"normal", "high", "urgent"}:
        raise ValueError("priority must be normal, high, or urgent")
    warehouse = resolve_order_warehouse(data)
    assignee_id = resolve_assignee(data, warehouse=warehouse)

    order = Order(
        order_number=order_number,
        external_source=source,
        external_order_id=external_order_id,
        source_payload=json.dumps(data, default=str, separators=(",", ":"))[:20000],
        warehouse_id=warehouse.id,
        customer_name=customer_name,
        customer_phone=trim_text(data.get("customer_phone") or customer.get("phone"), 30),
        customer_address=trim_text(data.get("customer_address") or customer.get("address") or format_address(data.get("shipping_address") or customer.get("shipping_address")), 2000),
        priority=priority,
        assigned_to_id=assignee_id,
        expected_dispatch_date=parse_expected_dispatch_date(data.get("expected_dispatch_date") or data.get("expectedDispatchDate")),
    )

    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each item must be an object")
        product = find_product_from_payload(item, required=True)
        quantity = positive_int(item.get("quantity"), "quantity")
        unit_price = numeric_or_default(item.get("unit_price") or item.get("price") or item.get("amount"), product.selling_price)
        order.items.append(OrderItem(product_id=product.id, quantity=quantity, unit_price=unit_price))

    db.session.add(order)
    db.session.flush()
    log_activity(
        "order_import",
        f"Imported order {order.order_number} from {source}",
        entity_type="Order",
        entity_id=order.id,
        meta={"source": source, "external_order_id": external_order_id},
    )
    return order, True


def apply_fast_delivery_metadata(order, data):
    automation = order_automation_summary(data)
    if not automation["is_express"]:
        return
    order.priority = "urgent"
    if order.status not in {"picking", "packed", "dispatched", "completed", "delivered", "cancelled", "cancel"}:
        order.status = "pending"
    order.source_payload = json.dumps(data, default=str, separators=(",", ":"))[:20000]


def sync_sale_transaction_payment(invoice, data):
    payment = data.get("payment") if isinstance(data.get("payment"), dict) else {}
    if not payment:
        return
    transaction = MoneyTransaction.query.filter_by(invoice_id=invoice.id, transaction_type="sale").first()
    if not transaction:
        return
    method = trim_text(payment.get("method"), 40).lower()
    gateway = trim_text(payment.get("gateway") or method, 40).lower()
    status = trim_text(payment.get("status") or "recorded", 40).lower()
    reference = trim_text(
        payment.get("paymentId")
        or payment.get("gatewayPaymentId")
        or payment.get("reference")
        or payment.get("gatewayOrderId"),
        160,
    )
    transaction.gateway = gateway or method
    transaction.status = status or transaction.status
    transaction.reference = reference
    transaction.payload_json = json.dumps(payment, default=str, separators=(",", ":"))[:20000]


def create_return_from_integration(data):
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")

    external_return_id = trim_text(data.get("return_id") or data.get("external_return_id") or data.get("id"), 120)
    website_order_id = trim_text(data.get("website_order_id") or data.get("external_order_id") or data.get("order_id"), 120)
    if not external_return_id and not website_order_id:
        raise ValueError("return_id or website_order_id is required")

    return_number = trim_text(data.get("return_number") or data.get("return_order_number") or f"RET-{external_return_id or website_order_id}", 80)
    existing = CustomerReturnOrder.query.filter_by(return_number=return_number).first()
    if existing:
        return existing, False

    original_order = find_order_for_return(data, website_order_id)
    customer = data.get("customer") or {}
    if customer and not isinstance(customer, dict):
        raise ValueError("customer must be an object")
    customer_name = trim_text(data.get("customer_name") or customer.get("name") or (original_order.customer_name if original_order else ""), 160)
    if not customer_name:
        raise ValueError("customer_name is required")

    return_order = CustomerReturnOrder(
        return_number=return_number,
        order_id=original_order.id if original_order else None,
        website_order_id=website_order_id or (original_order.external_order_id if original_order else ""),
        customer_name=customer_name,
        customer_phone=trim_text(data.get("customer_phone") or customer.get("phone") or (original_order.customer_phone if original_order else ""), 30),
        reason=trim_text(data.get("reason") or data.get("return_reason") or "other", 80).lower() or "other",
        status="requested",
        refund_status=trim_text(data.get("refund_status") or "pending", 40).lower() or "pending",
        notes=trim_text(data.get("notes"), 2000),
    )

    items = data.get("items")
    if items is None and original_order:
        items = [{"product_id": item.product_id, "quantity": item.quantity} for item in original_order.items]
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")

    for item_data in items:
        if not isinstance(item_data, dict):
            raise ValueError("Each item must be an object")
        product = find_product_from_payload(item_data, required=True)
        return_order.items.append(
            CustomerReturnItem(
                product_id=product.id,
                expected_quantity=positive_int(item_data.get("quantity") or item_data.get("expected_quantity") or 1, "quantity"),
                notes=trim_text(item_data.get("notes"), 1000),
            )
        )

    db.session.add(return_order)
    db.session.flush()
    log_activity(
        "return_import",
        f"Imported customer return {return_order.return_number}",
        entity_type="CustomerReturnOrder",
        entity_id=return_order.id,
        meta={"website_order_id": website_order_id, "external_return_id": external_return_id},
    )
    return return_order, True


def find_order_for_return(data, website_order_id):
    local_order_id = int_or_none(data.get("local_order_id") or data.get("warehouse_order_id"))
    if local_order_id:
        order = Order.query.get(local_order_id)
        if order:
            return order
    order_lookup = trim_text(data.get("order_number") or website_order_id, 120)
    if not order_lookup:
        return None
    return Order.query.filter(or_(Order.order_number == order_lookup, Order.external_order_id == order_lookup)).first()


def find_orders_for_action(data):
    if not isinstance(data, dict):
        return []
    lookup = trim_text(data.get("orderId") or data.get("order_id") or data.get("order_number") or data.get("external_order_id"), 120)
    if not lookup:
        return []
    candidates = Order.query.filter(
        or_(
            Order.order_number == lookup,
            Order.external_order_id == lookup,
            Order.order_number.like(f"{lookup}-%"),
        )
    ).order_by(Order.id).all()
    return [
        order
        for order in candidates
        if order.order_number == lookup
        or order.external_order_id == lookup
        or (
            order.order_number.startswith(f"{lookup}-")
            and order.order_number[len(lookup) + 1:].isdigit()
        )
    ]


def create_refund_from_cancel(data, order=None):
    refund_data = data.get("refund") if isinstance(data.get("refund"), dict) else {}
    payment = data.get("payment") if isinstance(data.get("payment"), dict) else {}
    amounts = data.get("amounts") if isinstance(data.get("amounts"), dict) else {}
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    snapshot = data.get("orderSnapshot") if isinstance(data.get("orderSnapshot"), dict) else {}
    snapshot_payment = snapshot.get("payment") if isinstance(snapshot.get("payment"), dict) else {}

    gateway = trim_text(refund_data.get("gateway") or payment.get("gateway") or snapshot_payment.get("gateway"), 40).lower()
    payment_method = trim_text(payment.get("method") or snapshot_payment.get("method"), 40).lower()
    payment_status = trim_text(payment.get("status") or snapshot_payment.get("status"), 40).lower()
    payment_id = trim_text(
        refund_data.get("paymentId")
        or refund_data.get("gatewayPaymentId")
        or payment.get("paymentId")
        or snapshot_payment.get("paymentId"),
        120,
    )
    eligible = bool(refund_data.get("eligible")) or (gateway == "razorpay" and payment_method == "online" and payment_status in {"paid", "captured", "success"})
    if not eligible:
        return None, False
    if gateway != "razorpay":
        raise ValueError("Only Razorpay refunds are supported")
    if not payment_id:
        raise ValueError("Razorpay refund request needs paymentId from the paid order")

    request_id = trim_text(data.get("requestId") or refund_data.get("requestId"), 120)
    existing = None
    if request_id:
        existing = PaymentRefund.query.filter_by(request_id=request_id).first()
    if not existing:
        existing = PaymentRefund.query.filter_by(gateway_payment_id=payment_id, status="requested").first()
    if existing:
        return existing, False

    order_lookup = trim_text(data.get("orderId") or data.get("order_id") or (order.order_number if order else ""), 120)
    amount = numeric_or_default(refund_data.get("amount") or amounts.get("total") or snapshot.get("amountTotal"), 0)
    if amount <= 0:
        raise ValueError("Refund amount must be greater than zero")
    refund = PaymentRefund(
        refund_number=next_refund_number(),
        order_id=order.id if order else None,
        website_order_id=order.external_order_id if order else order_lookup,
        request_id=request_id or None,
        customer_name=trim_text(customer.get("name") or (order.customer_name if order else ""), 160) or "Customer",
        customer_phone=trim_text(customer.get("phone") or (order.customer_phone if order else ""), 30),
        gateway="razorpay",
        gateway_payment_id=payment_id,
        gateway_transaction_id=trim_text(refund_data.get("gatewayOrderId") or payment.get("gatewayOrderId") or snapshot_payment.get("gatewayOrderId"), 120),
        amount=amount,
        currency=trim_text(refund_data.get("currency") or amounts.get("currency") or "INR", 8) or "INR",
        reason=trim_text(data.get("reason") or refund_data.get("reason") or "Customer cancelled order", 160),
        status="requested",
        source_payload=json.dumps(data, default=str, separators=(",", ":"))[:20000],
    )
    db.session.add(refund)
    db.session.flush()
    return refund, True


def order_is_shipped(order):
    status_text = " ".join(
        str(value or "")
        for value in [order.status, order.courier_status]
    ).lower()
    return any(token in status_text for token in ["shipped", "pickup", "transit", "delivered", "out for delivery", "rto"])


def create_cancel_stock_in_order(order, data):
    picked_items = [item for item in order.items if int(item.picked_quantity or 0) > 0]
    if not picked_items:
        return None
    return_number = f"CNL-{order.order_number}"[:80]
    existing = CustomerReturnOrder.query.filter_by(return_number=return_number).first()
    if existing:
        return existing
    cancel_order = CustomerReturnOrder(
        return_number=return_number,
        order_id=order.id,
        website_order_id=order.external_order_id or order.order_number,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        reason="cancelled_before_shipping",
        status="inspection",
        refund_status="pending",
        notes=trim_text(data.get("reason") or "Customer cancelled before shipping. Stock-in picked items back to bin.", 2000),
    )
    for item in picked_items:
        cancel_order.items.append(
            CustomerReturnItem(
                product_id=item.product_id,
                expected_quantity=int(item.picked_quantity or 0),
                picked_quantity=int(item.picked_quantity or 0),
                notes=f"Cancelled order stock-in for {order.order_number}",
            )
        )
    db.session.add(cancel_order)
    db.session.flush()
    return cancel_order


def next_refund_number():
    return f"RF-{india_timestamp()}"


def next_transaction_number(prefix="MT"):
    while True:
        number = f"{prefix}-{india_timestamp()}"
        if not MoneyTransaction.query.filter_by(transaction_number=number).first():
            return number


def summary_warehouse_id():
    warehouse = current_api_warehouse()
    return warehouse.id if warehouse else None


def refund_token(refund):
    if refund.refund_token:
        return refund.refund_token
    token = f"RF{refund.id}{india_now().strftime('%H%M%S%f')}"[:23]
    refund.refund_token = token
    return token


def approve_payment_refund(refund):
    if refund.gateway != "razorpay":
        raise ValueError("Only Razorpay refunds can be approved from this panel")
    payload = initiate_razorpay_refund(payment_id=refund.gateway_payment_id, receipt=refund_token(refund), amount=refund.amount)
    refund.status = "refunded" if str(payload.get("status") or "").lower() == "processed" else "approved"
    refund.approved_at = india_now()
    refund.approved_by_id = current_api_user_id()
    refund.gateway_transaction_id = trim_text(payload.get("id"), 120)
    refund.gateway_response = json.dumps(payload, default=str, separators=(",", ":"))[:20000]
    log_activity(
        "payment_refund_approved",
        f"Approved Razorpay refund {refund.refund_number}",
        user_id=current_api_user_id(),
        entity_type="PaymentRefund",
        entity_id=refund.id,
        meta={"amount": float(refund.amount or 0), "payment_id": refund.gateway_payment_id},
    )


def ensure_virtual_return_bins():
    return {
        "customer_return": ensure_virtual_location("RC-DA-01", "RC", "DA", "Virtual", "01"),
        "store_damage": ensure_virtual_location("RE-01-01", "RE", "01", "Virtual", "01"),
    }


def ensure_virtual_location(barcode, zone, rack, shelf, bin_code):
    location = WarehouseLocation.query.filter_by(barcode=barcode).first()
    if location:
        if not location.warehouse_id:
            location.warehouse_id = default_warehouse().id
        location.is_virtual = True
        location.is_active = True
        return location
    location = WarehouseLocation(
        warehouse_id=default_warehouse().id,
        zone=zone,
        rack=rack,
        shelf=shelf,
        bin_code=bin_code,
        barcode=barcode,
        is_active=True,
        is_virtual=True,
    )
    db.session.add(location)
    db.session.flush()
    return location


def trim_text(value, limit):
    return str(value or "").strip()[:limit]


def full_name(customer):
    return " ".join(part for part in [trim_text(customer.get("first_name"), 80), trim_text(customer.get("last_name"), 80)] if part)


def format_address(address):
    if not address:
        return ""
    if isinstance(address, str):
        return address
    if not isinstance(address, dict):
        raise ValueError("shipping_address must be an object or string")
    parts = [
        address.get("name"),
        address.get("line1") or address.get("address1"),
        address.get("line2") or address.get("address2"),
        address.get("city"),
        address.get("state") or address.get("province"),
        address.get("postal_code") or address.get("zip"),
        address.get("country"),
    ]
    return ", ".join(trim_text(part, 160) for part in parts if trim_text(part, 160))


def parse_expected_dispatch_date(value):
    if not value:
        return None
    cleaned = str(value).strip()
    try:
        if "T" in cleaned:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
        return datetime.strptime(cleaned[:10], "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("expected_dispatch_date must be YYYY-MM-DD or ISO datetime") from error


def resolve_order_warehouse(data):
    raw_warehouse_id = data.get("warehouse_id")
    try:
        warehouse_id = int_or_none(raw_warehouse_id)
    except (TypeError, ValueError):
        warehouse_id = None
    if warehouse_id:
        warehouse = Warehouse.query.filter_by(id=warehouse_id, is_active=True).first()
        if not warehouse:
            raise ValueError("warehouse_id not found")
        return warehouse
    warehouse_code = trim_text(data.get("warehouse_code") or data.get("warehouse") or data.get("warehouse_id_code") or raw_warehouse_id, 40).lower()
    if warehouse_code:
        warehouse = Warehouse.query.filter(func.lower(Warehouse.code) == warehouse_code, Warehouse.is_active.is_(True)).first()
        if not warehouse:
            raise ValueError("warehouse_code not found")
        return warehouse
    warehouse = current_api_warehouse() or default_warehouse()
    if not warehouse:
        raise ValueError("Warehouse is required")
    return warehouse


def resolve_assignee(data, warehouse=None):
    assigned_to_id = int_or_none(data.get("assigned_to_id"))
    if assigned_to_id:
        user = User.query.filter_by(id=assigned_to_id, is_active=True).first()
        if not user:
            raise ValueError("assigned_to_id not found")
        if warehouse and user.warehouses and warehouse not in user.warehouses:
            raise ValueError("assigned user is not mapped to this warehouse")
        return user.id

    assigned_to_email = trim_text(data.get("assigned_to_email"), 180).lower()
    if assigned_to_email:
        user = User.query.filter_by(email=assigned_to_email, is_active=True).first()
        if not user:
            raise ValueError("assigned_to_email not found")
        if warehouse and user.warehouses and warehouse not in user.warehouses:
            raise ValueError("assigned user is not mapped to this warehouse")
        return user.id
    return None


def positive_int(value, field_name):
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a number") from error
    if number <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return number


def positive_money(value, field_name):
    try:
        number = round(float(value), 2)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a number") from error
    if number <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return number


def numeric_or_default(value, default):
    if value in (None, ""):
        return default or 0
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("unit_price must be a number") from error


def int_or_none(value):
    if value in (None, ""):
        return None
    return int(value)


def int_or_default(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def find_product_from_payload(data, required=False):
    if isinstance(data, dict):
        try:
            product_id = int_or_none(data.get("product_id") or data.get("productId") or data.get("sourceId"))
        except (TypeError, ValueError):
            product_id = None
        if product_id:
            product = Product.query.get(product_id)
            if product:
                return product

    identifier = None
    if isinstance(data, dict):
        identifier = data.get("sku") or data.get("product_sku") or data.get("barcode")
        product = find_product(identifier=identifier, required=False)
        if product:
            return product

        product_payload = data.get("product") if isinstance(data.get("product"), dict) else {}
        title = (
            data.get("product")
            if isinstance(data.get("product"), str)
            else data.get("title")
            or data.get("name")
            or data.get("productName")
            or data.get("product_name")
            or product_payload.get("name")
            or product_payload.get("title")
        )
        product = find_product_by_name(title)
        if product:
            return product

    if required:
        raise ValueError("Product not found")
    return None


def find_product_by_name(name):
    value = trim_text(name, 180)
    if not value:
        return None
    product = Product.query.filter(Product.name.ilike(value)).first()
    if product:
        return product
    return Product.query.filter(Product.name.ilike(f"%{value}%")).order_by(Product.id).first()


def find_product(identifier=None, required=False):
    if identifier is None:
        if required:
            raise ValueError("Product is required")
        return None
    identifier = str(identifier).strip()
    candidates = sku_lookup_candidates(identifier)
    for candidate in candidates:
        product = Product.query.filter_by(sku=candidate).first()
        if product:
            return product
    for candidate in candidates:
        barcode = Barcode.query.filter_by(code=candidate, is_active=True).first()
        if barcode:
            return barcode.product
    normalized = normalize_sku(identifier)
    if normalized and normalized.isdigit():
        product = Product.query.get(int(normalized))
        if product:
            return product
    if required:
        raise ValueError("Product not found")
    return None


def find_location(identifier=None, required=False):
    if identifier is None:
        if required:
            raise ValueError("Location is required")
        return None
    identifier = str(identifier).strip()
    cleaned_identifier = identifier[4:].strip() if identifier[:4].lower() == "loc:" else identifier
    if identifier.isdigit():
        location = WarehouseLocation.query.get(int(identifier))
        warehouse = current_api_warehouse()
        if location and (not warehouse or location.warehouse_id == warehouse.id):
            return location
    warehouse = current_api_warehouse()
    barcode_query = WarehouseLocation.query.filter(func.lower(WarehouseLocation.barcode) == identifier.lower())
    if warehouse:
        barcode_query = barcode_query.filter_by(warehouse_id=warehouse.id)
    location = barcode_query.first()
    if location:
        return location
    if identifier[:4].lower() == "loc:":
        loc_identifier = cleaned_identifier
        barcode_query = WarehouseLocation.query.filter(func.lower(WarehouseLocation.barcode) == loc_identifier.lower())
        if warehouse:
            barcode_query = barcode_query.filter_by(warehouse_id=warehouse.id)
        location = barcode_query.first()
        if location:
            return location
    short_code_query = WarehouseLocation.query.filter(
        or_(
            func.lower(WarehouseLocation.bin_code) == cleaned_identifier.lower(),
            func.lower(WarehouseLocation.barcode).like(f"%-{cleaned_identifier.lower()}"),
            func.lower(WarehouseLocation.barcode).like(f"%:{cleaned_identifier.lower()}"),
        )
    )
    if warehouse:
        short_code_query = short_code_query.filter_by(warehouse_id=warehouse.id)
    location = short_code_query.first()
    if location:
        return location
    parts = [part.strip() for part in cleaned_identifier.replace("/", "-").split("-") if part.strip()]
    if len(parts) == 3:
        zone, rack, bin_code = parts
        filters = [
            func.lower(WarehouseLocation.zone) == zone.lower(),
            func.lower(WarehouseLocation.rack) == rack.lower(),
            func.lower(WarehouseLocation.bin_code) == bin_code.lower(),
        ]
        if current_api_warehouse():
            filters.append(WarehouseLocation.warehouse_id == current_api_warehouse().id)
        location = WarehouseLocation.query.filter(*filters).first()
        if location:
            return location
        compact_candidates = []
        if len(zone) > 1:
            compact_candidates.append((zone[0], zone[1:], rack, bin_code))
        if len(bin_code) > 1:
            compact_candidates.append((zone, rack, bin_code[:-1], bin_code[-1]))
        for compact_zone, compact_rack, compact_shelf, compact_bin in compact_candidates:
            compact_filters = [
                func.lower(WarehouseLocation.zone) == compact_zone.lower(),
                func.lower(WarehouseLocation.rack) == compact_rack.lower(),
                func.lower(WarehouseLocation.shelf) == compact_shelf.lower(),
                func.lower(WarehouseLocation.bin_code) == compact_bin.lower(),
            ]
            if current_api_warehouse():
                compact_filters.append(WarehouseLocation.warehouse_id == current_api_warehouse().id)
            location = WarehouseLocation.query.filter(*compact_filters).first()
            if location:
                return location
    if len(parts) >= 4:
        warehouse = None
        if len(parts) >= 5:
            possible_code = "-".join(parts[:4]).lower()
            warehouse = Warehouse.query.filter(func.lower(Warehouse.code) == possible_code).first()
        offset = 4 if warehouse else 0
        if len(parts) < offset + 4:
            warehouse = None
            offset = 0
        zone, rack, shelf = parts[offset], parts[offset + 1], parts[offset + 2]
        bin_code = "-".join(parts[offset + 3:])
        filters = [
            func.lower(WarehouseLocation.zone) == zone.lower(),
            func.lower(WarehouseLocation.rack) == rack.lower(),
            func.lower(WarehouseLocation.shelf) == shelf.lower(),
            func.lower(WarehouseLocation.bin_code) == bin_code.lower(),
        ]
        if warehouse:
            filters.append(WarehouseLocation.warehouse_id == warehouse.id)
        elif current_api_warehouse():
            filters.append(WarehouseLocation.warehouse_id == current_api_warehouse().id)
        location = WarehouseLocation.query.filter(
            *filters
        ).first()
        if location:
            return location
    if required:
        raise ValueError("Location not found")
    return None


def find_or_create_stock_in_location(identifier):
    location = find_location(identifier=identifier, required=False)
    if location:
        return location

    location_code = str(identifier or "").strip()
    if not location_code:
        raise ValueError("Location is required")

    cleaned_code = location_code.removeprefix("LOC:").strip()
    parts = [part.strip() for part in cleaned_code.replace("/", "-").split("-") if part.strip()]
    warehouse = current_api_warehouse() or default_warehouse()
    if len(parts) >= 5:
        possible_code = "-".join(parts[:4]).lower()
        matched_warehouse = Warehouse.query.filter(func.lower(Warehouse.code) == possible_code).first()
        if matched_warehouse:
            warehouse = matched_warehouse
            parts = parts[4:]
    if len(parts) >= 4:
        zone, rack, shelf = parts[0], parts[1], parts[2]
        bin_code = "-".join(parts[3:])
    else:
        zone = "Custom"
        rack = "Mobile"
        shelf = "Entry"
        bin_code = cleaned_code

    location = WarehouseLocation(
        warehouse_id=warehouse.id,
        zone=trim_location_part(zone),
        rack=trim_location_part(rack),
        shelf=trim_location_part(shelf),
        bin_code=trim_location_part(bin_code),
        barcode=location_code,
    )
    db.session.add(location)
    db.session.flush()
    return location


def default_warehouse():
    warehouse = Warehouse.query.filter_by(code="kol-136-wh-01").first()
    if warehouse:
        return warehouse
    warehouse = Warehouse(code="kol-136-wh-01", name="Kolkata 700136 Warehouse", pincode="700136", is_active=True)
    db.session.add(warehouse)
    db.session.flush()
    return warehouse


def trim_location_part(value):
    cleaned = str(value or "").strip()
    if not cleaned:
        return "NA"
    return cleaned[:30]


def parse_gs_url(image_url):
    path = image_url.removeprefix("gs://")
    if "/" not in path:
        raise ValueError("Invalid Google Storage image URL")
    bucket_name, object_name = path.split("/", 1)
    if not bucket_name or not object_name:
        raise ValueError("Invalid Google Storage image URL")
    return bucket_name, object_name


def serialize_user(user):
    warehouses = accessible_api_warehouses(user)
    current = current_api_warehouse() if user == current_api_user() else (warehouses[0] if warehouses else None)
    permissions = sorted(user_page_permissions(user)) if user.page_permissions else role_permissions(user.role)
    return {
        "id": user.id,
        "name": user.full_name,
        "email": user.email,
        "role": user.role,
        "picker_code": user.picker_code,
        "pickerCode": user.picker_code,
        "warehouses": [serialize_warehouse(warehouse) for warehouse in warehouses],
        "warehouse": serialize_warehouse(current) if current else None,
        "permissions": permissions,
        "page_permissions": permissions,
    }


def serialize_central_panel_user(user):
    return {
        "id": user.id,
        "userId": user.email,
        "name": user.full_name,
        "phone": user.phone,
        "role": user.role,
        "pickerCode": user.picker_code,
        "status": "active" if user.is_active else "blocked",
        "warehouseId": user.warehouses[0].id if user.warehouses else None,
        "warehouseCode": user.warehouses[0].code if user.warehouses else "",
        "warehouses": [serialize_warehouse(warehouse) for warehouse in user.warehouses],
        "permissions": sorted(user_page_permissions(user)) if user.page_permissions else role_permissions(user.role),
        "page_permissions": sorted(user_page_permissions(user)) if user.page_permissions else role_permissions(user.role),
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "updatedAt": user.updated_at.isoformat() if user.updated_at else None,
    }


def resolve_warehouse(identifier):
    value = str(identifier or "").strip()
    if not value:
        return None
    query = Warehouse.query.filter_by(is_active=True)
    if value.isdigit():
        warehouse = query.filter_by(id=int(value)).first()
        if warehouse:
            return warehouse
    return query.filter(Warehouse.code.ilike(value)).first()


def role_permissions(role):
    permissions = {
        "admin": list(ADMIN_PANEL_PERMISSIONS.keys()),
        "manager": ["dashboard", "products", "suppliers", "stock_in", "stock_out", "inventory", "locations", "orders", "picker_ops", "pick_transfer", "shiprocket", "shipping_status", "returns", "refunds", "coupons", "money_tracking", "cash_tracker", "cash_settlements", "invoices", "reports"],
        "staff": ["dashboard", "products", "stock_in", "stock_out", "inventory", "locations", "orders", "picker_ops", "pick_transfer", "shiprocket", "shipping_status", "returns", "coupons"],
        "picker": list(PICKER_APP_PERMISSIONS.keys()),
        "packer": ["dashboard", "orders", "stock_out", "shiprocket", "shipping_status"],
        "delivery": ["dashboard", "orders", "shipping_status"],
    }
    return permissions.get(role, ["orders"])


def serialize_warehouse(warehouse):
    return {
        "id": warehouse.id,
        "code": warehouse.code,
        "name": warehouse.name,
        "pincode": warehouse.pincode,
        "address": warehouse.address,
        "is_active": warehouse.is_active,
    }


def serialize_location(location):
    return {
        "id": location.id,
        "warehouse": serialize_warehouse(location.warehouse) if location.warehouse else None,
        "warehouse_id": location.warehouse_id,
        "zone": location.zone,
        "rack": location.rack,
        "shelf": location.shelf,
        "bin_code": location.bin_code,
        "full_code": location.full_code,
        "barcode": location.barcode,
        "is_virtual": location.is_virtual,
    }


def serialize_product(product):
    warehouse = current_api_warehouse()
    inventory_items = [
        item
        for item in product.inventory_items
        if not item.location.is_virtual and (not warehouse or item.location.warehouse_id == warehouse.id)
    ]
    total_quantity = sum(item.quantity for item in inventory_items)
    available_quantity = sum(item.available_quantity for item in inventory_items)
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "brand": product.brand,
        "description": product.description or "",
        "unit": product.unit,
        "category": product.category.name if product.category else "",
        "minimum_stock": product.minimum_stock,
        "purchase_price": float(product.purchase_price or 0),
        "selling_price": float(product.selling_price or 0),
        "total_quantity": total_quantity,
        "available_quantity": available_quantity,
        "is_low_stock": total_quantity <= product.minimum_stock,
        "image_url": product.image_url,
        "image_display_url": url_for("api.api_product_image", product_id=product.id) if product.image_url else None,
        "barcodes": [barcode.code for barcode in product.barcodes if barcode.is_active],
        "locations": [
            {
                "inventory_id": item.id,
                "location": serialize_location(item.location),
                "quantity": item.quantity,
                "reserved_quantity": item.reserved_quantity,
                "available_quantity": item.available_quantity,
            }
            for item in inventory_items
        ],
    }


def serialize_inventory_item(inventory):
    return {
        "inventory_id": inventory.id,
        "quantity": inventory.quantity,
        "reserved_quantity": inventory.reserved_quantity,
        "available_quantity": inventory.available_quantity,
        "product": serialize_product(inventory.product),
        "location": serialize_location(inventory.location),
    }


def serialize_public_product(product):
    value = product.selling_price or product.purchase_price or 0
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description or "",
        "category": product.category.name if product.category else "E Rickshaw",
        "value": float(value),
        "unit": product.unit,
        "available_quantity": product.available_quantity,
        "in_stock": product.available_quantity > 0,
        "image_url": url_for("api.api_public_product_image", product_id=product.id, _external=True) if product.image_url else None,
        "updated_at": india_iso(product.updated_at),
    }


def serialize_order(order):
    courier_payload = order_courier_payload(order)
    label_url = nested_payload_value(courier_payload, "label_url", "label", "label_url_s3", "url", "download_url")
    return {
        "id": order.id,
        "order_number": order.order_number,
        "external_source": order.external_source,
        "external_order_id": order.external_order_id,
        "warehouse": serialize_warehouse(order.warehouse) if order.warehouse else None,
        "warehouse_id": order.warehouse_id,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "customer_address": order.customer_address,
        "status": order.status,
        "priority": order.priority,
        "assigned_to_id": order.assigned_to_id,
        "picker": {
            "id": order.assigned_to.id,
            "name": order.assigned_to.full_name,
            "picker_code": order.assigned_to.picker_code,
        } if order.assigned_to else None,
        "amount": float(order.total_value),
        "total_items": order.total_items,
        "created_at": india_iso(order.created_at),
        "awb": order.courier_awb or "",
        "label_url": label_url,
        "courier": {
            "provider": order.courier_provider,
            "order_id": order.courier_order_id,
            "shipment_id": order.courier_shipment_id,
            "awb": order.courier_awb,
            "status": order.courier_status,
            "label_url": label_url,
        },
        "automation": order_automation_summary(order),
        "package": {
            "length": float(order.package_length_cm or 0),
            "breadth": float(order.package_breadth_cm or 0),
            "height": float(order.package_height_cm or 0),
            "weight": float(order.package_weight_kg or 0),
        },
        "items": [
            {
                "id": item.id,
                "product": serialize_product(item.product),
                "quantity": item.quantity,
                "unit_price": float(item.unit_price or 0),
                "line_total": float(item.unit_price or 0) * item.quantity,
                "picked_quantity": item.picked_quantity,
                "packed_quantity": item.packed_quantity,
                "recommended_bin": product_pick_location(item.product, order.warehouse_id),
            }
            for item in order.items
        ],
        "bin_analysis": order_bin_analysis(order),
    }


def serialize_inbound_order(order):
    result = serialize_order(order)
    invoice = Invoice.query.filter_by(order_id=order.id, invoice_type="sale").first()
    payment = (
        MoneyTransaction.query.filter_by(order_id=order.id, transaction_type="inbound_payment")
        .order_by(MoneyTransaction.id.desc())
        .first()
    )
    result.update(
        {
            "discount_percent": 20,
            "amount": float(invoice.amount if invoice else order.total_value),
            "invoice": {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "amount": float(invoice.amount or 0),
                "currency": invoice.currency,
                "issued_at": india_iso(invoice.issued_at),
            } if invoice else None,
            "payment": {
                "method": payment.gateway,
                "status": payment.status,
                "reference": payment.reference or "",
            } if payment else None,
        }
    )
    return result


def serialize_cash_transaction(transaction):
    return {
        "id": transaction.id,
        "transactionNumber": transaction.transaction_number,
        "warehouseId": transaction.warehouse_id,
        "warehouseCode": transaction.warehouse.code if transaction.warehouse else "",
        "orderId": transaction.order_id,
        "orderNumber": transaction.order.order_number if transaction.order else "",
        "customerName": transaction.customer_name or "",
        "customerPhone": transaction.customer_phone or "",
        "type": transaction.transaction_type,
        "direction": transaction.direction,
        "status": transaction.status,
        "gateway": transaction.gateway or "",
        "reference": transaction.reference or "",
        "amount": float(transaction.amount or 0),
        "currency": transaction.currency or "INR",
        "createdAt": india_iso(transaction.created_at),
        "updatedAt": india_iso(transaction.updated_at),
    }


def serialize_item_not_found_report(report):
    return {
        "id": report.id,
        "order_id": report.order_id,
        "order_number": report.order.order_number if report.order else "",
        "product_id": report.product_id,
        "product_name": report.product.name if report.product else "",
        "sku": report.product.sku if report.product else "",
        "quantity": report.quantity,
        "stock_deducted_quantity": report.stock_deducted_quantity,
        "unit_price": float(report.unit_price or 0),
        "amount": float(report.unit_price or 0) * int(report.quantity or 0),
        "warehouse_id": report.warehouse_id,
        "warehouse": report.warehouse.code if report.warehouse else "",
        "location": report.location.barcode or report.location.full_code if report.location else "",
        "picker_id": report.picker_id,
        "picker": report.picker.full_name if report.picker else "",
        "notes": report.notes or "",
        "created_at": india_iso(report.created_at),
    }


def serialize_central_panel_setting(setting):
    try:
        updates = json.loads(setting.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        updates = {}
    return {
        "id": setting.id,
        "section": setting.section,
        "updates": updates if isinstance(updates, dict) else {},
        "updated_at": india_iso(setting.updated_at),
    }


def order_courier_payload(order):
    try:
        payload = json.loads(order.courier_response or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def nested_payload_value(payload, *keys):
    if not isinstance(payload, dict):
        return ""
    containers = [payload]
    for key in ("data", "shipment", "order", "label"):
        value = payload.get(key)
        if isinstance(value, dict):
            containers.append(value)
    for container in containers:
        for key in keys:
            value = container.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def serialize_return_order(return_order):
    return {
        "id": return_order.id,
        "return_number": return_order.return_number,
        "order_id": return_order.order_id,
        "website_order_id": return_order.website_order_id,
        "customer_name": return_order.customer_name,
        "customer_phone": return_order.customer_phone,
        "reason": return_order.reason,
        "status": return_order.status,
        "refund_status": return_order.refund_status,
        "notes": return_order.notes,
        "assigned_to_id": return_order.assigned_to_id,
        "assigned_to": {
            "id": return_order.assigned_to.id,
            "full_name": return_order.assigned_to.full_name,
            "picker_code": return_order.assigned_to.picker_code,
        } if return_order.assigned_to else None,
        "requested_at": india_iso(return_order.requested_at),
        "created_at": india_iso(return_order.requested_at),
        "items": [
            {
                "id": item.id,
                "product": serialize_product(item.product),
                "expected_quantity": item.expected_quantity,
                "picked_quantity": item.picked_quantity,
                "stocked_quantity": item.stocked_quantity,
                "issue_quantity": item.issue_quantity,
                "remaining_stock_in_quantity": item.remaining_stock_in_quantity,
                "status": item.status,
                "notes": item.notes,
                "suggested_bins": serialize_return_stock_bins(item.product),
            }
            for item in return_order.items
        ],
    }


def serialize_return_stock_bins(product):
    warehouse = current_api_warehouse()
    query = (
        Inventory.query.join(WarehouseLocation)
        .filter(
            Inventory.product_id == product.id,
            WarehouseLocation.is_active.is_(True),
            WarehouseLocation.is_virtual.is_(False),
        )
    )
    normal_location_query = WarehouseLocation.query.filter(
        WarehouseLocation.is_active.is_(True),
        WarehouseLocation.is_virtual.is_(False),
    )
    if warehouse:
        query = query.filter(WarehouseLocation.warehouse_id == warehouse.id)
        normal_location_query = normal_location_query.filter(WarehouseLocation.warehouse_id == warehouse.id)
    inventory = query.order_by(Inventory.quantity.desc(), WarehouseLocation.zone, WarehouseLocation.rack, WarehouseLocation.bin_code).first()
    normal_location = inventory.location if inventory else normal_location_query.order_by(WarehouseLocation.zone, WarehouseLocation.rack, WarehouseLocation.bin_code).first()
    issue_location = WarehouseLocation.query.filter_by(barcode="RC-DA-01", is_virtual=True, is_active=True).first()
    return {
        "no_issue": serialize_location(normal_location) if normal_location else None,
        "issue": serialize_location(issue_location) if issue_location else None,
    }


def serialize_payment_refund(refund):
    if not refund:
        return None
    return {
        "id": refund.id,
        "refund_number": refund.refund_number,
        "order_id": refund.order_id,
        "website_order_id": refund.website_order_id,
        "request_id": refund.request_id,
        "customer_name": refund.customer_name,
        "customer_phone": refund.customer_phone,
        "gateway": refund.gateway,
        "gateway_payment_id": refund.gateway_payment_id,
        "gateway_transaction_id": refund.gateway_transaction_id,
        "refund_token": refund.refund_token,
        "amount": float(refund.amount or 0),
        "currency": refund.currency,
        "reason": refund.reason,
        "status": refund.status,
        "requested_at": india_iso(refund.requested_at),
        "approved_at": india_iso(refund.approved_at),
        "approved_by": refund.approved_by.full_name if refund.approved_by else "",
    }


@api_bp.route("/integrations/delivery-orders", methods=["GET", "OPTIONS"])
@integration_key_required
def integration_delivery_orders():
    delivery_filter = str(request.args.get("delivery") or "fast").lower()
    try:
        limit = min(int(request.args.get("limit") or 100), 500)
    except (TypeError, ValueError):
        limit = 100
    statuses = request.args.get("statuses") or "pending,picking,packed,ready_to_dispatch,dispatch_ready,confirmed,processing,paid,pending_cod,payment_initiated"
    status_list = [item.strip() for item in statuses.split(",") if item.strip()]

    query = Order.query.order_by(Order.created_at.desc())
    if status_list:
        query = query.filter(Order.status.in_(status_list))
    if delivery_filter in {"fast", "express"}:
        query = query.filter(
            or_(
                Order.priority == "urgent",
                Order.source_payload.ilike('%"mode":"fast"%'),
                Order.source_payload.ilike("%express%"),
                Order.source_payload.ilike("%Fast delivery%"),
                Order.source_payload.ilike("%fastDelivery%"),
                Order.source_payload.ilike("%fast_delivery%"),
            )
        )
        candidate_limit = min(max(limit * 5, 500), 2000)
        orders = query.limit(candidate_limit).all()
        orders = [order for order in orders if is_fast_delivery_order(order)]
        orders = orders[:limit]
    else:
        orders = query.limit(limit).all()

    return jsonify({
        "ok": True,
        "count": len(orders),
        "orders": [serialize_delivery_order(order) for order in orders],
    })
