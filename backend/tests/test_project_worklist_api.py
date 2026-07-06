def test_project_worklist_returns_generated_pages(client):
    headers = {
        "X-Mock-User-Id": "worklist-test-user",
        "X-Mock-Workspace-Id": "worklist-test-workspace",
    }

    seed_response = client.post("/api/v1/operations/seed", headers=headers)
    assert seed_response.status_code == 201

    response = client.get("/api/v1/projects/worklist", headers=headers)
    assert response.status_code == 200

    body = response.json()
    assert "items" in body
    assert len(body["items"]) >= 1

    item = body["items"][0]
    assert item["project_id"]
    assert item["project_name"]
    assert item["status"] in ["generating", "needs_review", "completed", "failed"]
    assert item["result_url"].startswith(f"/workspace/projects/{item['project_id']}")
    assert item["review_url"].startswith(f"/workspace/projects/{item['project_id']}")
    assert item["export_history_url"].startswith("/workspace/exports")
    assert "updated_at" in item


def test_project_worklist_is_empty_for_new_workspace(client):
    headers = {
        "X-Mock-User-Id": "empty-worklist-user",
        "X-Mock-Workspace-Id": "empty-worklist-workspace",
    }

    response = client.get("/api/v1/projects/worklist", headers=headers)
    assert response.status_code == 200

    body = response.json()
    assert body["items"] == []
