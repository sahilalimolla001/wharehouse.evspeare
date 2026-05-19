from urllib.parse import urlparse


def parse_database_url(database_url):
    normalized = (
        database_url.replace("postgres://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )
    parsed = urlparse(normalized)
    if parsed.scheme != "postgresql":
        return {
            "scheme": parsed.scheme,
            "is_postgres": False,
            "host": "",
            "port": "",
            "database": database_url,
            "username": "",
            "password": "",
        }
    return {
        "scheme": parsed.scheme,
        "is_postgres": True,
        "host": parsed.hostname or "",
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/"),
        "username": parsed.username or "",
        "password": parsed.password or "",
    }
