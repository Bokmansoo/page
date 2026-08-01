from pathlib import Path

from PIL import Image

from src.agents.nodes.image_generation.agent import ImageGenerationAgent
from src.agents.state import AgentRunState
from src.api.pages import get_image_candidates_for_section
from src.db.models import Asset, ImageGenerationJobRecord, PageSection, ProductPage, ProductProject
from src.services.detail_page_orchestrator import DetailPageOrchestrator
from src.services.image_asset_inspector import (
    apply_asset_inspection,
    backfill_project_asset_metadata,
    refresh_representative_product_asset,
)
from src.services.local_image_upscale import create_auto_upscale_preview
from src.services.image_asset_mapper import map_image_assets_to_sections
from src.services.page_asset_policy import clear_unconfirmed_low_quality_hero_assignments


def _project(db_session, project_id="asset-classification-project"):
    project = ProductProject(
        id=project_id,
        workspace_id="ws-1",
        brand_id="brand-1",
        name="Asset Classification Product",
        status="draft",
    )
    db_session.add(project)
    db_session.commit()
    return project


def _image_asset(db_session, project_id, tmp_path: Path, asset_id, filename, size=(1200, 1200)):
    image_path = tmp_path / f"{asset_id}.png"
    Image.new("RGB", size, color="white").save(image_path)
    asset = Asset(
        id=asset_id,
        project_id=project_id,
        source_type="uploaded",
        filename=filename,
        file_path=str(image_path),
        mime_type="image/png",
        file_size=image_path.stat().st_size,
    )
    db_session.add(asset)
    db_session.flush()
    return asset


def test_inspector_persists_role_dimensions_and_usable_quality(db_session, tmp_path):
    project = _project(db_session)
    asset = _image_asset(
        db_session, project.id, tmp_path, "main-image", "massage-gun-main-front.png"
    )

    apply_asset_inspection(asset, db_session)
    db_session.commit()

    assert asset.asset_role == "product_main"
    assert asset.role_confidence >= 0.5
    assert asset.width == 1200
    assert asset.height == 1200
    assert asset.image_format == "PNG"
    assert asset.quality_status == "usable"
    assert asset.identity_status == "needs_review"


def test_inspector_warns_for_low_resolution_extreme_ratio_and_duplicate(db_session, tmp_path):
    project = _project(db_session)
    first = _image_asset(
        db_session, project.id, tmp_path, "first-image", "product-main.png", size=(300, 1100)
    )
    apply_asset_inspection(first, db_session)
    db_session.commit()

    duplicate = Asset(
        id="duplicate-image",
        project_id=project.id,
        source_type="uploaded",
        filename="product-main-copy.png",
        file_path=first.file_path,
        mime_type="image/png",
        file_size=first.file_size,
    )
    db_session.add(duplicate)
    db_session.flush()
    apply_asset_inspection(duplicate, db_session)
    db_session.commit()

    assert first.quality_status == "warning"
    assert {"LOW_RESOLUTION", "EXTREME_ASPECT_RATIO"}.issubset(first.quality_warnings)
    assert duplicate.quality_status == "warning"
    assert "DUPLICATE_FILE" in duplicate.quality_warnings


def test_low_resolution_seller_upload_gets_an_unselected_upscale_preview(db_session, tmp_path, monkeypatch):
    project = _project(db_session, project_id="auto-upscale-preview-project")
    source = _image_asset(
        db_session,
        project.id,
        tmp_path,
        "auto-upscale-source",
        "small-product-main.png",
        size=(300, 300),
    )
    apply_asset_inspection(source, db_session)
    refresh_representative_product_asset(project.id, db_session)

    from src.config import settings
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "upscaled"))
    preview = create_auto_upscale_preview(source, db_session)
    db_session.commit()

    assert preview is not None
    assert preview.source_type == "local_upscaled"
    assert preview.source_asset_id == source.id
    assert (preview.width, preview.height) == (1200, 1200)
    assert preview.quality_status == "usable"
    assert preview.is_representative is False
    assert source.is_representative is True


def test_corrupt_file_is_rejected_but_manual_role_is_not_overwritten(db_session, tmp_path):
    project = _project(db_session)
    bad_path = tmp_path / "broken.jpg"
    bad_path.write_bytes(b"not an image")
    asset = Asset(
        id="corrupt-image",
        project_id=project.id,
        source_type="uploaded",
        filename="detail-closeup.jpg",
        file_path=str(bad_path),
        mime_type="image/jpeg",
        file_size=bad_path.stat().st_size,
        asset_role="components",
        role_source="manual",
    )
    db_session.add(asset)
    db_session.flush()
    apply_asset_inspection(asset, db_session)

    assert asset.asset_role == "components"
    assert asset.quality_status == "rejected"
    assert asset.quality_warnings == ["IMAGE_FILE_CORRUPT"]


def test_backfill_and_mapper_do_not_auto_assign_warning_asset_to_hero(db_session, tmp_path):
    project = _project(db_session)
    asset = _image_asset(
        db_session, project.id, tmp_path, "low-main", "product-main.png", size=(300, 300)
    )
    db_session.commit()

    assert backfill_project_asset_metadata(project.id, db_session) == 1
    assignments = map_image_assets_to_sections(
        [{"id": "hero", "section_type": "hero"}],
        [{
            "id": asset.id,
            "filename": asset.filename,
            "mime_type": asset.mime_type,
            "source_type": asset.source_type,
            "asset_role": asset.asset_role,
                "role_confidence": asset.role_confidence,
                "quality_status": asset.quality_status,
                "quality_warnings": asset.quality_warnings,
            }],
    )

    assert asset.quality_status == "warning"
    assert assignments == []


def test_largest_clear_product_photo_is_auto_representative_and_ocr_is_a_signal(db_session, tmp_path):
    project = _project(db_session)
    smaller = _image_asset(
        db_session, project.id, tmp_path, "small-main", "product-main-front.png", size=(900, 900)
    )
    larger = _image_asset(
        db_session, project.id, tmp_path, "large-main", "product-main-hero.png", size=(1600, 1600)
    )
    ocr_asset = _image_asset(
        db_session, project.id, tmp_path, "ocr-package", "photo.png", size=(1200, 1200)
    )
    ocr_asset.ocr_text = "패키지 구성품 안내"
    for asset in (smaller, larger, ocr_asset):
        apply_asset_inspection(asset, db_session)

    selected = refresh_representative_product_asset(project.id, db_session)
    db_session.commit()

    assert selected.id == larger.id
    assert larger.is_representative is True
    assert smaller.is_representative is False
    assert ocr_asset.asset_role in {"package", "components"}


def test_manual_representative_api_keeps_exactly_one_primary_asset(client, db_session):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }
    project = ProductProject(
        id="classification-api-project",
        workspace_id=headers["X-Mock-Workspace-Id"],
        brand_id="brand-1",
        name="대표 이미지 선택",
        status="draft",
    )
    first = Asset(
        id="classification-api-first",
        project_id=project.id,
        source_type="uploaded",
        filename="first-main.jpg",
        file_path="https://cdn.example.com/first-main.jpg",
        mime_type="image/jpeg",
        file_size=0,
        asset_role="product_main",
        is_representative=True,
        representative_source="auto",
    )
    second = Asset(
        id="classification-api-second",
        project_id=project.id,
        source_type="uploaded",
        filename="second-main.jpg",
        file_path="https://cdn.example.com/second-main.jpg",
        mime_type="image/jpeg",
        file_size=0,
    )
    db_session.add_all([project, first, second])
    db_session.commit()

    response = client.patch(
        f"/api/v1/projects/{project.id}/assets/{second.id}/classification",
        headers=headers,
        json={"is_representative": True},
    )

    assert response.status_code == 200
    assert response.json()["is_representative"] is True
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.is_representative is False
    assert second.is_representative is True
    assert second.representative_source == "manual"
    assert second.asset_role == "product_main"


def test_low_quality_hero_requires_explicit_server_confirmation(client, db_session):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }
    project = ProductProject(
        id="low-quality-hero-project",
        workspace_id=headers["X-Mock-Workspace-Id"],
        brand_id="brand-1",
        name="저품질 HERO 확인",
        status="draft",
    )
    page = ProductPage(id="low-quality-hero-page", project_id=project.id)
    asset = Asset(
        id="low-quality-hero-asset",
        project_id=project.id,
        source_type="uploaded",
        filename="small-main.jpg",
        file_path="https://cdn.example.com/small-main.jpg",
        mime_type="image/jpeg",
        file_size=0,
        quality_status="warning",
        quality_warnings=["LOW_RESOLUTION"],
    )
    section = PageSection(
        id="low-quality-hero-section",
        page_id=page.id,
        section_type="hero",
        title="Hero",
        body_copy="Body",
        sort_order=0,
        is_visible=True,
    )
    db_session.add_all([project, page, asset, section])
    db_session.commit()
    payload = {
        "sections": [{
            "id": section.id,
            "title": section.title,
            "body_copy": section.body_copy,
            "image_asset_id": asset.id,
            "sort_order": 0,
            "is_visible": True,
        }],
    }

    blocked = client.patch(f"/api/v1/projects/{project.id}/page", headers=headers, json=payload)
    assert blocked.status_code == 409

    allowed = client.patch(
        f"/api/v1/projects/{project.id}/page",
        headers=headers,
        json={**payload, "confirm_low_quality_hero": True},
    )
    assert allowed.status_code == 200


def test_agent_run_never_auto_recommends_low_quality_photo_for_hero():
    state = AgentRunState(
        project_id="asset-classification-project",
        outputs={
            "source_collection": {
                "uploaded_images": [
                    {
                        "asset_id": "low",
                        "filename": "product-main-small.jpg",
                        "source_type": "uploaded",
                        "quality_warnings": ["LOW_RESOLUTION"],
                    },
                    {
                        "asset_id": "representative",
                        "filename": "product-main-large.jpg",
                        "source_type": "uploaded",
                        "is_representative": True,
                        "quality_warnings": [],
                    },
                ],
                "url_images": [],
            },
            "visual_planning": {
                "visual_slots": [{"slot_id": "hero", "role": "representative_product"}]
            },
        },
    )

    output = ImageGenerationAgent().run(state).outputs["image_generation"]
    candidates = output["candidates"]["hero"]

    assert next(candidate for candidate in candidates if candidate["asset_id"] == "representative")["is_recommended"] is True
    assert next(candidate for candidate in candidates if candidate["asset_id"] == "low")["is_recommended"] is False


def test_auto_upscale_preview_is_visible_but_not_auto_recommended_for_hero():
    state = AgentRunState(
        project_id="auto-upscale-preview-project",
        outputs={
            "source_collection": {
                "uploaded_images": [
                    {
                        "asset_id": "low-original",
                        "filename": "small-product.png",
                        "source_type": "uploaded",
                        "quality_warnings": ["LOW_RESOLUTION"],
                        "is_representative": True,
                    },
                    {
                        "asset_id": "upscale-preview",
                        "filename": "small-product-upscaled.png",
                        "source_type": "local_upscaled",
                        "quality_status": "usable",
                        "quality_warnings": [],
                    },
                ],
                "url_images": [],
            },
            "visual_planning": {
                "visual_slots": [{"slot_id": "hero", "role": "representative_product"}]
            },
        },
    )

    candidates = ImageGenerationAgent().run(state).outputs["image_generation"]["candidates"]["hero"]

    preview = next(candidate for candidate in candidates if candidate["asset_id"] == "upscale-preview")
    assert preview["source_type"] == "local_upscaled"
    assert preview["is_recommended"] is False


def test_generation_job_candidate_uses_linked_uploaded_asset_provenance(db_session, tmp_path):
    project = _project(db_session, project_id="candidate-provenance-project")
    asset = _image_asset(
        db_session,
        project.id,
        tmp_path,
        "candidate-provenance-asset",
        "seller-product-photo.png",
    )
    job = ImageGenerationJobRecord(
        project_id=project.id,
        job_id="candidate-provenance-job",
        section_id="candidate-provenance-hero",
        role="hero",
        prompt="Use the existing seller photo",
        status="completed",
        output_asset_id=asset.id,
    )
    db_session.add(job)
    db_session.commit()

    section = type("Section", (), {"id": "candidate-provenance-hero"})()
    candidates = get_image_candidates_for_section(section, db_session, project.id)

    assert candidates[0]["source_type"] == "uploaded"
    assert candidates[0]["label"] == "seller-product-photo.png"


def test_low_quality_hero_job_keeps_original_photo_visible_for_review(db_session, tmp_path):
    project = _project(db_session, project_id="low-quality-candidate-project")
    asset = _image_asset(
        db_session,
        project.id,
        tmp_path,
        "low-quality-candidate-asset",
        "small-seller-product-photo.png",
        size=(300, 300),
    )
    apply_asset_inspection(asset, db_session)
    job = ImageGenerationJobRecord(
        project_id=project.id,
        job_id="low-quality-candidate-job",
        section_id="low-quality-candidate-hero",
        role="hero",
        source_asset_ids=[asset.id],
        prompt="Use the original product photo",
        status="skipped",
        provider="source_required",
        error_code="LOW_QUALITY_HERO_SOURCE",
    )
    db_session.add(job)
    db_session.commit()

    section = type("Section", (), {"id": "low-quality-candidate-hero"})()
    candidates = get_image_candidates_for_section(section, db_session, project.id)

    assert candidates[0]["asset_id"] == asset.id
    assert candidates[0]["source_type"] == "uploaded"
    assert candidates[0]["status"] == "quality_review_required"
    assert "LOW_RESOLUTION" in candidates[0]["quality_warnings"]


def test_low_quality_hero_shows_auto_upscale_as_manual_candidate(db_session, tmp_path, monkeypatch):
    project = _project(db_session, project_id="auto-upscale-candidate-project")
    source = _image_asset(
        db_session,
        project.id,
        tmp_path,
        "auto-upscale-candidate-source",
        "small-seller-product-photo.png",
        size=(300, 300),
    )
    apply_asset_inspection(source, db_session)
    from src.config import settings
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "upscaled-candidate"))
    preview = create_auto_upscale_preview(source, db_session)
    job = ImageGenerationJobRecord(
        project_id=project.id,
        job_id="auto-upscale-candidate-job",
        section_id="auto-upscale-candidate-hero",
        role="hero",
        source_asset_ids=[source.id],
        prompt="Use the seller product photo",
        status="skipped",
        provider="source_required",
        error_code="LOW_QUALITY_HERO_SOURCE",
    )
    db_session.add(job)
    db_session.commit()

    section = type("Section", (), {"id": "auto-upscale-candidate-hero"})()
    candidates = get_image_candidates_for_section(section, db_session, project.id)

    assert preview is not None
    assert candidates[0]["asset_id"] == preview.id
    assert candidates[0]["source_type"] == "local_upscaled"
    assert candidates[0]["status"] == "quality_review_required"


def test_existing_unconfirmed_low_quality_hero_is_cleared_for_review(db_session, tmp_path):
    project = _project(db_session, project_id="legacy-low-quality-hero-project")
    page = ProductPage(id="legacy-low-quality-hero-page", project_id=project.id)
    asset = _image_asset(
        db_session,
        project.id,
        tmp_path,
        "legacy-low-quality-hero-asset",
        "small-product-main.png",
        size=(300, 300),
    )
    apply_asset_inspection(asset, db_session)
    section = PageSection(
        id="legacy-low-quality-hero-section",
        page_id=page.id,
        section_type="hero",
        title="Hero",
        body_copy="Body",
        sort_order=0,
        is_visible=True,
        image_asset_id=asset.id,
    )
    db_session.add_all([page, section])
    db_session.commit()

    assert clear_unconfirmed_low_quality_hero_assignments(db_session, project.id) == 1
    db_session.refresh(section)

    assert section.image_asset_id is None
    assert section.visual_payload["missing_state"] == "quality_review_required"


def test_source_only_hero_job_skips_low_quality_photo_automatically(db_session, tmp_path):
    project = _project(db_session, project_id="source-only-low-quality-hero-project")
    page = ProductPage(id="source-only-low-quality-hero-page", project_id=project.id)
    asset = _image_asset(
        db_session,
        project.id,
        tmp_path,
        "source-only-low-quality-hero-asset",
        "small-product-main.png",
        size=(300, 300),
    )
    apply_asset_inspection(asset, db_session)
    section = PageSection(
        id="source-only-low-quality-hero-section",
        page_id=page.id,
        section_type="hero",
        title="Hero",
        body_copy="Body",
        sort_order=0,
        is_visible=True,
        image_asset_id=asset.id,
    )
    job = ImageGenerationJobRecord(
        project_id=project.id,
        job_id="source-only-low-quality-hero-job",
        section_id=section.id,
        role="representative_product",
        source_asset_ids=[asset.id],
        prompt="Use the original product photo",
        cost_tier="standard",
        status="planned",
    )
    db_session.add_all([page, section, job])
    db_session.commit()

    DetailPageOrchestrator._approve_source_only_jobs(project, db_session)
    db_session.refresh(job)
    db_session.refresh(section)

    assert job.status == "skipped"
    assert job.output_asset_id is None
    assert section.image_asset_id is None
    assert section.visual_payload["missing_state"] == "quality_review_required"
