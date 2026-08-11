from pathlib import Path

import pytest
from PIL import Image

from src.config import settings
from src.db.models import Asset, Brand, ImageGenerationJobRecord, ProductFact, ProductProject, User, Workspace
from src.services.storyboard_image_generation_service import (
    StoryboardImageGenerationError,
    approve_storyboard_job,
    attach_manual_storyboard_output,
    cancel_storyboard_job,
    list_storyboard_jobs,
    prepare_storyboard_jobs,
    start_storyboard_job,
    update_storyboard_job,
)
from src.services.page_asset_policy import get_page_eligible_assets


HEADERS = {"X-Mock-User-Id": "sprint5-user", "X-Mock-Workspace-Id": "sprint5-workspace"}


def _project(db_session, tmp_path, *, approved=True):
    user = User(id=HEADERS["X-Mock-User-Id"], email="s5@example.com", name="Sprint 5")
    workspace = Workspace(id=HEADERS["X-Mock-Workspace-Id"], name="Sprint 5", owner_id=user.id)
    brand = Brand(id="sprint5-brand", workspace_id=workspace.id, name="Brand")
    reference_path = tmp_path / "seller-product.png"
    Image.new("RGB", (1024, 1024), "gray").save(reference_path)
    detail_path = tmp_path / "seller-control.png"
    Image.new("RGB", (1024, 1024), "lightgray").save(detail_path)
    project = ProductProject(
        id="sprint5-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="YL-T02 Massage Pillow",
        planning_draft={
            "status": "approved" if approved else "draft",
            "revision": 1,
            "revision_history": [],
            "cards": [
                {
                    "id": "storyboard-hero-1",
                    "type": "hero",
                    "title": "Product hero",
                    "is_enabled": True,
                    "image_requirement": "ai_redesign_required",
                    "candidate_asset_ids": ["sprint5-reference"],
                    "source_fact_ids": [],
                    "scene_request": "product-only hero scene",
                },
                {
                    "id": "storyboard-spec-9",
                    "type": "specifications",
                    "title": "Final specs",
                    "is_enabled": True,
                    "image_requirement": "derived_graphic",
                    "candidate_asset_ids": [],
                    "source_fact_ids": [],
                },
            ],
        },
    )
    reference = Asset(
        id="sprint5-reference", project_id=project.id, source_type="uploaded", usage_status="seller_owned",
        filename="seller-product.png", file_path=str(reference_path), mime_type="image/png", file_size=reference_path.stat().st_size,
        asset_role="product_main",
    )
    detail = Asset(
        id="sprint5-control", project_id=project.id, source_type="self_shot", usage_status="seller_owned",
        filename="seller-control.png", file_path=str(detail_path), mime_type="image/png", file_size=detail_path.stat().st_size,
        asset_role="product_detail",
    )
    db_session.add_all([user, workspace, brand, project, reference, detail])
    db_session.commit()
    return project, reference


def test_prepare_creates_two_reviewable_variants_and_keeps_reference_input_only(db_session, tmp_path):
    project, reference = _project(db_session, tmp_path)
    jobs = prepare_storyboard_jobs(project, db_session)

    assert len(jobs) == 1
    assert {job["status"] for job in jobs} == {"awaiting_approval"}
    assert all(job["source_asset_ids"] == [reference.id, "sprint5-control"] for job in jobs)
    assert all(job["reference_only_input"] is True for job in jobs)
    assert all("supplier layouts" in job["negative_prompt"] for job in jobs)
    assert all(job["output_asset_id"] is None for job in jobs)
    assert jobs[0]["input_snapshot"]["provider_data_policy"]["training"] == "not_used_by_default"
    assert jobs[0]["input_snapshot"]["storyboard_status"] == "approved"
    # Idempotent preparation must not create an extra chargeable duplicate.
    assert len(prepare_storyboard_jobs(project, db_session)) == 1


def test_three_distinct_storyboard_scenes_create_independent_redesign_variants(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    draft = dict(project.planning_draft)
    draft["cards"] = [
        *project.planning_draft["cards"][:-1],
        {
            "id": "storyboard-lifestyle-2", "type": "lifestyle_scene", "title": "Use scene",
            "is_enabled": True, "image_requirement": "ai_redesign_required",
            "candidate_asset_ids": ["sprint5-reference"], "source_fact_ids": [], "scene_request": "quiet home use scene",
        },
        {
            "id": "storyboard-detail-3", "type": "material_detail", "title": "Material detail",
            "is_enabled": True, "image_requirement": "ai_redesign_required",
            "candidate_asset_ids": ["sprint5-reference"], "source_fact_ids": [], "scene_request": "material close-up",
        },
        project.planning_draft["cards"][-1],
    ]
    project.planning_draft = draft
    db_session.commit()

    jobs = prepare_storyboard_jobs(project, db_session)
    assert len(jobs) == 3
    assert {job["section_type"] for job in jobs} == {"hero", "lifestyle_scene", "material_detail"}
    assert {job["role"] for job in jobs} == {"representative_product", "lifestyle_scene", "detail_closeup"}


def test_charging_and_function_scenes_keep_distinct_visual_roles(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    power_fact = ProductFact(
        id="sprint5-power-fact", project_id=project.id, fact_text="정격 입력은 DC 5V 2A입니다.",
        field_key="rated_input", normalized_value="DC 5V 2A",
        verification_status="seller_confirmed", needs_review=False,
    )
    db_session.add(power_fact)
    draft = dict(project.planning_draft)
    draft["cards"] = [
        {
            "id": "storyboard-charge-2", "type": "charging_scene", "title": "Charging",
            "is_enabled": True, "image_requirement": "ai_redesign_required",
            "candidate_asset_ids": ["sprint5-reference"], "source_fact_ids": [power_fact.id], "scene_request": "charging at a desk",
        },
        {
            "id": "storyboard-function-3", "type": "function_visual", "title": "Function",
            "is_enabled": True, "image_requirement": "ai_redesign_required",
            "candidate_asset_ids": ["sprint5-reference"], "source_fact_ids": [], "scene_request": "show verified heat function",
        },
        project.planning_draft["cards"][-1],
    ]
    project.planning_draft = draft
    db_session.commit()

    jobs = prepare_storyboard_jobs(project, db_session)
    assert {job["role"] for job in jobs} == {"charging_storage_scene", "function_visualization"}
    charging = next(job for job in jobs if job["section_type"] == "charging_scene")
    assert charging["input_snapshot"]["confirmed_facts"][0]["id"] == power_fact.id


def test_charging_scene_without_confirmed_power_fact_is_blocked(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    draft = dict(project.planning_draft)
    draft["cards"] = [{
        "id": "storyboard-charge-unverified", "type": "charging_scene", "title": "Charging",
        "is_enabled": True, "image_requirement": "ai_redesign_required",
        "candidate_asset_ids": ["sprint5-reference"], "source_fact_ids": [], "scene_request": "charging at a desk",
    }]
    project.planning_draft = draft
    db_session.commit()

    job = prepare_storyboard_jobs(project, db_session)[0]
    assert job["status"] == "blocked"
    assert job["error_code"] == "POWER_FACT_REQUIRED"


def test_prepare_requires_approved_storyboard(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path, approved=False)
    with pytest.raises(StoryboardImageGenerationError, match="Approve"):
        prepare_storyboard_jobs(project, db_session)


def test_no_api_key_blocks_instead_of_persisting_mock_placeholder(db_session, tmp_path, monkeypatch):
    project, _ = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "mock")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    result = start_storyboard_job(project, job_id, cost_approved=True, db=db_session)
    assert result["status"] == "blocked"
    assert result["error_code"] == "IMAGE_PROVIDER_NOT_CONFIGURED"
    assert result["output_asset_id"] is None
    assert db_session.query(Asset).filter(Asset.project_id == project.id, Asset.source_type == "ai_generated").count() == 0


def test_real_provider_job_is_durably_queued_before_worker_execution(db_session, tmp_path, monkeypatch):
    project, _ = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "real")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")

    result = start_storyboard_job(project, job_id, cost_approved=True, db=db_session)
    assert result["status"] == "queued"
    assert result["estimated_cost"] == 1.0
    assert result["dispatch_required"] is True

    duplicate = start_storyboard_job(project, job_id, cost_approved=True, db=db_session)
    assert duplicate["status"] == "queued"
    assert duplicate["dispatch_required"] is False
    assert len(duplicate["usage_metadata"]["attempt_history"]) == 1


def test_seller_can_cancel_before_provider_execution(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    cancelled = cancel_storyboard_job(project, job_id, db_session)
    assert cancelled["status"] == "cancelled"
    assert cancelled["error_code"] == "SELLER_CANCELLED"


def test_supplier_capture_is_excluded_even_as_generation_reference(db_session, tmp_path):
    project, reference = _project(db_session, tmp_path)
    reference.source_type = "sourced"
    reference.usage_status = "reference_only"
    db_session.commit()

    job = prepare_storyboard_jobs(project, db_session)[0]
    assert reference.id not in job["source_asset_ids"]
    assert job["status"] == "blocked"


def test_seller_can_adjust_scene_before_running(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    updated = update_storyboard_job(project, job_id, "bright bedroom, no hands", db_session)
    assert updated["status"] == "awaiting_approval"
    assert "Seller adjustment: bright bedroom, no hands" in updated["prompt"]


def test_seller_can_choose_a_two_photo_reference_pack_before_running(db_session, tmp_path):
    project, reference = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    detail = db_session.query(Asset).filter(Asset.id == "sprint5-control").one()

    updated = update_storyboard_job(project, job_id, None, db_session, [reference.id, detail.id])

    assert updated["source_asset_ids"][0] == reference.id
    assert updated["source_asset_ids"][1] == detail.id
    assert updated["reference_assets"][0]["id"] == reference.id


def test_seller_adjustment_cannot_invent_product_features(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    with pytest.raises(StoryboardImageGenerationError, match="확인되지 않은"):
        update_storyboard_job(project, job_id, "add a new USB port and certification mark", db_session)


def test_insufficient_identity_views_are_blocked(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    only = db_session.query(Asset).filter(Asset.id == "sprint5-control").first()
    db_session.delete(only)
    db_session.commit()
    jobs = prepare_storyboard_jobs(project, db_session)
    assert {job["status"] for job in jobs} == {"blocked"}
    assert {job["error_code"] for job in jobs} == {"IDENTITY_REFERENCE_INSUFFICIENT"}


def test_product_main_plus_usage_scene_is_a_sufficient_identity_pack(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    control = db_session.query(Asset).filter(Asset.id == "sprint5-control").first()
    control.asset_role = "usage_scene"
    db_session.commit()

    jobs = prepare_storyboard_jobs(project, db_session)
    assert {job["status"] for job in jobs} == {"awaiting_approval"}


def test_reprepare_recovers_identity_block_without_duplicate_jobs(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    control = db_session.query(Asset).filter(Asset.id == "sprint5-control").first()
    db_session.delete(control)
    db_session.commit()
    blocked = prepare_storyboard_jobs(project, db_session)
    assert {job["status"] for job in blocked} == {"blocked"}

    path = tmp_path / "usage-scene.png"
    Image.new("RGB", (1024, 1024), "lightgray").save(path)
    db_session.add(Asset(
        id="sprint5-usage", project_id=project.id, source_type="uploaded", usage_status="seller_owned",
        filename="usage-scene.png", file_path=str(path), mime_type="image/png", file_size=path.stat().st_size,
        asset_role="usage_scene",
    ))
    db_session.commit()

    recovered = prepare_storyboard_jobs(project, db_session)
    assert len(recovered) == 1
    assert {job["status"] for job in recovered} == {"awaiting_approval"}


def test_only_real_generated_output_can_be_approved_and_linked_to_storyboard(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    output_path = tmp_path / "generated.png"
    Image.new("RGB", (1024, 1024), "navy").save(output_path)
    output = Asset(
        id="sprint5-output", project_id=project.id, source_type="ai_generated", usage_status="ai_generated",
        filename="generated.png", file_path=str(output_path), mime_type="image/png", file_size=output_path.stat().st_size,
        asset_role="product_main",
    )
    db_session.add(output)
    record = db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.job_id == job_id).first()
    record.status = "needs_review"
    record.output_asset_id = output.id
    record.provider = "openai"
    db_session.commit()

    approved = approve_storyboard_job(project, job_id, db_session)
    db_session.refresh(project)
    assert approved["status"] == "approved"
    hero = project.planning_draft["cards"][0]
    assert hero["image_asset_id"] == output.id
    assert hero["image_requirement"] == "asset_ready"


def test_identity_review_requires_explicit_seller_confirmation(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    output_path = tmp_path / "generated-needs-review.png"
    Image.new("RGB", (1024, 1024), "navy").save(output_path)
    output = Asset(
        id="sprint5-output-needs-review", project_id=project.id, source_type="ai_generated", usage_status="ai_generated",
        filename="generated-needs-review.png", file_path=str(output_path), mime_type="image/png", file_size=output_path.stat().st_size,
    )
    db_session.add(output)
    record = db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.job_id == job_id).first()
    record.status = "needs_review"
    record.output_asset_id = output.id
    record.provider = "openai"
    record.validation_result = {"status": "needs_review", "checks": ["text_review"]}
    db_session.commit()

    with pytest.raises(StoryboardImageGenerationError):
        approve_storyboard_job(project, job_id, db_session)
    approved = approve_storyboard_job(project, job_id, db_session, identity_confirmed=True)
    assert approved["status"] == "approved"
    assert approved["validation_result"]["seller_identity_confirmed"] is True


def test_reference_only_output_can_never_be_approved(db_session, tmp_path):
    project, reference = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    record = db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.job_id == job_id).first()
    record.status = "needs_review"
    record.output_asset_id = reference.id
    record.provider = "openai"
    db_session.commit()
    with pytest.raises(StoryboardImageGenerationError, match="supplier capture"):
        approve_storyboard_job(project, job_id, db_session)


def test_seller_owned_manual_final_can_be_reviewed_without_an_image_api(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    final_path = tmp_path / "seller-created-final.png"
    Image.new("RGB", (1024, 1024), "teal").save(final_path)
    final_asset = Asset(
        id="sprint5-manual-final", project_id=project.id, source_type="uploaded", usage_status="seller_owned",
        filename="seller-created-final.png", file_path=str(final_path), mime_type="image/png", file_size=final_path.stat().st_size,
        asset_role="product_main",
    )
    db_session.add(final_asset)
    db_session.commit()

    attached = attach_manual_storyboard_output(project, job_id, final_asset.id, True, db_session)
    assert attached["status"] == "needs_review"
    assert attached["output_asset_id"] == final_asset.id
    assert attached["provider"] == "manual_upload"

    approved = approve_storyboard_job(project, job_id, db_session, identity_confirmed=True)
    assert approved["status"] == "approved"
    assert project.planning_draft["cards"][0]["image_asset_id"] == final_asset.id


def test_manual_final_rejects_supplier_reference_even_with_seller_attestation(db_session, tmp_path):
    project, reference = _project(db_session, tmp_path)
    reference.source_type = "sourced"
    reference.usage_status = "reference_only"
    db_session.commit()
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    with pytest.raises(StoryboardImageGenerationError, match="공급처 참고"):
        attach_manual_storyboard_output(project, job_id, reference.id, True, db_session)


def test_manual_final_rejects_a_reuploaded_supplier_file_with_the_same_content_hash(db_session, tmp_path):
    project, reference = _project(db_session, tmp_path)
    reference.source_type = "sourced"
    reference.usage_status = "reference_only"
    reference.content_hash = "same-supplier-capture"
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    duplicate_path = tmp_path / "reuploaded-supplier.png"
    Image.new("RGB", (1024, 1024), "gray").save(duplicate_path)
    duplicate = Asset(
        id="sprint5-reuploaded-reference", project_id=project.id, source_type="uploaded", usage_status="seller_owned",
        filename="reuploaded-supplier.png", file_path=str(duplicate_path), mime_type="image/png", file_size=duplicate_path.stat().st_size,
        asset_role="product_main", content_hash="same-supplier-capture",
    )
    db_session.add(duplicate)
    db_session.commit()

    with pytest.raises(StoryboardImageGenerationError, match="동일"):
        attach_manual_storyboard_output(project, job_id, duplicate.id, True, db_session)


def test_listing_jobs_withdraws_a_legacy_duplicate_supplier_manual_approval(db_session, tmp_path):
    project, reference = _project(db_session, tmp_path)
    reference.source_type = "sourced"
    reference.usage_status = "reference_only"
    reference.content_hash = "legacy-supplier-capture"
    final_path = tmp_path / "legacy-reupload.png"
    Image.new("RGB", (1024, 1024), "gray").save(final_path)
    duplicate = Asset(
        id="sprint5-legacy-reupload", project_id=project.id, source_type="uploaded", usage_status="seller_owned",
        filename="legacy-reupload.png", file_path=str(final_path), mime_type="image/png", file_size=final_path.stat().st_size,
        asset_role="product_main", content_hash="legacy-supplier-capture",
    )
    db_session.add(duplicate)
    db_session.commit()
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    job = db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.job_id == job_id).first()
    job.provider = "manual_upload"
    job.status = "approved"
    job.output_asset_id = duplicate.id
    draft = dict(project.planning_draft)
    draft["cards"] = [dict(card) for card in draft["cards"]]
    draft["cards"][0]["image_asset_id"] = duplicate.id
    draft["cards"][0]["image_requirement"] = "asset_ready"
    project.planning_draft = draft
    db_session.commit()

    jobs = list_storyboard_jobs(project, db_session)
    assert jobs[0]["status"] == "blocked"
    assert jobs[0]["error_code"] == "SUPPLIER_REFERENCE_FINAL_OUTPUT_BLOCKED"
    db_session.refresh(project)
    assert project.planning_draft["cards"][0]["image_asset_id"] is None
    assert project.planning_draft["cards"][0]["image_requirement"] == "ai_redesign_required"


def test_listing_jobs_withdraws_a_legacy_source_asset_approval(db_session, tmp_path):
    """Pre-Sprint-5 assembly jobs must not bypass final-art policy."""
    project, reference = _project(db_session, tmp_path)
    reference.source_type = "sourced"
    reference.usage_status = "reference_only"
    reference.content_hash = "legacy-source-asset-capture"
    duplicate_path = tmp_path / "legacy-source-asset.png"
    Image.new("RGB", (1024, 1024), "gray").save(duplicate_path)
    duplicate = Asset(
        id="sprint5-legacy-source-asset", project_id=project.id, source_type="uploaded", usage_status="seller_owned",
        filename="legacy-source-asset.png", file_path=str(duplicate_path), mime_type="image/png", file_size=duplicate_path.stat().st_size,
        asset_role="product_main", content_hash="legacy-source-asset-capture",
    )
    db_session.add(duplicate)
    db_session.commit()
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    job = db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.job_id == job_id).first()
    job.provider = "source_asset"
    job.status = "approved"
    job.output_asset_id = duplicate.id
    draft = dict(project.planning_draft)
    draft["cards"] = [dict(card) for card in draft["cards"]]
    draft["cards"][0]["image_asset_id"] = duplicate.id
    draft["cards"][0]["image_requirement"] = "asset_ready"
    project.planning_draft = draft
    db_session.commit()

    jobs = list_storyboard_jobs(project, db_session)
    assert jobs[0]["status"] == "blocked"
    assert jobs[0]["error_code"] == "SUPPLIER_REFERENCE_FINAL_OUTPUT_BLOCKED"


def test_unapproved_generated_output_is_excluded_from_renderer_assets(db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    job_id = prepare_storyboard_jobs(project, db_session)[0]["job_id"]
    output_path = tmp_path / "pending-output.png"
    Image.new("RGB", (1024, 1024), "navy").save(output_path)
    output = Asset(
        id="sprint5-pending-output", project_id=project.id, source_type="ai_generated", usage_status="ai_generated",
        filename="pending-output.png", file_path=str(output_path), mime_type="image/png", file_size=output_path.stat().st_size,
    )
    db_session.add(output)
    record = db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.job_id == job_id).first()
    record.status = "needs_review"
    record.output_asset_id = output.id
    db_session.commit()
    assert output.id not in {asset.id for asset in get_page_eligible_assets(db_session, project.id)}


def test_storyboard_generation_api_requires_approval_and_exposes_blocked_provider_state(client, db_session, tmp_path):
    project, _ = _project(db_session, tmp_path)
    prepared = client.post(f"/api/v1/projects/{project.id}/storyboard/image-jobs", headers=HEADERS)
    assert prepared.status_code == 200
    job_id = prepared.json()["jobs"][0]["job_id"]
    started = client.post(
        f"/api/v1/projects/{project.id}/storyboard/image-jobs/{job_id}/start",
        headers=HEADERS,
        json={"cost_approved": True},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "blocked"


def test_storyboard_api_requires_and_persists_two_identity_references(client, db_session, tmp_path):
    project, reference = _project(db_session, tmp_path)
    detail = db_session.query(Asset).filter(Asset.id == "sprint5-control").one()
    prepared = client.post(f"/api/v1/projects/{project.id}/storyboard/image-jobs", headers=HEADERS)
    assert prepared.status_code == 200
    job_id = prepared.json()["jobs"][0]["job_id"]

    rejected = client.patch(
        f"/api/v1/projects/{project.id}/storyboard/image-jobs/{job_id}",
        headers=HEADERS,
        json={"source_asset_ids": [reference.id]},
    )
    assert rejected.status_code == 422

    saved = client.patch(
        f"/api/v1/projects/{project.id}/storyboard/image-jobs/{job_id}",
        headers=HEADERS,
        json={"source_asset_ids": [reference.id, detail.id]},
    )
    assert saved.status_code == 200
    assert saved.json()["source_asset_ids"] == [reference.id, detail.id]
    assert [item["id"] for item in saved.json()["reference_assets"]] == [reference.id, detail.id]
