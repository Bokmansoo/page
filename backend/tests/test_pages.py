from types import SimpleNamespace

import pytest
from src.api.auth import DEFAULT_BRAND_ID
from src.api.pages import create_page_snapshot
from src.db.models import Asset, DetailPageVersion, ProductProject, ProductFact, ProductPage, PageSection, PageVersion
from src.services.page_generator import PageGenerationService


def _create_project_with_page(client, db_session, headers=None):
    headers = headers or {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Sprint 4 Page", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "Spec sheet"},
        headers=headers
    )
    assert create_res.status_code == 201
    project_id = create_res.json()["id"]

    fact = ProductFact(
        project_id=project_id,
        fact_text="가벼운 소재입니다.",
        source_text="light material",
        verification_status="confirmed"
    )
    db_session.add(fact)
    db_session.commit()

    page_res = client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers
    )
    assert page_res.status_code == 201
    return project_id, page_res.json()

# 기본적으로 conftest에서 제공하는 클라이언트 및 db_session fixture 활용

def test_create_page_and_filter_unconfirmed_facts(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    
    # 1. API를 통해 프로젝트 직접 생성
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Test Shirt", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "Spec sheet"},
        headers=headers
    )
    assert create_res.status_code == 201
    p_id = create_res.json()["id"]

    # 2. 사실 카드 추가 (1개 확정, 1개 미확정)
    fact_confirmed = ProductFact(
        project_id=p_id,
        fact_text="100% 실크 원단으로 제작되어 매우 가볍습니다.",
        source_text="Silk 100%",
        verification_status="confirmed"
    )
    fact_unconfirmed = ProductFact(
        project_id=p_id,
        fact_text="평생 변색이 되지 않는 완벽한 코팅 처리가 적용되었습니다.",
        source_text="No fading coating",
        verification_status="unknown"  # 미확정
    )
    db_session.add(fact_confirmed)
    db_session.add(fact_unconfirmed)
    db_session.commit()

    # 3. AI 상세페이지 초안 생성 API 호출
    res = client.post(
        f"/api/v1/projects/{p_id}/page",
        json={"style_preset": "modern"},
        headers=headers
    )
    assert res.status_code == 201
    data = res.json()
    assert data["project_id"] == p_id
    assert len(data["sections"]) > 0

    # 4. 검증: 미확정 사실은 경고 리스트(warnings)로만 전달되었는지 검사
    sections = data["sections"]
    for sec in sections:
        # 미확정 사실 텍스트가 경고 리스트에 들어가 있는지 확인
        assert "평생 변색이 되지 않는 완벽한 코팅 처리가 적용되었습니다." in sec["warnings"]


def test_save_page_and_automatic_versioning(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    
    # 1. 프로젝트 생성
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Versioning Test Shirt", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "Specs"},
        headers=headers
    )
    assert create_res.status_code == 201
    p_id = create_res.json()["id"]

    # 2. 상세페이지 초안 생성
    client.post(
        f"/api/v1/projects/{p_id}/page",
        json={"style_preset": "modern"},
        headers=headers
    )

    # 3. 현재 생성된 상세페이지 획득
    page_res = client.get(f"/api/v1/projects/{p_id}/page", headers=headers)
    assert page_res.status_code == 200
    page_data = page_res.json()
    
    sections = page_data["sections"]
    assert len(sections) > 0
    
    # 4. 수정 요청 데이터 조립 (대표 색상과 첫 번째 섹션 타이틀 변경)
    target_sec = sections[0]
    updated_sections = [
        {
            "id": target_sec["id"],
            "title": "변경된 새 소제목",
            "body_copy": target_sec["body_copy"],
            "image_asset_id": target_sec["image_asset_id"],
            "sort_order": target_sec["sort_order"],
            "is_visible": target_sec["is_visible"]
        }
    ]
    # 나머지 섹션도 정렬 순서 유지하여 추가
    for sec in sections[1:]:
        updated_sections.append({
            "id": sec["id"],
            "title": sec["title"],
            "body_copy": sec["body_copy"],
            "image_asset_id": sec["image_asset_id"],
            "sort_order": sec["sort_order"],
            "is_visible": sec["is_visible"]
        })

    # 오토세이브/업데이트 PATCH 호출
    save_res = client.patch(
        f"/api/v1/projects/{p_id}/page",
        json={
            "theme_color": "#FF5733",
            "font_family": "serif",
            "sections": updated_sections
        },
        headers=headers
    )
    assert save_res.status_code == 200
    updated_data = save_res.json()
    assert updated_data["theme_color"] == "#FF5733"
    assert updated_data["font_family"] == "serif"
    assert updated_data["sections"][0]["title"] == "변경된 새 소제목"

    # 버전 이력(DetailPageVersion)이 데이터베이스에 안전하게 적재되었는지 확인
    from src.db.models import DetailPageVersion
    versions = db_session.query(DetailPageVersion).filter(DetailPageVersion.project_id == p_id).all()
    assert len(versions) == 2  # 초안 생성시 1개, PATCH(수정) 호출시 1개 총 2개
    
    # 두 번째 버전(최신 버전, 사용자 수정) 검증
    latest_version = sorted(versions, key=lambda v: v.created_at)[1]
    assert latest_version.name == "사용자 수정"
    assert latest_version.style_key == "problem_solution"
    assert latest_version.sections[0]["title"] == "변경된 새 소제목"


def test_restore_page_version(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    
    # 1. 프로젝트 생성
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Restore Test Shirt", "brand_id": DEFAULT_BRAND_ID},
        headers=headers
    )
    p_id = create_res.json()["id"]

    # 2. 페이지 생성
    client.post(
        f"/api/v1/projects/{p_id}/page",
        json={"style_preset": "modern"},
        headers=headers
    )

    # 3. 현재 페이지 로드 및 수정하여 버전 유발
    page_res = client.get(f"/api/v1/projects/{p_id}/page", headers=headers)
    page_data = page_res.json()
    sections = page_data["sections"]
    
    updated_sections = []
    for idx, sec in enumerate(sections):
        updated_sections.append({
            "id": sec["id"],
            "title": "수정 타이틀" if idx == 0 else sec["title"],
            "body_copy": sec["body_copy"],
            "image_asset_id": sec["image_asset_id"],
            "sort_order": sec["sort_order"],
            "is_visible": sec["is_visible"]
        })

    # PATCH 호출하여 버전 1 생성
    client.patch(
        f"/api/v1/projects/{p_id}/page",
        json={
            "theme_color": "#FF5733",
            "font_family": "serif",
            "sections": updated_sections
        },
        headers=headers
    )

    # DetailPageVersion 획득 (초안 버전)
    from src.db.models import DetailPageVersion
    versions = db_session.query(DetailPageVersion).filter(DetailPageVersion.project_id == p_id).all()
    draft_version = [v for v in versions if v.name == "AI 초안 생성"][0]
    v_id = draft_version.id

    # 4. 롤백 복원 API 호출
    restore_res = client.post(
        f"/api/v1/projects/{p_id}/page/versions/{v_id}/restore",
        headers=headers
    )
    assert restore_res.status_code == 200
    restored_data = restore_res.json()
    
    # 검증: 복원 후 테마 색상이 이전 값(#3B82F6)으로 원복되었는지 확인
    assert restored_data["theme_color"] == "#3B82F6"
    assert restored_data["font_family"] == "sans-serif"
    assert len(restored_data["sections"]) == len(draft_version.sections)
    # 첫 섹션의 타이틀도 원래대로 원상복구되었는지 검증
    assert restored_data["sections"][0]["title"] != "수정 타이틀"


def test_restore_page_version_preserves_fact_and_image_mappings(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Snapshot Mapping Test", "brand_id": DEFAULT_BRAND_ID},
        headers=headers
    )
    assert create_res.status_code == 201
    project_id = create_res.json()["id"]

    fact = ProductFact(
        project_id=project_id,
        fact_text="4,800mAh 배터리",
        source_text="4,800mAh",
        verification_status="confirmed"
    )
    asset = Asset(
        project_id=project_id,
        source_type="sourced",
        filename="fan-spec.png",
        file_path="/tmp/fan-spec.png",
        mime_type="image/png",
        file_size=123
    )
    page = ProductPage(
        project_id=project_id,
        theme_color="#111111",
        font_family="sans-serif"
    )
    db_session.add_all([fact, asset, page])
    db_session.flush()

    section = PageSection(
        page_id=page.id,
        section_type="features",
        title="대용량 배터리",
        body_copy="4,800mAh 배터리로 오래 사용할 수 있습니다.",
        associated_fact_ids=[fact.id],
        image_asset_id=asset.id,
        sort_order=0,
        is_visible=True
    )
    db_session.add(section)
    db_session.flush()

    version = DetailPageVersion(
        project_id=project_id,
        name="근거 매핑 스냅샷",
        style_key="problem_solution",
        sections_json={
            "theme_color": "#111111",
            "font_family": "sans-serif",
            "sections": [
                {
                    "section_type": "features",
                    "title": "대용량 배터리",
                    "body_copy": "4,800mAh 배터리로 오래 사용할 수 있습니다.",
                    "associated_fact_ids": [fact.id],
                    "image_asset_id": asset.id,
                    "sort_order": 0,
                    "is_visible": True,
                }
            ],
            "facts_snapshot": [
                {
                    "id": fact.id,
                    "fact_text": fact.fact_text,
                    "source_text": fact.source_text,
                    "verification_status": fact.verification_status,
                    "source_asset_id": fact.source_asset_id,
                }
            ],
            "assets_snapshot": [
                {
                    "id": asset.id,
                    "filename": asset.filename,
                    "source_type": asset.source_type,
                    "mime_type": asset.mime_type,
                }
            ],
        },
        is_final=False
    )
    db_session.add(version)
    db_session.commit()

    restore_res = client.post(
        f"/api/v1/projects/{project_id}/page/versions/{version.id}/restore",
        headers=headers
    )

    assert restore_res.status_code == 200
    restored_section = restore_res.json()["sections"][0]
    assert restored_section["associated_fact_ids"] == [fact.id]
    assert restored_section["image_asset_id"] == asset.id


def test_page_snapshot_includes_fact_and_asset_evidence(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Evidence Snapshot Test", "brand_id": DEFAULT_BRAND_ID},
        headers=headers
    )
    assert create_res.status_code == 201
    project = db_session.query(ProductProject).filter(
        ProductProject.id == create_res.json()["id"]
    ).first()

    fact = ProductFact(
        project_id=project.id,
        fact_text="4,800mAh 배터리",
        source_text="상세 스펙 4,800mAh",
        verification_status="confirmed",
        extraction_source="manual_text",
        confidence=0.98,
    )
    asset = Asset(
        project_id=project.id,
        source_type="sourced",
        filename="fan-main.png",
        file_path="/tmp/fan-main.png",
        mime_type="image/png",
        file_size=123,
    )
    page = ProductPage(
        project_id=project.id,
        theme_color="#2563EB",
        font_family="sans-serif",
    )
    db_session.add_all([fact, asset, page])
    db_session.flush()

    section = PageSection(
        page_id=page.id,
        section_type="features",
        title="대용량 배터리",
        body_copy="4,800mAh 배터리를 탑재했습니다.",
        associated_fact_ids=[fact.id],
        image_asset_id=asset.id,
        sort_order=0,
        is_visible=True,
    )
    db_session.add(section)
    db_session.commit()
    db_session.refresh(page)

    snapshot = create_page_snapshot(page, db_session)

    assert snapshot["category"] == project.category
    assert snapshot["style_key"] == project.selected_style
    assert snapshot["sections"][0]["associated_fact_ids"] == [fact.id]
    assert snapshot["sections"][0]["image_asset_id"] == asset.id
    assert snapshot["facts_snapshot"][0]["id"] == fact.id
    assert snapshot["facts_snapshot"][0]["fact_text"] == "4,800mAh 배터리"
    assert snapshot["assets_snapshot"][0]["id"] == asset.id
    assert snapshot["assets_snapshot"][0]["filename"] == "fan-main.png"


def test_create_page_with_problem_solution_template_generates_expected_section_order(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    
    # 1. 프로젝트 생성
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Sprint 13 Project", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "Spec sheet"},
        headers=headers
    )
    assert create_res.status_code == 201
    project_id = create_res.json()["id"]

    # 2. 사실 카드 추가 (확정 상태)
    fact = ProductFact(
        project_id=project_id,
        fact_text="가벼운 소재입니다.",
        source_text="light material",
        verification_status="confirmed"
    )
    db_session.add(fact)
    db_session.commit()

    # 3. problem_solution 템플릿으로 생성 API 호출
    response = client.post(
        f"/api/v1/projects/{project_id}/page",
        json={
            "style_preset": "modern",
            "narrative_template": "problem_solution",
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    section_types = [section["section_type"] for section in body["sections"]]
    assert section_types == [
        "problem_statement",
        "main_claim",
        "secondary_benefit",
        "main_claim_support",
        "benefit_list",
        "summary_claim",
        "product_information",
    ]


def test_create_page_rejects_unknown_narrative_template(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    project_id, _ = _create_project_with_page(client, db_session, headers)

    response = client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"narrative_template": "unsupported_template"},
        headers=headers,
    )

    assert response.status_code == 422


def test_problem_solution_main_claim_varies_by_category():
    service = PageGenerationService()
    facts = [{"id": "fact-1", "fact_text": "가벼운 소재입니다."}]

    fashion = service._get_problem_solution_mock_page("Fashion", facts)
    living = service._get_problem_solution_mock_page("Living", facts)

    assert fashion.sections[1].title != living.sections[1].title
    assert fashion.sections[1].body_copy != living.sections[1].body_copy


def test_problem_solution_uses_fallback_when_llm_returns_wrong_section_order(monkeypatch):
    invalid_sections = [
        {
            "section_type": "main_claim",
            "title": "Wrong first section",
            "body_copy": "가벼운 소재입니다.",
            "associated_fact_ids": ["fact-1"],
        }
    ]

    class FakeMessages:
        def create(self, **_kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", input={
                    "theme_color": "#3B82F6",
                    "font_family": "sans-serif",
                    "sections": invalid_sections,
                })]
            )

    service = PageGenerationService(api_key="test-key")
    service.client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr("src.services.page_generator.settings.SELLFORM_RAG_RUNTIME_MOCK", False)

    page = service.generate_page(
        category="Living",
        confirmed_facts=[{"id": "fact-1", "fact_text": "가벼운 소재입니다."}],
        narrative_template="problem_solution",
    )

    assert [section.section_type for section in page.sections] == [
        "problem_statement",
        "main_claim",
        "secondary_benefit",
        "main_claim_support",
        "benefit_list",
        "summary_claim",
        "product_information",
    ]
