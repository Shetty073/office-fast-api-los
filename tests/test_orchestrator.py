import pytest
import asyncio
from unittest.mock import patch, MagicMock
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

