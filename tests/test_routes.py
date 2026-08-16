import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from models import SequenceExecution, SequenceDefinition

def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "todo_service" in data["registered_services"]

def test_standalone_called_standalone_source(client):
    # Call directly without orchestrator header
    response = client.post(
        "/api/standalone/todo_service?mock=true",
        json={"todo_id": 9}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == 9
    assert data["execution_source"] == "standalone"

def test_standalone_called_orchestrator_source(client):
    # Call with X-Execution-Source header
    headers = {
        "X-Execution-Source": "orchestrator",
        "X-Execution-Id": "exec-abc-123"
    }
    response = client.post(
        "/api/standalone/todo_service?mock=true",
        json={"todo_id": 7},
        headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["execution_source"] == "orchestrator"

def test_create_and_get_sequence_definition(client, db_session):
    recipe = {
        "name": "user_onboarding_pipeline",
        "description": "Onboarding pipeline registering todo and post",
        "sequence": ["todo_service", "post_service"],
        "default_inputs": {
            "post_service": {"body": "Default description"}
        },
        "mappings": [
            {
                "from_service": "trigger_payload",
                "from_field": "target_id",
                "to_service": "todo_service",
                "to_field": "todo_id"
            },
            {
                "from_service": "todo_service",
                "from_field": "title",
                "to_service": "post_service",
                "to_field": "title"
            }
        ]
    }
    # Create sequence
    res_create = client.post("/api/sequences", json=recipe)
    assert res_create.status_code == 200
    created_data = res_create.json()
    assert created_data["name"] == "user_onboarding_pipeline"
    assert len(created_data["mappings"]) == 2

    # Get sequence
    res_get = client.get("/api/sequences/user_onboarding_pipeline")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == created_data["id"]

def test_trigger_by_sequence_name(client, db_session):
    recipe = {
        "name": "flow_test",
        "sequence": ["todo_service", "post_service"],
        "mappings": [
            {
                "from_service": "trigger_payload",
                "from_field": "account_id",
                "to_service": "todo_service",
                "to_field": "todo_id"
            }
        ]
    }
    client.post("/api/sequences", json=recipe)

    trigger_payload = {
        "payload": {"account_id": 42},
        "idempotency_key": "idemp-recipe-1"
    }

    mock_redis = AsyncMock()
    with patch("routes.get_arq_redis", return_value=mock_redis):
        res = client.post("/api/chain/trigger/flow_test", json=trigger_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["sequence_name"] == "flow_test"
        assert data["status"] == "PENDING"
        assert data["inputs"]["todo_service"]["todo_id"] == 42
        assert mock_redis.enqueue_job.called
