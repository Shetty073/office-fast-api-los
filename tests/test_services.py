import pytest
from unittest.mock import patch, MagicMock
import requests

from services.registry import ServiceRegistry, register_service
from services.todo_service import TodoService
from services.post_service import PostService
from services.base import BaseService
from utils import APIClient, get_by_path, set_by_path
from models import APILog

def test_service_registry():
    assert "todo_service" in ServiceRegistry.list_services()
    assert "post_service" in ServiceRegistry.list_services()
    
    with pytest.raises(ValueError):
        @register_service
        class DuplicateTodoService(TodoService):
            pass

    with pytest.raises(KeyError):
        ServiceRegistry.get("invalid_service")

@pytest.mark.asyncio
async def test_todo_service_mock_execution():
    service = ServiceRegistry.get("todo_service")
    response = await service.execute({"todo_id": 42}, mock_override=True)
    assert response["success"] is True
    assert response["data"]["id"] == 42
    assert response["data"]["source"] == "mock"
    assert response["status_code"] == 200

@pytest.mark.asyncio
async def test_todo_service_real_execution():
    service = ServiceRegistry.get("todo_service")
    
    mock_requests_response = MagicMock()
    mock_requests_response.status_code = 200
    mock_requests_response.json.return_value = {
        "userId": 1,
        "id": 1,
        "title": "delectus aut autem",
        "completed": False
    }
    
    with patch("requests.request", return_value=mock_requests_response):
        response = await service.execute({"todo_id": 1}, mock_override=False)
        assert response["success"] is True
        assert response["data"]["id"] == 1
        assert response["data"]["title"] == "delectus aut autem"
        assert response["status_code"] == 200

@pytest.mark.asyncio
async def test_todo_service_real_failure():
    service = ServiceRegistry.get("todo_service")
    
    mock_requests_response = MagicMock()
    mock_requests_response.status_code = 404
    
    with patch("requests.request", return_value=mock_requests_response):
        response = await service.execute({"todo_id": 999}, mock_override=False)
        assert response["success"] is False
        assert response["data"] is None
        assert "Failed" in response["error"]
        assert response["status_code"] == 404

@pytest.mark.asyncio
async def test_todo_service_missing_id():
    service = ServiceRegistry.get("todo_service")
    response = await service.execute({}, mock_override=False)
    assert response["success"] is False
    assert response["status_code"] == 400
    assert "required" in response["error"]

@pytest.mark.asyncio
async def test_post_service_mock_execution():
    service = ServiceRegistry.get("post_service")
    response = await service.execute({"title": "Test Post", "body": "Test Body", "userId": 10})
    assert response["success"] is True
    assert response["data"]["title"] == "Test Post"
    assert response["data"]["source"] == "mock"

@pytest.mark.asyncio
async def test_post_service_real_execution():
    service = ServiceRegistry.get("post_service")
    
    mock_requests_response = MagicMock()
    mock_requests_response.status_code = 201
    mock_requests_response.json.return_value = {
        "id": 101,
        "title": "Real Title",
        "body": "Real Body",
        "userId": 5
    }
    
    with patch("requests.request", return_value=mock_requests_response):
        response = await service.execute(
            {"title": "Real Title", "body": "Real Body", "userId": 5},
            mock_override=False
        )
        assert response["success"] is True
        assert response["data"]["id"] == 101
        assert response["data"]["title"] == "Real Title"
        assert response["status_code"] == 201

@pytest.mark.asyncio
async def test_post_service_real_failure():
    service = ServiceRegistry.get("post_service")
    
    mock_requests_response = MagicMock()
    mock_requests_response.status_code = 500
    
    with patch("requests.request", return_value=mock_requests_response):
        response = await service.execute(
            {"title": "Real Title", "body": "Real Body", "userId": 5},
            mock_override=False
        )
        assert response["success"] is False
        assert response["status_code"] == 500
        assert "Failed" in response["error"]

@pytest.mark.asyncio
async def test_post_service_missing_params():
    service = ServiceRegistry.get("post_service")
    response = await service.execute({"body": "Only Body"}, mock_override=False)
    assert response["success"] is False
    assert response["status_code"] == 400
    assert "required" in response["error"]

@pytest.mark.asyncio
async def test_base_service_generic_dict_wrap():
    class DummyService(BaseService):
        @property
        def name(self) -> str:
            return "dummy_service"
        async def _run(self, payload: dict, client: APIClient):
            return {"payload_received": payload}

    dummy = DummyService()
    res = await dummy.execute({"foo": "bar"}, mock_override=False)
    assert res["success"] is True
    assert res["data"] == {"payload_received": {"foo": "bar"}}
    assert res["status_code"] == 200

@pytest.mark.asyncio
async def test_base_service_exception_safety():
    class ExceptionService(BaseService):
        @property
        def name(self) -> str:
            return "exception_service"
        async def _run(self, payload: dict, client: APIClient):
            raise ValueError("Something exploded")

    svc = ExceptionService()
    res = await svc.execute({}, mock_override=False)
    assert res["success"] is False
    assert res["status_code"] == 500
    assert "Something exploded" in res["error"]

@pytest.mark.asyncio
async def test_base_service_mock_exception_safety():
    class MockExceptionService(BaseService):
        @property
        def name(self) -> str:
            return "mock_exception_service"
        @property
        def mock_enabled(self) -> bool:
            return True
        def get_mock_response(self, payload: dict):
            raise RuntimeError("Mock error")
        async def _run(self, payload: dict, client: APIClient):
            return {}

    svc = MockExceptionService()
    assert svc.name == "mock_exception_service"
    assert await svc._run({}, None) == {}
    res = await svc.execute({})
    assert res["success"] is False
    assert res["status_code"] == 500
    assert "Mock error" in res["error"]

def test_api_client_logging(db_session):
    client = APIClient(service_name="test_client_svc", execution_id="exec-123")
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.text = "Hello World"
    
    with patch("requests.request", return_value=mock_resp):
        res = client.get("https://google.com", headers={"X-Test": "yes"}, params={"q": "fastapi"})
        assert res.status_code == 200

    log = db_session.query(APILog).filter(APILog.service_name == "test_client_svc").first()
    assert log is not None
    assert log.execution_id == "exec-123"
    assert log.method == "GET"
    assert log.url == "https://google.com"
    assert log.response_status == 200
    assert "fastapi" in log.request_body
    assert log.response_body == "Hello World"
    assert log.duration_ms >= 0

def test_api_client_connection_error(db_session):
    client = APIClient(service_name="test_client_err")
    
    with patch("requests.request", side_effect=requests.exceptions.ConnectionError("Failed connection")):
        with pytest.raises(requests.exceptions.ConnectionError):
            client.post("https://doesnotexist.void", json={"data": 123})

    log = db_session.query(APILog).filter(APILog.service_name == "test_client_err").first()
    assert log is not None
    assert log.response_status == 0
    assert "Connection Exception" in log.response_body
    assert "Failed connection" in log.response_body

def test_utils_nested_paths():
    d = {"user": {"todos": [{"id": 10}, {"id": 20}]}}
    assert get_by_path(d, "user.todos.1.id") == 20
    assert get_by_path(d, "user.todos.3.id") is None
    assert get_by_path(d, "user.invalid.id") is None
    assert get_by_path(d, "") == d
    
    out = {}
    set_by_path(out, "profile.details.age", 30)
    assert out == {"profile": {"details": {"age": 30}}}
    
    set_by_path(out, "", 10)

def test_init_database_mysql():
    import config
    from database import init_database
    with patch("config.DATABASE_URL", "mysql+pymysql://root:10291996@localhost:3306/office_proj"):
        with patch("database.create_engine") as mock_create_engine:
            mock_conn = MagicMock()
            mock_create_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            
            init_database()
            
            mock_create_engine.assert_called_with(config.MYSQL_BASE_URL)
            mock_conn.execute.assert_called()

def test_init_database_mysql_failure():
    from database import init_database
    with patch("config.DATABASE_URL", "mysql+pymysql://root:10291996@localhost:3306/office_proj"):
        with patch("database.create_engine", side_effect=Exception("Connection failed")):
            with patch("builtins.print") as mock_print:
                init_database()
                mock_print.assert_called_with("Database auto-creation bypassed/failed: Connection failed")

def test_get_db_generator():
    from database import get_db
    db_gen = get_db()
    db = next(db_gen)
    assert db is not None
    try:
        next(db_gen)
    except StopIteration:
        pass

@pytest.mark.asyncio
async def test_base_service_abstract_coverage():
    class MinimalService(BaseService):
        @property
        def name(self) -> str:
            return super().name
        async def _run(self, payload, client):
            await super()._run(payload, client)

    min_svc = MinimalService()
    
    with pytest.raises(NotImplementedError):
        min_svc.get_mock_response({})

    res_mock = await min_svc.execute({}, mock_override=True)
    assert res_mock["success"] is False
    assert "Mock error" in res_mock["error"]

    with patch("utils.APIClient.request") as mock_req:
        res_real = await min_svc.execute({}, mock_override=False)
        assert res_real["success"] is True
        assert res_real["data"] is None

def test_api_client_verbs():
    client = APIClient(service_name="test_verbs")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.text = "OK"
    with patch("requests.request", return_value=mock_resp) as mock_req:
        client.put("https://test.url/put")
        mock_req.assert_called_with(
            "PUT",
            "https://test.url/put",
            timeout=10.0,
            headers={"Authorization": "Bearer mock-key-for-test_verbs"}
        )
        
        client.delete("https://test.url/delete")
        mock_req.assert_called_with(
            "DELETE",
            "https://test.url/delete",
            timeout=10.0,
            headers={"Authorization": "Bearer mock-key-for-test_verbs"}
        )
        
        client.patch("https://test.url/patch")
        mock_req.assert_called_with(
            "PATCH",
            "https://test.url/patch",
            timeout=10.0,
            headers={"Authorization": "Bearer mock-key-for-test_verbs"}
        )

        client.post("https://test.url/post", data="raw-body")
        mock_req.assert_called_with(
            "POST",
            "https://test.url/post",
            data="raw-body",
            timeout=10.0,
            headers={"Authorization": "Bearer mock-key-for-test_verbs"}
        )

def test_api_client_logger_failure():
    with patch("utils.SessionLocal", side_effect=RuntimeError("Logging DB crashed")):
        client = APIClient(service_name="test_logging_failure")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.text = "OK"
        with patch("requests.request", return_value=mock_resp):
            with patch("builtins.print") as mock_print:
                client.get("https://test.url")
                mock_print.assert_called_with("API Logger Exception: Logging DB crashed")

def test_conftest_setup_db_cleanup_error():
    from tests.conftest import setup_db_impl
    generator = setup_db_impl()
    next(generator)
    with patch("os.path.exists", return_value=True):
        with patch("os.remove", side_effect=OSError("Permission denied")):
            try:
                next(generator)
            except StopIteration:
                pass

