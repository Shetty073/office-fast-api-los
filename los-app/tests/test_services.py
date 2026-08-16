import pytest
from unittest.mock import patch, MagicMock
from app.services.registry import ServiceRegistry, register_service
from app.services.base import BaseService
from app.services.create_post_service import CreatePostService
from app.services.get_post_service import GetPostService
from app.services.update_post_service import UpdatePostService
from app.core.utils import get_by_path, set_by_path, SecretResolver, APIClient
from app.db.session import init_database, get_db

def test_service_registry_operations():
    assert "create_post_service" in ServiceRegistry.list_services()
    assert "get_post_service" in ServiceRegistry.list_services()
    assert "update_post_service" in ServiceRegistry.list_services()

    create_inst = ServiceRegistry.get("create_post_service")
    assert isinstance(create_inst, CreatePostService)

    with pytest.raises(KeyError):
        ServiceRegistry.get("non_existent_service")

    @register_service
    class DummyService(BaseService):
        @property
        def name(self) -> str:
            return "dummy_test_service"

        async def _run(self, payload, client):
            return {"hello": "world"}

    assert "dummy_test_service" in ServiceRegistry.list_services()
    assert isinstance(ServiceRegistry.get("dummy_test_service"), DummyService)

@pytest.mark.asyncio
async def test_create_post_service_mock_and_run():
    service = ServiceRegistry.get("create_post_service")
    # Mock mode
    mock_res = await service.execute({"title": "Test Title", "body": "Test Body"}, mock_override=True)
    assert mock_res["success"] is True
    assert mock_res["data"]["id"] == 101
    assert mock_res["data"]["source"] == "mock"

    # Real run success
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": 101, "title": "Test Title"}
    with patch("app.core.utils.APIClient.post", return_value=mock_resp):
        res = await service.execute({"title": "Test Title"}, mock_override=False)
        assert res["success"] is True
        assert res["data"]["id"] == 101

    # Real run failure
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 500
    with patch("app.core.utils.APIClient.post", return_value=mock_resp_fail):
        res_fail = await service.execute({"title": "Test Title"}, mock_override=False)
        assert res_fail["success"] is False
        assert res_fail["status_code"] == 500

    # Compensate
    with patch("app.core.utils.APIClient.delete") as mock_del:
        mock_cli = MagicMock()
        await service.compensate({}, {"data": {"id": 101}}, client=mock_cli)
        assert mock_cli.delete.called

@pytest.mark.asyncio
async def test_get_post_service_mock_and_run():
    service = ServiceRegistry.get("get_post_service")
    # Mock mode
    mock_res = await service.execute({"post_id": 2}, mock_override=True)
    assert mock_res["success"] is True
    assert mock_res["data"]["id"] == 2

    # Missing param
    res_missing = await service.execute({}, mock_override=False)
    assert res_missing["success"] is False
    assert res_missing["status_code"] == 400

    # Real run success
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 2, "title": "Real Post"}
    with patch("app.core.utils.APIClient.get", return_value=mock_resp):
        res = await service.execute({"post_id": 2}, mock_override=False)
        assert res["success"] is True
        assert res["data"]["title"] == "Real Post"

    # Real run failure
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 404
    with patch("app.core.utils.APIClient.get", return_value=mock_resp_fail):
        res_fail = await service.execute({"post_id": 999}, mock_override=False)
        assert res_fail["success"] is False
        assert res_fail["status_code"] == 404

@pytest.mark.asyncio
async def test_update_post_service_mock_and_run():
    service = ServiceRegistry.get("update_post_service")
    # Mock mode
    mock_res = await service.execute({"id": 1, "title": "Updated Title"}, mock_override=True)
    assert mock_res["success"] is True
    assert mock_res["data"]["title"] == "Updated Title"

    # Real run success
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "title": "Updated Title"}
    with patch("app.core.utils.APIClient.put", return_value=mock_resp):
        res = await service.execute({"id": 1, "title": "Updated Title"}, mock_override=False)
        assert res["success"] is True
        assert res["data"]["title"] == "Updated Title"

    # Real run failure
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 400
    with patch("app.core.utils.APIClient.put", return_value=mock_resp_fail):
        res_fail = await service.execute({"id": 1}, mock_override=False)
        assert res_fail["success"] is False
        assert res_fail["status_code"] == 400

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
    with patch("app.core.config.DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/office_proj"):
        with patch("app.db.session.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.scalar.return_value = 0
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            init_database()
            assert mock_conn.execute.called

    with patch("app.core.config.DATABASE_URL", "mysql+pymysql://root:pass@localhost:3306/db"):
        with patch("app.db.session.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            init_database()
            assert mock_conn.execute.called
