import pytest
import httpx
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from models import SequenceExecution
from orchestrator import Orchestrator, evaluate_condition
from worker import run_sequence_task, rollback_sequence_task, startup, shutdown
from utils import get_by_path, set_by_path, SecretResolver, APIClient
from database import init_database, get_db

def test_evaluate_condition():
    responses = {"todo_service": {"data": {"completed": True, "count": 5}}}
    context = {"is_vip": True}
    assert evaluate_condition("responses.todo_service.data.completed == True", responses, context) is True
    assert evaluate_condition("responses.todo_service.data.count > 10", responses, context) is False
    assert evaluate_condition("context.is_vip == True", responses, context) is True
    assert evaluate_condition("invalid_expression ++++", responses, context) is False
    assert evaluate_condition("", responses, context) is True

def test_utils_get_and_set_by_path():
    data = {"a": {"b": [{"c": "target"}]}}
    assert get_by_path(data, "a.b.0.c") == "target"
    assert get_by_path(data, "a.b.99.c") is None
    assert get_by_path(data, "a.invalid.c") is None
    assert get_by_path(data, "") == data

    target = {}
    set_by_path(target, "deep.nested.val", 123)
    assert target["deep"]["nested"]["val"] == 123
    set_by_path(target, "", 456)

def test_secret_resolver():
    with patch.dict("os.environ", {"TODO_SERVICE_API_KEY": "secret_key"}):
        headers = SecretResolver.get_auth_headers("todo_service")
        assert headers["Authorization"] == "Bearer secret_key"

    with patch.dict("os.environ", {}, clear=True):
        headers = SecretResolver.get_auth_headers("unknown")
        assert "Bearer mock-key-for-unknown" in headers["Authorization"]

def test_api_client():
    client = APIClient("todo_service", execution_id="exec-1")
    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"ok": true}'
        mock_req.return_value = mock_resp

        assert client.get("http://example.com").status_code == 200
        assert client.post("http://example.com", json={"k": "v"}).status_code == 200
        assert client.put("http://example.com").status_code == 200
        assert client.delete("http://example.com").status_code == 200
        assert client.patch("http://example.com").status_code == 200

def test_init_database_variants():
    with patch("config.DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/office_proj"):
        with patch("database.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.scalar.return_value = 0
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            init_database()
            assert mock_engine.called

    with patch("config.DATABASE_URL", "mysql+pymysql://root:pass@localhost:3306/office_proj"):
        with patch("database.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            init_database()
            assert mock_engine.called

    with patch("config.DATABASE_URL", "sqlite:///test.db"):
        init_database()

    db_gen = get_db()
    db = next(db_gen)
    assert db is not None
    try:
        next(db_gen)
    except StopIteration:
        pass

def test_model_task_counting(db_session):
    execution = SequenceExecution(
        id="test-model-prop-1",
        sequence=["todo_service", ["post_service", "kyc_service"]],
        inputs={},
        mappings=[],
        status="RUNNING",
        steps_data=[
            {"service_name": "todo_service", "status": "COMPLETED", "output_response": {"data": "ok"}},
            {"service_name": "post_service", "status": "PENDING", "output_response": None}
        ]
    )
    assert execution.total_tasks == 3
    assert execution.completed_tasks == 1
    assert execution.pending_tasks == 2
    assert "todo_service" in execution.responses

@pytest.mark.asyncio
async def test_worker_lifecycle():
    await startup({})
    await shutdown({})

@pytest.mark.asyncio
async def test_worker_tasks(db_session, db_session_factory):
    exec_id = "test-worker-run-task-1"
    exec_obj = SequenceExecution(
        id=exec_id,
        sequence=["todo_service"],
        inputs={"todo_service": {"_mock": True}},
        mappings=[],
        status="PENDING",
        current_step=0,
        steps_data=[]
    )
    db_session.add(exec_obj)
    db_session.commit()

    async def mock_handler(request: httpx.Request):
        return httpx.Response(200, json={"success": True, "data": {"id": 1}})

    transport = httpx.MockTransport(mock_handler)
    with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)), \
         patch("worker.get_db", db_session_factory):
        await run_sequence_task({}, exec_id)

    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_id).first()
    assert reloaded.status == "COMPLETED"

    # Test rollback task
    await rollback_sequence_task({}, exec_id, [("todo_service", {}, {})])

@pytest.mark.asyncio
async def test_orchestrator_parallel_and_transformations(db_session, db_session_factory):
    exec_id = "test-parallel-transform-1"
    exec_obj = SequenceExecution(
        id=exec_id,
        sequence=[
            "todo_service",
            ["post_service"]
        ],
        inputs={
            "todo_service": {},
            "post_service": {}
        },
        trigger_payload={"user_code": "100", "status_tag": "vip"},
        mappings=[
            {"from_service": "trigger_payload", "from_field": "user_code", "to_service": "todo_service", "to_field": "todo_id", "transform": "to_int"},
            {"from_service": "trigger_payload", "from_field": "status_tag", "to_service": "todo_service", "to_field": "tag", "transform": "upper"},
            {"from_service": "context", "from_field": "global_id", "to_service": "post_service", "to_field": "ctx_id", "transform": "to_str"},
            {"from_service": "todo_service", "from_field": "title", "to_service": "post_service", "to_field": "title", "transform": "lower"}
        ],
        context={"global_id": 999},
        conditions={"post_service": "responses.todo_service.data.completed == True"},
        status="PENDING",
        current_step=0,
        steps_data=[]
    )
    db_session.add(exec_obj)
    db_session.commit()

    async def mock_handler(request: httpx.Request):
        url = str(request.url)
        import json
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        if "compensate" in url:
            return httpx.Response(200, json={"status": "compensated"})
        elif "todo_service" in url:
            assert body.get("todo_id") == 100
            assert body.get("tag") == "VIP"
            return httpx.Response(200, json={
                "success": True,
                "data": {"title": "HELLO TODO", "completed": True},
                "context_updates": {"step1_done": True}
            })
        elif "post_service" in url:
            assert body.get("title") == "hello todo"
            assert body.get("ctx_id") == "999"
            return httpx.Response(200, json={"success": True, "data": {"id": 1}})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        await Orchestrator.run_sequence(exec_id, db_session_factory, http_client=mock_client)

    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_id).first()
    assert reloaded.status == "COMPLETED"
    assert reloaded.context.get("step1_done") is True

@pytest.mark.asyncio
async def test_orchestrator_skipped_step(db_session, db_session_factory):
    exec_id = "test-skip-step-1"
    exec_obj = SequenceExecution(
        id=exec_id,
        sequence=["todo_service", "post_service"],
        inputs={},
        mappings=[],
        conditions={"post_service": "False"},
        status="PENDING",
        current_step=0,
        steps_data=[]
    )
    db_session.add(exec_obj)
    db_session.commit()

    async def mock_handler(request: httpx.Request):
        return httpx.Response(200, json={"success": True, "data": {"id": 1}})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        await Orchestrator.run_sequence(exec_id, db_session_factory, http_client=mock_client)

    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_id).first()
    assert reloaded.status == "COMPLETED"
    assert reloaded.steps_data[1]["status"] == "SKIPPED"
