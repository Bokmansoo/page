from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import ProductFact


def _create_project_with_page(client, db_session, headers=None):
    headers = headers or {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    create_res = client.post(
        "/api/v1/projects",
        json={
            "name": "Sprint 4 Page",
            "brand_id": DEFAULT_BRAND_ID,
            "raw_input_text": "Spec sheet",
        },
        headers=headers,
    )
    assert create_res.status_code == 201
    project_id = create_res.json()["id"]

    fact = ProductFact(
        project_id=project_id,
        fact_text="가벼운 소재입니다.",
        source_text="light material",
        verification_status="confirmed",
    )
    db_session.add(fact)
    db_session.commit()

    page_res = client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers,
    )
    assert page_res.status_code == 201
    return project_id, page_res.json()


def test_regenerate_page_section_applies_user_instruction(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    project_id, page_data = _create_project_with_page(client, db_session, headers)
    section_id = page_data["sections"][0]["id"]
    original_copy = page_data["sections"][0]["body_copy"]

    res = client.post(
        f"/api/v1/projects/{project_id}/page/sections/{section_id}/regenerate",
        json={"user_instruction": "더 짧고 명확하게"},
        headers=headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["id"] == section_id
    assert data["body_copy"] != original_copy
    assert "더 짧고 명확하게" in data["body_copy"]


def test_page_api_rejects_project_from_other_workspace(client, db_session):
    owner_headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    other_headers = {
        "X-Mock-User-Id": "user-2",
        "X-Mock-Workspace-Id": "workspace-2",
    }
    project_id, _ = _create_project_with_page(client, db_session, owner_headers)

    res = client.get(f"/api/v1/projects/{project_id}/page", headers=other_headers)

    assert res.status_code == 404


def test_list_page_versions_returns_real_saved_versions(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    project_id, page_data = _create_project_with_page(client, db_session, headers)
    sections = page_data["sections"]

    save_res = client.patch(
        f"/api/v1/projects/{project_id}/page",
        json={
            "theme_color": "#111111",
            "font_family": "serif",
            "sections": [
                {
                    "id": sec["id"],
                    "title": sec["title"],
                    "body_copy": sec["body_copy"],
                    "image_asset_id": sec["image_asset_id"],
                    "sort_order": sec["sort_order"],
                    "is_visible": sec["is_visible"],
                }
                for sec in sections
            ],
        },
        headers=headers,
    )
    assert save_res.status_code == 200

    res = client.get(f"/api/v1/projects/{project_id}/page/versions", headers=headers)

    assert res.status_code == 200
    versions = res.json()
    assert len(versions) == 2
    assert versions[0]["name"] == "사용자 수정"
    assert versions[0]["id"]
    assert versions[0]["created_at"]


def test_add_page_section_inserts_section_with_next_sort_order(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    project_id, page_data = _create_project_with_page(client, db_session, headers)
    existing_count = len(page_data["sections"])

    res = client.post(
        f"/api/v1/projects/{project_id}/page/sections",
        json={
            "section_type": "faq",
            "title": "자주 묻는 질문",
            "body_copy": "배송과 사용 방법을 확인해 주세요.",
            "associated_fact_ids": [],
        },
        headers=headers,
    )

    assert res.status_code == 201
    data = res.json()
    assert data["section_type"] == "faq"
    assert data["sort_order"] == existing_count
    assert data["is_visible"] is True
