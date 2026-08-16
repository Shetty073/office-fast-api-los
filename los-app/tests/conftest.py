import os
import pytest
from fastapi.testclient import TestClient

# Force file-based SQLite database for testing
os.environ["DATABASE_URL"] = "sqlite:///test_los.db"

from app.db.base import Base
from app.db.session import engine, SessionLocal, get_db
from app.main import app

def setup_db_impl():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("test_los.db"):
        try:
            os.remove("test_los.db")
        except Exception:
            pass

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    gen = setup_db_impl()
    next(gen)
    yield
    try:
        next(gen)
    except StopIteration:
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
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
            
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
