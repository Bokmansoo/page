import pytest
from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import ProductProject, ProductFact, ProductPage

def _create_project(client, headers):
    res = client.post(
        "/api/v1/projects",
        json={"name": " 선풍기 ", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "Specs"},
        headers=headers
    )
    assert res.status_code == 201
    return res.json()["id"]

def test_style_candidates_flow(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # 1. Create project and fact
    p_id = _create_project(client, headers)
    fact = ProductFact(
        project_id=p_id,
        fact_text="18시간 무선 사용 가능",
        verification_status="confirmed"
    )
    db_session.add(fact)
    db_session.commit()

    # 2. GET candidates
    res = client.get(f"/api/v1/projects/{p_id}/style-candidates", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["candidates"]) == 3
    assert data["selected_key"] is None
    assert data["generation"] == 0

    # Check default recommend key is 'problem_solution'
    default_rec = [c for c in data["candidates"] if c["is_ai_recommended"]]
    assert len(default_rec) == 1
    assert default_rec[0]["key"] == "problem_solution"

    # 3. SELECT candidate
    sel_res = client.post(f"/api/v1/projects/{p_id}/style-candidates/lifestyle/select", headers=headers)
    assert sel_res.status_code == 200
    
    # DB verify
    project = db_session.query(ProductProject).filter(ProductProject.id == p_id).first()
    assert project.selected_style == "lifestyle"

    # GET again to verify selected_key
    res2 = client.get(f"/api/v1/projects/{p_id}/style-candidates", headers=headers)
    assert res2.json()["selected_key"] == "lifestyle"

    # 4. REGENERATE candidate with feedback
    regen_res = client.post(
        f"/api/v1/projects/{p_id}/style-candidates/regenerate",
        json={"feedback_option": "더 스펙 중심으로"},
        headers=headers
    )
    assert regen_res.status_code == 200
    regen_data = regen_res.json()
    new_rec = [c for c in regen_data["candidates"] if c["is_ai_recommended"]]
    assert len(new_rec) == 1
    assert new_rec[0]["key"] == "spec_focused"

    # generation must be incremented
    assert regen_data["generation"] == 1
    # previously selected style must NOT be overwritten by regenerate
    assert regen_data["selected_key"] == "lifestyle"

    # 5. CREATE page based on selected candidate (should default to style_preset=selected_style)
    page_res = client.post(
        f"/api/v1/projects/{p_id}/page",
        json={},
        headers=headers
    )
    assert page_res.status_code == 201
    page_data = page_res.json()
    assert len(page_data["sections"]) > 0
    # In mock page, it matches category frame section count (7 sections)
    assert len(page_data["sections"]) == 7


def test_regeneration_persists_a_new_generation_without_overwriting_selection(client, db_session):
    """기획 9절 Step 1 검증: 재추천 후 세대 번호 증가, 기존 선택 유지."""
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    p_id = _create_project(client, headers)

    # Select problem_solution first
    client.post(f"/api/v1/projects/{p_id}/style-candidates/problem_solution/select", headers=headers)

    # Regenerate with different feedback
    regen_res = client.post(
        f"/api/v1/projects/{p_id}/style-candidates/regenerate",
        json={"feedback_option": "더 감성적으로"},
        headers=headers
    )
    assert regen_res.status_code == 200
    data = regen_res.json()
    assert data["generation"] == 1
    # selected_key must remain as the previously selected value
    assert data["selected_key"] == "problem_solution"

    # Regenerate again
    regen_res2 = client.post(
        f"/api/v1/projects/{p_id}/style-candidates/regenerate",
        json={"feedback_option": "더 스펙 중심으로"},
        headers=headers
    )
    assert regen_res2.json()["generation"] == 2
    assert regen_res2.json()["selected_key"] == "problem_solution"


def test_select_style_candidate_rejects_invalid_key(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    p_id = _create_project(client, headers)

    res = client.post(f"/api/v1/projects/{p_id}/style-candidates/not-a-style/select", headers=headers)

    assert res.status_code == 400
    assert res.json()["detail"] == "Invalid style candidate key"

    project = db_session.query(ProductProject).filter(ProductProject.id == p_id).first()
    assert project.selected_style is None


def test_style_candidates_still_generate_after_sprint42_intake(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    p_id = _create_project(client, headers)

    intake_res = client.post(
        f"/api/v1/projects/{p_id}/intake",
        json={
            "urls": [],
            "description": "오가닉 대나무 테이블 매트",
            "asset_ids": [],
            "reference_urls": [],
            "competitor_urls": [],
        },
        headers=headers,
    )
    assert intake_res.status_code == 200

    res = client.get(f"/api/v1/projects/{p_id}/style-candidates", headers=headers)

    assert res.status_code == 200
    data = res.json()
    assert len(data["candidates"]) == 3
    project = db_session.query(ProductProject).filter(ProductProject.id == p_id).first()
    assert isinstance(project.style_candidates_snapshot, list)
