from src.db.models import (
    Asset,
    Brand,
    ImageGenerationJobRecord,
    PageSection,
    ProductPage,
    ProductProject,
    User,
    Workspace,
)


HEADERS = {
    "X-Mock-User-Id": "planning-approve-user",
    "X-Mock-Workspace-Id": "planning-approve-workspace",
}


def test_approve_planning_draft_generates_and_applies_image_candidates(client, db_session, monkeypatch):
    from src.services import image_generation_service

    monkeypatch.setattr(image_generation_service.settings, "SELLFORM_IMAGE_GENERATION_MODE", "mock")

    user = User(
        id=HEADERS["X-Mock-User-Id"],
        email="planning@example.com",
        name="Planning User",
    )
    workspace = Workspace(
        id=HEADERS["X-Mock-Workspace-Id"],
        name="Planning Workspace",
        owner_id=user.id,
    )
    brand = Brand(id="planning-brand", workspace_id=workspace.id, name="Planning Brand")
    project = ProductProject(
        id="planning-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="루메나 휴대용 무선 냉각선풍기",
        category="생활용품/리빙",
        raw_input_text="루메나 휴대용 무선 냉각선풍기",
        status="draft",
        planning_draft={
            "cards": [
                {
                    "id": "card-hero",
                    "type": "hero",
                    "label": "히어로",
                    "title": "콘센트 없이 시원하게",
                    "bullets": ["필요한 순간 바로 쓰는 휴대용 냉각선풍기"],
                    "visual_strategy": "image_overlay",
                    "source_fact_ids": [],
                    "sort_order": 0,
                    "is_enabled": True,
                },
                {
                    "id": "card-spec",
                    "type": "specifications",
                    "label": "스펙",
                    "title": "구매 전 확인",
                    "bullets": ["사용 시간과 충전 방식을 확인하세요"],
                    "visual_strategy": "text_only",
                    "source_fact_ids": [],
                    "sort_order": 1,
                    "is_enabled": True,
                },
            ]
        },
    )
    db_session.add_all([user, workspace, brand, project])
    db_session.commit()

    response = client.post(
        "/api/v1/projects/planning-project/planning-draft/approve",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["image_job_count"] == 1

    page = db_session.query(ProductPage).filter(ProductPage.project_id == project.id).one()
    hero = (
        db_session.query(PageSection)
        .filter(PageSection.page_id == page.id, PageSection.section_type == "hero")
        .one()
    )
    job = (
        db_session.query(ImageGenerationJobRecord)
        .filter(ImageGenerationJobRecord.project_id == project.id)
        .one()
    )

    assert job.section_id == hero.id
    assert job.output_asset_id
    assert job.status == "approved"
    assert hero.image_asset_id == job.output_asset_id
    assert db_session.query(Asset).filter(Asset.id == job.output_asset_id).one().mime_type == "image/png"

    page_response = client.get("/api/v1/projects/planning-project/page", headers=HEADERS)
    assert page_response.status_code == 200
    hero_payload = next(section for section in page_response.json()["sections"] if section["section_type"] == "hero")
    assert hero_payload["image_asset_id"] == job.output_asset_id
    assert hero_payload["image_candidates"][0]["asset_id"] == job.output_asset_id
