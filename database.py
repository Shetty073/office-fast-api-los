from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import config

def init_database():
    """Ensure the database exists on MySQL. Bypassed for SQLite."""
    db_url = config.DATABASE_URL
    if db_url.startswith("sqlite"):
        return
    try:
        # Connect to server without database specification
        temp_engine = create_engine(config.MYSQL_BASE_URL)
        with temp_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {config.DATABASE_NAME}"))
            conn.commit()
        temp_engine.dispose()
    except Exception as e:
        print(f"Database auto-creation bypassed/failed: {e}")

# Run database setup before creating engine
init_database()

connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
