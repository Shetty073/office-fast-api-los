import pytest
import json
from unittest.mock import patch, AsyncMock
from app.models.user import User
from app.core.security import get_password_hash, create_access_token, encrypt_payload, decrypt_payload

@pytest.fixture
def admin_user(db_session):
    user = User(
        id="admin-id-1",
        username="superadmin",
        app_name="admin_portal",
        hashed_password=get_password_hash("adminpass123"),
        is_admin=True,
        is_active=True,
        enable_encryption=False,
        token_expiry_seconds=86400
    )
    db_session.add(user)
    db_session.commit()
    return user

@pytest.fixture
def regular_user(db_session):
    user = User(
        id="regular-id-1",
        username="client_app_1",
        app_name="los_frontend",
        hashed_password=get_password_hash("clientpass123"),
        is_admin=False,
        is_active=True,
        enable_encryption=False,
        token_expiry_seconds=3600
    )
    db_session.add(user)
    db_session.commit()
    return user

@pytest.fixture
def admin_token(admin_user):
    return create_access_token(subject=admin_user.username, app_name=admin_user.app_name, is_admin=True)

@pytest.fixture
def regular_token(regular_user):
    return create_access_token(subject=regular_user.username, app_name=regular_user.app_name, is_admin=False)

def test_login_success(client, regular_user):
    res = client.post("/api/auth/login", json={"username": "client_app_1", "password": "clientpass123"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["app_name"] == "los_frontend"
    assert data["expires_in_seconds"] == 3600

def test_login_invalid_credentials(client, regular_user):
    res = client.post("/api/auth/login", json={"username": "client_app_1", "password": "wrongpassword"})
    assert res.status_code == 401

def test_login_deactivated_user(client, db_session, regular_user):
    regular_user.is_active = False
    db_session.commit()

    res = client.post("/api/auth/login", json={"username": "client_app_1", "password": "clientpass123"})
    assert res.status_code == 403

def test_register_app_as_admin(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {
        "username": "encrypted_client",
        "password": "strongpassword123",
        "app_name": "secure_los_app",
        "is_admin": False,
        "enable_encryption": True,
        "token_expiry_seconds": 7200
    }
    res = client.post("/api/auth/register-app", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "encrypted_client"
    assert data["enable_encryption"] is True
    assert data["encryption_key"] is not None

def test_register_app_forbidden_for_non_admin(client, regular_token):
    headers = {"Authorization": f"Bearer {regular_token}"}
    payload = {
        "username": "another_app",
        "password": "password123",
        "app_name": "app",
        "enable_encryption": False
    }
    res = client.post("/api/auth/register-app", json=payload, headers=headers)
    assert res.status_code == 403

def test_register_app_duplicate_username(client, admin_token, regular_user):
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {
        "username": regular_user.username,
        "password": "password123",
        "app_name": "duplicate_app"
    }
    res = client.post("/api/auth/register-app", json=payload, headers=headers)
    assert res.status_code == 400

def test_deactivate_user(client, admin_token, regular_user):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post(f"/api/auth/deactivate/{regular_user.id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["is_active"] is False

def test_deactivate_self_admin_blocked(client, admin_token, admin_user):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post(f"/api/auth/deactivate/{admin_user.id}", headers=headers)
    assert res.status_code == 400

def test_get_current_user_profile(client, regular_token):
    headers = {"Authorization": f"Bearer {regular_token}"}
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["username"] == "client_app_1"

def test_encryption_middleware_with_encrypted_user(client, db_session):
    from app.core.security import generate_aes_key
    enc_key = generate_aes_key()
    user = User(
        id="enc-user-1",
        username="crypto_user",
        app_name="secure_app",
        hashed_password=get_password_hash("pass123"),
        is_admin=False,
        is_active=True,
        enable_encryption=True,
        encryption_key=enc_key,
        token_expiry_seconds=3600
    )
    db_session.add(user)
    db_session.commit()

    token = create_access_token(
        subject=user.username, 
        app_name=user.app_name, 
        enable_encryption=True, 
        encryption_key=enc_key
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Encrypt the input payload
    raw_payload = json.dumps({"todo_id": 1})
    encrypted_body = encrypt_payload(raw_payload, enc_key)

    res = client.post("/api/standalone/todo_service?mock=true", json=encrypted_body, headers=headers)
    assert res.status_code == 200
    
    # Response must also be encrypted
    enc_resp = res.json()
    assert "ciphertext" in enc_resp
    decrypted_resp = json.loads(decrypt_payload(enc_resp, enc_key))
    assert decrypted_resp["success"] is True
    assert decrypted_resp["data"]["id"] == 1

def test_hash_idempotency_middleware(client):
    mock_redis = AsyncMock()
    # First request acquires lock (returns True), second within window returns False
    mock_redis.set = AsyncMock(side_effect=[True, False])
    
    with patch("app.middleware.idempotency.get_arq_redis", return_value=mock_redis):
        # 1st request succeeds
        res1 = client.post("/api/standalone/todo_service?mock=true", json={"todo_id": 2})
        assert res1.status_code == 200

        # 2nd identical request is blocked with 409 Conflict
        res2 = client.post("/api/standalone/todo_service?mock=true", json={"todo_id": 2})
        assert res2.status_code == 409
        assert "Duplicate request rejected" in res2.json()["detail"]

def test_unauthenticated_request_blocked(unauthenticated_client):
    """Ensure all business endpoints strictly reject requests without Bearer token (401 Unauthorized)."""
    res1 = unauthenticated_client.post("/api/standalone/todo_service", json={"todo_id": 1})
    assert res1.status_code == 401

    res2 = unauthenticated_client.get("/api/sequences")
    assert res2.status_code == 401

    res3 = unauthenticated_client.post("/api/chain/trigger", json={"sequence": ["todo_service"]})
    assert res3.status_code == 401
