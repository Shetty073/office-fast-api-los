from sqlalchemy import create_engine, text, inspect
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
engine_kwargs = {}
if config.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    engine_kwargs = {
        "pool_size": config.DB_POOL_SIZE,
        "max_overflow": config.DB_MAX_OVERFLOW,
        "pool_pre_ping": True
    }

engine = create_engine(config.DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def auto_migrate_columns():
    """Automatically adds newly declared model columns to existing relational tables if missing."""
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        is_pg = "postgresql" in config.DATABASE_URL
        is_sqlite = config.DATABASE_URL.startswith("sqlite")
        json_type = "JSONB" if is_pg else ("JSON" if not is_sqlite else "TEXT")

        with engine.begin() as conn:
            if "sequence_definitions" in tables:
                cols = [c["name"] for c in inspector.get_columns("sequence_definitions")]
                if "skip_conditions" not in cols:
                    conn.execute(text(f"ALTER TABLE sequence_definitions ADD COLUMN skip_conditions {json_type}"))
                if "success_conditions" not in cols:
                    conn.execute(text(f"ALTER TABLE sequence_definitions ADD COLUMN success_conditions {json_type}"))
                if "conditions" not in cols:
                    conn.execute(text(f"ALTER TABLE sequence_definitions ADD COLUMN conditions {json_type}"))

            if "sequence_executions" in tables:
                cols = [c["name"] for c in inspector.get_columns("sequence_executions")]
                if "skip_conditions" not in cols:
                    conn.execute(text(f"ALTER TABLE sequence_executions ADD COLUMN skip_conditions {json_type}"))
                if "success_conditions" not in cols:
                    conn.execute(text(f"ALTER TABLE sequence_executions ADD COLUMN success_conditions {json_type}"))
                if "conditions" not in cols:
                    conn.execute(text(f"ALTER TABLE sequence_executions ADD COLUMN conditions {json_type}"))
                if "trigger_payload" not in cols:
                    conn.execute(text(f"ALTER TABLE sequence_executions ADD COLUMN trigger_payload {json_type}"))
    except Exception as e:
        print(f"Column auto-migration bypassed/notice: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
