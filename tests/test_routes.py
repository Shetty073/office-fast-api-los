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

def test_standalone_service_not_found(client):
    response = client.post("/api/standalone/unknown_service", json={})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

def test_standalone_service_failure(client):
    response = client.post("/api/standalone/todo_service?mock=false", json={})
    assert response.status_code == 400

def test_standalone_compensate_endpoint(client):
    response = client.post(
        "/api/standalone/todo_service/compensate",
        json={"input_payload": {"todo_id": 10}, "output_response": {}},
        headers={"X-Execution-Id": "test-comp-1"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "compensated"

def test_standalone_compensate_unknown_service(client):
    response = client.post("/api/standalone/unknown_service/compensate", json={})
    assert response.status_code == 404

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

    # Update existing sequence definition
    recipe["description"] = "Updated description"
    res_update = client.post("/api/sequences", json=recipe)
    assert res_update.status_code == 200
    assert res_update.json()["description"] == "Updated description"

    # List all sequences
    res_list = client.get("/api/sequences")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    # Get sequence by name
    res_get = client.get("/api/sequences/user_onboarding_pipeline")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == created_data["id"]

def test_create_sequence_invalid_service(client):
    recipe = {
        "name": "invalid_flow",
        "sequence": ["unknown_service"],
        "mappings": []
    }
    res = client.post("/api/sequences", json=recipe)
    assert res.status_code == 404

def test_create_sequence_error_handling(client):
    with patch("sequence_manager.SequenceManager.create_definition", side_effect=ValueError("Invalid config")):
        res = client.post("/api/sequences", json={"name": "test", "sequence": ["todo_service"]})
        assert res.status_code == 400

def test_get_sequence_not_found(client):
    res = client.get("/api/sequences/non_existent")
    assert res.status_code == 404

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

def test_trigger_by_sequence_invalid_name(client):
    res = client.post("/api/chain/trigger/unregistered_flow", json={})
    assert res.status_code == 404

def test_trigger_by_sequence_general_error(client):
    with patch("sequence_manager.SequenceManager.trigger_by_definition", side_effect=ValueError("Bad params")):
        res = client.post("/api/chain/trigger/some_flow", json={})
        assert res.status_code == 400

def test_trigger_chain_adhoc_success(client):
    payload = {
        "sequence": ["todo_service", "post_service"],
        "inputs": {
            "todo_service": {"todo_id": 1, "_mock": True},
            "post_service": {"body": "Adhoc body", "_mock": True}
        },
        "mappings": []
    }
    mock_redis = AsyncMock()
    with patch("routes.get_arq_redis", return_value=mock_redis):
        res = client.post("/api/chain/trigger", json=payload)
        assert res.status_code == 200
        assert res.json()["status"] == "PENDING"
        assert mock_redis.enqueue_job.called

def test_trigger_chain_adhoc_invalid_service(client):
    payload = {
        "sequence": ["unknown_svc"],
        "inputs": {},
        "mappings": []
    }
    res = client.post("/api/chain/trigger", json=payload)
    assert res.status_code == 404

def test_trigger_chain_adhoc_error(client):
    with patch("sequence_manager.SequenceManager.create_execution", side_effect=ValueError("Error")):
        res = client.post("/api/chain/trigger", json={"sequence": ["todo_service"], "inputs": {}, "mappings": []})
        assert res.status_code == 400

def test_get_chain_status_with_progress_and_responses(client, db_session):
    exec_record = SequenceExecution(
        id="test-status-exec-1",
        sequence=["todo_service", ["post_service"]],
        inputs={},
        mappings=[],
        status="RUNNING",
        current_step=1,
        steps_data=[
            {
                "service_name": "todo_service",
                "status": "COMPLETED",
                "input_payload": {"todo_id": 1},
                "output_response": {"success": True, "data": {"title": "Sample"}},
                "duration_ms": 100
            }
        ]
    )
    db_session.add(exec_record)
    db_session.commit()

    res = client.get("/api/chain/status/test-status-exec-1")
    assert res.status_code == 200
    data = res.json()
    assert data["total_tasks"] == 2
    assert data["completed_tasks"] == 1
    assert data["pending_tasks"] == 1
    assert "todo_service" in data["responses"]

def test_get_chain_status_not_found(client):
    res = client.get("/api/chain/status/non-existent-id")
    assert res.status_code == 404

def test_cancel_chain_route(client, db_session):
    exec_id = "test-cancel-id-1"
    execution = SequenceExecution(
        id=exec_id,
        sequence=["todo_service", "post_service"],
        inputs={},
        mappings=[],
        status="RUNNING",
        steps_data=[
            {"service_name": "todo_service", "status": "COMPLETED", "input_payload": {}, "output_response": {}},
            {"service_name": "post_service", "status": "PENDING", "input_payload": {}}
        ]
    )
    db_session.add(execution)
    db_session.commit()

    mock_redis = AsyncMock()
    with patch("routes.get_arq_redis", return_value=mock_redis), \
         patch("routes.Job.abort", new_callable=AsyncMock) as mock_abort:
        res = client.post(f"/api/chain/cancel/{exec_id}")
        assert res.status_code == 200
        assert "Cancellation" in res.json()["detail"]
        assert mock_abort.called
        assert mock_redis.enqueue_job.called

    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_id).first()
    assert reloaded.status == "FAILED"
    assert reloaded.error_message == "Cancelled by user"

def test_cancel_chain_not_found(client):
    res = client.post("/api/chain/cancel/unknown-id")
    assert res.status_code == 404

def test_cancel_chain_invalid_status(client, db_session):
    exec_id = "test-cancel-done"
    execution = SequenceExecution(
        id=exec_id,
        sequence=["todo_service"],
        inputs={},
        mappings=[],
        status="COMPLETED"
    )
    db_session.add(execution)
    db_session.commit()

    res = client.post(f"/api/chain/cancel/{exec_id}")
    assert res.status_code == 400

def test_retry_chain_resume(client, db_session):
    exec_id = "test-retry-resume-1"
    execution = SequenceExecution(
        id=exec_id,
        sequence=["todo_service", "post_service"],
        inputs={},
        mappings=[],
        status="FAILED",
        steps_data=[
            {"service_name": "todo_service", "status": "COMPLETED", "input_payload": {}, "output_response": {}},
            {"service_name": "post_service", "status": "FAILED", "input_payload": {}, "output_response": None}
        ]
    )
    db_session.add(execution)
    db_session.commit()

    mock_redis = AsyncMock()
    with patch("routes.get_arq_redis", return_value=mock_redis):
        res = client.post(f"/api/chain/retry/{exec_id}", json={"strategy": "resume"})
        assert res.status_code == 200
        assert res.json()["status"] == "PENDING"
        assert mock_redis.enqueue_job.called

def test_retry_chain_restart(client, db_session):
    exec_id = "test-retry-restart-1"
    execution = SequenceExecution(
        id=exec_id,
        sequence=["todo_service", "post_service"],
        inputs={},
        mappings=[],
        status="FAILED",
        steps_data=[
            {"service_name": "todo_service", "status": "COMPLETED", "input_payload": {}},
            {"service_name": "post_service", "status": "FAILED", "input_payload": {}}
        ]
    )
    db_session.add(execution)
    db_session.commit()

    mock_redis = AsyncMock()
    with patch("routes.get_arq_redis", return_value=mock_redis):
        res = client.post(f"/api/chain/retry/{exec_id}", json={"strategy": "restart"})
        assert res.status_code == 200
        assert res.json()["status"] == "PENDING"

def test_retry_chain_not_found(client):
    res = client.post("/api/chain/retry/unknown-id", json={"strategy": "resume"})
    assert res.status_code == 404

def test_retry_chain_invalid_status(client, db_session):
    exec_id = "test-retry-invalid-status"
    execution = SequenceExecution(
        id=exec_id,
        sequence=["todo_service"],
        inputs={},
        mappings=[],
        status="COMPLETED"
    )
    db_session.add(execution)
    db_session.commit()

    res = client.post(f"/api/chain/retry/{exec_id}", json={"strategy": "resume"})
    assert res.status_code == 400

def test_retry_chain_invalid_strategy(client, db_session):
    exec_id = "test-retry-invalid-strat"
    execution = SequenceExecution(
        id=exec_id,
        sequence=["todo_service"],
        inputs={},
        mappings=[],
        status="FAILED"
    )
    db_session.add(execution)
    db_session.commit()

    res = client.post(f"/api/chain/retry/{exec_id}", json={"strategy": "invalid_strat"})
    assert res.status_code == 400
