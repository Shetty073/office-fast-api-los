import pytest
import httpx
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from models import SequenceExecution
from orchestrator import Orchestrator
from worker import run_sequence_task, rollback_sequence_task

@pytest.mark.asyncio
async def test_generic_orchestrator_run_sequence(db_session, db_session_factory):
    # Setup test sequence execution record
    exec_id = "test-generic-exec-1"
    exec_obj = SequenceExecution(
        id=exec_id,
        sequence_name="test_recipe",
        sequence=["todo_service", "post_service"],
        inputs={
            "todo_service": {"todo_id": 10},
            "post_service": {"body": "Initial static body"}
        },
        trigger_payload={"user_id_param": 99},
        mappings=[
            {
                "from_service": "trigger_payload",
                "from_field": "user_id_param",
                "to_service": "todo_service",
                "to_field": "userId"
            },
            {
                "from_service": "todo_service",
                "from_field": "title",
                "to_service": "post_service",
                "to_field": "title"
            }
        ],
        status="PENDING",
        current_step=0,
        steps_data=[]
    )
    db_session.add(exec_obj)
    db_session.commit()

    # Mock HTTP transport handler for httpx
    async def mock_handler(request: httpx.Request):
        url = str(request.url)
        assert request.headers.get("X-Execution-Id") == exec_id

        import json
        body = json.loads(request.content.decode("utf-8")) if request.content else {}

        if "todo_service" in url:
            assert body.get("userId") == 99
            return httpx.Response(200, json={
                "success": True,
                "data": {"id": 10, "title": "Todo from FastAPI", "userId": 99}
            })
        elif "post_service" in url:
            assert body.get("title") == "Todo from FastAPI"
            return httpx.Response(200, json={
                "success": True,
                "data": {"id": 201, "title": body.get("title")}
            })
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        await Orchestrator.run_sequence(exec_id, db_session_factory, http_client=mock_client)

    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_id).first()
    assert reloaded.status == "COMPLETED"
    assert reloaded.current_step == 2
    assert len(reloaded.steps_data) == 2
    assert reloaded.steps_data[0]["status"] == "COMPLETED"
    assert reloaded.steps_data[1]["status"] == "COMPLETED"
    assert reloaded.steps_data[1]["input_payload"]["title"] == "Todo from FastAPI"

@pytest.mark.asyncio
async def test_generic_saga_rollback_on_failure(db_session, db_session_factory):
    exec_id = "test-generic-saga-2"
    exec_obj = SequenceExecution(
        id=exec_id,
        sequence=["todo_service", "post_service"],
        inputs={"todo_service": {"todo_id": 1}, "post_service": {}},
        mappings=[],
        status="PENDING",
        current_step=0,
        steps_data=[]
    )
    db_session.add(exec_obj)
    db_session.commit()

    compensated_called = []

    async def mock_handler(request: httpx.Request):
        url = str(request.url)
        if "todo_service/compensate" in url:
            compensated_called.append("todo_service")
            return httpx.Response(200, json={"status": "compensated"})
        elif "todo_service" in url:
            return httpx.Response(200, json={"success": True, "data": {"id": 1}})
        elif "post_service" in url:
            return httpx.Response(500, json={"error": "Downstream server down"})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        await Orchestrator.run_sequence(exec_id, db_session_factory, http_client=mock_client)

    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_id).first()
    assert reloaded.status == "FAILED"
    assert "Downstream server down" in reloaded.error_message
    assert "todo_service" in compensated_called
