import json
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from ..models import User, Warehouse

auth_bp = Blueprint("auth", __name__)

ROLE_LABELS = {
    "admin": "Admin",
    "manager": "Manager",
    "staff": "Warehouse Staff",
    "picker": "Picker",
    "packer": "Packer",
    "delivery": "Delivery Staff",
    "inbound_customer": "Inbound Customer",
}


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.filter_by(id=user_id, is_active=True).first()


def user_has_role(user, *roles):
    if not user or not user.is_active:
        return False
    if not roles:
        return True
    allowed_roles = {role for role in roles if role}
    return user.role == "admin" or user.role in allowed_roles


PAGE_PERMISSIONS = {
    "dashboard": "Dashboard",
    "products": "Products",
    "suppliers": "Suppliers",
    "stock_in": "Stock In",
    "stock_out": "Stock Out",
    "inventory": "Inventory",
    "locations": "Locations",
    "orders": "Orders",
    "picker_ops": "Picker Ops",
    "pick_transfer": "Pick Transfer",
    "shiprocket": "Shiprocket",
    "shipping_status": "Shipping Status",
    "returns": "Customer Returns",
    "refunds": "Payment Refunds",
    "money_tracking": "Money Tracking",
    "cash_tracker": "Cash Tracker",
    "cash_settlements": "Cash Settlements",
    "invoices": "Invoices",
    "inbound_customers": "Inbound Customers",
    "reports": "Reports",
    "users": "Users",
    "ops_config": "Ops Config",
    "settings": "Settings",
}

ADMIN_PANEL_PERMISSIONS = {
    "panel_dashboard": "Dashboard",
    "panel_orders": "Orders",
    "panel_customers": "Customers",
    "panel_pickers": "Pickers",
    "panel_returns": "Returns",
    "panel_inventory": "Inventory",
    "panel_user_create": "User Creating",
    "panel_shiprocket": "Shiprocket",
    "panel_catalog": "Catalog",
    "panel_tracking": "Order Tracking",
    "panel_content": "Website / App Edit",
    "panel_ops_config": "Warehouse Ops Config",
    "panel_automation": "Automation",
    "panel_inbound_customers": "Inbound Customers",
    "panel_cash_tracker": "Cash Tracker",
    "panel_cash_settlements": "Cash Settlements",
    "panel_item_not_found": "Item Not Found",
}

PICKER_APP_PERMISSIONS = {
    "picker_home": "Home",
    "picker_pick": "Pick",
    "picker_ship": "Ship",
    "picker_returns": "Return",
    "picker_stock_in": "Stock In",
    "picker_stock_take": "Stock Take",
    "picker_move_stock": "Move Stock",
    "picker_bins": "Bins",
    "picker_tools": "Tools",
}

LEGACY_PAGE_PERMISSIONS = {
    "stock": {"stock_in", "stock_out", "inventory", "locations"},
    "picking": {"picker_ops", "pick_transfer"},
    "dispatch": {"shiprocket", "shipping_status"},
}

ADMIN_PANEL_PAGE_PERMISSIONS = {
    "panel_dashboard": {"dashboard"},
    "panel_orders": {"orders"},
    "panel_pickers": {"picker_ops", "pick_transfer"},
    "panel_returns": {"returns", "refunds"},
    "panel_inventory": {"products", "stock_in", "stock_out", "inventory", "locations", "reports"},
    "panel_user_create": {"users"},
    "panel_shiprocket": {"shiprocket", "shipping_status"},
    "panel_tracking": {"shipping_status"},
    "panel_ops_config": {"ops_config", "settings"},
    "panel_inbound_customers": {"inbound_customers"},
    "panel_cash_tracker": {"cash_tracker", "cash_settlements"},
    "panel_cash_settlements": {"cash_settlements"},
}


def user_page_permissions(user):
    try:
        values = json.loads(user.page_permissions or "[]")
    except (TypeError, json.JSONDecodeError):
        values = []
    allowed = set()
    for value in values:
        if value in PAGE_PERMISSIONS or value in ADMIN_PANEL_PERMISSIONS or value in PICKER_APP_PERMISSIONS:
            allowed.add(value)
        allowed.update(LEGACY_PAGE_PERMISSIONS.get(value, set()))
        allowed.update(ADMIN_PANEL_PAGE_PERMISSIONS.get(value, set()))
    return allowed


def endpoint_permission(endpoint):
    endpoint = endpoint or ""
    if endpoint in {"users.picker_ops", "users.pick_transfer", "users.transfer_pick"}:
        return "pick_transfer" if "pick_transfer" in endpoint or "transfer_pick" in endpoint else "picker_ops"
    if endpoint == "users.settings":
        return "settings"
    if endpoint == "users.ops_config":
        return "ops_config"
    if endpoint == "stock.stock_in":
        return "stock_in"
    if endpoint == "stock.stock_out":
        return "stock_out"
    if endpoint == "stock.inventory":
        return "inventory"
    if endpoint in {"stock.warehouse_locations", "stock.add_location", "stock.add_warehouse", "stock.warehouses"}:
        return "locations"
    if endpoint == "shiprocket.create_order":
        return "shiprocket"
    if endpoint in {"shiprocket.shipping_status", "shiprocket.shipping_status_live", "shiprocket.shipping_status_detail", "shiprocket.shipping_status_detail_live", "shiprocket.webhook_updates"}:
        return "shipping_status"
    if endpoint == "finance.money_tracking":
        return "money_tracking"
    if endpoint == "finance.warehouse_transactions":
        return "money_tracking"
    if endpoint == "finance.cash_tracker":
        return "cash_tracker"
    if endpoint == "finance.cash_settlements":
        return "cash_settlements"
    if endpoint == "finance.invoices":
        return "invoices"
    if endpoint and endpoint.startswith("inbound."):
        return "inbound_customers"
    prefix = endpoint.split(".", 1)[0]
    return prefix if prefix in PAGE_PERMISSIONS else ""


def user_can_page(user, endpoint):
    if not user:
        return False
    permission = endpoint_permission(endpoint)
    if not permission:
        return True
    if not user.page_permissions:
        return True
    allowed = user_page_permissions(user)
    return permission in allowed


def current_user_can(*roles):
    return user_has_role(get_current_user(), *roles)


def accessible_warehouses(user=None):
    user = user or get_current_user()
    if not user:
        return []
    assigned = [warehouse for warehouse in user.warehouses if warehouse.is_active]
    if assigned:
        return sorted(assigned, key=lambda warehouse: warehouse.code)
    if user.role == "admin":
        return Warehouse.query.filter_by(is_active=True).order_by(Warehouse.code).all()
    return []


def selected_warehouse(user=None):
    warehouses = accessible_warehouses(user)
    if not warehouses:
        return None
    allowed_ids = {warehouse.id for warehouse in warehouses}
    requested_id = request.values.get("warehouse_id") or request.headers.get("X-Warehouse-Id") or session.get("warehouse_id")
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


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect(url_for("auth.login", next=request.path))
        if not user_can_page(user, request.endpoint):
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            user = get_current_user()
            if not user:
                return redirect(url_for("auth.login", next=request.path))
            if not user_has_role(user, *roles):
                abort(403)
            if not user_can_page(user, request.endpoint):
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


@auth_bp.app_context_processor
def inject_current_user():
        return {
            "current_user": get_current_user(),
            "current_user_can": current_user_can,
            "accessible_warehouses": accessible_warehouses,
            "selected_warehouse": selected_warehouse,
            "role_label": lambda role: ROLE_LABELS.get(role, str(role or "").title()),
            "page_permissions": PAGE_PERMISSIONS,
            "user_can_page": user_can_page,
        }


@auth_bp.route("/")
def home():
    if get_current_user():
        return redirect(url_for("dashboard.dashboard"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email, is_active=True).first()
        if user and user.check_password(password):
            session.permanent = True
            session["user_id"] = user.id
            session["user_role"] = user.role
            flash("Welcome back.", "success")
            return redirect(request.args.get("next") or url_for("dashboard.dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("auth.login"))
