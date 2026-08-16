import os
import sys
import uuid

# Add parent and los-app directories to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "los-app")))

from app.db.session import SessionLocal, init_database, engine, auto_migrate_columns
from app.db.base import Base
from app.models.sequence_definition import SequenceDefinition
from app.services.sequence_manager import SequenceManager
import app.services

def seed_recipes():
    init_database()
    Base.metadata.create_all(bind=engine)
    auto_migrate_columns()
    
    db = SessionLocal()
    try:
        # 1. Register post_lifecycle_pipeline
        SequenceManager.create_definition(
            db=db,
            name="post_lifecycle_pipeline",
            description="Lifecycle pipeline: 1. Create post -> 2. Get post by id -> 3. Update post (PUT) -> 4. Get updated post",
            sequence=[
                "create_post_service",
                "get_post_service",
                "update_post_service",
                "get_post_service"
            ],
            default_inputs={
                "create_post_service": {"userId": 1},
                "get_post_service": {},
                "update_post_service": {"userId": 1}
            },
            mappings=[
                {
                    "from_service": "trigger_payload",
                    "from_field": "post_title",
                    "to_service": "create_post_service",
                    "to_field": "title"
                },
                {
                    "from_service": "trigger_payload",
                    "from_field": "post_body",
                    "to_service": "create_post_service",
                    "to_field": "body"
                },
                {
                    "from_service": "create_post_service",
                    "from_field": "data.id",
                    "to_service": "get_post_service",
                    "to_field": "post_id"
                },
                {
                    "from_service": "create_post_service",
                    "from_field": "data.id",
                    "to_service": "update_post_service",
                    "to_field": "id"
                },
                {
                    "from_service": "trigger_payload",
                    "from_field": "update_title",
                    "to_service": "update_post_service",
                    "to_field": "title"
                },
                {
                    "from_service": "trigger_payload",
                    "from_field": "update_body",
                    "to_service": "update_post_service",
                    "to_field": "body"
                }
            ],
            success_conditions={
                "create_post_service": {
                    "expected_status_code": [200, 201],
                    "equals": {"success": True}
                },
                "get_post_service": {
                    "expected_status_code": 200,
                    "equals": {"success": True}
                },
                "update_post_service": {
                    "expected_status_code": 200,
                    "equals": {"success": True}
                }
            },
            skip_conditions=[
                {
                    "service": "update_post_service",
                    "condition": "context.skip_update == True",
                    "reason": "Update skipped as per context flag"
                }
            ]
        )
        print("[+] Seeded 'post_lifecycle_pipeline' sequence definition successfully.")

        # 2. Update legacy user_onboarding_flow to use valid registered services
        SequenceManager.create_definition(
            db=db,
            name="user_onboarding_flow",
            description="Onboarding pipeline: 1. Create post -> 2. Get post by id -> 3. Update post (PUT) -> 4. Get updated post",
            sequence=[
                "create_post_service",
                "get_post_service",
                "update_post_service",
                "get_post_service"
            ],
            default_inputs={
                "create_post_service": {"userId": 1},
                "get_post_service": {},
                "update_post_service": {"userId": 1}
            },
            mappings=[
                {
                    "from_service": "trigger_payload",
                    "from_field": "post_title",
                    "to_service": "create_post_service",
                    "to_field": "title"
                },
                {
                    "from_service": "trigger_payload",
                    "from_field": "post_body",
                    "to_service": "create_post_service",
                    "to_field": "body"
                },
                {
                    "from_service": "create_post_service",
                    "from_field": "data.id",
                    "to_service": "get_post_service",
                    "to_field": "post_id"
                },
                {
                    "from_service": "create_post_service",
                    "from_field": "data.id",
                    "to_service": "update_post_service",
                    "to_field": "id"
                },
                {
                    "from_service": "trigger_payload",
                    "from_field": "update_title",
                    "to_service": "update_post_service",
                    "to_field": "title"
                },
                {
                    "from_service": "trigger_payload",
                    "from_field": "update_body",
                    "to_service": "update_post_service",
                    "to_field": "body"
                }
            ],
            success_conditions={
                "create_post_service": {
                    "expected_status_code": [200, 201],
                    "equals": {"success": True}
                },
                "get_post_service": {
                    "expected_status_code": 200,
                    "equals": {"success": True}
                },
                "update_post_service": {
                    "expected_status_code": 200,
                    "equals": {"success": True}
                }
            }
        )
        print("[+] Updated 'user_onboarding_flow' sequence definition to use registered JSONPlaceholder post services.")
    finally:
        db.close()

if __name__ == "__main__":
    seed_recipes()
