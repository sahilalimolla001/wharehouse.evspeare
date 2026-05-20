import os

from app import create_app
from app.extensions import db
from app.models import Barcode, Category, Product, Supplier, User, WarehouseLocation
from app.utils.barcode import build_location_barcode, build_product_barcode, product_payload
from app.utils.database_url import parse_database_url
from app.utils.google_sheets import auto_sync_current_stock_sheet
from app.utils.google_storage import test_storage_connection
from app.utils.stock import receive_stock
from config import Config

app = create_app()


@app.cli.command("init-db")
def init_db():
    """Create local tables and an initial admin user."""
    db.create_all()
    admin_email = os.getenv("ADMIN_EMAIL", "" if Config.IS_PRODUCTION else "admin@warehouse.local").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD", "" if Config.IS_PRODUCTION else "admin123")
    admin_name = os.getenv("ADMIN_NAME", "Admin User").strip() or "Admin User"
    if not admin_email or not admin_password:
        print("Database tables ready.")
        print("Set ADMIN_EMAIL and ADMIN_PASSWORD, then run init-db again to create the first admin.")
        return
    if Config.IS_PRODUCTION and admin_password in {"admin123", "password", "changeme"}:
        print("Refusing weak production admin password. Set a strong ADMIN_PASSWORD.")
        return
    admin = User.query.filter_by(email=admin_email).first()
    if not admin:
        admin = User(full_name=admin_name, email=admin_email, role="admin")
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()
        print(f"Created admin user: {admin_email}")
    else:
        print("Database already initialized")


@app.cli.command("create-admin")
def create_admin():
    """Create or update the admin user from ADMIN_EMAIL and ADMIN_PASSWORD."""
    db.create_all()
    admin_email = os.getenv("ADMIN_EMAIL", "" if Config.IS_PRODUCTION else "admin@warehouse.local").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD", "" if Config.IS_PRODUCTION else "admin123")
    admin_name = os.getenv("ADMIN_NAME", "Admin User").strip() or "Admin User"
    if not admin_email or not admin_password:
        print("Set ADMIN_EMAIL and ADMIN_PASSWORD before running create-admin.")
        raise SystemExit(1)
    if Config.IS_PRODUCTION and admin_password in {"admin123", "password", "changeme"}:
        print("Refusing weak production admin password. Set a strong ADMIN_PASSWORD.")
        raise SystemExit(1)

    admin = User.query.filter_by(email=admin_email).first()
    if not admin:
        admin = User(full_name=admin_name, email=admin_email, role="admin")
        db.session.add(admin)
        message = "Created admin user"
    else:
        admin.full_name = admin_name
        admin.role = "admin"
        admin.is_active = True
        message = "Updated admin user"

    admin.set_password(admin_password)
    db.session.commit()
    print(f"{message}: {admin_email}")


@app.cli.command("seed-demo")
def seed_demo():
    """Seed categories, suppliers, locations, products, and inventory."""
    if Config.IS_PRODUCTION and os.getenv("ALLOW_DEMO_SEED", "").lower() != "true":
        print("Refusing to seed demo data in production. Set ALLOW_DEMO_SEED=true only for a temporary test database.")
        return
    db.create_all()

    admin = User.query.filter_by(email="admin@warehouse.local").first()
    if not admin:
        admin = User(full_name="Admin User", email="admin@warehouse.local", role="admin")
        admin.set_password("admin123")
        db.session.add(admin)

    categories = {}
    for name in ["Electronics", "Packaging", "Hardware", "Furniture"]:
        category = Category.query.filter_by(name=name).first() or Category(name=name)
        db.session.add(category)
        categories[name] = category

    supplier = Supplier.query.filter_by(name="Metro Supply").first() or Supplier(
        name="Metro Supply",
        phone="+91 90000 00000",
        email="sales@metrosupply.local",
        address="Industrial Area, Delhi",
        gst_number="GST-DEMO-001",
    )
    db.session.add(supplier)

    location = WarehouseLocation.query.filter_by(zone="A", rack="2", shelf="4", bin_code="08").first() or WarehouseLocation(
        zone="A",
        rack="2",
        shelf="4",
        bin_code="08",
    )
    db.session.add(location)
    db.session.flush()
    location.barcode = location.barcode or build_location_barcode(location)

    product = Product.query.filter_by(sku="SKU-1001").first() or Product(
        name="Barcode Scanner",
        sku="SKU-1001",
        brand="ScanPro",
        unit="pcs",
        category=categories["Electronics"],
        supplier=supplier,
        purchase_price=1800,
        selling_price=2400,
        minimum_stock=10,
    )
    db.session.add(product)
    db.session.flush()

    if not Barcode.query.filter_by(code=build_product_barcode(product)).first():
        db.session.add(Barcode(product=product, code=build_product_barcode(product), payload=product_payload(product)))

    if product.total_quantity == 0:
        receive_stock(
            product_id=product.id,
            supplier_id=supplier.id,
            location_id=location.id,
            quantity=50,
            unit_cost=1800,
            invoice_number="DEMO-INV-001",
            received_by_id=admin.id,
            notes="Demo opening stock",
        )

    db.session.commit()
    print("Demo data ready. Login: admin@warehouse.local / admin123")


@app.cli.command("pgadmin-info")
def pgadmin_info():
    """Print DATABASE_URL as pgAdmin connection fields."""
    info = parse_database_url(Config.SQLALCHEMY_DATABASE_URI)
    if not info["is_postgres"]:
        print("Current DATABASE_URL is not PostgreSQL.")
        print(f"Current database: {info['database']}")
        print("Set DATABASE_URL like:")
        print("postgresql://USER:PASSWORD@HOST:5432/DBNAME")
        return
    print("pgAdmin connection fields")
    print(f"Host name/address: {info['host']}")
    print(f"Port: {info['port']}")
    print(f"Maintenance database: {info['database']}")
    print(f"Username: {info['username']}")
    print(f"Password: {'<set in DATABASE_URL>' if info['password'] else '<empty>'}")


@app.cli.command("sync-google-sheet")
def sync_google_sheet():
    """Manually sync current inventory to Google Sheets."""
    result = auto_sync_current_stock_sheet("manual_cli")
    print(result["message"])
    if result.get("updated_range"):
        print(f"Updated range: {result['updated_range']}")


@app.cli.command("test-google-storage")
def test_google_storage():
    """Check Google Cloud Storage credentials and bucket access."""
    try:
        result = test_storage_connection()
        print(f"Google Cloud Storage connected: {result['bucket']}")
    except Exception as error:
        print(f"Google Cloud Storage connection failed: {error}")


@app.cli.command("validate-production")
def validate_production():
    """Check required production settings before commercial use."""
    issues = []
    warnings = []
    db_info = parse_database_url(Config.SQLALCHEMY_DATABASE_URI)

    if not Config.IS_PRODUCTION:
        issues.append("APP_ENV must be set to production.")
    if Config.DEBUG:
        issues.append("FLASK_DEBUG must be false in production.")
    if not Config.SECRET_KEY or Config.SECRET_KEY == "change-this-secret-key" or len(Config.SECRET_KEY) < 32:
        issues.append("SECRET_KEY must be a strong random value with at least 32 characters.")
    if not db_info["is_postgres"]:
        issues.append("DATABASE_URL must point to PostgreSQL for production.")
    if not Config.SESSION_COOKIE_SECURE:
        issues.append("SESSION_COOKIE_SECURE must be true behind HTTPS.")
    if not Config.API_ALLOWED_ORIGINS:
        issues.append("API_ALLOWED_ORIGINS must include your website/mobile app HTTPS origin.")
    if Config.ALLOW_INSECURE_USER_HEADER:
        issues.append("ALLOW_INSECURE_USER_HEADER must be false in production.")
    if not Config.INTEGRATION_API_KEY or len(Config.INTEGRATION_API_KEY) < 24:
        issues.append("INTEGRATION_API_KEY must be set to a strong random value for external order imports.")
    if not Config.GOOGLE_CLOUD_STORAGE_BUCKET:
        warnings.append("GOOGLE_CLOUD_STORAGE_BUCKET is empty; product image uploads will not work.")
    if not Config.GOOGLE_APPS_SCRIPT_WEBHOOK_URL and not Config.GOOGLE_SHEETS_SPREADSHEET_ID:
        warnings.append("Google Sheets sync is not configured.")

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if issues:
        print("Production validation failed:")
        for issue in issues:
            print(f"- {issue}")
        raise SystemExit(1)
    print("Production validation passed.")


if __name__ == "__main__":
    app.run(debug=Config.DEBUG)
