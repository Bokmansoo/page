from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from PIL import Image
from sqlalchemy import inspect

from src.config import settings
from src.db.models import (
    AgentRun,
    Asset,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ProductProject,
    ScenePromptVersion,
)
from src.services.brand_kit_service import create_kit, create_version
from src.services.visual_prompt_compiler_service import (
    SCENE_PROFILES,
    VisualPromptCompileError,
    compile_project_scene_prompts,
    compile_scene_prompt,
    provider_prompt,
    visual_brand_hash,
)
from tests.test_lg5_image_generation_subgraph import _create_run, _resume, _to_generation_pending


AUTH_HEADERS = {
    "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
}


@pytest.fixture
def lg8_runtime(monkeypatch):
    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _approved_project(client, db_session, tmp_path, *, scene_types=("hero", "usage_guide")):
    run = _create_run(client, AUTH_HEADERS, db_session, tmp_path)
    project = db_session.query(ProductProject).filter_by(id=run.project_id).one()
    assets = db_session.query(Asset).filter_by(project_id=project.id).order_by(Asset.intake_order).all()
    fact_ids = [fact.id for fact in project.facts]
    project.planning_draft = {
        "status": "approved",
        "cards": [
            {
                "id": f"scene-{index}",
                "type": scene_type,
                "title": f"Scene {index}",
                "scene_request": "정확한 한글 판매 문구는 렌더러가 나중에 배치합니다.",
                "source_fact_ids": fact_ids,
                "candidate_asset_ids": [asset.id for asset in assets],
                "image_requirement": "ai_redesign_required",
                "is_enabled": True,
            }
            for index, scene_type in enumerate(scene_types, start=1)
        ],
    }
    db_session.commit()
    return run, project


def _brand_payload(*, primary="#2563EB", tone="clear"):
    return {
        "logo_asset_ids": [],
        "font_asset_ids": [],
        "color_tokens": {"primary": primary, "secondary": "#EFF6FF"},
        "typography": {"heading": "system"},
        "tone_of_voice": {"tone": tone},
        "forbidden_terms": [],
        "cta_rules": {"style": "fact_first"},
        "image_style": {"keywords": ["clean product-led", "premium studio"]},
        "layout_rules": {"mobile_first": True},
        "background_rules": {"style": "light_neutral"},
        "watermark_policy": {"enabled": False},
        "constraints": {"forbidden_visual_elements": ["medical badge"]},
        "asset_rights": {},
    }


def test_lg8_runtime_schema_migration_is_reentrant_and_links_image_jobs(db_session):
    """Local upgrades must survive startup retries and expose the LG-8 FK."""
    from src.db import database

    database.ensure_runtime_schema_compatibility()
    database.ensure_runtime_schema_compatibility()

    schema = inspect(database.engine)
    assert "scene_prompt_versions" in schema.get_table_names()
    prompt_columns = {column["name"] for column in schema.get_columns("scene_prompt_versions")}
    assert {"rights_snapshot", "instruction_priority", "prompt_hash"} <= prompt_columns
    job_columns = {column["name"] for column in schema.get_columns("image_generation_jobs")}
    assert "scene_prompt_version_id" in job_columns
    job_indexes = {index["name"] for index in schema.get_indexes("image_generation_jobs")}
    assert "ix_image_generation_jobs_scene_prompt_version_id" in job_indexes


def test_lg8_compiles_every_required_scene_template_and_keeps_copy_out_of_provider_prompt(
    client, db_session, tmp_path, monkeypatch
):
    required_types = (
        "hero", "usage_guide", "function_visual", "material_detail",
        "details_components", "product_specifications", "cta",
        "representative_product", "detail_closeup", "function_visualization",
    )
    run, project = _approved_project(client, db_session, tmp_path, scene_types=required_types)
    rows = compile_project_scene_prompts(project, db_session, run_id=run.id)

    assert len(rows) == len(required_types)
    assert all(row.scene_type in SCENE_PROFILES for row in rows)
    assert all(row.status == "active" and row.version == 1 for row in rows)
    assert all(row.reference_asset_ids for row in rows)
    assert all(row.approved_fact_ids for row in rows)
    assert all(row.identity_constraints["unknown_structure_policy"] == "do_not_invent" for row in rows)
    assert all(
        row.identity_constraints["feature_region_schema_version"] == "identity-feature-regions-v1"
        for row in rows
    )
    assert all(
        set(row.identity_constraints["feature_regions"]) == {"buttons", "ports", "components", "logo"}
        for row in rows
    )
    assert all(
        not any(row.identity_constraints["feature_regions"].values())
        for row in rows
    )
    assert all(row.text_policy["final_copy_owner"] == "deterministic_renderer" for row in rows)
    assert all(row.text_policy["allow_in_image_text"] is False for row in rows)
    assert all(row.rights_snapshot for row in rows)
    assert all(row.instruction_priority[0] == "safety" for row in rows)

    prompt, negative = provider_prompt(rows[0])
    assert "정확한 한글 판매 문구" not in prompt
    assert "no text" in negative.lower()
    assert "no provider-rendered logo" in negative.lower()

    # The canonical prompt is provider-neutral. Changing only the adapter
    # selection must not create a new immutable scene prompt version.
    ids = [row.id for row in rows]
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_PROVIDER", "another-provider")
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_MODEL", "another-model")
    again = compile_project_scene_prompts(project, db_session, run_id=run.id)
    assert [row.id for row in again] == ids
    assert all(row.version == 1 for row in again)


def test_lg8_compiler_derives_all_feature_regions_from_explicit_asset_evidence(
    client, db_session, tmp_path
):
    run, project = _approved_project(client, db_session, tmp_path, scene_types=("hero",))
    assets = db_session.query(Asset).filter_by(project_id=project.id).order_by(Asset.intake_order).all()
    _, detail_asset = assets
    detail_asset.filename = "seller-button-control-usb-port-brand-logo-detail.jpg"
    component_asset = Asset(
        project_id=project.id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename="seller-included-components.jpg",
        file_path=detail_asset.file_path,
        mime_type="image/jpeg",
        file_size=detail_asset.file_size,
        asset_role="components",
        quality_status="usable",
        identity_status="confirmed",
        intake_order=3,
    )
    db_session.add(component_asset)
    db_session.flush()
    draft = dict(project.planning_draft or {})
    draft["cards"] = [
        {
            **card,
            "candidate_asset_ids": [*(card.get("candidate_asset_ids") or []), component_asset.id],
        }
        for card in draft.get("cards") or []
    ]
    project.planning_draft = draft
    db_session.commit()

    row = compile_project_scene_prompts(project, db_session, run_id=run.id)[0]
    regions = row.identity_constraints["feature_regions"]

    assert all(regions[element] for element in ("buttons", "ports", "components", "logo"))
    assert regions["buttons"][0]["reference_asset_id"] == detail_asset.id
    assert regions["ports"][0]["reference_asset_id"] == detail_asset.id
    assert regions["components"][0]["reference_asset_id"] == component_asset.id
    assert regions["components"][0]["evidence_source"] == "asset_role"
    assert regions["logo"][0]["reference_asset_id"] == detail_asset.id
    assert all(
        entry["coordinate_space"] == "normalized"
        and entry["reference_box"] == [0.0, 0.0, 1.0, 1.0]
        and entry["output_box"] == [0.0, 0.0, 1.0, 1.0]
        for entries in regions.values()
        for entry in entries
    )


def test_lg8_scene_edit_is_local_and_invalidates_only_linked_job_and_outbox(client, db_session, tmp_path):
    run, project = _approved_project(client, db_session, tmp_path)
    first, second = compile_project_scene_prompts(project, db_session, run_id=run.id)
    job = ImageGenerationJobRecord(
        project_id=project.id,
        job_id="lg8-scene-one-job",
        section_id=first.scene_id,
        scene_id=first.scene_id,
        role="representative_product",
        source_asset_ids=first.reference_asset_ids,
        prompt="old provider prompt",
        negative_prompt="old negative prompt",
        status="queued",
        scene_prompt_version_id=first.id,
        prompt_version=first.prompt_version,
        prompt_hash=first.prompt_hash,
        reference_hash=first.reference_hash,
        input_hash=first.input_hash,
        idempotency_key="1" * 64,
    )
    db_session.add(job)
    db_session.flush()
    delivery = ImageGenerationOutboxRecord(
        workspace_id=project.workspace_id,
        project_id=project.id,
        run_id=run.id,
        thread_id=run.id,
        image_job_id=job.id,
        job_id=job.job_id,
        idempotency_key=job.idempotency_key,
        provider_mode="mock",
        status="queued",
    )
    db_session.add(delivery)
    db_session.commit()

    card = project.planning_draft["cards"][0]
    replacement = compile_scene_prompt(
        project, card, db_session, run_id=run.id, seller_adjustment="차가운 청색 배경과 부드러운 측면광"
    )
    db_session.commit()
    db_session.refresh(first)
    db_session.refresh(second)
    db_session.refresh(job)
    db_session.refresh(delivery)

    assert replacement.id != first.id and replacement.version == 2
    assert replacement.supersedes_version_id == first.id
    assert first.status == "stale"
    assert first.stale_impact == {"scene_ids": [first.scene_id], "artifact_types": ["scene_prompt", "image_job"]}
    assert second.status == "active" and second.version == 1
    assert job.status == "stale" and job.error_code == "SCENE_PROMPT_STALE"
    assert delivery.status == "cancelled" and delivery.last_error_code == "SCENE_PROMPT_STALE"


def test_lg8_brand_tone_does_not_stale_visuals_but_palette_change_does(client, db_session, tmp_path):
    run, project = _approved_project(client, db_session, tmp_path)
    actor_id = AUTH_HEADERS["X-Mock-User-Id"]
    kit = create_kit(db_session, project.workspace_id, actor_id, "LG-8 brand")
    v1 = create_version(
        db_session, project.workspace_id, actor_id, kit.id, _brand_payload(tone="clear"),
        scope="project", project_id=project.id, activate=True,
    )
    initial = compile_project_scene_prompts(project, db_session, run_id=run.id)
    initial_ids = [row.id for row in initial]
    initial_hash = visual_brand_hash(v1)

    v2 = create_version(
        db_session, project.workspace_id, actor_id, kit.id, _brand_payload(tone="warm"),
        scope="project", project_id=project.id, activate=True,
    )
    assert visual_brand_hash(v2) == initial_hash
    tone_only = compile_project_scene_prompts(project, db_session, run_id=run.id)
    assert [row.id for row in tone_only] == initial_ids
    assert all(row.status == "active" and row.version == 1 for row in tone_only)

    v3 = create_version(
        db_session, project.workspace_id, actor_id, kit.id, _brand_payload(primary="#16A34A", tone="warm"),
        scope="project", project_id=project.id, activate=True,
    )
    assert visual_brand_hash(v3) != initial_hash
    palette_changed = compile_project_scene_prompts(project, db_session, run_id=run.id)
    assert all(row.version == 2 and row.status == "active" for row in palette_changed)
    stale = db_session.query(ScenePromptVersion).filter_by(project_id=project.id, status="stale").all()
    assert {row.id for row in stale} == set(initial_ids)
    assert all(row.stale_reason == "brand_visual_changed" for row in stale)


def test_lg8_pins_the_creative_brief_brand_version_across_later_activation(
    client, db_session, tmp_path
):
    """BRAND-05: a running graph must not drift to a newly activated kit."""

    run, project = _approved_project(client, db_session, tmp_path, scene_types=("hero",))
    actor_id = AUTH_HEADERS["X-Mock-User-Id"]
    kit = create_kit(db_session, project.workspace_id, actor_id, "LG-8 pinned brand")
    pinned = create_version(
        db_session,
        project.workspace_id,
        actor_id,
        kit.id,
        _brand_payload(primary="#2563EB"),
        scope="project",
        project_id=project.id,
        activate=True,
    )
    initial = compile_project_scene_prompts(
        project,
        db_session,
        run_id=run.id,
        brand_kit_version_id=pinned.id,
        brand_kit_hash=pinned.content_hash,
    )[0]

    newer = create_version(
        db_session,
        project.workspace_id,
        actor_id,
        kit.id,
        _brand_payload(primary="#16A34A"),
        scope="project",
        project_id=project.id,
        activate=True,
    )
    assert newer.id != pinned.id

    same_run = compile_project_scene_prompts(
        project,
        db_session,
        run_id=run.id,
        brand_kit_version_id=pinned.id,
        brand_kit_hash=pinned.content_hash,
    )[0]
    assert same_run.id == initial.id
    assert same_run.brand_kit_version_id == pinned.id
    assert same_run.palette["primary"] == "#2563EB"

    with pytest.raises(VisualPromptCompileError, match="PINNED_BRAND_KIT_HASH_MISMATCH"):
        compile_project_scene_prompts(
            project,
            db_session,
            run_id=run.id,
            brand_kit_version_id=pinned.id,
            brand_kit_hash="0" * 64,
        )


def test_lg8_scene_prompt_api_rejects_raster_copy_and_preserves_workspace_boundary(
    client, db_session, tmp_path
):
    _, project = _approved_project(client, db_session, tmp_path, scene_types=("hero",))
    compiled = client.post(f"/api/v1/projects/{project.id}/scene-prompts/compile", headers=AUTH_HEADERS)
    assert compiled.status_code == 200, compiled.text
    item = compiled.json()["items"][0]
    assert item["prompt_hash"] and item["reference_hash"]

    unsafe = client.patch(
        f"/api/v1/projects/{project.id}/scene-prompts/{item['scene_id']}",
        headers=AUTH_HEADERS,
        json={"seller_adjustment": "이미지 안에 할인 가격 문구를 크게 추가해 주세요"},
    )
    assert unsafe.status_code == 422
    assert "RASTER_TEXT_OR_MARK_REQUEST_BLOCKED" in unsafe.json()["detail"]
    assert "해결 방법" in unsafe.json()["detail"]

    other_workspace = {**AUTH_HEADERS, "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000099"}
    blocked = client.get(f"/api/v1/projects/{project.id}/scene-prompts", headers=other_workspace)
    assert blocked.status_code == 404


def test_lg8_real_graph_interrupt_compiles_prompts_and_links_fake_worker_jobs(
    client, db_session, tmp_path, lg8_runtime, monkeypatch
):
    run = _create_run(client, AUTH_HEADERS, db_session, tmp_path)
    project = db_session.query(ProductProject).filter_by(id=run.project_id).one()
    main_asset = db_session.query(Asset).filter_by(
        project_id=project.id,
        asset_role="product_main",
    ).one()
    detail_asset = db_session.query(Asset).filter_by(
        project_id=project.id,
        asset_role="product_detail",
    ).one()
    from src.services.image_generation_provider import ImageGenerationRequest
    from src.services.image_generation_worker import DurableFakeImageProvider
    from src.services.product_identity_validator import ProductIdentityValidator

    # Make index 0 visibly incompatible, while index 1 is the exact identity
    # reference produced later by the production fake worker.
    Image.new("RGB", (512, 512), color="black").save(main_asset.file_path, format="JPEG")
    expected_output = DurableFakeImageProvider().generate(ImageGenerationRequest(
        job_id="lg8-reference-fixture",
        role="representative_product",
        prompt="Preserve the product structure.",
        source_asset_paths=[detail_asset.file_path],
    ))
    Path(detail_asset.file_path).write_bytes(expected_output.content)
    main_asset.file_size = Path(main_asset.file_path).stat().st_size
    detail_asset.file_size = len(expected_output.content)
    assert Path(main_asset.file_path).read_bytes() != Path(detail_asset.file_path).read_bytes()

    with (
        Image.open(main_asset.file_path) as main_image,
        Image.open(detail_asset.file_path) as detail_image,
        Image.open(BytesIO(expected_output.content)) as output_image,
    ):
        full_frame = [0.0, 0.0, 1.0, 1.0]
        main_crop = ProductIdentityValidator._normalized_crop(main_image, full_frame)
        detail_crop = ProductIdentityValidator._normalized_crop(detail_image, full_frame)
        output_crop = ProductIdentityValidator._normalized_crop(output_image, full_frame)
        assert main_crop is not None and detail_crop is not None and output_crop is not None
        assert ProductIdentityValidator._region_difference(main_crop, output_crop) > 45.0
        assert ProductIdentityValidator._region_difference(detail_crop, output_crop) <= 45.0

    # This is production asset metadata, not a feature_regions fixture. The
    # compiler must derive the immutable normalized evidence from it.
    detail_asset.filename = "seller-button-control-port-connector-detail.jpg"
    db_session.commit()
    actor_id = AUTH_HEADERS["X-Mock-User-Id"]
    kit = create_kit(db_session, project.workspace_id, actor_id, "LG-8 graph pinned brand")
    pinned_brand = create_version(
        db_session,
        project.workspace_id,
        actor_id,
        kit.id,
        _brand_payload(primary="#2563EB"),
        scope="project",
        project_id=project.id,
        activate=True,
    )
    generation_wait = _to_generation_pending(
        client, AUTH_HEADERS, run.id, db_session, minimum_generation_scenes=2
    )
    assert generation_wait["current_stage"] == "generation_pending"
    artifact = generation_wait["values"]["commerce"]["visual_prompt_compiler"]
    assert artifact["compiler_version"] == "lg8-visual-prompt-compiler-v1"
    assert artifact["scene_count"] >= 1
    assert any(event["stage"] == "visual_prompt_compiler" for event in generation_wait["values"]["events"])

    rows = db_session.query(ScenePromptVersion).filter_by(project_id=run.project_id, status="active").all()
    assert len(rows) == artifact["scene_count"]
    creative_brand_id = generation_wait["values"]["creative_brief"].get("brand_kit_version_id")
    assert creative_brand_id == pinned_brand.id
    assert all(row.brand_kit_version_id == creative_brand_id for row in rows)
    assert all(item["brand_kit_version_id"] == creative_brand_id for item in artifact["scene_prompts"])
    for row in rows:
        regions = row.identity_constraints["feature_regions"]
        assert regions["buttons"] and regions["ports"]
        assert regions["components"] == []
        assert regions["logo"] == []
        for element in ("buttons", "ports"):
            assert regions[element] == [{
                "feature": element,
                "reference_asset_id": detail_asset.id,
                "reference_index": 1,
                "reference_box": [0.0, 0.0, 1.0, 1.0],
                "output_box": [0.0, 0.0, 1.0, 1.0],
                "coordinate_space": "normalized",
                "evidence_source": "asset_metadata",
                "reference_role": "product_detail",
            }]

    # Activating a new visual version after cost planning must not change the
    # prompt contract used by this already-running graph/checkpoint.
    newer_brand = create_version(
        db_session,
        project.workspace_id,
        actor_id,
        kit.id,
        _brand_payload(primary="#16A34A"),
        scope="project",
        project_id=project.id,
        activate=True,
    )
    assert newer_brand.id != pinned_brand.id
    pending = generation_wait["values"]["review"]["pending"]
    cost_hash = pending["context"]["generation"]["cost_plan"]["cost_plan_hash"]
    provider_wait_response = _resume(
        client, AUTH_HEADERS, generation_wait, "approve", cost_plan_hash=cost_hash
    )
    assert provider_wait_response.status_code == 200, provider_wait_response.text
    provider_wait = provider_wait_response.json()
    assert provider_wait["current_stage"] == "provider_wait"
    jobs = db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
    assert jobs and all(job.scene_prompt_version_id for job in jobs)
    prompt_by_id = {row.id: row for row in rows}
    assert all(prompt_by_id[job.scene_prompt_version_id].brand_kit_version_id == pinned_brand.id for job in jobs)
    assert all(job.prompt_hash == prompt_by_id[job.scene_prompt_version_id].prompt_hash for job in jobs)
    assert all(job.scene_id == prompt_by_id[job.scene_prompt_version_id].scene_id for job in jobs)
    assert all(job.reference_hash == prompt_by_id[job.scene_prompt_version_id].reference_hash for job in jobs)
    assert all(job.generation_attempt == 1 for job in jobs)
    for job in jobs:
        scene_prompt = job.input_snapshot["scene_prompt"]
        assert scene_prompt["id"] == job.scene_prompt_version_id
        assert scene_prompt["scene_id"] == job.scene_id
        assert scene_prompt["prompt_version"] == job.prompt_version
        assert scene_prompt["prompt_hash"] == job.prompt_hash
        assert scene_prompt["reference_hash"] == job.reference_hash
        assert scene_prompt["input_hash"]
        assert scene_prompt["identity_constraints"]["feature_regions"] == (
            prompt_by_id[job.scene_prompt_version_id].identity_constraints["feature_regions"]
        )
        assert job.input_hash
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == len(jobs)

    # Duplicate refresh remains on the same checkpoint/thread and does not
    # create a second prompt/job or dispatch a provider call.
    refreshed = _resume(client, AUTH_HEADERS, provider_wait, "refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["thread_id"] == run.id
    assert db_session.query(ScenePromptVersion).filter_by(project_id=run.project_id).count() == len(rows)
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == len(jobs)
    deliveries = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).all()
    assert all(delivery.provider_dispatch_count == 0 for delivery in deliveries)

    # Process the durable outbox through the real fake-provider worker.  The
    # graph must remain at provider_wait until every latest scene attempt is
    # terminal, then resume the persisted thread exactly once.
    from src.db.database import SessionLocal
    from src.services import image_generation_worker

    real_resume = image_generation_worker._resume_completed_run
    resume_calls: list[str] = []

    def tracked_resume(run_id: str):
        resume_calls.append(run_id)
        return real_resume(run_id)

    monkeypatch.setattr(image_generation_worker, "_resume_completed_run", tracked_resume)
    worker_db = SessionLocal()
    try:
        results = image_generation_worker.run_image_worker_batch(
            worker_db, owner="lg8-real-graph-worker", batch_size=len(jobs) + 1
        )
    finally:
        worker_db.close()

    assert len(results) == len(jobs)
    assert resume_calls == [run.id]
    restored = client.get(f"/api/v1/graph-runs/{run.id}", headers=AUTH_HEADERS)
    assert restored.status_code == 200, restored.text
    assert restored.json()["thread_id"] == run.id
    assert restored.json()["current_stage"] == "image_review"
    review_jobs = restored.json()["values"]["generation"]["jobs"]
    assert len(review_jobs) == len(jobs)
    assert all(item["source_asset_ids"] for item in review_jobs)
    assert all(item["validation"]["schema_version"] == "lg9-image-validation-v1" for item in review_jobs)

    db_session.expire_all()
    completed = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).all()
    assert len(completed) == len(deliveries)
    assert all(row.status == "completed" for row in completed)
    assert all(row.provider_dispatch_count == 1 for row in completed)
    assert sum(row.completion_resume_count for row in completed) == 1
    completed_jobs = db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
    assert len(completed_jobs) == len(jobs)
    for job in completed_jobs:
        validation = job.validation_result
        assert validation["schema_version"] == "lg9-image-validation-v1"
        assert {"identity", "ocr", "crop", "resolution", "safety", "rights"} <= set(validation["checks"])
        assert validation["checks"]["identity"] == "needs_review"
        identity_checks = validation["details"]["identity"]["checks"]
        assert {"buttons", "ports", "components", "logo"} <= set(identity_checks)
        for element in ("buttons", "ports"):
            assert identity_checks[element]["status"] == "passed"
            assert identity_checks[element]["reason"] == "region_match"
            assert identity_checks[element]["max_mean_absolute_difference"] <= 45.0
            assert identity_checks[element]["region_count"] == 1
        for element in ("components", "logo"):
            assert identity_checks[element] == {
                "status": "needs_review",
                "reason": "structured_reference_unavailable",
            }
        assert validation["status"] in {"passed", "needs_review"}


def test_lg8_worker_restart_reconciles_final_commit_without_duplicate_dispatch(
    client, db_session, tmp_path, lg8_runtime, monkeypatch
):
    """A process loss after the final commit is repaired from DB state.

    The first worker session completes every fake-provider delivery but its
    callback is made unavailable, modelling a process exit in the narrow
    commit-to-resume window.  A fresh worker session must resume the same
    checkpoint once without re-dispatching or creating another job.
    """

    from src.db.database import SessionLocal
    from src.services import image_generation_worker

    run = _create_run(client, AUTH_HEADERS, db_session, tmp_path)
    generation_wait = _to_generation_pending(
        client, AUTH_HEADERS, run.id, db_session, minimum_generation_scenes=2
    )
    cost_hash = generation_wait["values"]["review"]["pending"]["context"]["generation"][
        "cost_plan"
    ]["cost_plan_hash"]
    provider_wait_response = _resume(
        client, AUTH_HEADERS, generation_wait, "approve", cost_plan_hash=cost_hash
    )
    assert provider_wait_response.status_code == 200, provider_wait_response.text
    assert provider_wait_response.json()["current_stage"] == "provider_wait"

    db_session.expire_all()
    job_count = db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count()
    outbox_count = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count()
    assert job_count == outbox_count >= 2

    real_resume = image_generation_worker._resume_completed_run
    lost_callback_attempts: list[str] = []

    def unavailable_resume(run_id: str):
        lost_callback_attempts.append(run_id)
        return None

    monkeypatch.setattr(image_generation_worker, "_resume_completed_run", unavailable_resume)
    first_worker_db = SessionLocal()
    try:
        first_results = image_generation_worker.run_image_worker_batch(
            first_worker_db, owner="lg8-before-restart", batch_size=outbox_count + 1
        )
    finally:
        first_worker_db.close()
    assert len(first_results) == outbox_count
    assert lost_callback_attempts

    still_waiting = client.get(f"/api/v1/graph-runs/{run.id}", headers=AUTH_HEADERS)
    assert still_waiting.status_code == 200, still_waiting.text
    assert still_waiting.json()["current_stage"] == "provider_wait"

    db_session.expire_all()
    committed = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).all()
    assert all(row.status == "completed" for row in committed)
    assert all(row.provider_dispatch_count == 1 for row in committed)
    assert sum(row.completion_resume_count for row in committed) == 0

    # A new process/session starts with an empty queue.  Startup reconciliation
    # must nevertheless observe the complete wave and resume the real graph.
    monkeypatch.setattr(image_generation_worker, "_resume_completed_run", real_resume)
    restarted_db = SessionLocal()
    try:
        assert image_generation_worker.run_image_worker_batch(
            restarted_db, owner="lg8-after-restart", batch_size=outbox_count + 1
        ) == []
        assert image_generation_worker.run_image_worker_batch(
            restarted_db, owner="lg8-duplicate-poll", batch_size=outbox_count + 1
        ) == []
    finally:
        restarted_db.close()

    recovered = client.get(f"/api/v1/graph-runs/{run.id}", headers=AUTH_HEADERS)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["thread_id"] == run.id
    assert recovered.json()["current_stage"] == "image_review"

    db_session.expire_all()
    final_jobs = db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
    final_outbox = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).all()
    assert len(final_jobs) == job_count
    assert len(final_outbox) == outbox_count
    assert all(row.provider_dispatch_count == 1 for row in final_outbox)
    assert sum(row.completion_resume_count for row in final_outbox) == 1
