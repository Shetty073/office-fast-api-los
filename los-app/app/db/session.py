from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core import config
from app.db.base import Base

def init_database():
    """Ensure the database exists on PostgreSQL / MySQL. Bypassed for SQLite."""
    db_url = config.DATABASE_URL
    if db_url.startswith("sqlite"):
        return
    try:
        if "postgresql" in db_url:
            postgres_admin_url = f"postgresql+psycopg2://{config.DATABASE_USER}:{config.DATABASE_PASS}@{config.DATABASE_HOST}:{config.DATABASE_PORT}/postgres"
            temp_engine = create_engine(postgres_admin_url, isolation_level="AUTOCOMMIT")
            with temp_engine.connect() as conn:
                res = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname='{config.DATABASE_NAME}'"))
                if not res.scalar():
                    conn.execute(text(f'CREATE DATABASE "{config.DATABASE_NAME}"'))
            temp_engine.dispose()
        elif "mysql" in db_url:
            temp_engine = create_engine(f"mysql+pymysql://{config.DATABASE_USER}:{config.DATABASE_PASS}@{config.DATABASE_HOST}:{config.DATABASE_PORT}")
            with temp_engine.connect() as conn:
                conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {config.DATABASE_NAME}"))
                conn.commit()
            temp_engine.dispose()
    except Exception as e:
        print(f"Database auto-creation bypassed/failed: {e}")

init_database()

connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
