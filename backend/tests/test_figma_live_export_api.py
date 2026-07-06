import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import responses
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.models import User, Workspace, Brand, ProductProject, ProductPage, FigmaExportJob
from src.api.auth import get_current_user_and_workspace


@pytest.fixture
def seed_data(client: TestClient, db_session: Session):
    # 1. Clear any existing seeds to avoid constraint duplicates
    db_session.query(ProductPage).delete()
    db_session.query(FigmaExportJob).delete()
    db_session.query(ProductProject).delete()
    db_session.query(Brand).delete()
    db_session.query(User).delete()
    db_session.query(Workspace).delete()
    db_session.commit()

    # 2. Add Workspace & User
    user = User(id="u-1", email="test@example.com", name="테스터")
    db_session.add(user)
    db_session.commit()

    workspace = Workspace(id="ws-1", name="테스트 워크스페이스", owner_id="u-1")
    db_session.add(workspace)
    db_session.commit()

    # 3. Add Brand
    brand = Brand(id="b-1", name="루메나", workspace_id="ws-1")
    db_session.add(brand)
    db_session.commit()

    # 4. Add ProductProject
    project = ProductProject(
        id="p-1",
        name="루메나 선풍기",
        brand_id="b-1",
        workspace_id="ws-1",
        category="Living",
        selected_style="living_style"
    )
    db_session.add(project)
    db_session.commit()

    # 5. Overrides Authentication Context
    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": user,
        "workspace": workspace,
        "role": "owner"
    }

    yield {
        "user": user,
        "workspace": workspace,
        "brand": brand,
        "project": project
    }

    client.app.dependency_overrides.pop(get_current_user_and_workspace, None)


def test_live_export_project_not_found(client: TestClient, seed_data):
    response = client.post(
        "/api/v1/projects/p-nonexist/page/figma/live-export",
        json={"target_file_url": "https://www.figma.com/design/ABC/Test"}
    )
    # Project id doesn't match p-nonexist because auth context returns ws-1 workspace
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_live_export_page_not_found(client: TestClient, seed_data):
    response = client.post(
        "/api/v1/projects/p-1/page/figma/live-export",
        json={"target_file_url": "https://www.figma.com/design/ABC/Test"}
    )
    assert response.status_code == 409
    assert "Page draft not found" in response.json()["detail"]


@responses.activate
def test_live_export_success_flow(client: TestClient, seed_data, db_session: Session):
    # 1. Create page draft
    page = ProductPage(
        project_id="p-1",
        theme_color="#5B7CFA",
        font_family="Sans-Serif"
    )
    db_session.add(page)
    db_session.commit()

    # 2. Mock Figma Bridge URL and HTTP responses
    from src.config import settings
    bridge_url = f"{settings.SELLFORM_FIGMA_BRIDGE_URL.rstrip('/')}/v1/exports"
    responses.add(
        responses.POST,
        bridge_url,
        json={
            "success": True,
            "result_file_url": "https://www.figma.com/design/ABC/Test",
            "result_node_url": "https://www.figma.com/design/ABC/Test?node-id=1-2"
        },
        status=200
    )

    # 3. Post live export
    response = client.post(
        "/api/v1/projects/p-1/page/figma/live-export",
        json={"target_file_url": "https://www.figma.com/design/ABC/Test"}
    )
    assert response.status_code == 200
    res_data = response.json()
    job_id = res_data["job_id"]
    assert res_data["status"] == "queued"

    # 4. Trigger perform_figma_live_export synchronously to simulate background execution
    from src.api.pages import perform_figma_live_export
    from src.services.figma_design_payload_builder import build_figma_design_payload
    payload = build_figma_design_payload(seed_data["project"], page, db_session)
    
    perform_figma_live_export(job_id, payload, "https://www.figma.com/design/ABC/Test", db=db_session)

    # 5. Fetch status
    status_response = client.get(
        f"/api/v1/projects/p-1/page/figma/exports/{job_id}"
    )
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["status"] == "completed"
    assert status_data["result_node_url"] == "https://www.figma.com/design/ABC/Test?node-id=1-2"


@responses.activate
def test_live_export_failure_flow(client: TestClient, seed_data, db_session: Session):
    # 1. Create page draft
    page = ProductPage(
        project_id="p-1",
        theme_color="#5B7CFA",
        font_family="Sans-Serif"
    )
    db_session.add(page)
    db_session.commit()

    # 2. Mock Figma Bridge auth error response
    from src.config import settings
    bridge_url = f"{settings.SELLFORM_FIGMA_BRIDGE_URL.rstrip('/')}/v1/exports"
    responses.add(
        responses.POST,
        bridge_url,
        json={
            "error_code": "AUTH_REQUIRED",
            "error_message": "Figma OAuth authorization required.",
            "auth_url": "https://www.figma.com/oauth"
        },
        status=401
    )

    # 3. Post live export
    response = client.post(
        "/api/v1/projects/p-1/page/figma/live-export",
        json={"target_file_url": "https://www.figma.com/design/ABC/Test"}
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    # 4. Trigger perform_figma_live_export synchronously to simulate background execution
    from src.api.pages import perform_figma_live_export
    from src.services.figma_design_payload_builder import build_figma_design_payload
    payload = build_figma_design_payload(seed_data["project"], page, db_session)
    
    perform_figma_live_export(job_id, payload, "https://www.figma.com/design/ABC/Test", db=db_session)

    # 5. Fetch status
    status_response = client.get(
        f"/api/v1/projects/p-1/page/figma/exports/{job_id}"
    )
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["status"] == "failed"
    assert status_data["error_code"] == "AUTH_REQUIRED"
    assert "authorization required" in status_data["error_message"].lower()
    assert status_data["auth_url"] == "https://www.figma.com/oauth"


def test_live_export_sets_rendering_before_bridge_call(
    client: TestClient, seed_data, db_session: Session, monkeypatch
):
    page = ProductPage(
        project_id="p-1",
        theme_color="#5B7CFA",
        font_family="Sans-Serif",
    )
    db_session.add(page)
    db_session.commit()

    response = client.post(
        "/api/v1/projects/p-1/page/figma/live-export",
        json={"target_file_url": "https://www.figma.com/design/ABC/Test"},
    )
    job_id = response.json()["job_id"]

    def fake_trigger_export(_self, *_args, **_kwargs):
        db_session.expire_all()
        job = db_session.query(FigmaExportJob).filter(FigmaExportJob.id == job_id).one()
        assert job.status == "rendering"
        return {
            "success": True,
            "result_file_url": "https://www.figma.com/design/ABC/Test",
            "result_node_url": "https://www.figma.com/design/ABC/Test?node-id=1-2",
        }

    monkeypatch.setattr(
        "src.services.figma_bridge_client.FigmaBridgeClient.trigger_export",
        fake_trigger_export,
    )
    from src.api.pages import perform_figma_live_export
    from src.services.figma_design_payload_builder import build_figma_design_payload

    payload = build_figma_design_payload(seed_data["project"], page, db_session)
    perform_figma_live_export(
        job_id,
        payload,
        "https://www.figma.com/design/ABC/Test",
        db=db_session,
    )

    db_session.expire_all()
    assert db_session.query(FigmaExportJob).filter(FigmaExportJob.id == job_id).one().status == "completed"
