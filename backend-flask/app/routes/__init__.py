def register_blueprints(app):
    from .api import api_bp
    from .auth import auth_bp
    from .dashboard import dashboard_bp
    from .finance import finance_bp
    from .orders import orders_bp
    from .products import products_bp
    from .reports import reports_bp
    from .refunds import refunds_bp
    from .returns import returns_bp
    from .shiprocket import shiprocket_bp
    from .stock import stock_bp
    from .suppliers import suppliers_bp
    from .users import users_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(shiprocket_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(refunds_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
