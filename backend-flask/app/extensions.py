from flask_sqlalchemy import SQLAlchemy

try:
    from flask_migrate import Migrate
except ImportError:
    class Migrate:
        def init_app(self, app, db):
            return None


db = SQLAlchemy()
migrate = Migrate()
