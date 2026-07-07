import datetime
from pathlib import Path

from src.db.models import Asset, Brand, ExportJob, ProductProject, User, Workspace


def test_list_export_history_returns_recent_exports(client):
    headers = {
        "X-Mock-User-Id": "history-test-user",
        "X-Mock-Workspace-Id": "history-test-workspace",
    }

    # Seed operations data which creates export jobs
    seed_res = client.post("/api/v1/operations/seed", headers=headers)
    assert seed_res.status_code == 201

    # Fetch export history
    response = client.get("/api/v1/page/exports", headers=headers)
    assert response.status_code == 200

    body = response.json()
    assert "items" in body
    assert len(body["items"]) > 0

    first = body["items"][0]
    assert "project_id" in first
    assert "project_name" in first
    assert first["status"] in {"pending", "running", "completed", "failed"}
    assert "created_at" in first
    assert "download_url" in first or first["download_url"] is None


def test_list_export_history_is_empty_for_new_workspace(client):
    headers = {
        "X-Mock-User-Id": "empty-history-user",
        "X-Mock-Workspace-Id": "empty-history-workspace",
    }

    response = client.get("/api/v1/page/exports", headers=headers)
    assert response.status_code == 200

    body = response.json()
    assert body["items"] == []


def test_list_export_history_returns_completed_download_url(client):
    headers = {
        "X-Mock-User-Id": "dl-url-test-user",
        "X-Mock-Workspace-Id": "dl-url-test-workspace",
    }

    seed_res = client.post("/api/v1/operations/seed", headers=headers)
    assert seed_res.status_code == 201

    response = client.get("/api/v1/page/exports", headers=headers)
    assert response.status_code == 200

    body = response.json()
    completed_items = [item for item in body["items"] if item["status"] == "completed"]
    
    if completed_items:
        item = completed_items[0]
        assert item["download_url"] is not None


def test_list_export_history_uses_exported_image_asset_contract(client, db_session, tmp_path):
    user = User(id="history-user", email="history@example.com", name="History User")
    workspace = Workspace(id="history-workspace", name="History Workspace", owner_id=user.id)
    brand = Brand(id="history-brand", workspace_id=workspace.id, name="History Brand")
    project = ProductProject(
        id="history-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="루메나 휴대용 무선 냉각선풍기",
        raw_input_url="https://example.com/product",
        status="completed",
    )
    export_file = Path(tmp_path) / "루메나-휴대용-무선-냉각선풍기-상세페이지.jpg"
    export_file.write_bytes(b"fake-jpg")
    image_asset = Asset(
        id="history-image-asset",
        project_id=project.id,
        source_type="exported_image",
        filename="루메나-휴대용-무선-냉각선풍기-상세페이지.jpg",
        file_path=str(export_file),
        mime_type="image/jpeg",
        file_size=8,
    )
    job = ExportJob(
        id="history-export-job",
        project_id=project.id,
        preset_name="smartstore",
        status="completed",
        zip_asset_id=None,
        output_images=[f"/api/v1/projects/{project.id}/page/export/download/{image_asset.id}"],
        created_by=user.id,
        created_at=datetime.datetime(2026, 7, 7, 12, 0, 0),
        completed_at=datetime.datetime(2026, 7, 7, 12, 1, 0),
    )
    db_session.add_all([user, workspace, brand, project, image_asset, job])
    db_session.commit()

    response = client.get(
        "/api/v1/page/exports",
        headers={
            "X-Mock-User-Id": user.id,
            "X-Mock-Workspace-Id": workspace.id,
        },
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["format"] == "jpg"
    assert item["filename"] == "루메나-휴대용-무선-냉각선풍기-상세페이지.jpg"
    assert item["content_type"] == "image/jpeg"
    assert item["download_url"] == f"/api/v1/projects/{project.id}/page/export/download/{image_asset.id}"
