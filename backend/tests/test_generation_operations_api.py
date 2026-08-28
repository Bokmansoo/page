import uuid

import pytest
from src.db.models import AgentRun, AgentRunStep, Asset, ProductProject, User, Workspace, WorkspaceMember, Brand


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


def test_generation_status_is_bounded_and_cross_workspace_hidden(
    client, client_db_session, custom_headers, test_workspace, test_user, test_brand,
):
    project = ProductProject(workspace_id=test_workspace.id, brand_id=test_brand.id, name="bounded", status="processing")
    client_db_session.add(project); client_db_session.flush()
    run = AgentRun(
        id=str(uuid.uuid4()), workspace_id=test_workspace.id, project_id=project.id,
        mode="real", status="failed", current_stage="copywriting", input_snapshot={}, outputs_json={},
        error_log=[{"message": "raw-provider-error private-ocr signed-url"}], created_by=test_user.id,
    )
    client_db_session.add_all([run, AgentRunStep(
        run_id=run.id, stage="copywriting", status="failed",
        error_message="raw-provider-error private-ocr signed-url",
    )])
    other = User(id=str(uuid.uuid4()), email="other-status@example.test", name="Other")
    other_workspace = Workspace(id=str(uuid.uuid4()), name="Other", owner_id=other.id)
    client_db_session.add_all([other, other_workspace]); client_db_session.commit()

    visible = client.get(f"/api/v1/operations/projects/{project.id}/generation-status", headers=custom_headers)
    assert visible.status_code == 200
    serialized = repr(visible.json())
    assert "raw-provider-error" not in serialized and "private-ocr" not in serialized and "signed-url" not in serialized
    assert visible.json()["last_error"] == "GRAPH_STEP_FAILED"

    denied = client.get(
        f"/api/v1/operations/projects/{project.id}/generation-status",
        headers={"X-Mock-User-Id": other.id, "X-Mock-Workspace-Id": other_workspace.id},
    )
    assert denied.status_code == 404


def test_operations_stats_allows_owner_and_denies_member(
    client, client_db_session, custom_headers, test_workspace,
):
    member = User(id=str(uuid.uuid4()), email="member-ops@example.test", name="Member")
    admin = User(id=str(uuid.uuid4()), email="admin-ops@example.test", name="Admin")
    client_db_session.add_all([
        member, admin,
        WorkspaceMember(workspace_id=test_workspace.id, user_id=member.id, role="member"),
        WorkspaceMember(workspace_id=test_workspace.id, user_id=admin.id, role="admin"),
    ])
    client_db_session.commit()

    assert client.get("/api/v1/operations/stats", headers=custom_headers).status_code == 200
    assert client.get(
        "/api/v1/operations/stats",
        headers={"X-Mock-User-Id": admin.id, "X-Mock-Workspace-Id": test_workspace.id},
    ).status_code == 200
    denied = client.get(
        "/api/v1/operations/stats",
        headers={"X-Mock-User-Id": member.id, "X-Mock-Workspace-Id": test_workspace.id},
    )
    assert denied.status_code == 403


def test_project_asset_projection_hides_storage_metadata_and_blocks_other_workspace(
    client, client_db_session, custom_headers, test_workspace, test_brand,
):
    project = ProductProject(workspace_id=test_workspace.id, brand_id=test_brand.id, name="asset privacy")
    client_db_session.add(project); client_db_session.flush()
    asset = Asset(
        project_id=project.id, source_type="uploaded", usage_status="seller_owned", filename="asset.png",
        file_path="C:/private/full-storage-path.png", mime_type="image/png", file_size=1,
        ocr_text="private OCR text",
    )
    other = User(id=str(uuid.uuid4()), email="other-asset@example.test", name="Other")
    other_workspace = Workspace(id=str(uuid.uuid4()), name="Other assets", owner_id=other.id)
    client_db_session.add_all([asset, other, other_workspace]); client_db_session.commit()

    visible = client.get(f"/api/v1/projects/{project.id}", headers=custom_headers)
    assert visible.status_code == 200
    serialized = repr(visible.json())
    assert "full-storage-path" not in serialized and "private OCR text" not in serialized
    denied = client.get(
        f"/api/v1/files/assets/{asset.id}",
        headers={"X-Mock-User-Id": other.id, "X-Mock-Workspace-Id": other_workspace.id},
    )
    assert denied.status_code == 404
