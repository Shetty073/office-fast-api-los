import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session
from models import SequenceExecution
from orchestrator import Orchestrator
from services.registry import ServiceRegistry, register_service
from services.base import BaseService
from utils import APIClient

@pytest.fixture
def db_session_factory(db_session):
    def _factory():
        yield db_session
    return _factory

def test_create_execution_validation(db_session):
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service", "post_service"],
        inputs={},
        mappings=[]
    )
    assert exec_obj.id is not None
    assert exec_obj.status == "PENDING"
    
    with pytest.raises(KeyError):
        Orchestrator.create_execution(
            db=db_session,
            sequence=["todo_service", "invalid_service_name"],
            inputs={},
            mappings=[]
        )

@pytest.mark.asyncio
async def test_successful_orchestration_run(db_session, db_session_factory):
    inputs = {
        "todo_service": {"todo_id": 5, "_mock": True},
        "post_service": {"body": "My Custom Body", "_mock": True}
    }
    
    mappings = [
        {
            "from_service": "todo_service",
            "from_field": "title",
            "to_service": "post_service",
            "to_field": "title"
        },
        {
            "from_service": "todo_service",
            "from_field": "userId",
            "to_service": "post_service",
            "to_field": "userId"
        }
    ]
    
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service", "post_service"],
        inputs=inputs,
        mappings=mappings
    )
    
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    
    assert reloaded.status == "COMPLETED"
    assert reloaded.current_step == 2
    assert len(reloaded.steps_data) == 2
    
    todo_step = reloaded.steps_data[0]
    post_step = reloaded.steps_data[1]
    
    assert todo_step["service_name"] == "todo_service"
    assert todo_step["status"] == "COMPLETED"
    assert todo_step["output_response"]["data"]["id"] == 5
    assert todo_step["output_response"]["data"]["title"] == "Mocked Todo Title 5"
    assert todo_step["output_response"]["data"]["userId"] == 99
    
    assert post_step["service_name"] == "post_service"
    assert post_step["status"] == "COMPLETED"
    
    assert post_step["input_payload"]["title"] == "Mocked Todo Title 5"
    assert post_step["input_payload"]["userId"] == 99
    assert post_step["input_payload"]["body"] == "My Custom Body"

@pytest.mark.asyncio
async def test_critical_step_failure(db_session, db_session_factory):
    @register_service
    class CriticalFailService(BaseService):
        @property
        def name(self) -> str:
            return "crit_fail_service"
        @property
        def max_retries(self) -> int:
            return 0
        async def _run(self, payload: dict, client: APIClient):
            return {"success": False, "error": "Critical api error", "status_code": 500}

    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["crit_fail_service", "todo_service"],
        inputs={"todo_service": {"todo_id": 1, "_mock": True}},
        mappings=[]
    )
    
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    
    assert reloaded.status == "FAILED"
    assert "Failed at critical step" in reloaded.error_message
    assert len(reloaded.steps_data) == 1
    assert reloaded.steps_data[0]["status"] == "FAILED"
    assert reloaded.steps_data[0]["error_message"] == "Critical api error"

@pytest.mark.asyncio
async def test_non_critical_step_failure(db_session, db_session_factory):
    @register_service
    class NonCriticalFailService(BaseService):
        @property
        def name(self) -> str:
            return "non_crit_fail_service"
        @property
        def max_retries(self) -> int:
            return 0
        @property
        def is_critical(self) -> bool:
            return False
        async def _run(self, payload: dict, client: APIClient):
            return {"success": False, "error": "Non-critical error", "status_code": 400}

    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["non_crit_fail_service", "todo_service"],
        inputs={"todo_service": {"todo_id": 1, "_mock": True}},
        mappings=[]
    )
    
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    
    assert reloaded.status == "PARTIAL_SUCCESS"
    assert len(reloaded.steps_data) == 2
    assert reloaded.steps_data[0]["status"] == "FAILED"
    assert reloaded.steps_data[0]["error_message"] == "Non-critical error"
    assert reloaded.steps_data[1]["status"] == "COMPLETED"

@pytest.mark.asyncio
async def test_retry_loop_behavior(db_session, db_session_factory):
    call_count = 0
    @register_service
    class RetryService(BaseService):
        @property
        def name(self) -> str:
            return "retry_service"
        @property
        def max_retries(self) -> int:
            return 2
        async def _run(self, payload: dict, client: APIClient):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Network issue")

    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["retry_service"],
        inputs={},
        mappings=[]
    )
    
    with patch("asyncio.sleep", return_value=None):
        await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
        
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    
    assert reloaded.status == "FAILED"
    assert call_count == 3
    assert reloaded.steps_data[0]["retry_count"] == 2

@pytest.mark.asyncio
async def test_orchestrator_not_found(db_session_factory):
    with patch("orchestrator.logger.error") as mock_log_err:
        await Orchestrator.run_sequence("non-existent-uuid-1234", db_session_factory)
        mock_log_err.assert_called_with("Execution non-existent-uuid-1234 not found.")

def test_create_execution_custom_mapping_type(db_session):
    mappings = [[("from_service", "todo_service"), ("from_field", "title"), ("to_service", "post_service"), ("to_field", "title")]]
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service", "post_service"],
        inputs={},
        mappings=mappings
    )
    assert exec_obj.mappings[0]["from_service"] == "todo_service"

@pytest.mark.asyncio
async def test_orchestrator_service_execute_throws_exception(db_session, db_session_factory):
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service"],
        inputs={},
        mappings=[]
    )
    with patch("services.todo_service.TodoService.execute", side_effect=RuntimeError("Extreme failure")):
        await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
        
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    assert reloaded.status == "FAILED"
    assert "Extreme failure" in reloaded.error_message

@pytest.mark.asyncio
async def test_orchestrator_internal_failure_safety(db_session, db_session_factory):
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service"],
        inputs={},
        mappings=[]
    )
    db = next(db_session_factory())
    with patch.object(db, "query", side_effect=RuntimeError("Database offline")):
        await Orchestrator.run_sequence(exec_obj.id, db_session_factory)

@pytest.mark.asyncio
async def test_orchestrator_outer_exception_handling(db_session, db_session_factory):
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service"],
        inputs={},
        mappings=[]
    )
    original_commit = db_session.commit
    commit_calls = 0
    
    def mock_commit():
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 4:
            raise RuntimeError("Database commit error")
        return original_commit()
        
    db_session.commit = mock_commit
    
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    assert reloaded.status == "FAILED"
    assert "Database commit error" in reloaded.error_message


@pytest.mark.asyncio
async def test_success_conditions_default_success(db_session, db_session_factory):
    # TodoService has a default success condition: data.completed == True
    # In mock mode, todo_service returns completed = True, so it passes.
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service"],
        inputs={"todo_service": {"todo_id": 1, "_mock": True}},
        mappings=[]
    )
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    assert reloaded.status == "COMPLETED"
    step = reloaded.steps_data[0]
    assert step["status"] == "COMPLETED"

@pytest.mark.asyncio
async def test_success_conditions_dynamic_body_failure(db_session, db_session_factory):
    # Request that todo_service data.completed is False, but mock returns True
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service"],
        inputs={"todo_service": {"todo_id": 1, "_mock": True}},
        mappings=[],
        success_conditions={
            "todo_service": {
                "status_codes": [200],
                "body_rules": {
                    "data.completed": False
                }
            }
        }
    )
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    assert reloaded.status == "FAILED"
    step = reloaded.steps_data[0]
    assert step["status"] == "FAILED"
    assert "Success condition failed: key 'data.completed' expected False, got True" in step["error_message"]

@pytest.mark.asyncio
async def test_success_conditions_dynamic_status_code_failure(db_session, db_session_factory):
    # Request status code to be 201, but service execution returns 200
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service"],
        inputs={"todo_service": {"todo_id": 1, "_mock": True}},
        mappings=[],
        success_conditions={
            "todo_service": {
                "status_codes": [201]
            }
        }
    )
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    assert reloaded.status == "FAILED"
    step = reloaded.steps_data[0]
    assert step["status"] == "FAILED"
    assert "Success condition failed: status code 200 not in [201]" in step["error_message"]


@pytest.mark.asyncio
async def test_parallel_execution(db_session, db_session_factory):
    # Pass parallel sequence: [["todo_service", "post_service"]]
    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=[["todo_service", "post_service"]],
        inputs={
            "todo_service": {"todo_id": 1, "_mock": True},
            "post_service": {"title": "Title", "body": "Body", "_mock": True}
        },
        mappings=[]
    )
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    assert reloaded.status == "COMPLETED"
    assert len(reloaded.steps_data) == 2
    assert reloaded.steps_data[0]["status"] == "COMPLETED"
    assert reloaded.steps_data[1]["status"] == "COMPLETED"

@pytest.mark.asyncio
async def test_saga_rollback_compensation(db_session, db_session_factory):
    # Sequence: todo_service succeeds (mocked), crit_fail_svc fails
    # We expect todo_service to undergo compensation.
    @register_service
    class CriticalFailSvc(BaseService):
        @property
        def name(self) -> str:
            return "crit_fail_svc"
        async def _run(self, payload: dict, client: APIClient):
            return {"success": False, "error": "Forced failure", "status_code": 500}

    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service", "crit_fail_svc"],
        inputs={
            "todo_service": {"todo_id": 1, "_mock": True},
            "crit_fail_svc": {}
        },
        mappings=[]
    )
    
    # We will spy on the compensate method of TodoService
    with patch("services.todo_service.TodoService.compensate", new_callable=AsyncMock if hasattr(pytest, "AsyncMock") else MagicMock) as mock_compensate:
        # standard MagicMock patch works for async if we mock return value or if we don't await the mock directly,
        # but since we await it inside orchestrator we can make it an AsyncMock or mock coroutine
        async def async_mock(*args, **kwargs):
            pass
        mock_compensate.side_effect = async_mock
        await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
        assert mock_compensate.called
        
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    assert reloaded.status == "FAILED"
    assert len(reloaded.steps_data) == 2

def test_idempotency_deduplication(db_session):
    # Trigger 1
    exec1 = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service"],
        inputs={},
        mappings=[],
        idempotency_key="unique-idemp-123"
    )
    
    # Trigger 2 with same idempotency key
    exec2 = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service"],
        inputs={},
        mappings=[],
        idempotency_key="unique-idemp-123"
    )
    
    assert exec1.id == exec2.id

def test_secret_header_injection(monkeypatch):
    monkeypatch.setenv("TEST_SERVICE_API_KEY", "prod-key-12345")
    from utils import SecretResolver
    headers = SecretResolver.get_auth_headers("test_service")
    assert headers["Authorization"] == "Bearer prod-key-12345"


@pytest.mark.asyncio
async def test_conditional_routing_run_and_skip(db_session, db_session_factory):
    # Test case 1: condition matches (todo completed is True) -> post service runs
    exec_run = Orchestrator.create_execution(
        db=db_session,
        sequence=["todo_service", "post_service"],
        inputs={
            "todo_service": {"todo_id": 1, "_mock": True},
            "post_service": {"body": "Test", "_mock": True}
        },
        mappings=[],
        conditions={
            "post_service": "responses.todo_service.data.completed == True"
        }
    )
    await Orchestrator.run_sequence(exec_run.id, db_session_factory)
    db_session.expire_all()
    reloaded_run = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_run.id).first()
    assert reloaded_run.steps_data[1]["status"] == "COMPLETED"

    # Test case 2: condition does not match (todo completed is False) -> post service skipped
    # Let's register a mock todo response returning completed=False
    @register_service
    class IncompleteTodoSvc(BaseService):
        @property
        def name(self) -> str:
            return "inc_todo_svc"
        async def _run(self, payload: dict, client: APIClient):
            return {"success": True, "data": {"completed": False}}

    exec_skip = Orchestrator.create_execution(
        db=db_session,
        sequence=["inc_todo_svc", "post_service"],
        inputs={
            "inc_todo_svc": {},
            "post_service": {"body": "Test", "_mock": True}
        },
        mappings=[],
        conditions={
            "post_service": "responses.inc_todo_svc.data.completed == True"
        }
    )
    await Orchestrator.run_sequence(exec_skip.id, db_session_factory)
    db_session.expire_all()
    reloaded_skip = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_skip.id).first()
    assert reloaded_skip.steps_data[1]["status"] == "SKIPPED"
    assert reloaded_skip.steps_data[1]["error_message"] == "Condition not met"

@pytest.mark.asyncio
async def test_mapping_transformations(db_session, db_session_factory):
    # Register service that outputs string/lowercase values
    @register_service
    class OutputSvc(BaseService):
        @property
        def name(self) -> str:
            return "output_svc"
        async def _run(self, payload: dict, client: APIClient):
            return {"success": True, "data": {"num_str": "123", "text": "hello"}}

    @register_service
    class InputSvc(BaseService):
        @property
        def name(self) -> str:
            return "input_svc"
        async def _run(self, payload: dict, client: APIClient):
            return {"success": True, "data": payload}

    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["output_svc", "input_svc"],
        inputs={},
        mappings=[
            {
                "from_service": "output_svc",
                "from_field": "num_str",
                "to_service": "input_svc",
                "to_field": "number",
                "transform": "to_int"
            },
            {
                "from_service": "output_svc",
                "from_field": "text",
                "to_service": "input_svc",
                "to_field": "upper_text",
                "transform": "upper"
            }
        ]
    )
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    assert reloaded.status == "COMPLETED"
    input_payload = reloaded.steps_data[1]["input_payload"]
    assert input_payload["number"] == 123  # Int!
    assert input_payload["upper_text"] == "HELLO"  # Upper case!

@pytest.mark.asyncio
async def test_global_context_mapping_and_updates(db_session, db_session_factory):
    # Register service that updates context
    @register_service
    class ContextUpdateSvc(BaseService):
        @property
        def name(self) -> str:
            return "context_update_svc"
        async def _run(self, payload: dict, client: APIClient):
            return {
                "success": True,
                "data": {},
                "context_updates": {
                    "runtime_val": "changed"
                }
            }

    @register_service
    class ContextReadSvc(BaseService):
        @property
        def name(self) -> str:
            return "context_read_svc"
        async def _run(self, payload: dict, client: APIClient):
            return {"success": True, "data": payload}

    exec_obj = Orchestrator.create_execution(
        db=db_session,
        sequence=["context_update_svc", "context_read_svc"],
        inputs={},
        context={
            "initial_key": "init"
        },
        mappings=[
            {
                "from_service": "context",
                "from_field": "initial_key",
                "to_service": "context_read_svc",
                "to_field": "val1"
            },
            {
                "from_service": "context",
                "from_field": "runtime_val",
                "to_service": "context_read_svc",
                "to_field": "val2"
            }
        ]
    )
    await Orchestrator.run_sequence(exec_obj.id, db_session_factory)
    db_session.expire_all()
    reloaded = db_session.query(SequenceExecution).filter(SequenceExecution.id == exec_obj.id).first()
    assert reloaded.status == "COMPLETED"
    assert reloaded.context["initial_key"] == "init"
    assert reloaded.context["runtime_val"] == "changed"
    
    read_payload = reloaded.steps_data[1]["input_payload"]
    assert read_payload["val1"] == "init"
    assert read_payload["val2"] == "changed"

