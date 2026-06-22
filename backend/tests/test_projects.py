from src.api.auth import DEFAULT_BRAND_ID


def test_create_and_get_project(client):
    # 1. Create a project
    payload = {
        "name": "Test Cotton Shirt",
        "brand_id": DEFAULT_BRAND_ID,
        "raw_input_text": "Size M, L. Made in Korea."
    }
    # Send mock workspace/user headers to trigger bootstrapping
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    response = client.post("/api/v1/projects", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Cotton Shirt"
    assert data["raw_input_text"] == "Size M, L. Made in Korea."
    assert data["status"] == "draft"
    assert data["current_step"] == "raw_input"
    project_id = data["id"]

    # 2. Get project by ID
    get_response = client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Test Cotton Shirt"


def test_workspace_isolation(client):
    # 1. Create project in Workspace 1
    headers_ws1 = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    payload = {
        "name": "Shirt WS1",
        "brand_id": DEFAULT_BRAND_ID
    }
    create_res = client.post("/api/v1/projects", json=payload, headers=headers_ws1)
    assert create_res.status_code == 201
    p_id = create_res.json()["id"]

    # 2. Access the project from Workspace 2
    headers_ws2 = {
        "X-Mock-User-Id": "user-2",
        "X-Mock-Workspace-Id": "workspace-2"
    }
    # It should return 404 because this project doesn't exist in Workspace 2
    get_res = client.get(f"/api/v1/projects/{p_id}", headers=headers_ws2)
    assert get_res.status_code == 404


def test_autosave_patch_project(client):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    # Create project
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Initial Shirt", "brand_id": DEFAULT_BRAND_ID},
        headers=headers
    )
    p_id = create_res.json()["id"]

    # Patch project (autosave)
    patch_res = client.patch(
        f"/api/v1/projects/{p_id}",
        json={"name": "Autosaved Shirt Name", "raw_input_text": "Updated content"},
        headers=headers
    )
    assert patch_res.status_code == 200
    data = patch_res.json()
    assert data["name"] == "Autosaved Shirt Name"
    assert data["raw_input_text"] == "Updated content"
