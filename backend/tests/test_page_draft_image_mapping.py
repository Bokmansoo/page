from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from src.db.models import ProductProject, ProductPage, PageSection, Asset


def test_create_page_draft_triggers_auto_image_mapping(
    client: TestClient, db_session: Session
):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }

    # Create project
    proj = ProductProject(
        id="proj-draft-mapping",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="테스트 선풍기",
        raw_input_url="http://example.com",
        status="active",
        current_step="page_editor",
        category="Living",
        selected_style="problem_solution",
    )
    db_session.add(proj)

    # Create image asset
    asset = Asset(
        id="asset-draft-1",
        project_id="proj-draft-mapping",
        source_type="uploaded",
        filename="hero-product-scene.jpg",
        file_path="uploads/hero-product-scene.jpg",
        mime_type="image/jpeg",
        file_size=2048,
    )
    db_session.add(asset)
    db_session.commit()

    # Call POST /projects/{project_id}/page to create page draft
    resp = client.post(
        "/api/v1/projects/proj-draft-mapping/page",
        json={
            "style_preset": "problem_solution",
            "primary_color": "#3B82F6",
            "narrative_template": "problem_solution",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()

    # The generated page should have sections, and some sections should match asset-draft-1
    page = (
        db_session.query(ProductPage)
        .filter(ProductPage.project_id == "proj-draft-mapping")
        .first()
    )
    assert page is not None
    assert len(page.sections) > 0

    # At least one section (e.g., hero or problem_statement) should be mapped
    mapped_sections = [s for s in page.sections if s.image_asset_id == "asset-draft-1"]
    assert len(mapped_sections) > 0
