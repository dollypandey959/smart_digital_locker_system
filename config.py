import os

class Config:
    SECRET_KEY = "my_secret_key"

    MYSQL_HOST = "localhost"
    MYSQL_USER = "root"
    MYSQL_PASSWORD = "root@1"
    MYSQL_DB = "smart_locker"

    UPLOAD_FOLDER = os.path.join("static", "uploads")

    