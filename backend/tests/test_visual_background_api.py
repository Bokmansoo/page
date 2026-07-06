from src.api.auth import DEFAULT_BRAND_ID


HEADERS = {
    "X-Mock-User-Id": "user-visual-bg",
    "X-Mock-Workspace-Id": "workspace-visual-bg",
}


def _create_project(client) -> str:
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "루메나 휴대용 무선 냉각선풍기",
            "brand_id": DEFAULT_BRAND_ID,
            "raw_input_text": "FAN JET ULTRA, 휴대용 무선 냉각선풍기",
        },
        headers=HEADERS,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_generate_visual_background_candidates_api_returns_safe_candidates(client):
    project_id = _create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/visual-backgrounds/generate",
        headers=HEADERS,
    )

    assert response.status_code == 200
    candidates = response.json()
    assert len(candidates) >= 3
    assert {candidate["id"] for candidate in candidates} >= {
        "cooling-blue",
        "minimal-white",
        "lifestyle-summer",
    }
    assert all("로고" in candidate["safety_note"] for candidate in candidates)


def test_select_visual_background_persists_on_project(client):
    project_id = _create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/visual-backgrounds/cooling-blue/select",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["selected_background"] == "cooling-blue"

    get_response = client.get(f"/api/v1/projects/{project_id}", headers=HEADERS)
    assert get_response.status_code == 200
    assert get_response.json()["selected_background"] == "cooling-blue"


def test_select_visual_background_rejects_unknown_candidate(client):
    project_id = _create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/visual-backgrounds/unknown-style/select",
        headers=HEADERS,
    )

    assert response.status_code == 400
