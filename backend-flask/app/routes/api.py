import json
import secrets
from datetime import datetime, time

from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, Response, current_app, jsonify, redirect, request, session, url_for
from sqlalchemy import func, or_
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..extensions import db
from ..models import Barcode, CustomerReturnItem, CustomerReturnOrder, Inventory, Order, OrderItem, Product, StockIn, StockOut, User, Warehouse, WarehouseLocation
from ..utils.customer_website import notify_product_change
from ..utils.google_sheets import auto_sync_current_stock_sheet
from ..utils.google_storage import get_storage_client, upload_product_image
from ..utils.sku import normalize_sku, sku_lookup_candidates
from ..utils.stock import get_or_create_inventory, issue_stock, log_activity, receive_stock
from .auth import user_has_role
from .shiprocket import ShiprocketError, dispatch_order_with_shiprocket

api_bp = Blueprint("api", __name__)


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
    allowed_headers = ["Authorization", "Content-Type", "X-CSRF-Token", "X-Integration-Key"]
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


def integration_request_key():
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get("X-Integration-Key", "").strip()


@api_bp.post("/login")
def api_login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(email=data.get("email", "").strip().lower(), is_active=True).first()
    if not user or not user.check_password(data.get("password", "")):
        return jsonify({"ok": False, "message": "Invalid email or password"}), 401
    session["user_id"] = user.id
    session["user_role"] = user.role
    return jsonify({"ok": True, "user": serialize_user(user), "token": create_api_token(user)})


@api_bp.post("/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@api_bp.get("/me")
@api_login_required
def api_me():
    return jsonify({"ok": True, "user": serialize_user(current_api_user())})


@api_bp.get("/dashboard")
@api_login_required
def api_dashboard():
    today_start = datetime.combine(datetime.utcnow().date(), time.min)
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
            "pending_orders": Order.query.filter(Order.status.in_(["pending", "picking", "packed"])).count(),
            "completed_orders": Order.query.filter_by(status="completed").count(),
            "top_selling_products": [
                {"id": row.id, "name": row.name, "sku": row.sku, "sold_qty": int(row.sold_qty or 0)}
                for row in top_selling
            ],
        }
    )


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
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "products": [serialize_public_product(product) for product in products],
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@api_bp.get("/public/products/<int:product_id>/image")
def api_public_product_image(product_id):
    product = Product.query.filter_by(id=product_id, is_active=True).first_or_404()
    return serve_product_image(product)


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


@api_bp.get("/scan/<path:code>")
@api_login_required
def api_scan(code):
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
        db.session.commit()
        return jsonify({"ok": True, "created": created, "order": serialize_order(order)}), 201 if created else 200
    except (TypeError, ValueError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/integrations/returns")
@integration_key_required
def api_import_return():
    data = request.get_json(silent=True) or {}
    try:
        return_order, created = create_return_from_integration(data)
        db.session.commit()
        return jsonify({"ok": True, "created": created, "return_order": serialize_return_order(return_order)}), 201 if created else 200
    except (TypeError, ValueError) as error:
        db.session.rollback()
        return jsonify({"ok": False, "message": str(error)}), 400


@api_bp.post("/stock-in")
@api_role_required("manager", "staff")
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
def api_pick_list():
    user = current_api_user()
    query = Order.query.filter(Order.status.in_(["pending", "picking", "packed", "dispatched"]))
    if user and not can_manage_all_orders(user):
        query = query.filter(or_(Order.assigned_to_id == user.id, Order.assigned_to_id.is_(None)))
    orders = query.order_by(Order.priority.desc(), Order.created_at).all()
    return jsonify({"orders": [serialize_order(order) for order in orders]})


@api_bp.get("/returns/pick-list")
@api_role_required("manager", "staff", "picker")
def api_return_pick_list():
    ensure_virtual_return_bins()
    db.session.commit()
    query = CustomerReturnOrder.query.filter(CustomerReturnOrder.status.in_(["approved", "return_picking", "return_picked", "inspection"]))
    returns = query.order_by(CustomerReturnOrder.requested_at, CustomerReturnOrder.id).all()
    return jsonify({"returns": [serialize_return_order(return_order) for return_order in returns]})


@api_bp.post("/returns/<int:return_id>/items/<int:item_id>/pick")
@api_role_required("manager", "staff", "picker")
def api_return_item_pick(return_id, item_id):
    data = request.get_json(silent=True) or {}
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
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
def api_return_initiate_pv(return_id):
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
    if not return_order.items or not all(item.picked_quantity >= item.expected_quantity for item in return_order.items):
        return jsonify({"ok": False, "message": "Pick all return items before PV"}), 400
    return_order.status = "inspection"
    log_activity("return_pv", f"PV initiated for {return_order.return_number}", user_id=current_api_user_id(), entity_type="CustomerReturnOrder", entity_id=return_order.id)
    db.session.commit()
    return jsonify({"ok": True, "return_order": serialize_return_order(return_order)})


@api_bp.post("/returns/<int:return_id>/items/<int:item_id>/stock-in")
@api_role_required("manager", "staff", "picker")
def api_return_item_stock_in(return_id, item_id):
    data = request.get_json(silent=True) or {}
    return_order = CustomerReturnOrder.query.get_or_404(return_id)
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
        if condition == "issue":
            location = ensure_virtual_return_bins()["customer_return"]
            item.issue_quantity += quantity
            item.status = "issue" if item.remaining_stock_in_quantity == 0 else "partial"
            notes = f"Customer return issue stock in: {return_order.return_number}"
        elif condition == "no_issue":
            location = find_location(identifier=data.get("location") or data.get("location_id") or data.get("location_barcode"), required=True)
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
            return_order.resolved_at = datetime.utcnow()
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
        order.assigned_to_id = current_api_user_id()
    order.status = status
    if status == "completed":
        order.completed_at = datetime.utcnow()
    log_activity("order_status", f"Order {order.order_number} marked {status}", user_id=current_api_user_id(), entity_type="Order", entity_id=order.id)
    db.session.commit()
    return jsonify({"ok": True, "order": serialize_order(order)})


@api_bp.post("/orders/<int:order_id>/dispatch")
@api_role_required("manager", "staff", "picker", "packer", "delivery")
def api_dispatch_order(order_id):
    data = request.get_json(silent=True) or {}
    order = Order.query.get_or_404(order_id)
    if not can_access_order(current_api_user(), order):
        return jsonify({"ok": False, "message": "Permission denied for this order"}), 403
    return dispatch_order_api_response(order, data)


def dispatch_order_api_response(order, data):
    if order.status not in {"packed", "dispatched"}:
        return jsonify({"ok": False, "message": "Order must be packed before dispatch"}), 400
    if not all(item.packed_quantity >= item.quantity for item in order.items):
        return jsonify({"ok": False, "message": "Pack all order items before dispatch"}), 400
    if data.get("manual_dispatch"):
        order.status = "dispatched"
        log_activity(
            "order_dispatch",
            f"Order {order.order_number} marked dispatched from picker app",
            user_id=current_api_user_id(),
            entity_type="Order",
            entity_id=order.id,
            meta={"manual_dispatch": True},
        )
        db.session.commit()
        return jsonify({"ok": True, "order": serialize_order(order), "created_courier_order": False})
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
        item.picked_quantity = quantity
        if not order.assigned_to_id:
            order.assigned_to_id = current_api_user_id()
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


@api_bp.post("/orders/<int:order_id>/items/<int:item_id>/pack")
@api_role_required("manager", "staff", "packer")
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
    return bool(user and (can_manage_all_orders(user) or order.assigned_to_id in {None, user.id}))


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
    external_order_id = trim_text(data.get("external_order_id") or data.get("order_id") or data.get("id"), 120)
    if not external_order_id:
        raise ValueError("external_order_id is required")

    existing = Order.query.filter_by(external_source=source, external_order_id=external_order_id).first()
    if existing:
        return existing, False

    order_number = trim_text(
        data.get("order_number") or data.get("external_order_number") or f"{source.upper()}-{external_order_id}",
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

    priority = trim_text(data.get("priority") or "normal", 20).lower()
    if priority not in {"normal", "high", "urgent"}:
        raise ValueError("priority must be normal, high, or urgent")

    order = Order(
        order_number=order_number,
        external_source=source,
        external_order_id=external_order_id,
        source_payload=json.dumps(data, default=str, separators=(",", ":"))[:20000],
        customer_name=customer_name,
        customer_phone=trim_text(data.get("customer_phone") or customer.get("phone"), 30),
        customer_address=trim_text(data.get("customer_address") or customer.get("address") or format_address(data.get("shipping_address") or customer.get("shipping_address")), 2000),
        priority=priority,
        assigned_to_id=resolve_assignee(data),
        expected_dispatch_date=parse_expected_dispatch_date(data.get("expected_dispatch_date")),
    )

    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each item must be an object")
        product = find_product_from_payload(item, required=True)
        quantity = positive_int(item.get("quantity"), "quantity")
        unit_price = numeric_or_default(item.get("unit_price"), product.selling_price)
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


def resolve_assignee(data):
    assigned_to_id = int_or_none(data.get("assigned_to_id"))
    if assigned_to_id:
        user = User.query.filter_by(id=assigned_to_id, is_active=True).first()
        if not user:
            raise ValueError("assigned_to_id not found")
        return user.id

    assigned_to_email = trim_text(data.get("assigned_to_email"), 180).lower()
    if assigned_to_email:
        user = User.query.filter_by(email=assigned_to_email, is_active=True).first()
        if not user:
            raise ValueError("assigned_to_email not found")
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
            product_id = int_or_none(data.get("product_id"))
        except (TypeError, ValueError):
            product_id = None
        if product_id:
            product = Product.query.get(product_id)
            if product:
                return product

    identifier = None
    if isinstance(data, dict):
        identifier = data.get("product") or data.get("sku") or data.get("product_sku") or data.get("barcode")
    return find_product(identifier=identifier, required=required)


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
    if identifier.isdigit():
        location = WarehouseLocation.query.get(int(identifier))
        warehouse = current_api_warehouse()
        if location and (not warehouse or location.warehouse_id == warehouse.id):
            return location
    warehouse = current_api_warehouse()
    barcode_query = WarehouseLocation.query.filter_by(barcode=identifier)
    if warehouse:
        barcode_query = barcode_query.filter_by(warehouse_id=warehouse.id)
    location = barcode_query.first()
    if location:
        return location
    if identifier.startswith("LOC:"):
        barcode_query = WarehouseLocation.query.filter_by(barcode=identifier)
        if warehouse:
            barcode_query = barcode_query.filter_by(warehouse_id=warehouse.id)
        location = barcode_query.first()
        if location:
            return location
    cleaned_identifier = identifier.removeprefix("LOC:").strip()
    parts = [part.strip() for part in cleaned_identifier.replace("/", "-").split("-") if part.strip()]
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
    return {
        "id": user.id,
        "name": user.full_name,
        "email": user.email,
        "role": user.role,
        "warehouses": [serialize_warehouse(warehouse) for warehouse in warehouses],
        "warehouse": serialize_warehouse(current) if current else None,
    }


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
        "unit": product.unit,
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
        "value": float(value),
        "unit": product.unit,
        "available_quantity": product.available_quantity,
        "in_stock": product.available_quantity > 0,
        "image_url": url_for("api.api_public_product_image", product_id=product.id, _external=True) if product.image_url else None,
        "updated_at": product.updated_at.isoformat() + "Z" if product.updated_at else None,
    }


def serialize_order(order):
    return {
        "id": order.id,
        "order_number": order.order_number,
        "external_source": order.external_source,
        "external_order_id": order.external_order_id,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "status": order.status,
        "priority": order.priority,
        "assigned_to_id": order.assigned_to_id,
        "total_items": order.total_items,
        "courier": {
            "provider": order.courier_provider,
            "order_id": order.courier_order_id,
            "shipment_id": order.courier_shipment_id,
            "awb": order.courier_awb,
            "status": order.courier_status,
        },
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
                "picked_quantity": item.picked_quantity,
                "packed_quantity": item.packed_quantity,
            }
            for item in order.items
        ],
    }


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
        "requested_at": return_order.requested_at.isoformat() + "Z" if return_order.requested_at else None,
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
            }
            for item in return_order.items
        ],
    }
