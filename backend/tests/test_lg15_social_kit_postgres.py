"""LG-15-A1 PostgreSQL acceptance for immutable SocialKitVersion persistence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import json
import hashlib
from pathlib import Path
from threading import Barrier
from uuid import uuid4
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import object_session, sessionmaker

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.db.models import (
    AgentRun,
    AgentRunEvent,
    Asset,
    Brand,
    CommerceCreativeMasterVersion,
    FactSnapshot,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ImageGenerationProviderAttemptRecord,
    ProductProject,
    SocialCardCopyVersion,
    SocialKitVersion,
    User,
    Workspace,
)
from src.app import app
from src.db.database import get_db
from src.services.product_intake_version_service import create_commerce_creative_master_version
from src.services.prompt_intelligence_service import canonical_hash
from src.services.social_kit_version_service import (
    SocialKitContractError,
    SOCIAL_CARD_MANIFEST_SCHEMA_VERSION,
    create_social_kit_version,
    deterministic_fake_social_cards,
    deterministic_social_channel_contract_reference,
    evolve_social_card_manifest,
    evaluate_social_card_quality,
    deterministic_social_render_profile,
    render_social_kit_deterministic,
    evaluate_social_platform_quality,
    validate_social_kit_version,
    apply_social_card_action,
    social_card_action_idempotency_key,
    public_social_kit_projection,
)
from src.services.langgraph_run_service import AgentRunEventJournal, GraphRunExecutionFailed, LangGraphRunService
from src.services.langgraph_image_generation_service import prepare_social_card_generation_jobs
from src.services import image_generation_worker
from src.config import settings
from test_lg12i_commerce_creative_master import _build_brief_and_master, _source_chain_with_asset
from test_lg12i_version_contract import _ref


pytestmark = [pytest.mark.postgres, pytest.mark.integration]
_MIGRATION = Path(__file__).parents[1] / "migrations" / "20260829_lg15_social_kit_version.sql"


@pytest.fixture(scope="module")
def social_engine():
    import os

    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        connection.exec_driver_sql(_MIGRATION.read_text(encoding="utf-8"))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def social_db(social_engine):
    connection = social_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _run(session) -> AgentRun:
    suffix = uuid4().hex
    user = User(id=str(uuid4()), email=f"lg15-{suffix}@test.invalid", name="LG15 test")
    session.add(user)
    session.flush()
    workspace = Workspace(id=str(uuid4()), name="LG15 workspace", owner_id=user.id)
    session.add(workspace)
    session.flush()
    brand = Brand(id=str(uuid4()), workspace_id=workspace.id, name="LG15 brand")
    session.add(brand)
    session.flush()
    project = ProductProject(id=str(uuid4()), workspace_id=workspace.id, brand_id=brand.id, name="LG15 project")
    session.add(project)
    session.flush()
    run = AgentRun(
        id=str(uuid4()),
        workspace_id=workspace.id,
        project_id=project.id,
        created_by=user.id,
        mode="lg12i_intake",
        status="completed",
        current_stage="planning_review",
        input_snapshot={"unified_product_intake": {"input_mode": "manual"}},
        outputs_json={},
        cost_approval_status="not_required",
    )
    session.add(run)
    session.flush()
    return run


def _lineage(session, tmp_path):
    run = _run(session)
    chain, asset, _asset_path = _source_chain_with_asset(session, run, tmp_path)
    brief, _facts, master, _kit = _build_brief_and_master(session, run, chain)
    assert brief.usable_asset_refs_json
    return run, chain, asset, brief, master


def _recovery_run(session, run: AgentRun) -> AgentRun:
    replay = AgentRun(
        id=str(uuid4()),
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        created_by=run.created_by,
        mode="lg15_social_kit",
        status="running",
        current_stage="social_kit_requested",
        input_snapshot={},
        outputs_json={},
        cost_approval_status="not_required",
    )
    session.add(replay)
    session.flush()
    return replay


def _social_request(
    run, brief, master, *,
    logical_targets=("hero", "benefit", "feature", "usage", "cta"),
    parent_version_id=None,
    channel="smartstore",
    format="card",
):
    template = "lg15-fake-template-v1"
    evaluator = "lg15-fake-evaluator-v1"
    session = object_session(run)
    assert session is not None
    cards = deterministic_fake_social_cards(
        session,
        master=master,
        channel=channel,
        format=format,
        logical_targets=logical_targets,
        template_version=template,
        evaluator_version=evaluator,
    )
    return {
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "creator_run_id": run.id,
        "created_by": run.created_by,
        "source_master_reference": _ref(master.id, master.version, master.canonical_hash),
        "target_channel": channel,
        "target_format": format,
        "channel_contract_reference": deterministic_social_channel_contract_reference(
            channel=channel,
            format=format,
        ),
        "card_manifest": cards,
        "template_version": template,
        "evaluator_version": evaluator,
        "execution_mode": "deterministic_fake",
        "parent_version_id": parent_version_id,
    }


def _cards(manifest):
    return list(manifest["cards"])


def _rehash_test_card(card):
    value = deepcopy(card)
    value.pop("output_hash", None)
    value["output_hash"] = canonical_hash(value)
    return value


@pytest.fixture
def social_graph_db(social_engine, monkeypatch):
    url = require_local_postgres_test_url(
        __import__("os").environ.get("TEST_DATABASE_URL"),
        allow=__import__("os").environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    monkeypatch.setattr(settings, "SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL", url)
    monkeypatch.setattr(settings, "SELLFORM_LANGGRAPH_CHECKPOINT_SETUP_ON_START", True)
    session = sessionmaker(bind=social_engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        _truncate_committed_a1_state(social_engine)


def test_postgres_social_subgraph_entry_persists_bounded_lifecycle_and_checkpoint(
    social_graph_db, tmp_path,
):
    source_run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    raw_request = _social_request(source_run, brief, master)
    request = {**{key: value for key, value in raw_request.items() if key not in {"creator_run_id", "created_by", "workspace_id", "project_id", "card_manifest"}}, "logical_targets": ["hero", "benefit", "feature", "usage", "cta"]}

    result = LangGraphRunService.start_social_kit(
        project_id=source_run.project_id,
        workspace_id=source_run.workspace_id,
        actor_id=source_run.created_by,
        request=request,
        db=social_graph_db,
    )
    assert result.status == "completed"
    social_graph_db.expire_all()
    run = social_graph_db.get(AgentRun, result.id)
    kits = social_graph_db.query(SocialKitVersion).filter_by(project_id=result.project_id).all()
    assert run is not None and run.mode == "lg15_social_kit"
    assert len(kits) == 1
    assert run.outputs_json["langgraph_social"]["social_kit_ref"]["id"] == kits[0].id
    event_types = [event.event_type for event in sorted(run.events, key=lambda item: item.sequence)]
    assert {"social_kit_requested", "social_planning_completed", "social_kit_version_created", "social_review_ready"} <= set(event_types)
    assert all(set((event.payload_json or {}).get("social", {})) == {
        "channel", "format", "execution_mode", "template_version", "evaluator_version", "card_count", "status",
    } for event in run.events if event.event_type.startswith("social_"))

    state = LangGraphRunService.get_state(result.id, result.workspace_id, social_graph_db)
    assert state.values["social"]["social_kit_ref"]["id"] == kits[0].id
    assert state.values["social"]["card_count"] == 5
    assert run.outputs_json["langgraph_social"]["manifest_schema_version"] == SOCIAL_CARD_MANIFEST_SCHEMA_VERSION
    assert run.outputs_json["langgraph_social"]["manifest_hash"] == kits[0].output_hash
    quality = run.outputs_json["langgraph_quality"]
    assert quality["quality_stage"] == "content"
    assert quality["verdict"] == "PASS"
    assert {item["status"] for item in quality["dimension_results"]} >= {"PASS", "DEFERRED"}
    assert social_graph_db.query(AgentRunEvent).filter_by(
        run_id=run.id, event_type="quality_evaluated"
    ).count() == 1
    quality_event = social_graph_db.query(AgentRunEvent).filter_by(
        run_id=run.id, event_type="quality_evaluated"
    ).one()
    assert quality_event.payload_json["quality"] == quality
    render = run.outputs_json["langgraph_social"]["render"]
    assert render["schema_version"] == "lg15-social-render-v1"
    assert render["status"] == "completed"
    assert len(render["cards"]) == 5
    generated_jobs = social_graph_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
    generated_outbox = social_graph_db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).all()
    generated_attempts = social_graph_db.query(ImageGenerationProviderAttemptRecord).filter(
        ImageGenerationProviderAttemptRecord.image_job_id.in_([job.id for job in generated_jobs])
    ).all()
    assert len(generated_jobs) == len(generated_outbox) == 5
    assert len(generated_attempts) == 5
    assert all(job.status == "needs_review" and job.estimated_cost == 0 for job in generated_jobs)
    assert all(attempt.actual_cost == 0 and attempt.cost_state == "EXPLICIT_ZERO" for attempt in generated_attempts)
    assert all(outbox.status == "completed" and outbox.provider_mode == "mock" for outbox in generated_outbox)
    social_assets = social_graph_db.query(Asset).filter(
        Asset.project_id == run.project_id, Asset.asset_role.like("social_%")
    ).all()
    assert len(social_assets) == 5
    assert all(asset.source_asset_id and asset.content_hash and asset.source_type == "ai_generated" for asset in social_assets)
    generation = run.outputs_json["langgraph_social"]["generation"]
    assert generation["status"] == "completed" and len(generation["cards"]) == 5
    assert all(set(card) == {"card_id", "role", "job_ref", "asset_ref", "semantic_hash", "status"} for card in generation["cards"])
    assert {event.event_type for event in run.events} >= {
        "social_render_started", "social_card_rendered", "social_render_completed",
    }
    assert all(
        marker not in json.dumps(event.payload_json, sort_keys=True)
        for event in run.events
        for marker in ("raw_provider_payload", "prompt", "signed_url")
    )

    unresolved_contract = deterministic_social_channel_contract_reference(channel="smartstore", format="unsupported")
    with pytest.raises(SocialKitContractError, match="channel_contract"):
        LangGraphRunService.start_social_kit(
            project_id=source_run.project_id,
            workspace_id=source_run.workspace_id,
            actor_id=source_run.created_by,
            request={**request, "channel_contract_reference": unresolved_contract},
            db=social_graph_db,
        )


def test_postgres_instagram_social_subgraph_uses_publishing_profile(social_graph_db, tmp_path):
    source_run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    raw_request = _social_request(source_run, brief, master, channel="instagram", format="feed_portrait")
    request = {key: raw_request[key] for key in (
        "source_master_reference", "target_channel", "target_format", "channel_contract_reference",
        "template_version", "evaluator_version", "parent_version_id", "execution_mode",
    )}
    request["logical_targets"] = ["hero", "benefit", "feature", "usage", "cta"]
    result = LangGraphRunService.start_social_kit(
        project_id=source_run.project_id,
        workspace_id=source_run.workspace_id,
        actor_id=source_run.created_by,
        request=request,
        db=social_graph_db,
    )
    social_graph_db.expire_all()
    run = social_graph_db.get(AgentRun, result.id)
    render = dict((run.outputs_json or {}).get("langgraph_social") or {}).get("render") or {}
    profile = render["render_profile"]
    assert result.status == "completed"
    assert profile["profile_id"] == "instagram_feed_portrait"
    assert profile["canvas"] == {"width": 1080, "height": 1350}
    assert profile["production_compliance"] == "production"
    assert evaluate_social_platform_quality(
        social_graph_db,
        social_graph_db.query(SocialKitVersion).filter_by(project_id=result.project_id).one(),
        render,
    )["verdict"] == "PASS"


def test_postgres_social_subgraph_replay_and_recovery_do_not_duplicate_kit(
    social_graph_db, tmp_path,
):
    source_run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    raw_request = _social_request(source_run, brief, master)
    request = {**{key: value for key, value in raw_request.items() if key not in {"creator_run_id", "created_by", "workspace_id", "project_id", "card_manifest"}}, "logical_targets": ["hero", "benefit", "feature", "usage", "cta"]}
    first = LangGraphRunService.start_social_kit(
        project_id=source_run.project_id,
        workspace_id=source_run.workspace_id,
        actor_id=source_run.created_by,
        request=request,
        db=social_graph_db,
    )
    first_count = social_graph_db.query(SocialKitVersion).filter_by(project_id=first.project_id).count()
    first_asset_count = social_graph_db.query(Asset).filter(
        Asset.project_id == first.project_id, Asset.asset_role.like("social_%")
    ).count()
    first_render_event_count = social_graph_db.query(AgentRunEvent).filter(
        AgentRunEvent.run_id == first.id, AgentRunEvent.event_type == "social_render_completed"
    ).count()
    replay = LangGraphRunService.start_social_kit(
        project_id=source_run.project_id,
        workspace_id=source_run.workspace_id,
        actor_id=source_run.created_by,
        request=request,
        db=social_graph_db,
    )
    recovered = LangGraphRunService.resume(first.id, first.workspace_id, social_graph_db, recovery_only=True)
    assert replay.id == first.id == recovered.id
    assert social_graph_db.query(SocialKitVersion).filter_by(project_id=first.project_id).count() == first_count == 1
    assert social_graph_db.query(Asset).filter(
        Asset.project_id == first.project_id, Asset.asset_role.like("social_%")
    ).count() == first_asset_count == 5
    assert social_graph_db.query(AgentRunEvent).filter(
        AgentRunEvent.run_id == first.id, AgentRunEvent.event_type == "social_render_completed"
    ).count() == first_render_event_count == 1
    assert social_graph_db.query(ImageGenerationJobRecord).filter_by(project_id=first.project_id).count() == 5
    assert social_graph_db.query(ImageGenerationOutboxRecord).filter_by(run_id=first.id).count() == 5
    assert social_graph_db.query(ImageGenerationProviderAttemptRecord).join(
        ImageGenerationJobRecord,
        ImageGenerationProviderAttemptRecord.image_job_id == ImageGenerationJobRecord.id,
    ).filter(ImageGenerationJobRecord.project_id == first.project_id).count() == 5
    assert social_graph_db.query(Asset).filter(
        Asset.project_id == first.project_id, Asset.asset_role.like("social_%")
    ).count() == 5
    assert social_graph_db.query(AgentRunEvent).filter(
        AgentRunEvent.run_id == first.id, AgentRunEvent.event_type == "social_card_generation_completed"
    ).count() == 1
    assert social_graph_db.query(SocialKitVersion).filter_by(project_id=first.project_id).one().card_manifest_json


def test_postgres_social_worker_dead_letter_keeps_provider_error_bounded(
    social_db, tmp_path, monkeypatch,
):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    kit = create_social_kit_version(social_db, **_social_request(run, brief, master))
    generation = prepare_social_card_generation_jobs(
        run_id=run.id,
        project_id=run.project_id,
        kit_id=kit.id,
        render_profile=deterministic_social_render_profile(kit),
        db=social_db,
    )
    job_id = generation["cards"][0]["job_id"]
    delivery = social_db.query(ImageGenerationOutboxRecord).filter_by(job_id=job_id).one()
    delivery.max_delivery_attempts = 1
    social_db.commit()

    marker = "PROMPT_SECRET_LG15_PROVIDER_FAILURE"
    def fail_provider(*_args, **_kwargs):
        raise RuntimeError(f"TIMEOUT: {marker} https://signed.example/private?token=SECRET")

    monkeypatch.setattr(image_generation_worker.DurableFakeImageProvider, "generate", fail_provider)
    claimed = image_generation_worker.claim_image_delivery(
        social_db, owner="lg15-test-worker", run_id=run.id,
    )
    assert claimed is not None
    result = image_generation_worker.process_image_delivery(
        claimed.id, "lg15-test-worker", social_db,
    )
    assert result["status"] == "dead_letter"
    social_db.expire_all()
    job = social_db.query(ImageGenerationJobRecord).filter_by(job_id=job_id).one()
    delivery = social_db.query(ImageGenerationOutboxRecord).filter_by(job_id=job_id).one()
    persisted = json.dumps({
        "job": {
            "warnings": job.warnings,
            "error_code": job.error_code,
            "input_snapshot": job.input_snapshot,
            "usage_metadata": job.usage_metadata,
        },
        "delivery": {
            "last_error_code": delivery.last_error_code,
            "last_error_message": delivery.last_error_message,
        },
    }, sort_keys=True)
    assert marker not in persisted
    assert "SECRET" not in persisted
    assert job.error_code == "PROVIDER_TIMEOUT"
    assert job.warnings and delivery.last_error_message
    attempts = social_db.query(ImageGenerationProviderAttemptRecord).filter_by(image_job_id=job.id).all()
    assert attempts and all(marker not in json.dumps(attempt.__dict__, default=str) for attempt in attempts)
    assert social_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == 5


def test_postgres_social_generation_crash_after_provider_result_replays_without_duplicate(
    social_graph_db, tmp_path, monkeypatch,
):
    source_run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    raw_request = _social_request(source_run, brief, master)
    request = {
        **{key: value for key, value in raw_request.items()
           if key not in {"creator_run_id", "created_by", "workspace_id", "project_id", "card_manifest"}},
        "logical_targets": ["hero", "benefit", "feature", "usage", "cta"],
    }
    original = image_generation_worker.process_image_delivery
    crashed = {"value": False}

    def crash_after_first_result(delivery_id, owner, db):
        result = original(delivery_id, owner, db)
        if not crashed["value"] and result.get("status") == "completed":
            crashed["value"] = True
            raise RuntimeError("simulated crash after provider result commit")
        return result

    monkeypatch.setattr(image_generation_worker, "process_image_delivery", crash_after_first_result)
    with pytest.raises(GraphRunExecutionFailed):
        LangGraphRunService.start_social_kit(
            project_id=source_run.project_id,
            workspace_id=source_run.workspace_id,
            actor_id=source_run.created_by,
            request=request,
            db=social_graph_db,
        )
    failed = social_graph_db.query(AgentRun).filter_by(
        mode="lg15_social_kit", project_id=source_run.project_id,
    ).one()
    monkeypatch.setattr(image_generation_worker, "process_image_delivery", original)
    recovered = LangGraphRunService.resume(failed.id, failed.workspace_id, social_graph_db)
    assert recovered.status == "completed"
    assert social_graph_db.query(ImageGenerationJobRecord).filter_by(project_id=failed.project_id).count() == 5
    assert social_graph_db.query(ImageGenerationProviderAttemptRecord).join(
        ImageGenerationJobRecord,
        ImageGenerationProviderAttemptRecord.image_job_id == ImageGenerationJobRecord.id,
    ).filter(ImageGenerationJobRecord.project_id == failed.project_id).count() == 5
    assert social_graph_db.query(Asset).filter(
        Asset.project_id == failed.project_id, Asset.asset_role.like("social_%")
    ).count() == 5
    assert social_graph_db.query(AgentRunEvent).filter(
        AgentRunEvent.run_id == failed.id,
        AgentRunEvent.event_type.in_(["social_card_generation_requested", "social_card_generation_completed"]),
    ).count() == 2


def test_postgres_social_subgraph_crash_after_kit_persistence_recovers_without_duplicate(
    social_graph_db, tmp_path, monkeypatch,
):
    source_run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    raw_request = _social_request(source_run, brief, master)
    request = {**{key: value for key, value in raw_request.items() if key not in {"creator_run_id", "created_by", "workspace_id", "project_id", "card_manifest"}}, "logical_targets": ["hero", "benefit", "feature", "usage", "cta"]}
    from src.services import langgraph_run_service

    original = langgraph_run_service.AgentRunGraphProjector.apply_node_update
    def crash_after_planner(run, db, update):
        event = dict((update.get("events") or [{}])[-1])
        if event.get("stage") == "social_review_ready":
            raise RuntimeError("simulated transport crash after SocialKit persistence")
        return original(run, db, update)

    monkeypatch.setattr(langgraph_run_service.AgentRunGraphProjector, "apply_node_update", crash_after_planner)
    with pytest.raises(langgraph_run_service.GraphRunExecutionFailed):
        LangGraphRunService.start_social_kit(
            project_id=source_run.project_id,
            workspace_id=source_run.workspace_id,
            actor_id=source_run.created_by,
            request=request,
            db=social_graph_db,
        )
    failed = social_graph_db.query(AgentRun).filter_by(mode="lg15_social_kit", project_id=source_run.project_id).one()
    assert social_graph_db.query(SocialKitVersion).filter_by(project_id=source_run.project_id).count() == 1
    monkeypatch.setattr(langgraph_run_service.AgentRunGraphProjector, "apply_node_update", original)

    recovered = LangGraphRunService.resume(failed.id, failed.workspace_id, social_graph_db)
    assert recovered.status == "completed"
    assert recovered.current_stage == "social_review_ready"
    assert social_graph_db.query(SocialKitVersion).filter_by(project_id=source_run.project_id).count() == 1
    assert social_graph_db.query(AgentRunEvent).filter(
        AgentRunEvent.run_id == failed.id,
        AgentRunEvent.event_type == "social_kit_version_created",
    ).count() == 1


def _successor_master(session, run, master):
    return create_commerce_creative_master_version(
        session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        source_reference={"id": master.source_snapshot_version_id, "version": master.source_snapshot_version, "hash": master.source_snapshot_hash},
        truth_reference={"id": master.truth_version_id, "version": master.truth_version, "hash": master.truth_version_hash},
        confirmation_reference={"id": master.confirmation_version_id, "version": master.confirmation_version, "hash": master.confirmation_version_hash},
        creative_brief_reference={"id": master.creative_brief_version_id, "version": master.creative_brief_version, "hash": master.creative_brief_hash},
        brand_kit_reference={"id": master.brand_kit_version_id, "version": master.brand_kit_version, "hash": master.brand_kit_hash},
        evidence_artifact_refs=master.evidence_artifact_refs_json,
        approved_fact_snapshot_ref=master.approved_fact_snapshot_ref_json,
        approved_asset_manifest_ref=master.approved_asset_manifest_ref_json,
        copy_artifact_ref=master.copy_artifact_ref_json,
        page_plan_artifact_ref=master.page_plan_artifact_ref_json,
        target_channels=master.target_channels,
        parent_version_id=master.id,
    )


def test_postgres_social_kit_persists_frozen_master_refs_and_replays_without_duplicate(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    request = _social_request(run, brief, master)
    first_cards = request["card_manifest"]
    assert first_cards == _social_request(run, brief, master)["card_manifest"]

    first = create_social_kit_version(social_db, **request)
    manifest = first.card_manifest_json
    cards = _cards(manifest)
    assert manifest["manifest_schema_version"] == SOCIAL_CARD_MANIFEST_SCHEMA_VERSION
    assert manifest["brand_kit_ref"] == first.brand_kit_ref_json
    assert [card["role"] for card in cards] == ["hero", "benefit", "feature", "usage", "cta"]
    assert [card["order"] for card in cards] == [1, 2, 3, 4, 5]
    assert len({card["card_id"] for card in cards}) == 5
    assert all(
        card["fact_refs"] and card["provenance_refs"] and card["selected_variant_ref"] and card["status"] == "planned"
        for card in cards
    )
    replay = create_social_kit_version(social_db, **request)
    assert replay.id == first.id
    recovery_run = _recovery_run(social_db, run)
    recovered = create_social_kit_version(social_db, **_social_request(recovery_run, brief, master))
    assert recovered.id == first.id and recovered.creator_run_id == run.id
    assert social_db.query(SocialKitVersion).filter_by(project_id=run.project_id).count() == 1
    assert (first.source_master_id, first.source_master_version, first.source_master_hash) == (
        master.id,
        master.version,
        master.canonical_hash,
    )
    assert first.approved_fact_snapshot_ref_json == master.approved_fact_snapshot_ref_json
    assert first.creative_brief_ref_json == _ref(brief.id, brief.version, brief.output_hash)
    assert first.brand_kit_ref_json == _ref(master.brand_kit_version_id, master.brand_kit_version, master.brand_kit_hash)
    assert first.rights_asset_refs_json == brief.usable_asset_refs_json
    assert len(first.idempotency_key) == len(first.output_hash) == len(first.canonical_hash) == 64
    validate_social_kit_version(social_db, first)

    successor_request = _social_request(run, brief, master, parent_version_id=first.id)
    successor = create_social_kit_version(social_db, **successor_request)
    assert successor.id != first.id and successor.version == first.version + 1
    assert successor.parent_version_id == first.id
    assert create_social_kit_version(social_db, **successor_request).id == successor.id
    assert social_db.query(SocialKitVersion).filter_by(project_id=run.project_id).count() == 2

    with pytest.raises(SocialKitContractError, match="current kit version"):
        create_social_kit_version(
            social_db,
            **_social_request(run, brief, master, logical_targets=("hero", "benefit", "cta"), parent_version_id=first.id),
        )


def test_postgres_social_quality_fails_safety_inputs_with_bounded_rework_target(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    row = create_social_kit_version(social_db, **_social_request(run, brief, master))
    valid = evaluate_social_card_quality(social_db, row)
    assert valid["verdict"] == "PASS"
    assert valid["reason_codes"] == []

    tampered = deepcopy(row.card_manifest_json)
    tampered["cards"] = [card for card in _cards(tampered) if card["role"] != "benefit"]
    row.card_manifest_json = tampered
    failed = evaluate_social_card_quality(social_db, row)
    assert failed["verdict"] == "FAIL"
    assert "required_role_missing" in failed["reason_codes"]
    assert failed["rework_targets"][0]["action_type"] == "card_rework"
    assert set(failed["rework_targets"][0]) == {"card_id", "logical_target", "role", "reason_code", "action_type"}


def test_postgres_social_quality_replay_is_deterministic_and_deduplicated(social_graph_db, tmp_path):
    source_run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    raw_request = _social_request(source_run, brief, master)
    request = {
        **{key: value for key, value in raw_request.items() if key not in {"creator_run_id", "created_by", "workspace_id", "project_id", "card_manifest"}},
        "logical_targets": ["hero", "benefit", "feature", "usage", "cta"],
    }
    first = LangGraphRunService.start_social_kit(
        project_id=source_run.project_id,
        workspace_id=source_run.workspace_id,
        actor_id=source_run.created_by,
        request=request,
        db=social_graph_db,
    )
    before = dict((first.outputs_json or {}).get("langgraph_quality") or {})
    resumed = LangGraphRunService.resume(first.id, first.workspace_id, social_graph_db, recovery_only=True)
    social_graph_db.expire_all()
    after = dict((social_graph_db.get(AgentRun, resumed.id).outputs_json or {}).get("langgraph_quality") or {})
    assert after == before
    assert social_graph_db.query(AgentRunEvent).filter_by(
        run_id=first.id, event_type="quality_evaluated"
    ).count() == 1


def test_postgres_social_deterministic_render_persists_bounded_asset_lineage_and_replays(
    social_db, tmp_path,
):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    kit = create_social_kit_version(social_db, **_social_request(run, brief, master))
    output_dir = tmp_path / "renders"
    first = render_social_kit_deterministic(social_db, kit, output_dir=str(output_dir))
    assert first["execution_mode"] == "deterministic_fake"
    assert first["render_profile"]["production_compliance"] == "unresolved"
    assert first["render_profile"]["canvas"] == {"width": 640, "height": 360}
    assert len(first["cards"]) == 5
    assets = social_db.query(Asset).filter_by(project_id=run.project_id, source_type="html-graphic").all()
    assert len(assets) == 5
    for card in first["cards"]:
        asset = social_db.get(Asset, card["asset_ref"]["id"])
        assert asset is not None
        assert asset.content_hash == hashlib.sha256(Path(asset.file_path).read_bytes()).hexdigest()
        assert asset.source_asset_id
        assert asset.usage_status == "derived_graphic"
    forbidden = ("PROMPT_SECRET", "provider_payload", "signed.example", "customer@example.com")
    persisted = " ".join(
        json.dumps(value, sort_keys=True)
        for value in (first, kit.card_manifest_json, [asset.quality_warnings for asset in assets])
    )
    assert all(marker not in persisted for marker in forbidden)
    replay = render_social_kit_deterministic(social_db, kit, output_dir=str(output_dir))
    assert replay == first
    assert social_db.query(Asset).filter_by(project_id=run.project_id, source_type="html-graphic").count() == 5
    alternate = render_social_kit_deterministic(
        social_db, kit, output_dir=str(output_dir),
        profile=deterministic_social_render_profile(kit, profile_id="lg15-alt-profile-v1"),
    )
    assert {item["semantic_hash"] for item in alternate["cards"]}.isdisjoint(
        {item["semantic_hash"] for item in first["cards"]}
    )
    assert social_db.query(Asset).filter_by(project_id=run.project_id, source_type="html-graphic").count() == 10


def test_postgres_instagram_feed_portrait_profile_and_platform_quality(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    request = _social_request(run, brief, master, channel="instagram", format="feed_portrait")
    kit = create_social_kit_version(social_db, **request)
    profile = deterministic_social_render_profile(kit)
    assert profile["profile_id"] == "instagram_feed_portrait"
    assert profile["profile_version"] == 1
    assert profile["target_platform"] == "instagram"
    assert profile["target_format"] == "feed_portrait"
    assert profile["canvas"] == {"width": 1080, "height": 1350}
    assert profile["aspect_ratio"] == "4:5"
    assert profile["safe_area_policy"] == "none_v1"
    assert profile["copy_policy"] == "existing_content_quality"
    assert profile["classification"] == "SELLFORM_PRODUCT_DECISION"
    assert profile["exports"] == ["png", "jpg", "zip"]
    assert kit.card_manifest_json["publishing_profile_ref"]["id"] == "instagram_feed_portrait"
    rendered = render_social_kit_deterministic(social_db, kit, output_dir=str(tmp_path / "renders"))
    quality = evaluate_social_platform_quality(social_db, kit, rendered)
    assert quality["verdict"] == "PASS"
    assert quality["reasons"] == []
    for card in rendered["cards"]:
        asset = social_db.get(Asset, card["asset_ref"]["id"])
        assert (asset.width, asset.height) == (1080, 1350)


def test_postgres_instagram_profile_rejects_stale_or_wrong_geometry(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    kit = create_social_kit_version(social_db, **_social_request(run, brief, master, channel="instagram", format="feed_portrait"))
    stale = deterministic_social_render_profile(kit)
    stale["canvas"] = {"width": 1080, "height": 1080}
    stale["canonical_hash"] = canonical_hash({key: value for key, value in stale.items() if key != "canonical_hash"})
    with pytest.raises(SocialKitContractError, match="canonical Instagram profile"):
        render_social_kit_deterministic(social_db, kit, output_dir=str(tmp_path / "stale"), profile=stale)
    with pytest.raises(SocialKitContractError, match="Unknown SocialKit publishing profile"):
        deterministic_social_render_profile(kit, profile_id="instagram_feed_square")
    rendered = render_social_kit_deterministic(social_db, kit, output_dir=str(tmp_path / "wrong"))
    asset = social_db.get(Asset, rendered["cards"][0]["asset_ref"]["id"])
    asset.width = 1080
    asset.height = 1080
    social_db.flush()
    quality = evaluate_social_platform_quality(social_db, kit, rendered)
    assert quality["verdict"] == "FAIL"
    assert "wrong_dimensions" in quality["reasons"]


def test_postgres_instagram_api_exports_match_profile_bytes_and_zip_manifest(social_graph_db, tmp_path):
    source_run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    raw_request = _social_request(source_run, brief, master, channel="instagram", format="feed_portrait")
    request = {key: raw_request[key] for key in (
        "source_master_reference", "target_channel", "target_format", "channel_contract_reference",
        "template_version", "evaluator_version", "parent_version_id", "execution_mode",
    )}
    request["logical_targets"] = ["hero", "benefit", "feature", "usage", "cta"]
    run = LangGraphRunService.start_social_kit(
        project_id=source_run.project_id,
        workspace_id=source_run.workspace_id,
        actor_id=source_run.created_by,
        request=request,
        db=social_graph_db,
    )
    social_graph_db.expire_all()
    headers = {"X-Mock-User-Id": run.created_by, "X-Mock-Workspace-Id": run.workspace_id}

    def override_db():
        yield social_graph_db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            projection = client.get(
                f"/api/v1/projects/{run.project_id}/social-kit", headers=headers,
            )
            assert projection.status_code == 200
            body = projection.json()["kit"]
            assert body["publishing_profile"] == {
                "platform": "instagram", "format": "feed_portrait", "width": 1080,
                "height": 1350, "aspect_ratio": "4:5", "safe_area_policy": "none_v1",
                "copy_policy": "existing_content_quality", "exports": ["png", "jpg", "zip"],
                "readiness": "ready",
            }
            assert body["platform_quality"]["verdict"] == "PASS"
            for output_format in ("png", "jpg"):
                response = client.get(
                    f"/api/v1/projects/{run.project_id}/social-kit/export/{output_format}",
                    headers=headers,
                )
                assert response.status_code == 200
                with Image.open(BytesIO(response.content)) as image:
                    assert image.size == (1080, 1350)
            response = client.get(
                f"/api/v1/projects/{run.project_id}/social-kit/export/zip", headers=headers,
            )
            assert response.status_code == 200
            with zipfile.ZipFile(BytesIO(response.content)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                assert manifest["platform"] == "instagram"
                assert manifest["format"] == "feed_portrait"
                assert manifest["profile_version"] == 1
                assert len(manifest["cards"]) == 5
                assert all(name.startswith("instagram-feed-portrait-") for name in archive.namelist() if name.endswith(".png"))
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_postgres_social_seller_projection_is_bounded_and_asset_downloadable(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    kit = create_social_kit_version(social_db, **_social_request(run, brief, master))
    rendered = render_social_kit_deterministic(social_db, kit, output_dir=str(tmp_path / "renders"))
    run.outputs_json = {"langgraph_social": {"render": rendered}}
    social_db.commit()
    projection = public_social_kit_projection(social_db, kit, run)
    assert projection["status"] == "rendered"
    assert len(projection["cards"]) == 5
    assert all(card["preview_url"].startswith("/api/v1/files/assets/") for card in projection["cards"])
    serialized = json.dumps(projection, sort_keys=True)
    assert all(marker not in serialized for marker in ("prompt", "provider", "checkpoint", "storage_path", "signed_url"))


def test_postgres_social_api_actions_and_exports_use_current_bounded_kit(social_graph_db, tmp_path):
    source_run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    request = _social_request(source_run, brief, master)
    request = {key: value for key, value in request.items() if key not in {"creator_run_id", "created_by", "workspace_id", "project_id", "card_manifest"}}
    request["logical_targets"] = ["hero", "benefit", "feature", "usage", "cta"]
    run = LangGraphRunService.start_social_kit(
        project_id=source_run.project_id,
        workspace_id=source_run.workspace_id,
        actor_id=source_run.created_by,
        request=request,
        db=social_graph_db,
    )
    social_graph_db.expire_all()
    initial = social_graph_db.query(SocialKitVersion).filter_by(project_id=run.project_id).one()
    headers = {"X-Mock-User-Id": run.created_by, "X-Mock-Workspace-Id": run.workspace_id}

    def override_db():
        yield social_graph_db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/projects/{run.project_id}/social-kit", headers=headers)
            assert response.status_code == 200
            payload = response.json()
            assert payload["kit"]["status"] == "rendered"
            assert len(payload["kit"]["cards"]) == 5
            for output_format in ("png", "jpg", "zip"):
                exported = client.get(
                    f"/api/v1/projects/{run.project_id}/social-kit/export/{output_format}",
                    headers=headers,
                )
                assert exported.status_code == 200
                assert exported.content
                if output_format == "zip":
                    with zipfile.ZipFile(BytesIO(exported.content)) as archive:
                        names = archive.namelist()
                        assert "manifest.json" in names
                        assert len([name for name in names if name.endswith(".png")]) == len(payload["kit"]["cards"])
                else:
                    assert exported.headers["content-type"].startswith("image/")
            cards = payload["kit"]["cards"]
            action_url = f"/api/v1/projects/{run.project_id}/social-kit/actions"
            reordered = client.post(action_url, headers=headers, json={
                "run_id": run.id,
                "action": "reorder",
                "parent_social_kit_ref": {"id": payload["kit"]["id"], "version": payload["kit"]["version"]},
                "ordered_card_ids": [card["card_id"] for card in reversed(cards)],
            })
            assert reordered.status_code == 200 and reordered.json()["replayed"] is False
            latest = reordered.json()["kit"]
            optional = next(card for card in latest["cards"] if card["role"] == "feature")
            deleted = client.post(action_url, headers=headers, json={
                "run_id": run.id,
                "action": "delete",
                "parent_social_kit_ref": {"id": latest["id"], "version": latest["version"]},
                "card_id": optional["card_id"],
            })
            assert deleted.status_code == 200 and len(deleted.json()["kit"]["cards"]) == 4
            latest = deleted.json()["kit"]
            target = latest["cards"][0]["card_id"]
            regenerated = client.post(action_url, headers=headers, json={
                "run_id": run.id, "action": "regenerate",
                "parent_social_kit_ref": {"id": latest["id"], "version": latest["version"]},
                "card_id": target, "variant_key": "regen-a9",
            })
            assert regenerated.status_code == 200
            latest = regenerated.json()["kit"]
            regenerated_target = next(card for card in latest["cards"] if card["card_id"] == target)
            assert regenerated_target["status"] == "planned"
            assert any(
                card["card_id"] != target and card["status"] == "rendered"
                for card in latest["cards"]
            )
            alternative = client.post(action_url, headers=headers, json={
                "run_id": run.id, "action": "request_alternative",
                "parent_social_kit_ref": {"id": latest["id"], "version": latest["version"]},
                "card_id": target, "variant_key": "alt-a9",
            })
            assert alternative.status_code == 200
            latest = alternative.json()["kit"]
            target_card = next(card for card in latest["cards"] if card["card_id"] == target)
            selected = client.post(action_url, headers=headers, json={
                "run_id": run.id, "action": "select_alternative",
                "parent_social_kit_ref": {"id": latest["id"], "version": latest["version"]},
                "card_id": target, "variant_ref": target_card["variant_refs"][0],
            })
            assert selected.status_code == 200
            selected_target = next(
                card for card in selected.json()["kit"]["cards"] if card["card_id"] == target
            )
            assert selected_target["status"] == "planned"
            reloaded = client.get(f"/api/v1/projects/{run.project_id}/social-kit", headers=headers)
            assert reloaded.status_code == 200
            assert reloaded.json()["kit"]["id"] == selected.json()["kit"]["id"]
            stale = client.post(action_url, headers=headers, json={
                "run_id": run.id, "action": "reorder",
                "parent_social_kit_ref": {"id": initial.id, "version": initial.version},
                "ordered_card_ids": [card["card_id"] for card in selected.json()["kit"]["cards"]],
            })
            assert stale.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_postgres_social_render_rejects_quality_failure_and_unresolved_production_profile(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    kit = create_social_kit_version(social_db, **_social_request(run, brief, master))
    tampered = deepcopy(kit.card_manifest_json)
    tampered["cards"] = [card for card in tampered["cards"] if card["role"] != "benefit"]
    kit.card_manifest_json = tampered
    with pytest.raises(SocialKitContractError, match="requires hero, benefit, and cta"):
        render_social_kit_deterministic(social_db, kit, output_dir=str(tmp_path / "renders"))

    kit.card_manifest_json = _social_request(run, brief, master)["card_manifest"]
    profile = deterministic_social_render_profile(kit)
    profile["production_compliance"] = "production"
    profile["canonical_hash"] = canonical_hash({key: value for key, value in profile.items() if key != "canonical_hash"})
    with pytest.raises(SocialKitContractError, match="cannot claim production compliance"):
        render_social_kit_deterministic(social_db, kit, output_dir=str(tmp_path / "renders"), profile=profile)


def test_postgres_social_render_full_journal_rebuild_restores_bounded_projection(social_graph_db, tmp_path):
    source_run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    raw_request = _social_request(source_run, brief, master)
    request = {
        **{key: value for key, value in raw_request.items() if key not in {"creator_run_id", "created_by", "workspace_id", "project_id", "card_manifest"}},
        "logical_targets": ["hero", "benefit", "feature", "usage", "cta"],
    }
    first = LangGraphRunService.start_social_kit(
        project_id=source_run.project_id,
        workspace_id=source_run.workspace_id,
        actor_id=source_run.created_by,
        request=request,
        db=social_graph_db,
    )
    run = social_graph_db.get(AgentRun, first.id)
    run.outputs_json = {}
    run.last_applied_event_sequence = 0
    social_graph_db.commit()
    rebuilt = AgentRunEventJournal.rebuild_projection(run, social_graph_db)
    social = dict(rebuilt.outputs_json.get("langgraph_social") or {})
    assert social.get("social_kit_ref", {}).get("id")
    assert social.get("render", {}).get("status") == "completed"
    assert len(social["render"]["cards"]) == 5


def test_postgres_social_card_manifest_allows_required_three_and_rejects_role_contract_violations(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    request = _social_request(run, brief, master, logical_targets=("hero", "benefit", "cta"))
    row = create_social_kit_version(social_db, **request)
    assert [card["role"] for card in _cards(row.card_manifest_json)] == ["hero", "benefit", "cta"]
    evidence_request = _social_request(run, brief, master, logical_targets=("hero", "benefit", "evidence", "cta"), parent_version_id=row.id)
    evidence_row = create_social_kit_version(social_db, **evidence_request)
    assert [card["role"] for card in _cards(evidence_row.card_manifest_json)] == ["hero", "benefit", "evidence", "cta"]

    with pytest.raises(SocialKitContractError, match="unique supported semantic roles"):
        _social_request(run, brief, master, logical_targets=("hero", "benefit", "unknown", "cta"))
    with pytest.raises(SocialKitContractError, match="requires hero, benefit, and cta"):
        _social_request(run, brief, master, logical_targets=("hero", "benefit"))

    missing_required = deepcopy(row.card_manifest_json)
    missing_required["cards"] = [
        _rehash_test_card({**card, "order": index + 1})
        for index, card in enumerate(card for card in _cards(missing_required) if card["role"] != "benefit")
    ]
    with pytest.raises(SocialKitContractError, match="requires hero, benefit, and cta"):
        create_social_kit_version(social_db, **{**request, "card_manifest": missing_required})

    duplicate_order = deepcopy(row.card_manifest_json)
    duplicate_order["cards"][1]["order"] = 1
    with pytest.raises(SocialKitContractError, match="unique positive integer"):
        create_social_kit_version(social_db, **{**request, "card_manifest": duplicate_order})

    duplicate_role = deepcopy(row.card_manifest_json)
    duplicate_role["cards"][1]["role"] = "hero"
    duplicate_role["cards"][1]["logical_target"] = "hero"
    with pytest.raises(SocialKitContractError, match="identities and semantic roles must be unique"):
        create_social_kit_version(social_db, **{**request, "card_manifest": duplicate_role})


def test_postgres_social_card_successors_preserve_identity_and_change_semantic_hash(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    first_request = _social_request(run, brief, master)
    first = create_social_kit_version(social_db, **first_request)
    original_ids = [card["card_id"] for card in _cards(first.card_manifest_json)]

    reordered_manifest = evolve_social_card_manifest(
        first.card_manifest_json,
        intent="reorder",
        ordered_card_ids=list(reversed(original_ids)),
    )
    reordered = create_social_kit_version(
        social_db,
        **{**first_request, "card_manifest": reordered_manifest, "parent_version_id": first.id},
    )
    assert [card["card_id"] for card in _cards(reordered.card_manifest_json)] == list(reversed(original_ids))
    assert set(card["card_id"] for card in _cards(reordered.card_manifest_json)) == set(original_ids)
    assert reordered.output_hash != first.output_hash
    assert create_social_kit_version(
        social_db,
        **{**first_request, "card_manifest": reordered_manifest, "parent_version_id": first.id},
    ).id == reordered.id

    feature_id = next(card["card_id"] for card in _cards(reordered.card_manifest_json) if card["role"] == "feature")
    deleted_manifest = evolve_social_card_manifest(reordered.card_manifest_json, intent="delete", card_id=feature_id)
    deleted = create_social_kit_version(
        social_db,
        **{**first_request, "card_manifest": deleted_manifest, "parent_version_id": reordered.id},
    )
    assert feature_id not in {card["card_id"] for card in _cards(deleted.card_manifest_json)}
    assert [card["order"] for card in _cards(deleted.card_manifest_json)] == [1, 2, 3, 4]
    required_id = next(card["card_id"] for card in _cards(deleted.card_manifest_json) if card["role"] == "hero")
    with pytest.raises(SocialKitContractError, match="cannot be deleted"):
        evolve_social_card_manifest(deleted.card_manifest_json, intent="delete", card_id=required_id)

    current = deleted
    for intent in ("alternative", "edit", "regenerate"):
        before = next(card for card in _cards(current.card_manifest_json) if card["card_id"] == required_id)
        successor_manifest = evolve_social_card_manifest(
            current.card_manifest_json,
            intent=intent,
            card_id=required_id,
            variant_key=f"{intent}-v1",
        )
        successor = create_social_kit_version(
            social_db,
            **{**first_request, "card_manifest": successor_manifest, "parent_version_id": current.id},
        )
        after = next(card for card in _cards(successor.card_manifest_json) if card["card_id"] == required_id)
        assert after["card_id"] == before["card_id"] and after["order"] == before["order"]
        assert after["selected_variant_ref"] != before["selected_variant_ref"]
        assert successor.output_hash != current.output_hash
        current = successor


def test_postgres_social_card_manifest_rejects_stale_fact_provenance_brand_and_cross_project_asset(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    request = _social_request(run, brief, master)

    stale_fact = deepcopy(request["card_manifest"])
    stale_fact["cards"][0]["fact_refs"][0]["hash"] = "0" * 64
    stale_fact["cards"][0] = _rehash_test_card(stale_fact["cards"][0])
    with pytest.raises(SocialKitContractError, match="approved Master fact"):
        create_social_kit_version(social_db, **{**request, "card_manifest": stale_fact})

    wrong_provenance = deepcopy(request["card_manifest"])
    wrong_provenance["cards"][0]["provenance_refs"][0]["hash"] = "0" * 64
    wrong_provenance["cards"][0] = _rehash_test_card(wrong_provenance["cards"][0])
    with pytest.raises(SocialKitContractError, match="approved Master provenance"):
        create_social_kit_version(social_db, **{**request, "card_manifest": wrong_provenance})

    wrong_brand = deepcopy(request["card_manifest"])
    wrong_brand["brand_kit_ref"]["hash"] = "0" * 64
    with pytest.raises(SocialKitContractError, match="Brand Kit"):
        create_social_kit_version(social_db, **{**request, "card_manifest": wrong_brand})

    other_run, _other_chain, _other_asset, other_brief, _other_master = _lineage(social_db, tmp_path)
    cross_project_asset = deepcopy(request["card_manifest"])
    cross_project_asset["cards"][0]["asset_ref"] = dict(other_brief.usable_asset_refs_json[0])
    cross_project_asset["cards"][0] = _rehash_test_card(cross_project_asset["cards"][0])
    with pytest.raises(SocialKitContractError, match="rights-confirmed Master assets"):
        create_social_kit_version(social_db, **{**request, "card_manifest": cross_project_asset})


def test_postgres_social_card_manifest_rejects_raw_fields_without_persistence(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    request = _social_request(run, brief, master)
    marker = "PROMPT_SECRET_LG15_A4"
    raw_manifest = deepcopy(request["card_manifest"])
    raw_manifest["cards"][0]["raw_provider_payload"] = marker
    with pytest.raises(SocialKitContractError, match="bounded reference fields"):
        create_social_kit_version(social_db, **{**request, "card_manifest": raw_manifest})
    persisted = social_db.execute(text("""
        SELECT
            (SELECT count(*) FROM social_kit_versions WHERE card_manifest_json::text LIKE :pattern)
          + (SELECT count(*) FROM agent_run_events WHERE payload_json::text LIKE :pattern)
          + (SELECT count(*) FROM agent_runs WHERE outputs_json::text LIKE :pattern OR input_snapshot::text LIKE :pattern)
    """), {"pattern": f"%{marker}%"}).scalar_one()
    assert persisted == 0
    serialized = json.dumps(request["card_manifest"], sort_keys=True)
    assert all(forbidden not in serialized for forbidden in ("raw_copy", "prompt", "provider_payload", "signed_url"))


def test_postgres_social_kit_rejects_cross_scope_mismatched_hash_and_stale_master(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    request = _social_request(run, brief, master)

    with pytest.raises(SocialKitContractError, match="creator_run_id"):
        create_social_kit_version(social_db, **{**request, "workspace_id": str(uuid4())})
    with pytest.raises(SocialKitContractError, match="creator_run_id"):
        create_social_kit_version(social_db, **{**request, "project_id": str(uuid4())})
    with pytest.raises(SocialKitContractError, match="does not match"):
        create_social_kit_version(
            social_db,
            **{**request, "source_master_reference": _ref(master.id, master.version, "0" * 64)},
        )

    successor_master = _successor_master(social_db, run, master)
    assert successor_master.version == master.version + 1
    with pytest.raises(SocialKitContractError, match="stale"):
        create_social_kit_version(social_db, **request)


def test_postgres_social_kit_rejects_unapproved_fact_snapshot(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    request = _social_request(run, brief, master)
    snapshot = social_db.get(FactSnapshot, master.approved_fact_snapshot_ref_json["id"])
    snapshot.facts_json = [*snapshot.facts_json, {"id": "fact:not-approved"}]
    social_db.flush()
    with pytest.raises(ValueError, match="Only seller-confirmed facts"):
        create_social_kit_version(social_db, **request)


def test_postgres_social_kit_rejects_asset_that_loses_final_use_rights(social_db, tmp_path):
    run, _chain, asset, brief, master = _lineage(social_db, tmp_path)
    request = _social_request(run, brief, master)
    asset.usage_status = "reference_only"
    social_db.flush()
    with pytest.raises(ValueError, match="final-use integrity"):
        create_social_kit_version(social_db, **request)


@pytest.mark.parametrize("statement", [
    "UPDATE social_kit_versions SET target_format = 'tampered' WHERE id = :id",
    "DELETE FROM social_kit_versions WHERE id = :id",
])
def test_postgres_social_kit_rejects_direct_update_and_delete(social_db, tmp_path, statement):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    row = create_social_kit_version(social_db, **_social_request(run, brief, master))
    with pytest.raises(DBAPIError, match="LG12I_IMMUTABLE_VERSION"):
        social_db.execute(text(statement), {"id": row.id})


def _truncate_committed_a1_state(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("""
            TRUNCATE TABLE
                social_kit_versions,
                commerce_creative_master_versions,
                product_creative_brief_versions,
                fact_snapshots,
                seller_confirmation_versions,
                product_truth_versions,
                product_source_snapshot_versions,
                brand_kit_versions,
                brand_kits,
                agent_runs,
                assets,
                product_projects,
                brands,
                workspaces,
                users
            RESTART IDENTITY CASCADE
        """))


def test_postgres_concurrent_same_social_request_creates_one_semantic_result(social_engine, tmp_path):
    _truncate_committed_a1_state(social_engine)
    factory = sessionmaker(bind=social_engine, autoflush=False)
    setup = factory()
    try:
        run, _chain, _asset, brief, master = _lineage(setup, tmp_path)
        request = _social_request(run, brief, master)
        setup.commit()
    finally:
        setup.close()

    barrier = Barrier(2)

    def create_once() -> str:
        session = factory()
        try:
            barrier.wait()
            row = create_social_kit_version(session, **request)
            session.commit()
            return str(row.id)
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(lambda _index: create_once(), range(2)))
        assert len(set(ids)) == 1
        verify = factory()
        try:
            assert verify.query(SocialKitVersion).filter_by(project_id=request["project_id"]).count() == 1
        finally:
            verify.close()
    finally:
        _truncate_committed_a1_state(social_engine)


def _action_request(kit, *, action, card_id=None, ordered_card_ids=(), variant_key=None, variant_ref=None):
    request = {
        "action": action,
        "parent_social_kit_ref": _ref(kit.id, kit.version, kit.canonical_hash),
    }
    if card_id is not None:
        request["card_id"] = card_id
    if ordered_card_ids:
        request["ordered_card_ids"] = list(ordered_card_ids)
    if variant_key is not None:
        request["variant_key"] = variant_key
    if variant_ref is not None:
        request["variant_ref"] = variant_ref
    return request


def test_postgres_social_card_actions_create_immutable_successors_and_replay(social_graph_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    parent = create_social_kit_version(social_graph_db, **_social_request(run, brief, master))
    before = {card["card_id"]: card for card in _cards(parent.card_manifest_json)}

    reorder_request = _action_request(
        parent, action="reorder", ordered_card_ids=list(reversed(before)),
    )
    reordered = apply_social_card_action(social_graph_db, run=run, request=reorder_request)
    assert reordered["replayed"] is False
    successor = reordered["successor"]
    assert successor.parent_version_id == parent.id
    assert [card["card_id"] for card in _cards(successor.card_manifest_json)] == list(reversed(before))
    assert all(
        next(card for card in _cards(successor.card_manifest_json) if card["card_id"] == card_id)["asset_ref"]
        == card["asset_ref"]
        for card_id, card in before.items()
    )
    replay = apply_social_card_action(social_graph_db, run=run, request=reorder_request)
    assert replay["replayed"] is True and replay["successor"].id == successor.id
    assert social_graph_db.query(AgentRunEvent).filter_by(
        run_id=run.id, event_type="social_card_action_submitted",
    ).count() == 1
    assert social_graph_db.query(AgentRunEvent).filter_by(
        run_id=run.id, event_type="social_kit_version_forked",
    ).count() == 1
    rebuilt = AgentRunEventJournal.rebuild_projection(run, social_graph_db)
    assert rebuilt.outputs_json["langgraph_social"]["last_action"]["action"] == "reorder"

    feature_id = next(card["card_id"] for card in before.values() if card["role"] == "feature")
    deleted = apply_social_card_action(
        social_graph_db,
        run=run,
        request=_action_request(successor, action="delete", card_id=feature_id),
    )["successor"]
    assert feature_id not in {card["card_id"] for card in _cards(deleted.card_manifest_json)}
    required_id = next(card["card_id"] for card in before.values() if card["role"] == "hero")
    with pytest.raises(SocialKitContractError, match="cannot be deleted"):
        apply_social_card_action(
            social_graph_db,
            run=run,
            request=_action_request(deleted, action="delete", card_id=required_id),
        )


def test_postgres_social_card_actions_selective_generation_and_alternative_replay(social_graph_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    parent = create_social_kit_version(social_graph_db, **_social_request(run, brief, master))
    cards = _cards(parent.card_manifest_json)
    target = next(card for card in cards if card["role"] == "hero")
    untouched = {card["card_id"]: card["selected_variant_ref"] for card in cards if card["card_id"] != target["card_id"]}

    regenerated_result = apply_social_card_action(
        social_graph_db,
        run=run,
        request=_action_request(parent, action="regenerate", card_id=target["card_id"], variant_key="regen-v1"),
    )
    regenerated = regenerated_result["successor"]
    jobs = social_graph_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
    outbox = social_graph_db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).all()
    assert len(jobs) == len(outbox) == 1
    assert jobs[0].input_snapshot["social_generation"]["selected_variant_ref"] == next(
        card["selected_variant_ref"] for card in _cards(regenerated.card_manifest_json) if card["card_id"] == target["card_id"]
    )
    assert all(
        next(card for card in _cards(regenerated.card_manifest_json) if card["card_id"] == card_id)["selected_variant_ref"] == ref
        for card_id, ref in untouched.items()
    )

    requested_result = apply_social_card_action(
        social_graph_db,
        run=run,
        request=_action_request(regenerated, action="request_alternative", card_id=target["card_id"], variant_key="alt-v1"),
    )
    requested = requested_result["successor"]
    requested_card = next(card for card in _cards(requested.card_manifest_json) if card["card_id"] == target["card_id"])
    candidate = _variant_reference_for_test(target["card_id"], "alternative", "alt-v1")
    assert candidate in requested_card["variant_refs"]
    assert requested_card["selected_variant_ref"] == next(
        card["selected_variant_ref"] for card in _cards(regenerated.card_manifest_json) if card["card_id"] == target["card_id"]
    )
    assert social_graph_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == 2
    assert apply_social_card_action(
        social_graph_db,
        run=run,
        request=_action_request(regenerated, action="request_alternative", card_id=target["card_id"], variant_key="alt-v1"),
    )["replayed"] is True

    selected = apply_social_card_action(
        social_graph_db,
        run=run,
        request=_action_request(requested, action="select_alternative", card_id=target["card_id"], variant_key="alt-v1"),
    )["successor"]
    selected_card = next(card for card in _cards(selected.card_manifest_json) if card["card_id"] == target["card_id"])
    assert selected_card["selected_variant_ref"] == candidate
    assert social_graph_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == 2


def _variant_reference_for_test(card_id, intent, variant_key):
    from src.services.social_kit_version_service import _variant_reference
    return _variant_reference(card_id=card_id, intent=intent, variant_key=variant_key)


def test_postgres_social_card_actions_fail_closed_for_stale_cross_scope_and_copy_edit(social_graph_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_graph_db, tmp_path)
    parent = create_social_kit_version(social_graph_db, **_social_request(run, brief, master))
    reordered = apply_social_card_action(
        social_graph_db,
        run=run,
        request=_action_request(parent, action="reorder", ordered_card_ids=[card["card_id"] for card in reversed(_cards(parent.card_manifest_json))]),
    )["successor"]
    with pytest.raises(SocialKitContractError, match="stale"):
        apply_social_card_action(
            social_graph_db,
            run=run,
            request=_action_request(parent, action="delete", card_id=next(card["card_id"] for card in _cards(parent.card_manifest_json) if card["role"] == "feature")),
        )
    other_run, _other_chain, _other_asset, other_brief, other_master = _lineage(social_graph_db, tmp_path)
    other_parent = create_social_kit_version(social_graph_db, **_social_request(other_run, other_brief, other_master))
    with pytest.raises(SocialKitContractError, match="out of scope"):
        apply_social_card_action(
            social_graph_db,
            run=run,
            request=_action_request(other_parent, action="reorder", ordered_card_ids=[card["card_id"] for card in _cards(other_parent.card_manifest_json)]),
        )
    target = _cards(reordered.card_manifest_json)[0]
    edited = apply_social_card_action(
        social_graph_db,
        run=run,
        request={**_action_request(reordered, action="edit_copy", card_id=target["card_id"]),
                 "copy_reference": target["copy_ref"],
                 "proposed_text": "상품의 핵심 가치를 한눈에 확인하세요."},
    )
    assert edited["replayed"] is False
    edited_card = next(card for card in _cards(edited["successor"].card_manifest_json) if card["card_id"] == target["card_id"])
    assert edited_card["copy_ref"] != target["copy_ref"]
    assert social_graph_db.query(SocialCardCopyVersion).filter_by(project_id=run.project_id).count() == len(_cards(parent.card_manifest_json)) + 1
    assert public_social_kit_projection(social_graph_db, edited["successor"], run)["cards"][0]["copy_text"] == "상품의 핵심 가치를 한눈에 확인하세요."
    with pytest.raises(SocialKitContractError, match="stale"):
        apply_social_card_action(
            social_graph_db,
            run=run,
            request={**_action_request(edited["successor"], action="edit_copy", card_id=target["card_id"]),
                     "copy_reference": target["copy_ref"], "proposed_text": "다른 문구"},
        )


def test_postgres_social_copy_edit_concurrent_current_version_allows_one_successor(social_engine, tmp_path):
    _truncate_committed_a1_state(social_engine)
    factory = sessionmaker(bind=social_engine, autoflush=False)
    setup = factory()
    try:
        run, _chain, _asset, brief, master = _lineage(setup, tmp_path)
        parent = create_social_kit_version(setup, **_social_request(run, brief, master))
        setup.commit()
        target = _cards(parent.card_manifest_json)[0]
        request = {**_action_request(parent, action="edit_copy", card_id=target["card_id"]),
                   "copy_reference": target["copy_ref"], "proposed_text": "상품의 핵심 가치를 한눈에 확인하세요."}
        run_id, parent_id = run.id, parent.id
    finally:
        setup.close()
    barrier = Barrier(2)

    def apply_once():
        session = factory()
        try:
            local_run = session.get(AgentRun, run_id)
            local_parent = session.get(SocialKitVersion, parent_id)
            barrier.wait()
            return apply_social_card_action(session, run=local_run, request={**request,
                "parent_social_kit_ref": _ref(local_parent.id, local_parent.version, local_parent.canonical_hash),})
        except Exception as exc:
            return exc
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: apply_once(), range(2)))
    # Both callers may return the same committed successor: only one call
    # performs the mutation, while the other is an idempotent replay.
    assert sum(not isinstance(result, Exception) and not result.get("replayed", False) for result in results) == 1
    assert sum(not isinstance(result, Exception) for result in results) == 2
    verify = factory()
    try:
        assert verify.query(SocialKitVersion).filter_by(project_id=run.project_id).count() == 2
        assert verify.query(SocialCardCopyVersion).filter_by(project_id=run.project_id, card_id=target["card_id"]).count() == 2
    finally:
        verify.close()
        _truncate_committed_a1_state(social_engine)


def test_postgres_social_copy_versions_are_immutable(social_db, tmp_path):
    run, _chain, _asset, brief, master = _lineage(social_db, tmp_path)
    kit = create_social_kit_version(social_db, **_social_request(run, brief, master))
    social_db.commit()
    copy_id = _cards(kit.card_manifest_json)[0]["copy_ref"]["id"]
    connection = social_db.connection()
    for statement in (
        "UPDATE social_card_copy_versions SET body_text = 'tampered' WHERE id = :id",
        "DELETE FROM social_card_copy_versions WHERE id = :id",
    ):
        savepoint = connection.begin_nested()
        try:
            with pytest.raises(DBAPIError, match="LG12I_IMMUTABLE_VERSION"):
                connection.execute(text(statement), {"id": copy_id})
        finally:
            savepoint.rollback()


def test_postgres_social_card_action_concurrent_same_request_replays_one_successor(social_engine, tmp_path):
    _truncate_committed_a1_state(social_engine)
    factory = sessionmaker(bind=social_engine, autoflush=False)
    setup = factory()
    try:
        run, _chain, _asset, brief, master = _lineage(setup, tmp_path)
        parent = create_social_kit_version(setup, **_social_request(run, brief, master))
        setup.commit()
        action = _action_request(parent, action="regenerate", card_id=_cards(parent.card_manifest_json)[0]["card_id"], variant_key="concurrent-v1")
        run_id, parent_id = run.id, parent.id
    finally:
        setup.close()
    barrier = Barrier(2)

    def apply_once():
        session = factory()
        try:
            local_run = session.get(AgentRun, run_id)
            local_parent = session.get(SocialKitVersion, parent_id)
            request = _action_request(local_parent, action="regenerate", card_id=_cards(local_parent.card_manifest_json)[0]["card_id"], variant_key="concurrent-v1")
            barrier.wait()
            try:
                result = apply_social_card_action(session, run=local_run, request=request)
                return ("ok", result["successor"].id)
            except SocialKitContractError as exc:
                session.rollback()
                return ("stale", str(exc))
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: apply_once(), range(2)))
        assert all(result[0] == "ok" for result in results)
        assert len({result[1] for result in results}) == 1
        verify = factory()
        try:
            assert verify.query(SocialKitVersion).filter_by(project_id=run.project_id).count() == 2
            assert verify.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == 1
        finally:
            verify.close()
    finally:
        _truncate_committed_a1_state(social_engine)
