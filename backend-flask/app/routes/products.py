from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Barcode, Category, Product, Supplier
from ..utils.barcode import build_product_barcode, product_payload
from ..utils.google_storage import import_product_images_by_sku, upload_product_image
from .auth import login_required, role_required

products_bp = Blueprint("products", __name__)


@products_bp.route("/products")
@login_required
def products():
    q = request.args.get("q", "").strip()
    query = Product.query
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.sku.ilike(like)) | (Product.brand.ilike(like)))
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
    categories = Category.query.order_by(Category.name).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()

    if request.method == "POST":
        sku = request.form.get("sku", "").strip()
        existing = Product.query.filter(Product.sku == sku)
        if product:
            existing = existing.filter(Product.id != product.id)
        if existing.first():
            flash("SKU already exists.", "danger")
            return render_template("add_product.html", product=product, categories=categories, suppliers=suppliers)

        if not product:
            product = Product()
            db.session.add(product)

        product.name = request.form.get("name", "").strip()
        product.sku = sku
        product.brand = request.form.get("brand", "").strip()
        product.unit = request.form.get("unit", "pcs").strip() or "pcs"
        product.category_id = int_or_none(request.form.get("category_id"))
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
                return render_template("add_product.html", product=product, categories=categories, suppliers=suppliers)
        else:
            product.image_url = request.form.get("image_url", "").strip()
        db.session.flush()

        code = build_product_barcode(product)
        barcode = Barcode.query.filter_by(product_id=product.id, code=code).first()
        if not barcode:
            db.session.add(Barcode(product_id=product.id, code=code, payload=product_payload(product)))

        db.session.commit()
        flash("Product saved.", "success")
        return redirect(url_for("products.products"))

    return render_template("add_product.html", product=product, categories=categories, suppliers=suppliers)


@products_bp.post("/product/<int:product_id>/delete")
@role_required("manager")
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_active = False
    db.session.commit()
    flash("Product archived.", "info")
    return redirect(url_for("products.products"))


def int_or_none(value):
    return int(value) if value else None


def numeric_or_zero(value):
    try:
        return float(value or 0)
    except ValueError:
        return 0
