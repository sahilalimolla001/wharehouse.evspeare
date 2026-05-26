from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Barcode, Category, Product, Supplier
from ..utils.barcode import build_product_barcode, product_payload
from ..utils.customer_website import notify_product_change
from ..utils.google_storage import import_product_images_by_sku, upload_product_image
from ..utils.sku import normalize_sku, sku_lookup_candidates
from .auth import login_required, role_required

products_bp = Blueprint("products", __name__)

VEHICLE_CATEGORIES = ["E Scooty", "E Rickshaw", "Auto", "Car"]
DEFAULT_PRODUCT_CATEGORY = "E Rickshaw"


@products_bp.route("/products")
@login_required
def products():
    ensure_vehicle_categories()
    q = request.args.get("q", "").strip()
    query = Product.query.filter_by(is_active=True)
    if q:
        like = f"%{q}%"
        sku_q = normalize_sku(q)
        sku_like = f"%{sku_q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.sku.ilike(like)) | (Product.sku.ilike(sku_like)) | (Product.brand.ilike(like)))
    products_list = query.order_by(Product.name).all()
    return render_template("products.html", products=products_list, q=q)


@products_bp.post("/products/import-images")
@role_required("manager")
def import_images():
    products_list = Product.query.filter_by(is_active=True).order_by(Product.sku).all()
    try:
        result = import_product_images_by_sku(products_list, replace_existing=True)
        db.session.commit()
    except RuntimeError as error:
        db.session.rollback()
        flash(str(error), "danger")
        return redirect(url_for("products.products"))
    except Exception as error:
        db.session.rollback()
        flash(f"Google Cloud image import failed: {error}", "danger")
        return redirect(url_for("products.products"))

    if result["matched"]:
        flash(
            f"Imported {result['matched']} images from Google Cloud by SKU. "
            f"{result['missing']} products had no matching image.",
            "success",
        )
    else:
        flash("No matching Google Cloud images found for product SKUs.", "warning")
    return redirect(url_for("products.products"))


@products_bp.route("/add-product", methods=["GET", "POST"])
@products_bp.route("/product/<int:product_id>", methods=["GET", "POST"])
@role_required("manager")
def product_form(product_id=None):
    product = Product.query.get(product_id) if product_id else None
    default_category = ensure_vehicle_categories()
    categories = vehicle_categories()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()

    if request.method == "POST":
        sku = normalize_sku(request.form.get("sku"))
        if not sku or not sku.isdigit():
            flash("SKU me sirf number hona chahiye. Example: 1001", "danger")
            return render_template("add_product.html", product=product, categories=categories, suppliers=suppliers, default_category=default_category)

        existing = Product.query.filter(Product.sku.in_(sku_lookup_candidates(sku)))
        if product:
            existing = existing.filter(Product.id != product.id)
        if existing.first():
            flash("SKU number already exists.", "danger")
            return render_template("add_product.html", product=product, categories=categories, suppliers=suppliers, default_category=default_category)

        if not product:
            product = Product()
            db.session.add(product)

        product.name = request.form.get("name", "").strip()
        product.sku = sku
        product.brand = request.form.get("brand", "").strip()
        product.unit = request.form.get("unit", "pcs").strip() or "pcs"
        category_id = int_or_none(request.form.get("category_id")) or default_category.id
        if not Category.query.get(category_id):
            flash("Select a valid vehicle category.", "danger")
            return render_template("add_product.html", product=product, categories=categories, suppliers=suppliers, default_category=default_category)
        product.category_id = category_id
        product.supplier_id = int_or_none(request.form.get("supplier_id"))
        product.purchase_price = numeric_or_zero(request.form.get("purchase_price"))
        product.selling_price = numeric_or_zero(request.form.get("selling_price"))
        product.minimum_stock = int(request.form.get("minimum_stock") or 0)
        product.description = request.form.get("description", "").strip()
        uploaded_file = request.files.get("image_file")
        if uploaded_file and uploaded_file.filename:
            try:
                product.image_url = upload_product_image(uploaded_file, sku=product.sku)
            except (RuntimeError, ValueError) as error:
                flash(str(error), "danger")
                return render_template("add_product.html", product=product, categories=categories, suppliers=suppliers, default_category=default_category)
        else:
            product.image_url = request.form.get("image_url", "").strip()
        try:
            db.session.flush()

            code = build_product_barcode(product)
            barcode = Barcode.query.filter_by(code=code).first()
            if barcode and barcode.product_id != product.id:
                raise IntegrityError("Barcode already exists", {}, None)
            if not barcode:
                db.session.add(Barcode(product_id=product.id, code=code, payload=product_payload(product)))
            elif barcode.product_id == product.id:
                barcode.payload = product_payload(product)

            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("SKU number already exists. Product duplicate save nahi hua.", "danger")
            return render_template("add_product.html", product=product, categories=categories, suppliers=suppliers, default_category=default_category)

        push_result = notify_product_change(product, "product.saved")
        flash("Product saved.", "success")
        flash_customer_push_result(push_result)
        return redirect(url_for("products.products"))

    return render_template("add_product.html", product=product, categories=categories, suppliers=suppliers, default_category=default_category)


@products_bp.post("/product/<int:product_id>/delete")
@role_required("manager")
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_active = False
    db.session.commit()
    push_result = notify_product_change(product, "product.archived")
    flash("Product archived.", "info")
    flash_customer_push_result(push_result)
    return redirect(url_for("products.products"))


def int_or_none(value):
    return int(value) if value else None


def numeric_or_zero(value):
    try:
        return float(value or 0)
    except ValueError:
        return 0


def ensure_vehicle_categories():
    existing = {category.name.lower(): category for category in Category.query.all()}
    for name in VEHICLE_CATEGORIES:
        if name.lower() not in existing:
            category = Category(name=name, description=f"{name} spare parts")
            db.session.add(category)
            existing[name.lower()] = category
    db.session.flush()
    default_category = existing[DEFAULT_PRODUCT_CATEGORY.lower()]
    Product.query.filter(Product.category_id.is_(None)).update({Product.category_id: default_category.id})
    db.session.commit()
    return default_category


def vehicle_categories():
    rows = Category.query.filter(Category.name.in_(VEHICLE_CATEGORIES)).all()
    order = {name: index for index, name in enumerate(VEHICLE_CATEGORIES)}
    return sorted(rows, key=lambda category: order.get(category.name, 999))


def flash_customer_push_result(result):
    if result.get("skipped"):
        return
    if result.get("ok"):
        flash("Customer website updated.", "success")
    else:
        flash(result.get("message", "Customer website update failed."), "warning")
