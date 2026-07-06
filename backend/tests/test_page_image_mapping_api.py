from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from src.db.models import ProductProject, ProductPage, PageSection, Asset


def test_auto_map_images_api_success(client: TestClient, db_session: Session):
    # Setup test workspace, brand, project, page, sections and image assets
    # In order to request this endpoint, we need mock authentication headers
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }

    # Create project
    proj = ProductProject(
        id="proj-auto-map",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="테스트 상품",
        raw_input_url="http://example.com",
        status="active",
        current_step="page_editor",
    )
    db_session.add(proj)

    # Create page
    page = ProductPage(
        id="page-auto-map",
        project_id="proj-auto-map",
        theme_color="#3B82F6",
        font_family="sans-serif",
    )
    db_session.add(page)

    # Create section
    sec = PageSection(
        id="sec-auto-map-1",
        page_id="page-auto-map",
        section_type="problem_statement",
        title="소제목",
        body_copy="본문 카피 문구",
        sort_order=0,
        is_visible=True,
    )
    db_session.add(sec)

    # Create asset
    asset = Asset(
        id="asset-auto-map-1",
        project_id="proj-auto-map",
        source_type="uploaded",
        filename="main-banner.jpg",
        file_path="uploads/main-banner.jpg",
        mime_type="image/jpeg",
        file_size=1024,
    )
    db_session.add(asset)
    db_session.commit()

    # Call POST auto-map-images
    resp = client.post(
        "/api/v1/projects/proj-auto-map/page/auto-map-images",
        json={"overwrite": True},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["assigned_count"] == 1
    assert len(data["assignments"]) == 1
    assert data["assignments"][0]["asset_id"] == "asset-auto-map-1"
    assert data["assignments"][0]["asset_role"] == "product_main"
    assert 0.0 <= data["assignments"][0]["confidence"] <= 1.0
    assert "missing_roles" in data
    assert "lifestyle_scene" in data["missing_roles"]

    # Verify database update
    db_session.refresh(sec)
    assert sec.image_asset_id == "asset-auto-map-1"


def test_auto_map_images_does_not_overwrite_manual_mapping_by_default(
    client: TestClient, db_session: Session
):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }
    project = ProductProject(
        id="proj-preserve-map",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="수동 매핑 보존",
        status="active",
        current_step="page_editor",
    )
    page = ProductPage(id="page-preserve-map", project_id=project.id)
    manual_asset = Asset(
        id="asset-manual",
        project_id=project.id,
        source_type="uploaded",
        filename="manual-main-product.jpg",
        file_path="uploads/manual-main-product.jpg",
        mime_type="image/jpeg",
        file_size=1024,
    )
    suggested_asset = Asset(
        id="asset-suggested",
        project_id=project.id,
        source_type="uploaded",
        filename="new-main-product.jpg",
        file_path="uploads/new-main-product.jpg",
        mime_type="image/jpeg",
        file_size=1024,
    )
    section = PageSection(
        id="sec-preserve-map",
        page_id=page.id,
        section_type="main_claim",
        image_asset_id=manual_asset.id,
        sort_order=0,
        is_visible=True,
    )
    db_session.add_all([project, page, manual_asset, suggested_asset, section])
    db_session.commit()

    response = client.post(
        f"/api/v1/projects/{project.id}/page/auto-map-images",
        json={"overwrite": False},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["assigned_count"] == 0
    assert response.json()["skipped_count"] == 1
    db_session.refresh(section)
    assert section.image_asset_id == manual_asset.id
