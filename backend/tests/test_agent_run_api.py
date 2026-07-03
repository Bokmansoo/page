import pytest


@pytest.fixture
def auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def test_create_agent_run_from_product_name(client, auth_headers):
    response = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "유아 자전거", "description": "보조 바퀴가 있는 첫 자전거"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["current_stage"] == "intake"
    assert data["mode"] == "mock"
    assert data["product_input"]["product_name"] == "유아 자전거"


def test_run_mock_generation_returns_page_assembly(client, auth_headers):
    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "유아 자전거"},
    ).json()
    response = client.post(f"/api/agent-runs/{created['id']}/run-mock", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["current_stage"] == "review_editor"
    assert data["outputs"]["page_assembly"]["sections"]

