from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from src.db.models import ProductProject, Asset


def test_list_project_assets_api(client: TestClient, db_session: Session):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }

    # Create project
    proj = ProductProject(
        id="proj-assets-test",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="자산 조회 테스트",
        raw_input_url="http://example.com",
        status="active",
        current_step="page_editor",
    )
    db_session.add(proj)

    # Create image assets
    asset1 = Asset(
        id="asset-1",
        project_id="proj-assets-test",
        source_type="uploaded",
        filename="hero.jpg",
        file_path="uploads/hero.jpg",
        mime_type="image/jpeg",
        file_size=1024,
    )
    asset2 = Asset(
        id="asset-2",
        project_id="proj-assets-test",
        source_type="uploaded",
        filename="spec.png",
        file_path="uploads/spec.png",
        mime_type="image/png",
        file_size=2048,
    )
    db_session.add_all([asset1, asset2])
    db_session.commit()

    resp = client.get(
        "/api/v1/projects/proj-assets-test/assets",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {a["id"] for a in data} == {"asset-1", "asset-2"}


def test_asset_file_api_serves_stored_file_path_not_original_filename(
    client: TestClient, db_session: Session, tmp_path
):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }

    project = ProductProject(
        id="proj-asset-file-test",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="Asset file test",
        raw_input_url="http://example.com",
        status="active",
        current_step="page_editor",
    )
    db_session.add(project)

    stored_file = tmp_path / "stored-uuid-name.png"
    stored_file.write_bytes(b"fake image bytes")
    asset = Asset(
        id="asset-file-1",
        project_id=project.id,
        source_type="uploaded",
        filename="samtanbyme.png",
        file_path=str(stored_file),
        mime_type="image/png",
        file_size=stored_file.stat().st_size,
    )
    db_session.add(asset)
    db_session.commit()

    response = client.get("/api/v1/files/assets/asset-file-1", headers=headers)

    assert response.status_code == 200
    assert response.content == b"fake image bytes"
    assert response.headers["content-type"] == "image/png"
