import uuid

import pytest
from src.db.models import AgentRun, ProductProject, User, Workspace, Brand


@pytest.fixture
def test_user(db_session):
    user = User(
        id=str(uuid.uuid4()),
        email="guard-test@example.com",
        name="Guard Test User",
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def test_workspace(db_session, test_user):
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Guard Test Workspace",
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
        name="Guard Test Brand",
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


def test_create_agent_run_blocks_when_same_project_is_running(client, client_db_session, custom_headers, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="루메나 휴대용 무선 냉각선풍기",
        raw_input_text="무선 냉각선풍기",
        status="processing",
        current_step="copywriting",
    )
    client_db_session.add(project)
    client_db_session.flush()
    client_db_session.add(
        AgentRun(
            id="existing-run",
            workspace_id=test_workspace.id,
            project_id=project.id,
            mode="real",
            status="running",
            current_stage="copywriting",
            input_snapshot={"product_name": project.name},
            outputs_json={},
            created_by=test_user.id,
        )
    )
    client_db_session.commit()

    response = client.post(
        "/api/agent-runs",
        headers=custom_headers,
        json={
            "product_name": "루메나 휴대용 무선 냉각선풍기",
            "description": "무선 냉각선풍기",
            "freeform_input": "무선 냉각선풍기",
            "asset_ids": [],
            "reference_urls": [],
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "generation_already_running"
    assert detail["project_id"] == project.id
    assert detail["run_id"] == "existing-run"


def test_create_agent_run_allows_new_product_when_no_matching_active_project(client, custom_headers):
    response = client.post(
        "/api/agent-runs",
        headers=custom_headers,
        json={
            "product_name": "새 상품",
            "description": "새 상품 설명",
            "freeform_input": "새 상품 설명",
            "asset_ids": [],
            "reference_urls": [],
        },
    )

    assert response.status_code == 201
    assert response.json()["project_id"]
