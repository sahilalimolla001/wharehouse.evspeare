from run import app as application
from app.startup import auto_upgrade_database


auto_upgrade_database(application)


app = application
