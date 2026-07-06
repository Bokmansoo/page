import pytest
from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import ProductFact, ProductPage


def test_copy_rewrite_preview_does_not_mutate_section(client, db_session, monkeypatch):
    from src.api import pages

    monkeypatch.setattr(pages.settings, "SELLFORM_GENERATION_MODE", "mock")
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    created = client.post(
        "/api/v1/projects",
        json={"name": "Copy rewrite", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "무선 사용"},
        headers=headers,
    )
    project_id = created.json()["id"]
    db_session.add(
        ProductFact(
            project_id=project_id,
            fact_text="무선으로 사용할 수 있음",
            source_text="상품 설명",
            verification_status="confirmed",
        )
    )
    db_session.commit()
    assert client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers,
    ).status_code == 201
    page = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).one()
    section = page.sections[0]
    original = (section.title, section.body_copy)
    response = client.post(
        f"/api/v1/projects/{project_id}/page/sections/{section.id}/copy-rewrite/preview",
        json={"command": "stronger_headline", "instruction": "", "scope": "section"},
        headers=headers,
    )
    assert response.status_code == 200
    db_session.refresh(section)
    assert (section.title, section.body_copy) == original
    assert response.json()["title"] != original[0]


def test_copy_rewrite_preview_returns_404_for_nonexistent_section(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    response = client.post(
        "/api/v1/projects/nonexistent/page/sections/bad-id/copy-rewrite/preview",
        json={"command": "stronger_headline", "instruction": ""},
        headers=headers,
    )
    assert response.status_code == 404


def test_old_ai_edit_returns_410(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    created = client.post(
        "/api/v1/projects",
        json={"name": "Old AI Edit", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "test"},
        headers=headers,
    )
    project_id = created.json()["id"]
    assert client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers,
    ).status_code == 201

    response = client.post(
        f"/api/v1/projects/{project_id}/pages/ai-edit",
        headers=headers,
        json={"section_id": "hero", "command": "제목을 더 강하게"},
    )
    assert response.status_code == 410
    assert "copy-rewrite/preview" in response.json()["detail"]["new_endpoint"]


def test_old_section_ai_edit_returns_410(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    created = client.post(
        "/api/v1/projects",
        json={"name": "Old section AI Edit", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "test"},
        headers=headers,
    )
    project_id = created.json()["id"]
    assert client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers,
    ).status_code == 201

    page = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).one()
    section = page.sections[0]

    response = client.post(
        f"/api/v1/projects/{project_id}/page/sections/{section.id}/ai-edit",
        headers=headers,
        json={
            "section_id": section.id,
            "command_type": "stronger_headline",
            "freeform_instruction": "",
            "scope": "section",
        },
    )
    assert response.status_code == 410
    assert "copy-rewrite/preview" in response.json()["detail"]["new_endpoint"]


def test_copy_rewrite_preview_returns_mock_proposal(
    client,
    db_session,
):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    created = client.post(
        "/api/v1/projects",
        json={"name": "Mock copy rewrite", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "무선 사용"},
        headers=headers,
    )
    project_id = created.json()["id"]
    assert client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers,
    ).status_code == 201
    page = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).one()
    section = page.sections[0]

    response = client.post(
        f"/api/v1/projects/{project_id}/page/sections/{section.id}/copy-rewrite/preview",
        json={"command": "stronger_headline", "instruction": "", "scope": "section"},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] != page.sections[0].title
    assert "[AI 수정됨]" not in data["title"]
    assert "[AI 수정됨]" not in data["body_copy"]
    assert "title" in data
    assert "body_copy" in data
    assert "change_summary" in data
