import pytest

def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "create_post_service" in data["registered_services"]
    assert "get_post_service" in data["registered_services"]
    assert "update_post_service" in data["registered_services"]

def test_standalone_called_standalone_source(client):
    response = client.post(
        "/api/standalone/create_post_service?mock=true",
        json={"title": "Test Title", "body": "Test Body"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == 101
    assert data["execution_source"] == "standalone"

def test_standalone_called_orchestrator_source(client):
    headers = {
        "X-Execution-Source": "orchestrator",
        "X-Execution-Id": "exec-abc-123"
    }
    response = client.post(
        "/api/standalone/get_post_service?mock=true",
        json={"post_id": 5},
        headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == 5
    assert data["execution_source"] == "orchestrator"

def test_standalone_service_not_found(client):
    response = client.post("/api/standalone/unknown_service", json={})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

def test_standalone_service_failure(client):
    response = client.post("/api/standalone/get_post_service?mock=false", json={})
    assert response.status_code == 400

def test_standalone_compensate_endpoint(client):
    response = client.post(
        "/api/standalone/create_post_service/compensate",
        json={"input_payload": {"title": "Post"}, "output_response": {"data": {"id": 101}}},
        headers={"X-Execution-Id": "test-comp-1"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "compensated"

def test_standalone_compensate_unknown_service(client):
    response = client.post("/api/standalone/unknown_service/compensate", json={})
    assert response.status_code == 404
