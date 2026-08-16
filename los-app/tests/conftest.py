import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use a consistent SQLite test database file
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///test_los.db"

from app.db.base import Base
from app.db.session import engine, SessionLocal, get_db
from app.models.user import User
from app.core.security import get_password_hash, create_access_token
from app.main import app

@pytest.fixture(scope="session", autouse=True)
def init_test_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("test_los.db"):
        try:
            os.remove("test_los.db")
        except Exception:
            pass

@pytest.fixture(autouse=True)
def clean_tables_between_tests():
    # Clean table records before each test for clean isolation
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())

@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()

@pytest.fixture
def default_user(db_session):
    user = User(
        id="default-test-user-id",
        username="test_api_client",
        app_name="los_test_client",
        hashed_password=get_password_hash("testpassword123"),
        is_admin=True,
        is_active=True,
        enable_encryption=False,
        token_expiry_seconds=86400
    )
    db_session.add(user)
    db_session.commit()
    return user

@pytest.fixture
def default_token(default_user):
    return create_access_token(
        subject=default_user.username,
        app_name=default_user.app_name,
        is_admin=default_user.is_admin
    )

@pytest.fixture
def client(default_token):
    with TestClient(app, raise_server_exceptions=True) as test_client:
        test_client.headers["Authorization"] = f"Bearer {default_token}"
        yield test_client

@pytest.fixture
def unauthenticated_client():
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
