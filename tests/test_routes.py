import pytest
from unittest.mock import patch, MagicMock
from fastapi import BackgroundTasks
from models import SequenceExecution

def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "todo_service" in data["registered_services"]

def test_standalone_success_mock(client):
    response = client.post(
        "/api/standalone/todo_service?mock=true",
        json={"todo_id": 9}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == 9
    assert data["data"]["source"] == "mock"

def test_standalone_success_real(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "userId": 1,
        "id": 2,
        "title": "quis ut nam facilis et officia qui",
        "completed": False
    }
    
    with patch("requests.request", return_value=mock_resp):
        response = client.post(
            "/api/standalone/todo_service?mock=false",
            json={"todo_id": 2}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == 2

def test_standalone_not_found(client):
    response = client.post(
        "/api/standalone/non_existent_service",
        json={}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

def test_standalone_failure(client):
    response = client.post(
        "/api/standalone/todo_service?mock=false",
        json={}
    )
    assert response.status_code == 400
    assert "todo_id parameter is required" in response.json()["detail"]

def test_trigger_chain_success(client):
    payload = {
        "sequence": ["todo_service", "post_service"],
        "inputs": {
            "todo_service": {"todo_id": 1, "_mock": True},
            "post_service": {"body": "Test body", "_mock": True}
        },
        "mappings": [
            {
                "from_service": "todo_service",
                "from_field": "title",
                "to_service": "post_service",
                "to_field": "title"
            }
        ]
    }
    
    with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
        response = client.post("/api/chain/trigger", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "PENDING"
        assert len(data["sequence"]) == 2
        assert mock_add_task.called

def test_trigger_chain_invalid_service(client):
    payload = {
        "sequence": ["todo_service", "invalid_name"],
        "inputs": {},
        "mappings": []
    }
    response = client.post("/api/chain/trigger", json=payload)
    assert response.status_code == 404
    assert "not registered" in response.json()["detail"]

def test_trigger_chain_db_error(client):
    payload = {
        "sequence": ["todo_service"],
        "inputs": {},
        "mappings": []
    }
    with patch("orchestrator.Orchestrator.create_execution", side_effect=ValueError("DB issue")):
        response = client.post("/api/chain/trigger", json=payload)
        assert response.status_code == 400
        assert "DB issue" in response.json()["detail"]

def test_get_chain_status_success(client, db_session):
    exec_record = SequenceExecution(
        id="test-uuid-999",
        sequence=["todo_service"],
        inputs={},
        mappings=[],
        status="COMPLETED",
        current_step=1,
        steps_data=[]
    )
    db_session.add(exec_record)
    db_session.commit()
    
    response = client.get("/api/chain/status/test-uuid-999")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-uuid-999"
    assert data["status"] == "COMPLETED"

def test_get_chain_status_not_found(client):
    response = client.get("/api/chain/status/uuid-does-not-exist")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

def test_trigger_chain_with_success_conditions(client):
    payload = {
        "sequence": ["todo_service"],
        "inputs": {
            "todo_service": {"todo_id": 1, "_mock": True}
        },
        "mappings": [],
        "success_conditions": {
            "todo_service": {
                "status_codes": [200],
                "body_rules": {
                    "data.completed": True
                }
            }
        }
    }
    with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
        response = client.post("/api/chain/trigger", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "PENDING"
        assert data["success_conditions"]["todo_service"]["status_codes"] == [200]
        assert mock_add_task.called

def test_trigger_chain_idempotency(client):
    payload = {
        "sequence": ["todo_service"],
        "inputs": {
            "todo_service": {"todo_id": 1, "_mock": True}
        },
        "mappings": [],
        "idempotency_key": "idemp-key-route-abc"
    }
    with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
        # First request creates it and launches background task
        response1 = client.post("/api/chain/trigger", json=payload)
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["status"] == "PENDING"
        assert mock_add_task.call_count == 1
        
        # Second request with same idempotency key returns the same execution object but doesn't launch task again
        response2 = client.post("/api/chain/trigger", json=payload)
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["id"] == data1["id"]
        assert mock_add_task.call_count == 1 # still 1!
