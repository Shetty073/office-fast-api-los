import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.models.sequence_execution import SequenceExecution

def test_trigger_by_sequence_name(client, db_session):
    recipe = {
        "name": "flow_test",
        "sequence": ["create_post_service", "get_post_service"],
        "mappings": [
            {
                "from_service": "trigger_payload",
                "from_field": "account_id",
                "to_service": "get_post_service",
                "to_field": "post_id"
            }
        ]
    }
    client.post("/api/sequences", json=recipe)

    trigger_payload = {
        "payload": {"account_id": 42},
        "idempotency_key": "idemp-recipe-1"
    }

    mock_redis = AsyncMock()
    with patch("app.api.endpoints.chain.get_arq_redis", return_value=mock_redis):
        res = client.post("/api/chain/trigger/flow_test", json=trigger_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["task_name"] == "flow_test"
        assert "task_id" in data
        assert mock_redis.enqueue_job.called

def test_trigger_by_sequence_invalid_name(client):
    res = client.post("/api/chain/trigger/unregistered_flow", json={})
    assert res.status_code == 404

def test_trigger_by_sequence_general_error(client):
    with patch("app.services.sequence_manager.SequenceManager.trigger_by_definition", side_effect=ValueError("Bad params")):
        res = client.post("/api/chain/trigger/some_flow", json={})
        assert res.status_code == 400

def test_trigger_chain_adhoc_success(client):
    payload = {
        "sequence": ["create_post_service", ["get_post_service"]],
        "inputs": {
            "create_post_service": {"title": "Adhoc Post", "_mock": True},
            "get_post_service": {"post_id": 1, "_mock": True}
        },
        "mappings": [],
        "idempotency_key": "idemp-adhoc-unique-123"
    }

    mock_redis = AsyncMock()
    with patch("app.api.endpoints.chain.get_arq_redis", return_value=mock_redis):
        response = client.post("/api/chain/trigger", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] is not None
        assert data["status"] == "PENDING"
        assert mock_redis.enqueue_job.called

def test_trigger_chain_adhoc_invalid_service(client):
    payload = {
        "sequence": ["non_existent_service"],
        "inputs": {}
    }
    response = client.post("/api/chain/trigger", json=payload)
    assert response.status_code == 404

def test_trigger_chain_adhoc_general_error(client):
    with patch("app.services.sequence_manager.SequenceManager.create_execution", side_effect=Exception("Database error")):
        payload = {"sequence": ["create_post_service"], "inputs": {}}
        response = client.post("/api/chain/trigger", json=payload)
        assert response.status_code == 400

def test_get_chain_status_with_progress_and_responses(client, db_session):
    execution = SequenceExecution(
        id="test-status-exec-1",
        sequence=["create_post_service", ["get_post_service"]],
        inputs={"create_post_service": {"title": "P1"}},
        mappings=[],
        status="RUNNING",
        current_step=1,
        steps_data=[
            {
                "service_name": "create_post_service",
                "status": "COMPLETED",
                "input_payload": {"title": "P1"},
                "output_response": {"success": True, "data": {"id": 101}},
                "duration_ms": 120,
                "retry_count": 0
            },
            {
                "service_name": "get_post_service",
                "status": "PENDING",
                "input_payload": {},
                "output_response": None,
                "duration_ms": 0,
                "retry_count": 0
            }
        ]
    )
    db_session.add(execution)
    db_session.commit()

    response = client.get(f"/api/chain/status/{execution.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == execution.id
    assert data["status"] == "RUNNING"
    assert data["count"]["total"] == 2
    assert data["count"]["completed"] == 1
    assert data["count"]["pending"] == 1
    assert "create_post_service" in data["data"]

def test_get_chain_status_not_found(client):
    response = client.get("/api/chain/status/missing-exec-id")
    assert response.status_code == 404

def test_cancel_chain_route(client, db_session):
    execution = SequenceExecution(
        id="test-cancel-exec-1",
        sequence=["create_post_service"],
        inputs={"create_post_service": {"title": "P1"}},
        mappings=[],
        status="RUNNING",
        current_step=0,
        steps_data=[
            {
                "service_name": "create_post_service",
                "status": "COMPLETED",
                "input_payload": {"title": "P1"},
                "output_response": {"data": {"id": 101}},
                "duration_ms": 100,
                "retry_count": 0
            }
        ]
    )
    db_session.add(execution)
    db_session.commit()

    mock_redis = AsyncMock()
    with patch("app.api.endpoints.chain.get_arq_redis", return_value=mock_redis):
        with patch("app.api.endpoints.chain.Job.abort", new_callable=AsyncMock) as mock_abort:
            response = client.post(f"/api/chain/cancel/{execution.id}")
            assert response.status_code == 200
            assert "Cancellation command issued" in response.json()["detail"]
            assert mock_abort.called
            assert mock_redis.enqueue_job.called

def test_cancel_chain_not_found(client):
    response = client.post("/api/chain/cancel/unknown-id")
    assert response.status_code == 404

def test_cancel_chain_invalid_status(client, db_session):
    execution = SequenceExecution(
        id="test-cancel-done-1",
        sequence=["create_post_service"],
        inputs={},
        mappings=[],
        status="COMPLETED",
        current_step=1,
        steps_data=[]
    )
    db_session.add(execution)
    db_session.commit()

    response = client.post(f"/api/chain/cancel/{execution.id}")
    assert response.status_code == 400

def test_retry_chain_resume(client, db_session):
    execution = SequenceExecution(
        id="test-retry-resume-1",
        sequence=["create_post_service", "get_post_service"],
        inputs={"create_post_service": {"title": "P1"}, "get_post_service": {"post_id": 1}},
        mappings=[],
        status="FAILED",
        current_step=1,
        steps_data=[
            {
                "service_name": "create_post_service",
                "status": "COMPLETED",
                "input_payload": {"title": "P1"},
                "output_response": {"data": {"id": 101}},
                "duration_ms": 100,
                "retry_count": 0
            },
            {
                "service_name": "get_post_service",
                "status": "FAILED",
                "error_message": "Network timeout",
                "input_payload": {"post_id": 1},
                "output_response": None,
                "duration_ms": 50,
                "retry_count": 3
            }
        ]
    )
    db_session.add(execution)
    db_session.commit()

    mock_redis = AsyncMock()
    with patch("app.api.endpoints.chain.get_arq_redis", return_value=mock_redis):
        response = client.post(f"/api/chain/retry/{execution.id}", json={"strategy": "resume"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "PENDING"
        assert data["current_step"] == 1
        assert data["steps_data"][1]["status"] == "PENDING"
        assert mock_redis.enqueue_job.called

def test_retry_chain_restart(client, db_session):
    execution = SequenceExecution(
        id="test-retry-restart-1",
        sequence=["create_post_service"],
        inputs={},
        mappings=[],
        status="FAILED",
        current_step=0,
        steps_data=[{"service_name": "create_post_service", "status": "FAILED"}]
    )
    db_session.add(execution)
    db_session.commit()

    mock_redis = AsyncMock()
    with patch("app.api.endpoints.chain.get_arq_redis", return_value=mock_redis):
        response = client.post(f"/api/chain/retry/{execution.id}", json={"strategy": "restart"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "PENDING"
        assert data["current_step"] == 0
        assert len(data["steps_data"]) == 0

def test_retry_chain_not_found(client):
    response = client.post("/api/chain/retry/unknown-id", json={"strategy": "restart"})
    assert response.status_code == 404

def test_retry_chain_invalid_status(client, db_session):
    execution = SequenceExecution(
        id="test-retry-running-1",
        sequence=["create_post_service"],
        inputs={},
        mappings=[],
        status="RUNNING",
        current_step=0,
        steps_data=[]
    )
    db_session.add(execution)
    db_session.commit()

    response = client.post(f"/api/chain/retry/{execution.id}", json={"strategy": "restart"})
    assert response.status_code == 400

def test_retry_chain_invalid_strategy(client, db_session):
    execution = SequenceExecution(
        id="test-retry-invalid-strat",
        sequence=["create_post_service"],
        inputs={},
        mappings=[],
        status="FAILED",
        current_step=0,
        steps_data=[]
    )
    db_session.add(execution)
    db_session.commit()

    response = client.post(f"/api/chain/retry/{execution.id}", json={"strategy": "invalid_strat"})
    assert response.status_code == 400
