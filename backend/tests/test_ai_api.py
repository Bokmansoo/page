from unittest.mock import patch

from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import JobStatus


def create_project(client, headers, name="AI API Product"):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": name,
            "brand_id": DEFAULT_BRAND_ID,
            "raw_input_text": "Material: cotton 100%, color: black",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_analyze_project_uses_workspace_scope_and_returns_processing_status(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    project_id = create_project(client, headers)

    with patch("src.api.ai.run_ai_analysis") as mocked_run:
        response = client.post(
            f"/api/v1/projects/{project_id}/analyze",
            json={"provider": "openai", "model_name": "gpt-4o-mini"},
            headers=headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["project_id"] == project_id
    assert body["status"] == "processing"
    assert body["message"] == "AI analysis and compliance check has been scheduled."

    job = db_session.query(JobStatus).filter(JobStatus.id == body["job_id"]).first()
    assert job is not None
    assert job.project_id == project_id
    assert job.status == "processing"
    mocked_run.assert_called_once()


def test_analyze_project_rejects_other_workspace_project(client):
    owner_headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    other_headers = {
        "X-Mock-User-Id": "user-2",
        "X-Mock-Workspace-Id": "workspace-2",
    }
    project_id = create_project(client, owner_headers)

    response = client.post(
        f"/api/v1/projects/{project_id}/analyze",
        json={"provider": "openai"},
        headers=other_headers,
    )

    assert response.status_code == 404


def test_confirm_project_category_updates_user_decision(client):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    project_id = create_project(client, headers)

    response = client.patch(
        f"/api/v1/projects/{project_id}/category",
        json={"category": "Beauty", "confirmed": True},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "Beauty"
    assert body["category_confirmed"] is True
    assert body["current_step"] == "facts_verification"


def test_confirm_project_category_rejects_invalid_category(client):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    project_id = create_project(client, headers)

    response = client.patch(
        f"/api/v1/projects/{project_id}/category",
        json={"category": "Electronics", "confirmed": True},
        headers=headers,
    )

    assert response.status_code == 422
