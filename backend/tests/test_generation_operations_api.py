import uuid

import pytest
from src.db.models import AgentRun, ProductProject, User, Workspace, Brand


@pytest.fixture
def test_user(db_session):
    user = User(
        id=str(uuid.uuid4()),
        email="ops-api-test@example.com",
        name="Ops API Test User",
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def test_workspace(db_session, test_user):
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Ops API Test Workspace",
        owner_id=test_user.id,
    )
    db_session.add(ws)
    db_session.flush()
    return ws


@pytest.fixture
def test_brand(db_session, test_workspace):
    brand = Brand(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        name="Ops API Test Brand",
        font_tone="modern",
    )
    db_session.add(brand)
    db_session.flush()
    return brand


@pytest.fixture
def client_db_session(db_session):
    return db_session


@pytest.fixture
def custom_headers(test_workspace, test_user):
    return {
        "X-Mock-User-Id": test_user.id,
        "X-Mock-Workspace-Id": test_workspace.id,
    }


def test_get_workspace_generation_status(client, client_db_session, custom_headers, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="상태 대시보드 상품",
        status="processing",
        current_step="copywriting",
    )
    client_db_session.add(project)
    client_db_session.flush()
    client_db_session.add(
        AgentRun(
            id="run-status-api",
            workspace_id=test_workspace.id,
            project_id=project.id,
            mode="real",
            status="running",
            current_stage="copywriting",
            input_snapshot={},
            outputs_json={},
            created_by=test_user.id,
        )
    )
    client_db_session.commit()

    response = client.get("/api/v1/operations/generation-status", headers=custom_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["running"] >= 1
    assert any(item["project_id"] == project.id for item in payload["projects"])


def test_get_project_generation_status(client, client_db_session, custom_headers, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="프로젝트 상태 상품",
        status="completed",
        current_step="review_editor",
    )
    client_db_session.add(project)
    client_db_session.commit()

    response = client.get(
        f"/api/v1/operations/projects/{project.id}/generation-status",
        headers=custom_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project.id
    assert payload["state"] in {"completed", "not_started"}
