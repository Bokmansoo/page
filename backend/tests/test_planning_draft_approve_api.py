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


def test_approve_planning_draft_uses_product_cutout_as_generation_reference(client, db_session, monkeypatch, tmp_path):
    from src.services import image_generation_service

    monkeypatch.setattr(image_generation_service.settings, "SELLFORM_IMAGE_GENERATION_MODE", "mock")

    user = User(
        id="planning-cutout-user",
        email="planning-cutout@example.com",
        name="Planning Cutout User",
    )
    workspace = Workspace(
        id="planning-cutout-workspace",
        name="Planning Cutout Workspace",
        owner_id=user.id,
    )
    brand = Brand(id="planning-cutout-brand", workspace_id=workspace.id, name="Planning Cutout Brand")
    project = ProductProject(
        id="planning-cutout-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Lumena portable cooling fan",
        category="living",
        raw_input_text="wireless handheld cooling fan",
        status="draft",
        planning_draft={
            "cards": [
                {
                    "id": "card-hero",
                    "type": "hero",
                    "label": "Hero",
                    "title": "Use cool wind anywhere",
                    "bullets": [
                        "Portable fan for desk, car, and outdoor use.",
                        "Cordless comfort without moving power cables.",
                    ],
                    "visual_strategy": "image_overlay",
                    "source_fact_ids": [],
                    "sort_order": 0,
                    "is_enabled": True,
                },
                {
                    "id": "card-spec",
                    "type": "specifications",
                    "label": "Specs",
                    "title": "Check before purchase",
                    "bullets": ["Confirm charging type and included accessories."],
                    "visual_strategy": "text_only",
                    "source_fact_ids": [],
                    "sort_order": 1,
                    "is_enabled": True,
                },
            ]
        },
    )
    original_path = tmp_path / "original.png"
    cutout_path = tmp_path / "cutout.png"
    original_path.write_bytes(b"fake-original")
    cutout_path.write_bytes(b"fake-cutout")
    source_asset = Asset(
        id="source-product-asset",
        project_id=project.id,
        source_type="self_shot",
        filename="original.png",
        file_path=str(original_path),
        mime_type="image/png",
        file_size=13,
        background_removed=False,
        product_identity_preserved=True,
    )
    cutout_asset = Asset(
        id="cutout-product-asset",
        project_id=project.id,
        source_type="ai_corrected",
        filename="cutout.png",
        file_path=str(cutout_path),
        mime_type="image/png",
        file_size=11,
        source_asset_id=source_asset.id,
        cutout_status="completed",
        background_removed=True,
        product_identity_preserved=True,
    )
    db_session.add_all([user, workspace, brand, project, source_asset, cutout_asset])
    db_session.commit()

    response = client.post(
        "/api/v1/projects/planning-cutout-project/planning-draft/approve",
        headers={
            "X-Mock-User-Id": user.id,
            "X-Mock-Workspace-Id": workspace.id,
        },
    )

    assert response.status_code == 200

    jobs = (
        db_session.query(ImageGenerationJobRecord)
        .filter(ImageGenerationJobRecord.project_id == project.id)
        .all()
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job.role == "hero"
    assert job.source_asset_ids == [cutout_asset.id]
    assert job.preserve_product_identity is True
    assert "provided product cutout/reference" in job.prompt

    page = db_session.query(ProductPage).filter(ProductPage.project_id == project.id).one()
    hero = (
        db_session.query(PageSection)
        .filter(PageSection.page_id == page.id, PageSection.section_type == "hero")
        .one()
    )
    assert hero.body_copy == (
        "- Portable fan for desk, car, and outdoor use.\n"
        "- Cordless comfort without moving power cables."
    )
    spec = (
        db_session.query(PageSection)
        .filter(PageSection.page_id == page.id, PageSection.section_type == "specifications")
        .one()
    )
    assert spec.visual_kind == "html_graphic"
