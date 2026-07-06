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
