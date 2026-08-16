import pytest
from unittest.mock import patch
from app.models.sequence_definition import SequenceDefinition

def test_create_and_get_sequence_definition(client, db_session):
    recipe = {
        "name": "post_lifecycle_pipeline",
        "description": "Lifecycle pipeline with post services",
        "sequence": ["create_post_service", "get_post_service"],
        "default_inputs": {
            "create_post_service": {"body": "Default description"}
        },
        "mappings": [
            {
                "from_service": "create_post_service",
                "from_field": "data.id",
                "to_service": "get_post_service",
                "to_field": "post_id"
            }
        ],
        "skip_conditions": [
            {
                "service": "get_post_service",
                "condition": "context.skip == True",
                "reason": "Context flag"
            }
        ]
    }

    create_res = client.post("/api/sequences", json=recipe)
    assert create_res.status_code == 200
    created = create_res.json()
    assert created["name"] == "post_lifecycle_pipeline"
    assert created["sequence"] == ["create_post_service", "get_post_service"]
    assert len(created["skip_conditions"]) == 1

    get_res = client.get(f"/api/sequences/{created['name']}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == created["id"]

    get_by_id = client.get(f"/api/sequences/{created['id']}")
    assert get_by_id.status_code == 200
    assert get_by_id.json()["name"] == "post_lifecycle_pipeline"

    list_res = client.get("/api/sequences")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

def test_create_sequence_definition_invalid_service(client):
    recipe = {
        "name": "invalid_flow",
        "sequence": ["non_existent_service"]
    }
    res = client.post("/api/sequences", json=recipe)
    assert res.status_code == 404
    assert "not registered" in res.json()["detail"]

def test_get_sequence_definition_not_found(client):
    res = client.get("/api/sequences/missing_recipe_id")
    assert res.status_code == 404

def test_sequence_definition_update_existing(client, db_session):
    recipe = {
        "name": "updatable_flow",
        "sequence": ["create_post_service"]
    }
    client.post("/api/sequences", json=recipe)

    updated_recipe = {
        "name": "updatable_flow",
        "description": "Updated Description",
        "sequence": ["create_post_service", "get_post_service"]
    }
    res = client.post("/api/sequences", json=updated_recipe)
    assert res.status_code == 200
    assert res.json()["description"] == "Updated Description"
    assert len(res.json()["sequence"]) == 2

def test_create_sequence_general_exception(client):
    with patch("app.services.sequence_manager.SequenceManager.create_definition", side_effect=Exception("Database down")):
        recipe = {
            "name": "err_flow",
            "sequence": ["create_post_service"]
        }
        res = client.post("/api/sequences", json=recipe)
        assert res.status_code == 400
