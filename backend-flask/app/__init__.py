import secrets

from flask import Flask, abort, render_template, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

from .extensions import db, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    if app.config.get("TRUST_PROXY_HEADERS"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    db.init_app(app)
    migrate.init_app(app, db)

    register_security_hooks(app)

    from .routes import register_blueprints

    register_blueprints(app)

    @app.context_processor
    def inject_template_helpers():
        return {
            "app_name": "Evsphere Warehouse",
            "csrf_token": csrf_token,
        }

    @app.template_filter("money")
    def money(value):
        return f"Rs. {float(value or 0):,.2f}"

    @app.errorhandler(403)
    def access_denied(error):
        return render_template("403.html"), 403

    return app


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def register_security_hooks(app):
    @app.before_request
    def protect_admin_forms():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if request.endpoint and request.endpoint.startswith("api."):
            return None
        if request.endpoint == "shiprocket.receive_webhook":
            return None
        expected = session.get("_csrf_token")
        submitted = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token")
        if not expected or not submitted or not secrets.compare_digest(expected, submitted):
            abort(400, description="Invalid CSRF token")
        return None

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(self), geolocation=(), microphone=()")
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
