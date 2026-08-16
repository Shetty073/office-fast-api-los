import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Force file-based SQLite database for testing orchestration service
os.environ["DATABASE_URL"] = "sqlite:///test_orch.db"

import config
from database import Base, engine, SessionLocal, get_db

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("test_orch.db"):
        try:
            os.remove("test_orch.db")
        except Exception:
            pass

@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def db_session_factory(db_session):
    def _factory():
        yield db_session
    return _factory
