import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlunparse

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def env_list(name):
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def database_uri():
    uri = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'warehouse.db'}").replace("postgres://", "postgresql://")
    if uri.startswith("postgresql://"):
        parsed = urlparse(uri)
        username = quote(unquote(parsed.username or ""), safe="")
        password = quote(unquote(parsed.password or ""), safe="")
        auth = username
        if password:
            auth = f"{auth}:{password}"
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        uri = urlunparse((parsed.scheme, f"{auth}@{host}", parsed.path, parsed.params, parsed.query, parsed.fragment))
    if uri.startswith("postgresql://"):
        return uri.replace("postgresql://", "postgresql+psycopg://", 1)
    return uri


class Config:
    APP_ENV = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).lower()
    IS_PRODUCTION = APP_ENV == "production"
    DEBUG = env_bool("FLASK_DEBUG", False)
    SECRET_KEY = os.getenv("SECRET_KEY") or ("change-this-secret-key" if not IS_PRODUCTION else "")
    SQLALCHEMY_DATABASE_URI = database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": env_int("SQLALCHEMY_POOL_RECYCLE", 300),
    }
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "None" if IS_PRODUCTION else "Lax")
    SESSION_REFRESH_EACH_REQUEST = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=env_int("SESSION_LIFETIME_HOURS", 24))
    PREFERRED_URL_SCHEME = "https" if IS_PRODUCTION else "http"
    TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", IS_PRODUCTION)
    API_ALLOWED_ORIGINS = env_list("API_ALLOWED_ORIGINS")
    API_ALLOW_RAILWAY_ORIGINS = env_bool("API_ALLOW_RAILWAY_ORIGINS", IS_PRODUCTION)
    ALLOW_INSECURE_USER_HEADER = env_bool("ALLOW_INSECURE_USER_HEADER", False)
    INTEGRATION_API_KEY = os.getenv("INTEGRATION_API_KEY", "")
    MAX_CONTENT_LENGTH = env_int("MAX_UPLOAD_MB", 8) * 1024 * 1024
    GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    GOOGLE_APPLICATION_CREDENTIALS_JSON = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "") or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    GOOGLE_CLOUD_STORAGE_BUCKET = os.getenv("GOOGLE_CLOUD_STORAGE_BUCKET", "")
    GOOGLE_CLOUD_STORAGE_PRODUCTS_PREFIX = os.getenv("GOOGLE_CLOUD_STORAGE_PRODUCTS_PREFIX", "products")
    GOOGLE_CLOUD_STORAGE_PUBLIC = os.getenv("GOOGLE_CLOUD_STORAGE_PUBLIC", "false").lower() == "true"
    GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    GOOGLE_SHEETS_RANGE = os.getenv("GOOGLE_SHEETS_RANGE", "CurrentStock!A:H")
    GOOGLE_SHEETS_AUTO_SYNC = os.getenv("GOOGLE_SHEETS_AUTO_SYNC", "true").lower() == "true"
    GOOGLE_APPS_SCRIPT_WEBHOOK_URL = os.getenv("GOOGLE_APPS_SCRIPT_WEBHOOK_URL", "")
    GOOGLE_APPS_SCRIPT_TOKEN = os.getenv("GOOGLE_APPS_SCRIPT_TOKEN", "")
    CUSTOMER_PRODUCT_WEBHOOK_URL = os.getenv("CUSTOMER_PRODUCT_WEBHOOK_URL", "")
    CUSTOMER_PRODUCT_WEBHOOK_TOKEN = os.getenv("CUSTOMER_PRODUCT_WEBHOOK_TOKEN", "")
    CUSTOMER_PRODUCT_WEBHOOK_TIMEOUT = env_int("CUSTOMER_PRODUCT_WEBHOOK_TIMEOUT", 10)
    CUSTOMER_SHIPPING_WEBHOOK_URL = os.getenv("CUSTOMER_SHIPPING_WEBHOOK_URL", "")
    CUSTOMER_SHIPPING_WEBHOOK_TOKEN = os.getenv("CUSTOMER_SHIPPING_WEBHOOK_TOKEN", "")
    CUSTOMER_SHIPPING_WEBHOOK_TIMEOUT = env_int("CUSTOMER_SHIPPING_WEBHOOK_TIMEOUT", env_int("CUSTOMER_PRODUCT_WEBHOOK_TIMEOUT", 10))
    PAYU_ENV = os.getenv("PAYU_ENV", "test").strip().lower()
    PAYU_KEY = os.getenv("PAYU_KEY", "")
    PAYU_SALT = os.getenv("PAYU_SALT", "")
    PAYU_REFUND_CALLBACK_URL = os.getenv("PAYU_REFUND_CALLBACK_URL", "")
    PAYU_TIMEOUT = env_int("PAYU_TIMEOUT", 20)
    SHIPROCKET_API_BASE_URL = os.getenv("SHIPROCKET_API_BASE_URL", "https://apiv2.shiprocket.in/v1/external").rstrip("/")
    SHIPROCKET_EMAIL = os.getenv("SHIPROCKET_EMAIL", "")
    SHIPROCKET_PASSWORD = os.getenv("SHIPROCKET_PASSWORD", "")
    SHIPROCKET_TOKEN = os.getenv("SHIPROCKET_TOKEN", "")
    SHIPROCKET_PICKUP_LOCATION = os.getenv("SHIPROCKET_PICKUP_LOCATION", "")
    SHIPROCKET_CHANNEL_ID = os.getenv("SHIPROCKET_CHANNEL_ID", "")
    SHIPROCKET_RETURN_WAREHOUSE_ID = os.getenv("SHIPROCKET_RETURN_WAREHOUSE_ID", "")
    SHIPROCKET_WEBHOOK_TOKEN = os.getenv("SHIPROCKET_WEBHOOK_TOKEN", "")
    SHIPROCKET_TIMEOUT = env_int("SHIPROCKET_TIMEOUT", 20)
    SHIPROCKET_DEFAULT_LENGTH_CM = env_float("SHIPROCKET_DEFAULT_LENGTH_CM", 10)
    SHIPROCKET_DEFAULT_BREADTH_CM = env_float("SHIPROCKET_DEFAULT_BREADTH_CM", 10)
    SHIPROCKET_DEFAULT_HEIGHT_CM = env_float("SHIPROCKET_DEFAULT_HEIGHT_CM", 10)
    SHIPROCKET_DEFAULT_WEIGHT_KG = env_float("SHIPROCKET_DEFAULT_WEIGHT_KG", 0.5)
    CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")
    GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
