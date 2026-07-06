import pytest
from src.api.auth import DEFAULT_BRAND_ID

def test_ai_edit_command_creates_new_page_version(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # 1. Create a project
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Sprint 53 Monitor", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "Spec sheet"},
        headers=headers
    )
    assert create_res.status_code == 201
    p_id = create_res.json()["id"]

    # 2. Create detail page draft
    page_res = client.post(
        f"/api/v1/projects/{p_id}/page",
        json={"style_preset": "modern"},
        headers=headers
    )
    assert page_res.status_code == 201

    # 3. Call AI edit endpoint
    response = client.post(
        f"/api/v1/projects/{p_id}/pages/ai-edit",
        headers=headers,
        json={"section_id": "hero", "command": "제목을 더 자연스럽게 바꿔줘"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["version_id"]
    assert data["status"] in {"mock_applied", "applied"}
