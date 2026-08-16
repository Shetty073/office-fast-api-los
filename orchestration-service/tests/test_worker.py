import pytest
import httpx
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from models import SequenceExecution
from orchestrator import Orchestrator, evaluate_condition, evaluate_success_criteria, TokenManager
from worker import run_sequence_task, rollback_sequence_task, startup, shutdown
from utils import get_by_path, set_by_path, SecretResolver, APIClient
from database import init_database, get_db

def test_evaluate_condition():
    responses = {"create_post_service": {"data": {"completed": True, "count": 5}}}
    context = {"is_vip": True}
    assert evaluate_condition("responses.create_post_service.data.completed == True", responses, context) is True
    assert evaluate_condition("responses.create_post_service.data.count > 10", responses, context) is False
    assert evaluate_condition("context.is_vip == True", responses, context) is True
    assert evaluate_condition("invalid_expression ++++", responses, context) is False
    assert evaluate_condition("", responses, context) is True

def test_evaluate_success_criteria():
    resp_success = {"status_code": 200, "success": True, "data": {"status": "APPROVED", "score": 750, "is_blacklisted": False}}
    
    # 1. Default
    ok, err = evaluate_success_criteria(resp_success, None)
    assert ok is True
    assert err is None

    # 2. Equals & Not Equals & Types
    criteria = {
        "expected_status_code": 200,
        "equals": {"data.status": "APPROVED"},
        "not_equals": {"data.is_blacklisted": True},
        "types": {"data.score": "int"}
    }
    ok, err = evaluate_success_criteria(resp_success, criteria)
    assert ok is True

    # 3. Failed Criteria
    fail_criteria = {"equals": {"data.status": "REJECTED"}}
    ok, err = evaluate_success_criteria(resp_success, fail_criteria)
    assert ok is False
    assert "Field 'data.status' expected 'REJECTED'" in err

    # 4. Failed Type
    fail_type = {"types": {"data.score": "str"}}
    ok, err = evaluate_success_criteria(resp_success, fail_type)
    assert ok is False

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
    with patch.dict("os.environ", {"CREATE_POST_SERVICE_API_KEY": "secret_key"}):
        headers = SecretResolver.get_auth_headers("create_post_service")
        assert headers["Authorization"] == "Bearer secret_key"

    with patch.dict("os.environ", {}, clear=True):
        headers = SecretResolver.get_auth_headers("unknown")
        assert "Bearer mock-key-for-unknown" in headers["Authorization"]

def test_api_client():
    client = APIClient("create_post_service", execution_id="exec-1")
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
            assert mock_conn.execute.called

    with patch("config.DATABASE_URL", "mysql+pymysql://root:pass@localhost:3306/db"):
        with patch("database.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            init_database()
            assert mock_conn.execute.called

@pytest.mark.asyncio
async def test_worker_tasks(db_session):
    exec_id = "test-worker-exec-1"
    exec_obj = SequenceExecution(
        id=exec_id,
        sequence=["create_post_service"],
        inputs={"create_post_service": {"title": "Post 1"}},
        mappings=[],
        status="PENDING",
        current_step=0,
        steps_data=[]
    )
    db_session.add(exec_obj)
    db_session.commit()

    with patch("orchestrator.Orchestrator.run_sequence", new_callable=AsyncMock) as mock_run:
        await run_sequence_task({}, exec_id)
        mock_run.assert_called_once()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200, json={"status": "compensated"})
        await rollback_sequence_task({}, exec_id, [("create_post_service", {}, {})])
        assert mock_post.called

@pytest.mark.asyncio
async def test_worker_lifecycle():
    await startup({})
    await shutdown({})

@pytest.mark.asyncio
async def test_token_manager():
    async def mock_handler(request: httpx.Request):
        if "login" in str(request.url):
            return httpx.Response(200, json={"access_token": "mock-jwt-token", "expires_in_seconds": 3600})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        with patch.object(TokenManager, "get_redis", new_callable=AsyncMock) as mock_redis_getter:
            mock_redis = AsyncMock()
            mock_redis.get.return_value = None
            mock_redis_getter.return_value = mock_redis
            token = await TokenManager.get_bearer_token(mock_client)
            assert token == "mock-jwt-token"
            mock_redis.set.assert_called_once()

@pytest.mark.asyncio
async def test_orchestrator_full_workflow(db_session, db_session_factory):
    exec_id = "test-orch-flow-1"
    exec_obj = SequenceExecution(
        id=exec_id,
        sequence=[
            "create_post_service",
            ["get_post_service"]
        ],
        inputs={
            "create_post_service": {},
            "get_post_service": {}
        },
        trigger_payload={"user_code": "100", "status_tag": "vip"},
        mappings=[
            {"from_service": "trigger_payload", "from_field": "user_code", "to_service": "create_post_service", "to_field": "user_id", "transform": "to_int"},
            {"from_service": "trigger_payload", "from_field": "status_tag", "to_service": "create_post_service", "to_field": "tag", "transform": "upper"},
            {"from_service": "context", "from_field": "global_id", "to_service": "get_post_service", "to_field": "ctx_id", "transform": "to_str"},
            {"from_service": "create_post_service", "from_field": "id", "to_service": "get_post_service", "to_field": "post_id"}
        ],
        context={"global_id": 999},
        conditions={"get_post_service": "responses.create_post_service.data.id == 101"},
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
        if "login" in url:
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in_seconds": 3600})
        elif "compensate" in url:
            return httpx.Response(200, json={"status": "compensated"})
        elif "create_post_service" in url:
            assert body.get("user_id") == 100
            assert body.get("tag") == "VIP"
            return httpx.Response(200, json={
                "success": True,
                "data": {"id": 101, "title": "HELLO POST"},
                "context_updates": {"step1_done": True}
            })
        elif "get_post_service" in url:
            assert body.get("post_id") == 101
            assert body.get("ctx_id") == "999"
            return httpx.Response(200, json={"success": True, "data": {"id": 101, "title": "HELLO POST"}})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        with patch.object(TokenManager, "get_bearer_token", new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "mock-bearer-token"
            await Orchestrator.run_sequence(exec_id, db_session_factory, http_client=mock_client)

    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_id).first()
    assert reloaded.status == "COMPLETED"
    assert reloaded.context.get("step1_done") is True

@pytest.mark.asyncio
async def test_orchestrator_skip_conditions_list(db_session, db_session_factory):
    exec_id = "test-skip-conditions-list-1"
    exec_obj = SequenceExecution(
        id=exec_id,
        sequence=["create_post_service", "update_post_service"],
        inputs={},
        mappings=[],
        skip_conditions=[
            {
                "service": "update_post_service",
                "condition": "responses.create_post_service.data.id == 101",
                "reason": "Skip update when post ID is 101"
            }
        ],
        status="PENDING",
        current_step=0,
        steps_data=[]
    )
    db_session.add(exec_obj)
    db_session.commit()

    async def mock_handler(request: httpx.Request):
        if "login" in str(request.url):
            return httpx.Response(200, json={"access_token": "mock-token"})
        elif "create_post_service" in str(request.url):
            return httpx.Response(200, json={"success": True, "data": {"id": 101}})
        return httpx.Response(200, json={"success": True, "data": {"id": 1}})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        with patch.object(TokenManager, "get_bearer_token", new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "mock-bearer-token"
            await Orchestrator.run_sequence(exec_id, db_session_factory, http_client=mock_client)

    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_id).first()
    assert reloaded.status == "COMPLETED"
    assert reloaded.steps_data[1]["status"] == "SKIPPED"
    assert "Skip update when post ID is 101" in reloaded.steps_data[1]["error_message"]
