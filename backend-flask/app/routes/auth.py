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
    "stock": "Stock",
    "orders": "Orders",
    "picker_ops": "Picker Ops",
    "shiprocket": "Shiprocket",
    "returns": "Customer Returns",
    "refunds": "Payment Refunds",
    "money_tracking": "Money Tracking",
    "invoices": "Invoices",
    "reports": "Reports",
    "users": "Users",
    "settings": "Settings",
}


def user_page_permissions(user):
    try:
        values = json.loads(user.page_permissions or "[]")
    except (TypeError, json.JSONDecodeError):
        values = []
    return set(value for value in values if value in PAGE_PERMISSIONS)


def endpoint_permission(endpoint):
    prefix = (endpoint or "").split(".", 1)[0]
    if endpoint == "users.picker_ops":
        return "picker_ops"
    if endpoint in {"users.settings", "users.ops_config"}:
        return "settings"
    if endpoint == "finance.money_tracking":
        return "money_tracking"
    if endpoint == "finance.invoices":
        return "invoices"
    return prefix if prefix in PAGE_PERMISSIONS else ""


def user_can_page(user, endpoint):
    if not user or user.role == "admin":
        return bool(user)
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
        if not get_current_user():
            return redirect(url_for("auth.login", next=request.path))
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
                flash("You do not have permission to open that page.", "warning")
                return redirect(url_for("dashboard.dashboard"))
            if not user_can_page(user, request.endpoint):
                flash("Page permission approval required.", "warning")
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
