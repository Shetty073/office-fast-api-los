from app.models.sequence_execution import SequenceExecution
from app.models.sequence_definition import SequenceDefinition
from app.models.api_log import APILog

def test_models_properties_and_attributes(db_session):
    seq_def = SequenceDefinition(
        id="def-1",
        name="test_pipeline",
        sequence=["todo_service", "post_service"],
        mappings=[]
    )
    db_session.add(seq_def)
    db_session.commit()
    assert seq_def.name == "test_pipeline"

    exec_record = SequenceExecution(
        id="exec-1",
        sequence=["todo_service", ["post_service", "todo_service"]],
        inputs={},
        mappings=[],
        status="RUNNING",
        steps_data=[
            {"service_name": "todo_service", "status": "COMPLETED", "output_response": {"data": "ok"}},
            {"service_name": "post_service", "status": "PENDING", "output_response": None}
        ]
    )
    db_session.add(exec_record)
    db_session.commit()

    assert exec_record.total_tasks == 3
    assert exec_record.completed_tasks == 1
    assert exec_record.pending_tasks == 2
    assert "todo_service" in exec_record.responses
    assert exec_record.responses["todo_service"] == {"data": "ok"}

    api_log = APILog(
        execution_id="exec-1",
        service_name="todo_service",
        method="GET",
        url="http://test.com",
        duration_ms=50
    )
    db_session.add(api_log)
    db_session.commit()
    assert api_log.service_name == "todo_service"
