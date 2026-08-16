import pytest
from unittest.mock import patch, MagicMock
from app.services.registry import ServiceRegistry, register_service
from app.services.base import BaseService
from app.services.todo_service import TodoService
from app.services.post_service import PostService
from app.core.utils import get_by_path, set_by_path, SecretResolver, APIClient
from app.db.session import init_database, get_db

def test_service_registry_operations():
    assert "todo_service" in ServiceRegistry.list_services()
    assert "post_service" in ServiceRegistry.list_services()

    todo_instance = ServiceRegistry.get("todo_service")
    assert isinstance(todo_instance, TodoService)

    with pytest.raises(KeyError):
        ServiceRegistry.get("non_existent_service")

    @register_service
    class DummyService(BaseService):
        @property
        def name(self) -> str:
            return "dummy_service"

        async def _run(self, payload, client):
            return {"hello": "world"}

    assert "dummy_service" in ServiceRegistry.list_services()
    assert isinstance(ServiceRegistry.get("dummy_service"), DummyService)

@pytest.mark.asyncio
async def test_todo_service_mock_mode():
    service = ServiceRegistry.get("todo_service")
    result = await service.execute({"todo_id": 5}, mock_override=True)
    assert result["success"] is True
    assert result["data"]["id"] == 5
    assert result["data"]["source"] == "mock"
    assert result["status_code"] == 200

@pytest.mark.asyncio
async def test_todo_service_mock_error():
    service = ServiceRegistry.get("todo_service")
    with patch.object(service, "get_mock_response", side_effect=Exception("Mock crashed")):
        result = await service.execute({"todo_id": 5}, mock_override=True)
        assert result["success"] is False
        assert "Mock crashed" in result["error"]

@pytest.mark.asyncio
async def test_todo_service_real_run_missing_param():
    service = ServiceRegistry.get("todo_service")
    result = await service.execute({}, mock_override=False)
    assert result["success"] is False
    assert result["status_code"] == 400
    assert "todo_id parameter is required" in result["error"]

@pytest.mark.asyncio
async def test_todo_service_real_run_success():
    service = ServiceRegistry.get("todo_service")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "title": "Real Todo"}
    mock_resp.headers = {}
    mock_resp.text = '{"id": 1, "title": "Real Todo"}'

    with patch("requests.request", return_value=mock_resp):
        result = await service.execute({"todo_id": 1}, mock_override=False)
        assert result["success"] is True
        assert result["data"]["title"] == "Real Todo"

@pytest.mark.asyncio
async def test_todo_service_real_run_http_error():
    service = ServiceRegistry.get("todo_service")
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.headers = {}
    mock_resp.text = "Not found"

    with patch("requests.request", return_value=mock_resp):
        result = await service.execute({"todo_id": 99999}, mock_override=False)
        assert result["success"] is False
        assert result["status_code"] == 404
        assert "Third-party status: 404" in result["error"]

@pytest.mark.asyncio
async def test_post_service_mock_mode():
    service = ServiceRegistry.get("post_service")
    result = await service.execute({"title": "Test Title", "body": "Test Body"}, mock_override=True)
    assert result["success"] is True
    assert result["data"]["title"] == "Test Title"
    assert result["data"]["source"] == "mock"
    assert result["status_code"] == 200

@pytest.mark.asyncio
async def test_post_service_real_run_success():
    service = ServiceRegistry.get("post_service")
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": 101, "title": "Real Post"}
    mock_resp.headers = {}
    mock_resp.text = '{"id": 101, "title": "Real Post"}'

    with patch("requests.request", return_value=mock_resp):
        result = await service.execute({"title": "Real Post", "body": "Body"}, mock_override=False)
        assert result["success"] is True
        assert result["data"]["id"] == 101

@pytest.mark.asyncio
async def test_post_service_real_run_failure():
    service = ServiceRegistry.get("post_service")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.headers = {}
    mock_resp.text = "Server Error"

    with patch("requests.request", return_value=mock_resp):
        result = await service.execute({"title": "Fail Post"}, mock_override=False)
        assert result["success"] is False
        assert result["status_code"] == 500

@pytest.mark.asyncio
async def test_service_execution_exception_handling():
    service = ServiceRegistry.get("todo_service")
    with patch("requests.request", side_effect=Exception("Network Timeout")):
        result = await service.execute({"todo_id": 1}, mock_override=False)
        assert result["success"] is False
        assert "Network Timeout" in result["error"]
        assert result["status_code"] == 500

@pytest.mark.asyncio
async def test_service_success_conditions():
    service = ServiceRegistry.get("todo_service")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "status": "PENDING"}
    mock_resp.headers = {}
    mock_resp.text = '{"id": 1, "status": "PENDING"}'

    with patch("requests.request", return_value=mock_resp):
        custom_conditions = {
            "status_codes": [200],
            "body_rules": {
                "data.status": "ACTIVE"
            }
        }
        result = await service.execute({"todo_id": 1}, mock_override=False, success_conditions=custom_conditions)
        assert result["success"] is False
        assert "expected ACTIVE, got PENDING" in result["error"]

    with patch("requests.request", return_value=mock_resp):
        custom_conditions = {
            "status_codes": [201]
        }
        result = await service.execute({"todo_id": 1}, mock_override=False, success_conditions=custom_conditions)
        assert result["success"] is False
        assert "status code 200 not in [201]" in result["error"]

@pytest.mark.asyncio
async def test_compensate_methods():
    todo_service = ServiceRegistry.get("todo_service")
    post_service = ServiceRegistry.get("post_service")
    client = APIClient("test_service")

    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.text = "{}"
        mock_req.return_value = mock_resp

        await todo_service.compensate({"todo_id": 1}, {}, client)
        assert mock_req.called

        await post_service.compensate({}, {"data": {"id": 101}}, client)
        assert mock_req.called

def test_secret_resolver_and_api_client():
    with patch.dict("os.environ", {"TODO_SERVICE_API_KEY": "custom_secret"}):
        headers = SecretResolver.get_auth_headers("todo_service")
        assert headers["Authorization"] == "Bearer custom_secret"

    with patch.dict("os.environ", {}, clear=True):
        headers = SecretResolver.get_auth_headers("unknown")
        assert "mock-key-for-unknown" in headers["Authorization"]

    client = APIClient("test_service", execution_id="exec-123")
    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"status": "ok"}'
        mock_req.return_value = mock_resp

        assert client.get("http://test.com").status_code == 200
        assert client.post("http://test.com", json={"a": 1}).status_code == 200
        assert client.put("http://test.com", data="data").status_code == 200
        assert client.delete("http://test.com", params={"p": 1}).status_code == 200
        assert client.patch("http://test.com").status_code == 200

    with patch("requests.request", side_effect=Exception("Connection drop")):
        with pytest.raises(Exception):
            client.get("http://test.com")

def test_utils_get_and_set_by_path():
    d = {
        "user": {
            "profile": {
                "name": "Alice"
            },
            "todos": [
                {"id": 1, "title": "Todo 1"},
                {"id": 2, "title": "Todo 2"}
            ]
        }
    }
    assert get_by_path(d, "user.profile.name") == "Alice"
    assert get_by_path(d, "user.todos.1.title") == "Todo 2"
    assert get_by_path(d, "user.todos.3.id") is None
    assert get_by_path(d, "user.invalid.id") is None
    assert get_by_path(d, "") == d
    
    out = {}
    set_by_path(out, "profile.details.age", 30)
    assert out == {"profile": {"details": {"age": 30}}}
    
    set_by_path(out, "", 10)

def test_init_database_postgres():
    with patch("app.core.config.DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/office_proj"):
        with patch("app.db.session.create_engine") as mock_create_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.scalar.return_value = 0
            mock_create_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            init_database()
            assert mock_create_engine.called

def test_init_database_mysql():
    with patch("app.core.config.DATABASE_URL", "mysql+pymysql://root:10291996@localhost:3306/office_proj"):
        with patch("app.db.session.create_engine") as mock_create_engine:
            mock_conn = MagicMock()
            mock_create_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            init_database()
            mock_conn.execute.assert_called()

def test_init_database_failure():
    with patch("app.core.config.DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/office_proj"):
        with patch("app.db.session.create_engine", side_effect=Exception("Connection failed")):
            with patch("builtins.print") as mock_print:
                init_database()
                mock_print.assert_called_with("Database auto-creation bypassed/failed: Connection failed")

def test_get_db_generator():
    db_gen = get_db()
    db = next(db_gen)
    assert db is not None
    try:
        next(db_gen)
    except StopIteration:
        pass
