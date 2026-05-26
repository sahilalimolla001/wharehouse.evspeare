import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)

from run import app as application  # noqa: E402
from app.startup import auto_upgrade_database  # noqa: E402


auto_upgrade_database(application, default_enabled=True)


app = application
