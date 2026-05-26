import os


def auto_upgrade_database(app, default_enabled=False):
    enabled = os.getenv("AUTO_DB_UPGRADE_ON_START")
    if enabled is None:
        enabled = "true" if default_enabled else "false"
    if enabled.strip().lower() not in {"1", "true", "yes", "on"}:
        return

    from flask_migrate import upgrade

    with app.app_context():
        upgrade()
