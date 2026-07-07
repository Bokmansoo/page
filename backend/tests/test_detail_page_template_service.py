from src.db.models import Brand, PageSection, ProductPage, ProductProject, User, Workspace
from src.services.detail_page_template_service import DetailPageTemplateService


def test_template_selection_heuristics():
    assert (
        DetailPageTemplateService.select_template_id(
            "Living",
            {"selling_purpose": "제품 스펙 비교 및 구성품 안내"},
        )
        == "comparison_focused"
    )
    assert (
        DetailPageTemplateService.select_template_id(
            "Living",
            {"selling_purpose": "comparison of sizes"},
        )
        == "comparison_focused"
    )
    assert (
        DetailPageTemplateService.select_template_id(
            "Living",
            {"selling_purpose": "고급 브랜드 감성 전달"},
        )
        == "premium"
    )
    assert (
        DetailPageTemplateService.select_template_id(
            "Living",
            {"selling_purpose": "감성 라이프스타일 컷 중심"},
        )
        == "lifestyle"
    )
    assert (
        DetailPageTemplateService.select_template_id(
            "Living",
            {"selling_purpose": "기존 제품의 불편 해결"},
        )
        == "problem_solving"
    )
    assert (
        DetailPageTemplateService.select_template_id(
            "Living",
            {"selling_purpose": "초보 셀러도 쓰기 쉬운 안전한 안내"},
        )
        == "beginner_seller"
    )
    assert (
        DetailPageTemplateService.select_template_id(
            "Other",
            {"selling_purpose": "일반 판매"},
        )
        == "general_sales"
    )
    assert DetailPageTemplateService.select_template_id("Beauty", None) == "premium"
    assert DetailPageTemplateService.select_template_id("Living", None) == "problem_solving"


def test_page_section_template_properties():
    section = PageSection(
        page_id="dummy-page",
        section_type="problem",
        title="더운 날, 휴대용 선풍기만으로 부족할 때",
        body_copy="책상, 차량, 야외처럼 전원 연결이 번거로운 순간에도 바로 꺼내 쓸 수 있습니다.",
        associated_fact_ids=["fact-1", "fact-2"],
        visual_kind="image",
        visual_payload={"strategy": "text_only"},
        sort_order=0,
    )

    assert section.role == "문제 제기"
    assert section.headline == "더운 날, 휴대용 선풍기만으로 부족할 때"
    assert section.body == "책상, 차량, 야외처럼 전원 연결이 번거로운 순간에도 바로 꺼내 쓸 수 있습니다."
    assert section.evidence_fact_ids == ["fact-1", "fact-2"]
    assert section.visual_strategy == "text_only"
    assert section.editable is True


def test_detail_page_package_endpoint_returns_template_fields(client, db_session):
    user = User(id="user-temp", email="temp@example.com", name="Temp User")
    workspace = Workspace(id="workspace-temp", name="Temp Workspace", owner_id=user.id)
    brand = Brand(id="brand-temp", workspace_id=workspace.id, name="Temp Brand")
    project = ProductProject(
        id="project-temp",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="템플릿 상품",
        category="Living",
        status="ready",
    )
    page = ProductPage(
        id="page-temp",
        project_id=project.id,
    )
    section = PageSection(
        id="section-temp",
        page_id=page.id,
        section_type="hero",
        title="콘센트 없이 바로 시원하게",
        body_copy="책상과 차량, 야외에서도 휴대용 냉각 선풍기를 바로 사용할 수 있습니다.",
        associated_fact_ids=["fact-id-abc"],
        visual_kind="image",
        visual_payload={"strategy": "image_overlay"},
        sort_order=0,
    )
    db_session.add_all([user, workspace, brand, project, page, section])
    db_session.commit()

    response = client.get(
        f"/api/v1/projects/{project.id}/detail-page-package",
        headers={
            "X-Mock-User-Id": user.id,
            "X-Mock-Workspace-Id": workspace.id,
        },
    )

    assert response.status_code == 200
    data = response.json()
    section_data = data["copy_sections"][0]
    assert section_data["role"] == "메인 소구점 강조"
    assert section_data["headline"] == "콘센트 없이 바로 시원하게"
    assert section_data["body"] == "책상과 차량, 야외에서도 휴대용 냉각 선풍기를 바로 사용할 수 있습니다."
    assert section_data["evidence_fact_ids"] == ["fact-id-abc"]
    assert section_data["visual_strategy"] == "image_overlay"
    assert section_data["editable"] is True
