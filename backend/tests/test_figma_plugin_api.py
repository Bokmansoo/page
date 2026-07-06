import base64
import os
import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import Session
from src.db.models import ProductProject, ProductPage, Brand, Asset
from src.api.auth import get_current_user_and_workspace
from src.config import settings


def test_issue_ticket_requires_project_tenant(client, db_session: Session):
    brand = Brand(id="b-plug-1", workspace_id="ws-plug-owner", name="Brand")
    db_session.add(brand)
    db_session.commit()
    project = ProductProject(
        id="p-plug-1",
        workspace_id="ws-plug-owner",
        brand_id="b-plug-1",
        name="Project"
    )
    db_session.add(project)
    db_session.commit()

    mock_user = MagicMock(id="user-outsider")
    mock_ws = MagicMock(id="ws-outsider")
    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": mock_user,
        "workspace": mock_ws,
        "role": "owner",
    }

    try:
        response = client.post(f"/api/v1/projects/{project.id}/page/figma-plugin/tickets")
        assert response.status_code == 404
    finally:
        client.app.dependency_overrides.clear()


def test_plugin_redeem_is_single_use(client, db_session: Session):
    brand = Brand(id="b-plug-2", workspace_id="ws-plug-2", name="Brand")
    db_session.add(brand)
    db_session.commit()
    project = ProductProject(
        id="p-plug-2",
        workspace_id="ws-plug-2",
        brand_id="b-plug-2",
        name="Project"
    )
    db_session.add(project)
    db_session.commit()
    page = ProductPage(
        id="pg-plug-2",
        project_id="p-plug-2",
        theme_color="#5B7CFA",
        font_family="Sans-Serif"
    )
    db_session.add(page)
    from src.db.models import PageSection
    for index in range(7):
        db_session.add(PageSection(
            page_id=page.id,
            section_type=f"section_{index + 1}",
            title=f"Title {index + 1}",
            body_copy="Body copy",
            sort_order=index,
            is_visible=True,
        ))
    db_session.commit()

    mock_user = MagicMock(id="user-owner")
    mock_user.id = "user-owner"
    mock_ws = MagicMock(id="ws-plug-2")
    mock_ws.id = "ws-plug-2"
    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": mock_user,
        "workspace": mock_ws,
        "role": "owner",
    }

    try:
        # Issue ticket
        issue_res = client.post(f"/api/v1/projects/{project.id}/page/figma-plugin/tickets")
        assert issue_res.status_code == 200
        code = issue_res.json()["code"]

        # Redeem ticket first time
        redeem_res1 = client.post("/api/v1/figma-plugin/import", json={"code": code})
        assert redeem_res1.status_code == 200
        redeem_body = redeem_res1.json()
        assert redeem_body["schema_version"] == "1.0"
        assert redeem_body["payload"]["schema_version"] == "1.0"
        assert redeem_body["embedded_assets"] == []
        assert redeem_body["asset_session_token"]
        assert redeem_body["asset_session_expires_at"]

        # Redeem ticket second time -> 409
        redeem_res2 = client.post("/api/v1/figma-plugin/import", json={"code": code})
        assert redeem_res2.status_code == 409
    finally:
        client.app.dependency_overrides.clear()


def test_issue_ticket_rejects_page_without_sections(
    client,
    db_session: Session,
):
    brand = Brand(id="b-plug-invalid", workspace_id="ws-plug-invalid", name="Brand")
    project = ProductProject(
        id="p-plug-invalid",
        workspace_id="ws-plug-invalid",
        brand_id=brand.id,
        name="Project",
    )
    page = ProductPage(
        id="pg-plug-invalid",
        project_id=project.id,
        theme_color="#5B7CFA",
        font_family="Inter",
    )
    db_session.add_all([brand, project, page])
    db_session.commit()

    mock_user = MagicMock(id="user-owner")
    mock_ws = MagicMock(id=project.workspace_id)
    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": mock_user,
        "workspace": mock_ws,
        "role": "owner",
    }

    try:
        response = client.post(
            f"/api/v1/projects/{project.id}/page/figma-plugin/tickets",
        )
        assert response.status_code == 409
        assert "at least 1 section" in response.json()["detail"]
    finally:
        client.app.dependency_overrides.clear()


def test_asset_requires_matching_session(client, db_session: Session):
    # Try fetching with dummy session
    response = client.get("/api/v1/figma-plugin/assets/asset_0", headers={"Authorization": "Bearer dummy"})
    assert response.status_code == 401


def test_invalid_ticket_attempts_are_rate_limited(client):
    headers = {"X-Forwarded-For": "203.0.113.34"}
    for attempt in range(10):
        response = client.post(
            "/api/v1/figma-plugin/import",
            json={"code": f"SF-BAD{attempt}-CODE"},
            headers=headers,
        )
        assert response.status_code == 404

    response = client.post(
        "/api/v1/figma-plugin/import",
        json={"code": "SF-BLOCKED-CODE"},
        headers=headers,
    )
    assert response.status_code == 429


def test_json_package_embeds_assets(client, db_session: Session, tmp_path):
    # Setup files and upload dir settings override
    brand = Brand(id="b-plug-3", workspace_id="ws-plug-3", name="Brand")
    db_session.add(brand)
    db_session.commit()
    project = ProductProject(
        id="p-plug-3",
        workspace_id="ws-plug-3",
        brand_id="b-plug-3",
        name="Project"
    )
    db_session.add(project)
    db_session.commit()
    page = ProductPage(
        id="pg-plug-3",
        project_id="p-plug-3",
        theme_color="#5B7CFA",
        font_family="Sans-Serif"
    )
    db_session.add(page)
    db_session.commit()

    # Create dummy image file
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    temp_file = os.path.join(settings.UPLOAD_DIR, "test_plug_image.png")
    with open(temp_file, "wb") as f:
        f.write(b"PNGDATA")

    asset = Asset(
        id="a-plug-3",
        project_id="p-plug-3",
        source_type="uploaded",
        filename="test_plug_image.png",
        file_path=temp_file,
        mime_type="image/png",
        file_size=7
    )
    db_session.add(asset)
    db_session.commit()

    # We also need a page section with image mapped
    from src.db.models import PageSection
    for index in range(7):
        db_session.add(PageSection(
            page_id="pg-plug-3",
            section_type="header" if index == 0 else f"section_{index + 1}",
            title="headline text",
            body_copy="body copy text",
            sort_order=index,
            is_visible=True,
            image_asset_id="a-plug-3" if index == 0 else None,
        ))
    db_session.commit()

    mock_user = MagicMock(id="user-owner")
    mock_ws = MagicMock(id="ws-plug-3")
    mock_ws.id = "ws-plug-3"
    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": mock_user,
        "workspace": mock_ws,
        "role": "owner",
    }

    try:
        response = client.get(f"/api/v1/projects/{project.id}/page/figma-plugin/package.json")
        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == "1.0"
        assert len(body["embedded_assets"]) == 1
        assert body["embedded_assets"][0]["mime_type"] == "image/png"
        assert base64.b64decode(body["embedded_assets"][0]["base64"]) == b"PNGDATA"
    finally:
        client.app.dependency_overrides.clear()
        if os.path.exists(temp_file):
            os.remove(temp_file)


def test_json_package_rejects_over_twenty_megabytes(client, db_session: Session):
    brand = Brand(id="b-plug-4", workspace_id="ws-plug-4", name="Brand")
    db_session.add(brand)
    db_session.commit()
    project = ProductProject(
        id="p-plug-4",
        workspace_id="ws-plug-4",
        brand_id="b-plug-4",
        name="Project"
    )
    db_session.add(project)
    db_session.commit()
    page = ProductPage(
        id="pg-plug-4",
        project_id="p-plug-4",
        theme_color="#5B7CFA",
        font_family="Sans-Serif"
    )
    db_session.add(page)
    db_session.commit()

    temp_file = os.path.join(settings.UPLOAD_DIR, "large_image.png")
    # Write a file slightly larger than max config limit
    # We override SELLFORM_FIGMA_PLUGIN_PACKAGE_MAX_BYTES setting to 10 bytes for this test
    old_max = settings.SELLFORM_FIGMA_PLUGIN_PACKAGE_MAX_BYTES
    settings.SELLFORM_FIGMA_PLUGIN_PACKAGE_MAX_BYTES = 20

    try:
        with open(temp_file, "wb") as f:
            f.write(b"A" * 15)

        asset = Asset(
            id="a-plug-4",
            project_id="p-plug-4",
            source_type="uploaded",
            filename="large_image.png",
            file_path=temp_file,
            mime_type="image/png",
            file_size=15
        )
        db_session.add(asset)
        
        from src.db.models import PageSection
        for index in range(7):
            db_session.add(PageSection(
                page_id="pg-plug-4",
                section_type="header" if index == 0 else f"section_{index + 1}",
                title="headline text",
                body_copy="body copy text",
                sort_order=index,
                is_visible=True,
                image_asset_id="a-plug-4" if index == 0 else None,
            ))
        db_session.commit()

        mock_user = MagicMock(id="user-owner")
        mock_ws = MagicMock(id="ws-plug-4")
        mock_ws.id = "ws-plug-4"
        client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
            "user": mock_user,
            "workspace": mock_ws,
            "role": "owner",
        }

        response = client.get(f"/api/v1/projects/{project.id}/page/figma-plugin/package.json")
        assert response.status_code == 413
    finally:
        settings.SELLFORM_FIGMA_PLUGIN_PACKAGE_MAX_BYTES = old_max
        client.app.dependency_overrides.clear()
        if os.path.exists(temp_file):
            os.remove(temp_file)
