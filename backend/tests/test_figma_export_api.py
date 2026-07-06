import pytest
from sqlalchemy.orm import Session
from src.db.models import ProductProject, ProductPage, Brand
from src.api.auth import get_current_user_and_workspace


def test_figma_export_endpoint_success(client, db_session: Session):
    # 0. Create brand with workspace_id due to NOT NULL constraint
    brand = Brand(id="b-figma-1", workspace_id="ws-figma-1", name="루메나 브랜드")
    db_session.add(brand)
    db_session.commit()

    # 1. Create real project and page draft in test DB
    project = ProductProject(
        id="p-figma-success",
        workspace_id="ws-figma-1",
        brand_id="b-figma-1",
        name="루메나 선풍기",
        category="Living",
        selected_style="problem_solution_living"
    )
    db_session.add(project)
    db_session.commit()

    page = ProductPage(
        id="pg-figma-success",
        project_id="p-figma-success",
        theme_color="#5B7CFA",
        font_family="Sans-Serif"
    )
    db_session.add(page)
    db_session.commit()

    # 2. Configure mock auth context
    mock_user = MagicMock()
    mock_user.id = "user-figma-1"
    
    mock_ws = MagicMock()
    mock_ws.id = "ws-figma-1"

    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": mock_user,
        "workspace": mock_ws,
        "role": "owner"
    }

    try:
        response = client.post("/api/v1/projects/p-figma-success/page/figma/export")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "payload" in data
        assert data["payload"]["project"]["id"] == "p-figma-success"
        assert "message" in data
    finally:
        client.app.dependency_overrides.clear()


def test_figma_export_endpoint_no_page(client, db_session: Session):
    # 0. Create brand with workspace_id due to NOT NULL constraint
    brand = Brand(id="b-figma-2", workspace_id="ws-figma-1", name="루메나 브랜드")
    db_session.add(brand)
    db_session.commit()

    # 1. Create project without page draft in test DB
    project = ProductProject(
        id="p-figma-nopage",
        workspace_id="ws-figma-1",
        brand_id="b-figma-2",
        name="루메나 선풍기",
        category="Living",
        selected_style="problem_solution_living"
    )
    db_session.add(project)
    db_session.commit()

    # 2. Configure mock auth context
    mock_user = MagicMock()
    mock_user.id = "user-figma-1"
    
    mock_ws = MagicMock()
    mock_ws.id = "ws-figma-1"

    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": mock_user,
        "workspace": mock_ws,
        "role": "owner"
    }

    try:
        response = client.post("/api/v1/projects/p-figma-nopage/page/figma/export")
        assert response.status_code == 409
        assert "Page draft not found" in response.json()["detail"]
    finally:
        client.app.dependency_overrides.clear()


def test_figma_export_endpoint_rejects_project_from_another_workspace(client, db_session: Session):
    brand = Brand(id="b-figma-other-workspace", workspace_id="ws-figma-owner", name="다른 워크스페이스 브랜드")
    db_session.add(brand)
    db_session.commit()

    project = ProductProject(
        id="p-figma-other-workspace",
        workspace_id="ws-figma-owner",
        brand_id=brand.id,
        name="다른 워크스페이스 상품",
        category="Living",
        selected_style="problem_solution_living",
    )
    db_session.add(project)
    db_session.commit()

    mock_user = MagicMock(id="user-figma-outsider")
    mock_ws = MagicMock(id="ws-figma-outsider")
    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": mock_user,
        "workspace": mock_ws,
        "role": "owner",
    }

    try:
        response = client.post("/api/v1/projects/p-figma-other-workspace/page/figma/export")
        assert response.status_code == 404
        assert response.json()["detail"] == "Project not found"
    finally:
        client.app.dependency_overrides.clear()


# Helper import mocking for MagicMock
from unittest.mock import MagicMock
