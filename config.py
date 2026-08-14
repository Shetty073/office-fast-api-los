import os

DATABASE_HOST = os.getenv("DB_HOST", "localhost")
DATABASE_PORT = os.getenv("DB_PORT", "3306")
DATABASE_USER = os.getenv("DB_USER", "root")
DATABASE_PASS = os.getenv("DB_PASS", "10291996")
DATABASE_NAME = os.getenv("DB_NAME", "office_proj")

# Base connection URL (without selecting database) to allow auto-creation
MYSQL_BASE_URL = f"mysql+pymysql://{DATABASE_USER}:{DATABASE_PASS}@{DATABASE_HOST}:{DATABASE_PORT}"

# Full connection URL
DATABASE_URL = os.getenv("DATABASE_URL", f"{MYSQL_BASE_URL}/{DATABASE_NAME}")
