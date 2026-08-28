"""TASK-13.1 PostgreSQL acceptance proof for the immutable AgentRun journal."""

from __future__ import annotations

import os
import datetime
import hashlib
import json
from collections import Counter
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.db.models import AgentRun, AgentRunEvent, Brand, DetailPageVersion, ImageGenerationJobRecord, ImageGenerationOutboxRecord, ImageGenerationProviderAttemptRecord, ProductProject, User, Workspace
from src.services.langgraph_run_service import (
    AgentRunEventJournal,
    AgentRunGraphProjector,
    GraphRunNotFound,
    GraphRunThreadMismatch,
    LangGraphRunService,
)
from src.services.image_generation_provider import ImageGenerationRequest, ImageGenerationResult
from src.services.generation_status_service import GenerationStatusService
from src.services.image_generation_service import (
    execute_image_generation,
    reconcile_provider_cost_projection,
    record_unknown_provider_attempt_for_delivery,
)
from src.services.image_generation_worker import DurableFakeImageProvider, claim_image_delivery, process_image_delivery, recover_expired_image_work, retry_dead_letter
from src.agents.langgraph_runtime import (
    build_lg0_compiled_graph,
    build_lg0_graph_input,
    open_postgres_checkpointer,
)
from src.app import app
from src.db.database import SessionLocal


pytestmark = [pytest.mark.postgres, pytest.mark.integration]


def _payload(stage: str, *, status: str = "running") -> dict:
    return {
        "stage": stage,
        "status": status,
        "node_status": "completed",
        "input_mode": "manual",
        "source_fidelity": "unknown",
        "references": {},
        "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
    }


@pytest.fixture
def journal_db():
    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    engine = create_engine(url)
    try:
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()


@pytest.fixture
def clean_lg13_slo_recovery_state(journal_db, monkeypatch):
    """Give only the stateful LG-13.5 PG tests a clean recovery sweep input."""

    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    engine = create_engine(url)
    try:
        monkeypatch.setattr(
            "src.agents.langgraph_runtime.settings.SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL",
            url,
        )
        # These tests intentionally commit through TestClient, worker, and
        # checkpoint connections, so an ORM rollback cannot isolate them. The
        # explicit setting keeps every nested production checkpointer local.
        # TRUNCATE runs before each selected test so a prior interrupted run
        # cannot become input to the production-wide recovery sweep.
        with engine.begin() as connection:
            connection.execute(text("""
                TRUNCATE TABLE
                    agent_runs,
                    image_generation_jobs,
                    checkpoints,
                    checkpoint_blobs,
                    checkpoint_writes
                RESTART IDENTITY CASCADE
            """))
        yield
    finally:
        engine.dispose()


def _run(session, *, workspace_id: str | None = None, mode: str = "lg12i_intake") -> AgentRun:
    suffix = uuid4().hex
    user = User(id=str(uuid4()), email=f"lg13-{suffix}@test.invalid", name="LG13 test")
    workspace = session.get(Workspace, workspace_id) if workspace_id else None
    new_workspace = workspace is None
    if new_workspace:
        workspace = Workspace(id=workspace_id or str(uuid4()), name="LG13 workspace", owner_id=user.id)
    brand = Brand(id=str(uuid4()), workspace_id=workspace.id, name="LG13 brand")
    project = ProductProject(id=str(uuid4()), workspace_id=workspace.id, brand_id=brand.id, name="LG13 project")
    run = AgentRun(
        id=str(uuid4()), workspace_id=workspace.id, project_id=project.id, created_by=user.id,
        graph_thread_id=None, mode=mode, status="running", current_stage="unified_intake_router",
        input_snapshot={"unified_product_intake": {"input_mode": "manual"}}, outputs_json={}, cost_approval_status="not_required",
    )
    session.add_all([user, brand, project, run])
    if new_workspace:
        session.add(workspace)
    session.commit()
    return run


def _append(session, run: AgentRun, stage: str):
    return AgentRunEventJournal.append(
        run, session, event_type="graph_node_updated", payload=_payload(stage),
        workspace_id=run.workspace_id, project_id=run.project_id,
    )


def _frozen_preview_version(session, run: AgentRun, *, identifier: str | None = None) -> DetailPageVersion:
    from src.services.page_finalization_service import (
        LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION,
        LG10_CANONICAL_RENDER_SCHEMA_VERSION,
        LG10_DETAIL_PAGE_VERSION_SCHEMA_VERSION,
        _canonical_hash,
    )

    canonical = {
        "schema_version": LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION,
        "run_id": run.id,
        "project_id": run.project_id,
        "approved_asset_manifest": {"assets": [{"scene_id": "scene-hero", "section_id": "hero"}]},
        "sections": [
            {"section_id": "hero", "sort_order": 0, "image_required": True, "rendering_mode": "approved_asset", "approved_assets": [{"scene_id": "scene-hero", "asset_id": "asset-hero"}], "seller_owned_fallback_assets": [], "scene_ref": {"scene_id": "scene-hero"}},
            {"section_id": "specs", "sort_order": 1, "image_required": False, "rendering_mode": "information_only", "approved_assets": [], "seller_owned_fallback_assets": [], "scene_ref": {"scene_id": ""}},
        ],
    }
    snapshot = {
        "schema_version": LG10_DETAIL_PAGE_VERSION_SCHEMA_VERSION,
        "lg10": {
            "canonical_page_assembly_input": canonical,
            "page_assembly": {},
            "canonical_rendering": {"schema_version": LG10_CANONICAL_RENDER_SCHEMA_VERSION},
        },
        "sections": [{"id": "specs", "title": "제품 정보"}],
    }
    snapshot["snapshot_hash"] = _canonical_hash(snapshot)
    version = DetailPageVersion(
        id=identifier or str(uuid4()), project_id=run.project_id, name="LG-13 preview", style_key="safe_information",
        sections_json=snapshot, is_final=True,
    )
    session.add(version)
    session.flush()
    return version


def test_postgres_progressive_preview_uses_current_frozen_lineage_and_rework_targets(journal_db):
    """SLO-06/FAST-08 is a projection of immutable sections, never job attempts."""

    from src.services.langgraph_run_service import _browser_checkpoint_values, seller_progressive_preview

    session = journal_db()
    try:
        run = _run(session, mode="lg11_edit")
        source = _frozen_preview_version(session, run)
        source_ref = {"id": source.id, "snapshot_hash": source.sections_json["snapshot_hash"]}
        run.current_stage = "quality_image_rework"
        run.outputs_json = {
            "langgraph_quality": {
                "quality_bar_verdict": "FAIL",
                "current_detail_page_ref": source_ref,
                "active_attempt": {"target_ref": {"type": "scene", "id": "scene-hero"}},
            },
            "langgraph_edit": {"impact_preview": {"affected_artifacts": {"section_ids": ["hero"]}}},
        }
        session.flush()

        preview = seller_progressive_preview(run, session)
        assert preview == {
            "completed_sections": [{"section_id": "specs", "summary": "제품 정보"}],
            "pending_sections": [{"section_id": "hero"}],
            "completed_count": 1,
            "total_sections": 2,
            "progress_percent": 50,
            "current_section": "hero",
            "preview_version": source_ref,
        }
        status = GenerationStatusService(session).get_project_status(run.project_id, run.workspace_id)
        assert status["progress_percent"] == 50
        assert status["progress_preview"] == preview
        graph = _browser_checkpoint_values(
            run,
            SimpleNamespace(values={"quality": run.outputs_json["langgraph_quality"], "edit": run.outputs_json["langgraph_edit"]}),
            progress_preview=preview,
        )
        assert graph["execution"]["progress_preview"] == preview
        assert LangGraphRunService.get_state(run.id, run.workspace_id, session).values["execution"]["progress_preview"] == preview
        assert "asset-hero" not in repr(preview)

        _event, inserted, _locked = _append(session, run, "quality_image_rework")
        _duplicate, deduplicated, _locked = _append(session, run, "quality_image_rework")
        assert inserted is True and deduplicated is False
        rebuilt = AgentRunEventJournal.rebuild_projection(run, session, thread_id=run.id)
        assert seller_progressive_preview(rebuilt, session) == preview

        source.is_final = False
        session.flush()
        assert seller_progressive_preview(run, session) is None

        child = _frozen_preview_version(session, run)
        child_ref = {"id": child.id, "snapshot_hash": child.sections_json["snapshot_hash"]}
        run.outputs_json = {"langgraph_quality": {"quality_bar_verdict": "PASS", "current_detail_page_ref": child_ref}}
        run.current_stage = "quality_promotion_ready"
        session.flush()
        child_preview = seller_progressive_preview(run, session)
        assert child_preview and child_preview["completed_count"] == child_preview["total_sections"] == 2
        assert child_preview["progress_percent"] == 100

        other = _run(session)
        other.outputs_json = {"langgraph_quality": {"current_detail_page_ref": child_ref}}
        session.flush()
        assert seller_progressive_preview(other, session) is None
    finally:
        session.close()


def test_postgres_seller_guidance_rebuild_is_deterministic_for_provider_outcome_unknown(journal_db):
    """A bounded persisted code produces the same seller view after replay."""

    from src.services.langgraph_run_service import _browser_checkpoint_values

    session = journal_db()
    try:
        run = _run(session)
        run.status = "failed"
        run.current_stage = "provider_wait"
        run.error_log = [{"code": "PROVIDER_OUTCOME_UNKNOWN", "recoverable": False}]
        _append(session, run, "provider_wait")
        session.commit()

        snapshot = SimpleNamespace(values={"generation": {"jobs": [{
            "job_id": "job-provider-unknown",
            "scene_id": "scene-provider-unknown",
            "status": "failed",
            "error_code": "PROVIDER_OUTCOME_UNKNOWN",
        }]}})
        before_values = _browser_checkpoint_values(run, snapshot)
        before = before_values["execution"]["last_error"]["seller_guidance"]
        rebuilt = AgentRunEventJournal.rebuild_projection(run, session, thread_id=run.id)
        after_values = _browser_checkpoint_values(rebuilt, snapshot)
        after = after_values["execution"]["last_error"]["seller_guidance"]

        assert before == after == {
            "status": "failed",
            "safe_code": "PROVIDER_OUTCOME_UNKNOWN",
            "cause_ko": "이미지 생성 결과를 아직 확인하지 못했습니다.",
            "action_ko": "작업 상태를 새로고침한 뒤 필요하면 장면을 다시 생성하세요.",
            "action_type": "refresh_status",
            "retryable": False,
            "review_required": False,
        }
        assert before_values["generation"]["jobs"][0]["seller_guidance"] == after
        assert GenerationStatusService(session).get_project_status(run.project_id, run.workspace_id)["seller_guidance"] == after
        assert "provider_wait" not in repr(before)
    finally:
        session.close()


def test_postgres_public_intake_projection_is_mode_scoped_and_bounded(journal_db):
    """LG-14 exposes source/truth status without checkpoint source bodies."""

    from src.services.langgraph_run_service import _browser_checkpoint_values

    digest = "a" * 64
    markers = {
        "RAW_MANUAL_SECRET_MARKER",
        "RAW_OCR_SECRET_MARKER",
        "RAW_URL_SECRET_MARKER",
        "RAW_PROVIDER_SECRET_MARKER",
    }
    sources = {
        "manual": {
            "manual_source": {
                "schema_version": "lg12i-manual-source-candidates-v1",
                "source_snapshot": {"id": "manual-source", "version": 1, "hash": digest},
                "manual_artifact_ref": {"id": "manual-artifact", "version": 1, "hash": digest},
                "fact_candidates": [{"value": "RAW_MANUAL_SECRET_MARKER"}],
                "unknown_candidates": [{}],
                "conflict_candidates": [],
                "creative_directions": [{"value": "RAW_PROVIDER_SECRET_MARKER"}],
                "rights": {"confirmation_state": "confirmed", "final_use_status": "not_approved"},
            },
        },
        "photo_only": {
            "photo_source": {
                "schema_version": "lg12i-photo-source-candidates-v1",
                "source_snapshot": {"id": "photo-source", "version": 1, "hash": digest},
                "photo_observation_artifact_ref": {"id": "photo-observation", "version": 1, "hash": digest},
                "source_asset_refs": [{"id": "photo-asset", "version": 1, "hash": digest}],
                "observations": [{"observed_value": "RAW_OCR_SECRET_MARKER"}],
                "unknown_candidates": [{}],
                "conflict_candidates": [],
                "prohibited_inference_fields": ["private_claim"],
                "observation_status": "ready",
                "rights": {"confirmation_state": "pending", "final_use_status": "not_approved"},
            },
        },
        "owned_product_url": {
            "owned_url_source": {
                "schema_version": "lg12i-owned-url-source-candidates-v1",
                "source_snapshot": {"id": "url-source", "version": 1, "hash": digest},
                "capture_request_ref": {"id": "url-request", "version": 1, "hash": digest},
                "capture_artifact_ref": {"id": "url-capture", "version": 1, "hash": digest},
                "final_url": "https://owned.example/private?token=RAW_URL_SECRET_MARKER",
                "image_asset_refs": [{"id": "observed-image", "version": 1, "hash": digest}],
                "rights": {"confirmation_state": "seller_owned", "final_use_status": "not_approved"},
            },
        },
    }
    truth = {
        "schema_version": "lg12i-product-truth-normalization-v1",
        "truth_version": {"id": "truth-version", "version": 1, "hash": digest},
        "fact_candidates": [{"value": "RAW_PROVIDER_SECRET_MARKER"}],
        "unknown_facts": [{}],
        "conflict_facts": [],
        "prohibited_inferences": [{}],
        "observation_risks": [],
        "requires_review": True,
    }
    session = journal_db()
    try:
        run = _run(session)
        for mode, mode_source in sources.items():
            intake = {
                "input_mode": mode,
                "requested_generation_mode": "quick",
                "target_channels": ["smartstore"],
                "product_truth": truth,
                **sources["manual"],
                **sources["photo_only"],
                **sources["owned_product_url"],
                **mode_source,
            }
            public = _browser_checkpoint_values(run, SimpleNamespace(values={"intake": intake}))["intake"]
            expected_source = {
                "manual": "manual_source",
                "photo_only": "photo_observation",
                "owned_product_url": "owned_url_source",
            }[mode]
            assert expected_source in public
            assert not ({"manual_source", "photo_observation", "owned_url_source"} - {expected_source}) & public.keys()
            assert public["product_truth"] == {
                "schema_version": "lg12i-product-truth-normalization-v1",
                "truth_version": {"id": "truth-version", "version": 1, "hash": digest},
                "requires_review": True,
                "fact_count": 1,
                "unknown_count": 1,
                "conflict_count": 0,
                "prohibited_inference_count": 1,
                "observation_risk_count": 0,
            }
            serialized = json.dumps(public, sort_keys=True)
            assert not any(marker in serialized for marker in markers)
    finally:
        session.close()


_SLO_STAGE = {
    "main_execution_started": ("input_router", "running"),
    "product_understanding_completed": ("product_understanding", "completed"),
    "planning_copy_completed": ("copywriting", "completed"),
    "first_usable_draft_ready": ("canonical_renderer", "completed"),
    "quality_promotion_ready": ("quality_promotion_ready", "completed"),
    "review_wait_started": ("seller_review", "awaiting_review"),
    "review_wait_resolved": ("seller_review", "running"),
    "delivery_enqueued": ("image_delivery", "queued"),
    "delivery_leased": ("image_delivery", "leased"),
    "retry_scheduled": ("image_delivery", "retry_wait"),
}


def _slo_event(session, run: AgentRun, event_type: str, occurred_at: datetime.datetime, timing: dict) -> None:
    stage, status = _SLO_STAGE[event_type]
    sequence = session.execute(
        text("SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_run_events WHERE run_id = :run_id"),
        {"run_id": run.id},
    ).scalar_one()
    payload = {**_payload(stage, status=status), "timing": timing}
    session.execute(
        text("""
            INSERT INTO agent_run_events (id, run_id, sequence, event_type, idempotency_key, payload_json, occurred_at, created_at)
            VALUES (:id, :run_id, :sequence, :event_type, :idempotency_key, CAST(:payload AS json), :occurred_at, :created_at)
        """),
        {
            "id": str(uuid4()),
            "run_id": run.id,
            "sequence": sequence,
            "event_type": event_type,
            "idempotency_key": hashlib.sha256(f"{run.id}:{sequence}:{event_type}".encode("utf-8")).hexdigest(),
            "payload": json.dumps(payload),
            "occurred_at": occurred_at,
            "created_at": occurred_at.replace(tzinfo=None),
        },
    )


def _ops12_payload(
    stage: str,
    *,
    input_mode: str,
    source_fidelity: str = "unknown",
    unknown_fact_count: int = 0,
    prohibited_inference_count: int = 0,
    clarification_count: int = 0,
) -> dict:
    return {
        "stage": stage,
        "status": "completed",
        "node_status": "completed",
        "input_mode": input_mode,
        "source_fidelity": source_fidelity,
        "references": {},
        "metrics": {
            "unknown_fact_count": unknown_fact_count,
            "prohibited_inference_count": prohibited_inference_count,
            "clarification_count": clarification_count,
        },
    }


def _ops12_event(session, run: AgentRun, event_type: str, payload: dict, *, age_seconds: float) -> None:
    sequence = session.execute(
        text("SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_run_events WHERE run_id = :run_id"),
        {"run_id": run.id},
    ).scalar_one()
    session.execute(
        text("""
            INSERT INTO agent_run_events (id, run_id, sequence, event_type, idempotency_key, payload_json, occurred_at, created_at)
            VALUES (
              :id, :run_id, :sequence, :event_type, :idempotency_key, CAST(:payload AS json),
              clock_timestamp() - make_interval(secs => CAST(:age_seconds AS double precision)), clock_timestamp()
            )
        """),
        {
            "id": str(uuid4()),
            "run_id": run.id,
            "sequence": sequence,
            "event_type": event_type,
            "idempotency_key": hashlib.sha256(f"{run.id}:{sequence}:{event_type}".encode("utf-8")).hexdigest(),
            "payload": json.dumps(payload),
            "age_seconds": age_seconds,
        },
    )


def _delivery(
    session,
    run: AgentRun,
    *,
    status: str = "queued",
    provider_mode: str = "mock",
    lease_owner: str | None = None,
    lease_expires_at: datetime.datetime | None = None,
    provider_dispatch_count: int = 0,
    thread_id: str | None = None,
) -> ImageGenerationOutboxRecord:
    suffix = uuid4().hex
    key = hashlib.sha256(suffix.encode("utf-8")).hexdigest()
    job = ImageGenerationJobRecord(
        project_id=run.project_id,
        job_id=f"lg13-recovery-{suffix}",
        section_id="scene",
        scene_id="scene",
        role="generated_image",
        prompt="bounded test prompt",
        preserve_product_identity=False,
        status="running" if status == "leased" else "queued",
        idempotency_key=key,
        usage_metadata={"langgraph_run_id": run.id},
    )
    session.add(job)
    session.flush()
    delivery = ImageGenerationOutboxRecord(
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        run_id=run.id,
        thread_id=thread_id or (run.graph_thread_id or run.id),
        image_job_id=job.id,
        job_id=job.job_id,
        idempotency_key=key,
        provider_mode=provider_mode,
        status=status,
        lease_owner=lease_owner,
        lease_expires_at=lease_expires_at,
        provider_dispatch_count=provider_dispatch_count,
    )
    session.add(delivery)
    session.commit()
    return delivery


def test_postgres_agent_run_event_append_idempotency_and_rollback(journal_db):
    session = journal_db()
    try:
        run = _run(session)
        first, inserted, _ = _append(session, run, "intake")
        duplicate, duplicated, _ = _append(session, run, "intake")
        assert inserted is True and duplicated is False
        assert first.id == duplicate.id and first.sequence == 1
        session.commit()

        with pytest.raises(ValueError, match="allowlisted"):
            AgentRunEventJournal.validate_payload("graph_node_updated", {**_payload("intake"), "raw_checkpoint": {}})

        rollback_event, _inserted, locked = _append(session, run, "rollback_only")
        locked.current_stage = "rollback_only"
        locked.last_applied_event_sequence = rollback_event.sequence
        session.flush()
        session.rollback()
        assert session.execute(text("SELECT count(*) FROM agent_run_events WHERE run_id = :run_id"), {"run_id": run.id}).scalar_one() == 1
        restored = session.get(AgentRun, run.id)
        assert restored.current_stage == "unified_intake_router"
        assert restored.last_applied_event_sequence == 0
    finally:
        session.close()


def test_postgres_ops05_lifecycle_identity_and_rebuild_are_durable_and_deduplicated(journal_db):
    session = journal_db()
    try:
        run = _run(session)
        run.graph_thread_id = run.id
        session.commit()
        AgentRunEventJournal.append_run_lifecycle(
            run, session, event_type="run_started", transition="started", status="running",
        )
        AgentRunGraphProjector.apply_node_update(
            run,
            session,
            {"events": [{"stage": "product_understanding", "status": "completed"}]},
        )
        rows = session.query(AgentRunEvent).filter_by(run_id=run.id).order_by(AgentRunEvent.sequence).all()
        assert {row.event_type for row in rows} >= {
            "run_started", "stage_started", "stage_completed", "run_completed",
        }
        identity = next(row.payload_json["identity"] for row in rows if row.event_type == "run_started")
        assert identity == {
            "graph_version": "lg13-runtime-v1",
            "run_id": run.id,
            "thread_id": run.id,
            "checkpoint_id": "",
            "event_schema_version": "agent-run-event-v1",
            "projection_version": 1,
        }
        before = len(rows)
        rebuilt = AgentRunEventJournal.rebuild_projection(run, session, thread_id=run.id)
        after = session.query(AgentRunEvent).filter_by(run_id=run.id).count()
        assert after == before
        AgentRunEventJournal.rebuild_projection(rebuilt, session, thread_id=run.id)
        assert session.query(AgentRunEvent).filter_by(run_id=run.id).count() == after
        assert rebuilt.status == "completed"
        assert rebuilt.current_stage == "product_understanding"
    finally:
        session.rollback()
        session.close()


@pytest.mark.parametrize("decision", ["regenerate", "upload"])
def test_postgres_image_review_action_lifecycle_is_stage_limited(journal_db, decision):
    """Public image-review actions remain bounded journal scalars."""

    session = journal_db()
    try:
        run = _run(session)
        event, inserted, _locked = AgentRunEventJournal.append_review_lifecycle(
            run,
            session,
            event_type="seller_choice_submitted",
            transition="submitted",
            stage="image_review",
            decision=decision,
        )
        session.commit()

        assert inserted is True
        assert event.payload_json["stage"] == "image_review"
        assert event.payload_json["lifecycle"] == {
            "transition": "submitted", "checkpoint_id": "", "decision": decision,
        }
        with pytest.raises(ValueError, match="Seller review decision is not allowlisted"):
            AgentRunEventJournal.append_review_lifecycle(
                run,
                session,
                event_type="seller_choice_submitted",
                transition="submitted",
                stage="planning_review",
                decision=decision,
            )
    finally:
        session.rollback()
        session.close()


def test_postgres_seller_confirmation_submit_lifecycle_is_allowlisted(journal_db):
    """The real seller-confirmation submit action is accepted by the journal."""

    session = journal_db()
    try:
        run = _run(session)
        event, inserted, _locked = AgentRunEventJournal.append_review_lifecycle(
            run,
            session,
            event_type="seller_choice_submitted",
            transition="submitted",
            stage="seller_confirmation",
            decision="submit",
        )
        session.commit()

        assert inserted is True
        assert event.payload_json["stage"] == "seller_confirmation"
        assert event.payload_json["lifecycle"]["decision"] == "submit"
    finally:
        session.rollback()
        session.close()


def test_postgres_checkpoint_persists_only_the_operational_input_allowlist(journal_db):
    """The real PG checkpoint bytes must not retain raw seller/provider input."""

    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    thread_id = f"lg13-redaction-{uuid4()}"
    raw_values = {
        "product_name": "private-manual-body",
        "ocr_text": "private-ocr-body",
        "product_url": "https://private.example/signed-token",
        "OPENAI_API_KEY": "private-provider-secret",
        "seller_phone": "private-seller-data",
    }
    with open_postgres_checkpointer(url) as checkpointer:
        graph = build_lg0_compiled_graph(checkpointer=checkpointer)
        graph.invoke(
            build_lg0_graph_input(
                run_id=thread_id,
                project_id="lg13-redaction-project",
                input_snapshot={**raw_values, "asset_ids": ["safe-asset-ref"]},
            ),
            {"configurable": {"thread_id": thread_id}},
        )
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    assert snapshot.values["input_snapshot"] == {"asset_ids": ["safe-asset-ref"]}

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT checkpoint FROM checkpoints WHERE thread_id = :thread_id"),
                {"thread_id": thread_id},
            ).scalars().all()
        assert rows
        serialized = repr(rows)
        for raw_value in raw_values.values():
            assert raw_value not in serialized
    finally:
        engine.dispose()


def test_postgres_agent_run_event_sequences_are_concurrent_and_run_local(journal_db):
    seed = journal_db()
    try:
        run = _run(seed)
        other = _run(seed, workspace_id=str(uuid4()))
        run_id, other_id = run.id, other.id
    finally:
        seed.close()

    barrier = Barrier(2)

    def append_in_session(run_id: str, stage: str, *, synchronize: bool = False) -> int:
        session = journal_db()
        try:
            run = session.get(AgentRun, run_id)
            if synchronize:
                barrier.wait()
            record, _inserted, _locked = _append(session, run, stage)
            session.commit()
            return record.sequence
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        sequences = list(pool.map(lambda item: append_in_session(run_id, item, synchronize=True), ("concurrent_a", "concurrent_b")))
    assert sorted(sequences) == [1, 2]
    assert append_in_session(other_id, "independent") == 1


def test_postgres_agent_run_event_is_immutable_and_rebuilds_full_or_partial(journal_db):
    session = journal_db()
    try:
        run = _run(session)
        for stage in ("intake", "truth", "master"):
            _append(session, run, stage)
        session.commit()

        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE agent_run_events SET event_type = 'tampered' WHERE run_id = :run_id"), {"run_id": run.id})
            session.commit()
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(text("DELETE FROM agent_run_events WHERE run_id = :run_id"), {"run_id": run.id})
            session.commit()
        session.rollback()

        run.outputs_json = {}
        run.current_stage = "stale"
        run.last_applied_event_sequence = 0
        session.commit()
        rebuilt = AgentRunEventJournal.rebuild_projection(run, session, thread_id=run.id)
        assert rebuilt.current_stage == "master"
        assert rebuilt.last_applied_event_sequence == 3

        rebuilt.current_stage = "truth"
        rebuilt.last_applied_event_sequence = 2
        session.commit()
        partial = AgentRunEventJournal.rebuild_projection(rebuilt, session, from_sequence=2, thread_id=run.id)
        assert partial.current_stage == "master"
        assert partial.last_applied_event_sequence == 3
    finally:
        session.close()


def test_postgres_agent_run_event_scope_thread_and_crash_replay_fail_closed(journal_db):
    session = journal_db()
    try:
        run = _run(session)
        with pytest.raises(GraphRunNotFound):
            AgentRunEventJournal.append(run, session, event_type="graph_node_updated", payload=_payload("wrong_scope"), workspace_id=str(uuid4()))
        with pytest.raises(GraphRunThreadMismatch):
            AgentRunEventJournal.append(run, session, event_type="graph_node_updated", payload=_payload("wrong_thread"), thread_id=str(uuid4()))
        session.rollback()

        record, inserted, _ = _append(session, run, "checkpoint_committed")
        assert inserted is True
        session.commit()  # crash boundary: journal committed, projection has not advanced
        run = session.get(AgentRun, run.id)
        assert run.last_applied_event_sequence == 0
        replayed = AgentRunEventJournal.rebuild_projection(run, session, thread_id=run.id)
        assert replayed.last_applied_event_sequence == record.sequence
        duplicate, inserted_again, _ = _append(session, replayed, "checkpoint_committed")
        session.commit()
        assert inserted_again is False and duplicate.id == record.id
        assert session.execute(text("SELECT count(*) FROM agent_run_events WHERE run_id = :run_id"), {"run_id": run.id}).scalar_one() == 1
    finally:
        session.close()


def test_postgres_recovery_sweep_is_idempotent_and_projects_bounded_events(journal_db):
    session = journal_db()
    try:
        run = _run(session)
        run.status = "awaiting_review"
        run.current_stage = "provider_wait"
        now = datetime.datetime.utcnow()
        mock_delivery = _delivery(
            session,
            run,
            status="leased",
            lease_owner="crashed-mock",
            lease_expires_at=now - datetime.timedelta(seconds=1),
        )
        paid_delivery = _delivery(
            session,
            run,
            status="leased",
            provider_mode="real",
            lease_owner="crashed-paid",
            lease_expires_at=now - datetime.timedelta(seconds=1),
            provider_dispatch_count=1,
        )

        assert recover_expired_image_work(session, now=now, workspace_id=run.workspace_id) == {"recovered": 1, "dead_lettered": 1}
        assert session.get(ImageGenerationOutboxRecord, mock_delivery.id).status == "queued"
        assert session.get(ImageGenerationOutboxRecord, paid_delivery.id).status == "dead_letter"
        assert recover_expired_image_work(session, now=now, workspace_id=run.workspace_id) == {"recovered": 0, "dead_lettered": 0}

        events = session.execute(
            text("SELECT event_type FROM agent_run_events WHERE run_id = :run_id ORDER BY sequence"), {"run_id": run.id}
        ).scalars().all()
        assert events == ["lease_expired_requeued", "provider_cost_unknown", "lease_expired_provider_outcome_unknown"]
        rebuilt = AgentRunEventJournal.rebuild_projection(session.get(AgentRun, run.id), session, thread_id=run.id)
        assert rebuilt.last_applied_event_sequence == 3
        assert rebuilt.outputs_json["langgraph_runtime"]["last_event"]["type"] == "lease_expired_provider_outcome_unknown"
    finally:
        session.close()


def test_postgres_scope_mismatch_blocks_dispatch_and_deduplicates_journal(journal_db):
    session = journal_db()
    try:
        run = _run(session)
        delivery = _delivery(session, run, status="leased", lease_owner="worker", thread_id=str(uuid4()))
        assert process_image_delivery(delivery.id, "worker", session) == {"status": "stale_delivery_blocked"}
        assert process_image_delivery(delivery.id, "worker", session) == {"status": "stale_delivery_blocked"}
        persisted = session.get(ImageGenerationOutboxRecord, delivery.id)
        assert persisted.status == "leased" and persisted.provider_dispatch_count == 0
        assert session.execute(
            text("SELECT count(*) FROM agent_run_events WHERE run_id = :run_id AND event_type = 'stale_delivery_blocked'"),
            {"run_id": run.id},
        ).scalar_one() == 1
        assert session.query(ImageGenerationProviderAttemptRecord).filter_by(run_id=run.id).count() == 0
    finally:
        session.close()


def test_postgres_concurrent_claim_and_dead_letter_requeue_are_exactly_once(journal_db, monkeypatch):
    seed = journal_db()
    try:
        seed.query(ImageGenerationOutboxRecord).filter(
            ImageGenerationOutboxRecord.status.in_(["queued", "retry_wait"])
        ).update(
            {ImageGenerationOutboxRecord.available_at: datetime.datetime.utcnow() + datetime.timedelta(days=1)},
            synchronize_session=False,
        )
        seed.commit()
        run = _run(seed)
        delivery = _delivery(seed, run)
        run_id, delivery_id = run.id, delivery.id
    finally:
        seed.close()

    barrier = Barrier(2)

    def claim(owner: str) -> str | None:
        session = journal_db()
        try:
            barrier.wait()
            delivery = claim_image_delivery(session, owner=owner)
            return delivery.id if delivery is not None else None
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(claim, ("worker-a", "worker-b")))
    winner = next(item for item in claimed if item is not None)
    assert claimed.count(winner) == 1

    session = journal_db()
    try:
        delivery = session.get(ImageGenerationOutboxRecord, delivery_id)
        assert delivery.status == "leased" and delivery.delivery_attempts == 1
        assert session.execute(
            text("SELECT count(*) FROM agent_run_events WHERE run_id = :run_id AND event_type = 'delivery_leased'"),
            {"run_id": run_id},
        ).scalar_one() == 1
        owner = delivery.lease_owner
        monkeypatch.setattr("src.services.image_generation_worker.execute_image_generation", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("timeout")))
        assert process_image_delivery(delivery_id, owner, session)["provider_dispatch_count"] == 1
        delivery = session.get(ImageGenerationOutboxRecord, delivery_id)
        assert delivery.status == "retry_wait" and delivery.delivery_attempts == 1
        assert session.execute(
            text("SELECT count(*) FROM agent_run_events WHERE run_id = :run_id AND event_type = 'retry_scheduled'"),
            {"run_id": run_id},
        ).scalar_one() == 1
        assert delivery.available_at <= datetime.datetime.utcnow()
        retried = claim_image_delivery(session, owner="retry-worker", now=datetime.datetime.utcnow() + datetime.timedelta(seconds=1))
        assert retried is not None and retried.id == delivery_id and retried.delivery_attempts == 2
        retried.lease_expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
        session.commit()
        assert recover_expired_image_work(session, workspace_id=run.workspace_id) == {"recovered": 1, "dead_lettered": 0}
        assert session.get(ImageGenerationOutboxRecord, delivery_id).status == "queued"
        assert session.query(ImageGenerationOutboxRecord).filter_by(idempotency_key=delivery.idempotency_key).count() == 1

        delivery.status = "dead_letter"
        delivery.image_job.status = "failed"
        session.commit()
    finally:
        session.close()


    retry_barrier = Barrier(2)

    def retry() -> str:
        session = journal_db()
        try:
            retry_barrier.wait()
            try:
                return retry_dead_letter(delivery_id, session).status
            except ValueError:
                return "blocked"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _item: retry(), range(2)))
    assert sorted(outcomes) == ["blocked", "queued"]

    session = journal_db()
    try:
        assert session.get(ImageGenerationOutboxRecord, delivery_id).status == "queued"
        assert session.execute(
            text("SELECT count(*) FROM agent_run_events WHERE run_id = :run_id AND event_type = 'dead_letter_requeue'"),
            {"run_id": run_id},
        ).scalar_one() == 1
    finally:
        session.close()


def test_postgres_provider_completion_crash_reconciles_checkpoint_and_journal(
    journal_db, clean_lg13_slo_recovery_state, monkeypatch, tmp_path,
):
    """Use the production PG checkpointer; only the paid provider boundary is fake."""

    from src.services import image_generation_worker, langgraph_run_service
    from test_lg5_image_generation_subgraph import _cost_hash, _create_run, _resume, _to_generation_pending

    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    engine = create_engine(url)
    prior_bind = SessionLocal.kw.get("bind")
    SessionLocal.configure(bind=engine)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    headers = {
        "X-Mock-User-Id": str(uuid4()),
        "X-Mock-Workspace-Id": str(uuid4()),
    }
    try:
        with open_postgres_checkpointer(url), TestClient(app) as client:
            db = SessionLocal()
            try:
                run = _create_run(client, headers, db, tmp_path)
                generation_wait = _to_generation_pending(client, headers, run.id, db, minimum_generation_scenes=2)
                provider_wait = _resume(client, headers, generation_wait, "approve", cost_plan_hash=_cost_hash(generation_wait)).json()
                assert provider_wait["current_stage"] == "provider_wait"

                original_resume = image_generation_worker._resume_completed_run
                monkeypatch.setattr(image_generation_worker, "_resume_completed_run", lambda _run_id: None)
                worker_db = SessionLocal()
                try:
                    assert len(image_generation_worker.run_image_worker_batch(worker_db, owner="pg-crash-worker", batch_size=100)) >= 2
                finally:
                    worker_db.close()

                stale = db.query(ImageGenerationJobRecord).filter(
                    ImageGenerationJobRecord.project_id == run.project_id,
                    ImageGenerationJobRecord.output_asset_id.isnot(None),
                ).order_by(ImageGenerationJobRecord.created_at).first()
                assert stale is not None
                stale.status = "queued"
                db.commit()

                boundary_state: dict[str, int | bool] = {}

                def resume_after_reconciliation(run_id: str):
                    boundary_state.update(
                        in_transaction=worker_db.in_transaction(),
                        new=len(worker_db.new),
                        dirty=len(worker_db.dirty),
                        deleted=len(worker_db.deleted),
                    )
                    return original_resume(run_id)

                monkeypatch.setattr(image_generation_worker, "_resume_completed_run", resume_after_reconciliation)
                worker_db = SessionLocal()
                try:
                    assert image_generation_worker.run_image_worker_batch(worker_db, owner="pg-crash-reconciler", batch_size=100) == []
                finally:
                    worker_db.close()

                assert boundary_state == {"in_transaction": False, "new": 0, "dirty": 0, "deleted": 0}

                db.expire_all()
                assert db.get(ImageGenerationJobRecord, stale.id).status == "needs_review"
                restored = client.get(f"/api/v1/graph-runs/{run.id}", headers=headers)
                assert restored.status_code == 200 and restored.json()["current_stage"] == "image_review"
                events = db.query(AgentRunEvent).filter(
                    AgentRunEvent.run_id == run.id,
                    AgentRunEvent.event_type == "provider_wait_reconciled",
                ).all()
                assert len(events) == 1
                rebuilt = AgentRunEventJournal.rebuild_projection(db.get(AgentRun, run.id), db, thread_id=run.id)
                assert rebuilt.last_applied_event_sequence == events[0].sequence
            finally:
                db.close()
    finally:
        SessionLocal.configure(bind=prior_bind)
        engine.dispose()


def _fake_result(*, actual_cost: float | None, status: str = "success") -> ImageGenerationResult:
    content = DurableFakeImageProvider().generate(
        ImageGenerationRequest(job_id="cost-fake", role="generated_image", prompt="bounded", preserve_product_identity=False)
    ).content
    usage = {} if actual_cost is None else {"actual_cost": actual_cost, "input_tokens": 12, "output_tokens": 4}
    return ImageGenerationResult(
        content=content,
        provider="fake_provider",
        model="fake-cost-v1",
        status=status,
        usage_metadata=usage,
    )


def test_postgres_provider_cost_ledger_records_known_zero_retry_and_replay(journal_db):
    """Real executor + PostgreSQL persistence; only the provider boundary is fake."""

    from unittest.mock import MagicMock

    session = journal_db()
    try:
        run = _run(session)
        zero_delivery = _delivery(session, run, status="leased", lease_owner="zero")
        assert process_image_delivery(zero_delivery.id, "zero", session)["status"] == "completed"
        zero = session.query(ImageGenerationProviderAttemptRecord).filter_by(image_job_id=zero_delivery.image_job_id).one()
        assert zero.dispatch_state == "DISPATCHED"
        assert zero.cost_state == "EXPLICIT_ZERO" and zero.actual_cost == 0
        assert zero.usage_json == {"availability": "reported", "provider_reported_cost": 0.0}

        known_delivery = _delivery(session, run)
        known_job = session.get(ImageGenerationJobRecord, known_delivery.image_job_id)
        known_job.estimated_cost = 0.25
        known_job.provider = "fake_provider"
        known_job.model = "fake-cost-v1"
        session.commit()
        provider = MagicMock()
        provider.generate.return_value = _fake_result(actual_cost=0.12)
        completed = execute_image_generation(run.project_id, known_job.job_id, session, cost_approved=True, provider_override=provider)
        assert completed.actual_cost == 0.12
        provider.reset_mock()
        assert execute_image_generation(run.project_id, known_job.job_id, session, cost_approved=True, provider_override=provider).id == completed.id
        provider.generate.assert_not_called()

        retry_delivery = _delivery(session, run)
        retry_job = session.get(ImageGenerationJobRecord, retry_delivery.image_job_id)
        retry_job.provider = "fake_provider"
        retry_job.model = "fake-cost-v1"
        session.commit()
        retry_provider = MagicMock()
        retry_provider.generate.side_effect = [RuntimeError("TIMEOUT"), _fake_result(actual_cost=0.08)]
        retried = execute_image_generation(run.project_id, retry_job.job_id, session, cost_approved=True, provider_override=retry_provider)
        assert retried.actual_cost == 0.08 and retry_provider.generate.call_count == 2

        missing_delivery = _delivery(session, run)
        missing_job = session.get(ImageGenerationJobRecord, missing_delivery.image_job_id)
        missing_job.provider = "fake_provider"
        missing_job.model = "fake-cost-v1"
        session.commit()
        missing_provider = MagicMock()
        missing_provider.generate.return_value = _fake_result(actual_cost=None)
        assert execute_image_generation(
            run.project_id, missing_job.job_id, session, cost_approved=True, provider_override=missing_provider,
        ).status == "needs_review"

        failed_delivery = _delivery(session, run)
        failed_job = session.get(ImageGenerationJobRecord, failed_delivery.image_job_id)
        failed_job.provider = "fake_provider"
        failed_job.model = "fake-cost-v1"
        session.commit()
        failed_provider = MagicMock()
        failed_provider.generate.return_value = _fake_result(actual_cost=0.05, status="failed")
        with pytest.raises(RuntimeError, match="PROVIDER_RESULT_ERROR"):
            execute_image_generation(run.project_id, failed_job.job_id, session, cost_approved=True, provider_override=failed_provider)

        rows = session.query(ImageGenerationProviderAttemptRecord).filter_by(run_id=run.id).all()
        assert len(rows) == 6
        assert Counter(row.cost_state for row in rows) == Counter({
            "EXPLICIT_ZERO": 1, "KNOWN": 3, "UNKNOWN_AFTER_DISPATCH": 2,
        })
        assert all(set(row.usage_json) <= {"availability", "provider_reported_cost", "input_tokens", "output_tokens", "total_tokens", "input_images", "output_images"} for row in rows)
        refreshed = session.get(AgentRun, run.id)
        assert refreshed.actual_cost == pytest.approx(0.25)
        projection = refreshed.outputs_json["provider_cost_projection"]
        assert projection["known_actual_cost"] == pytest.approx(0.25)
        assert projection["has_unknown_cost"] is True
        assert projection["actual_cost_complete"] is False
        assert projection["attempt_count"] == 6
        assert projection["unknown_attempt_count"] == 2
        assert session.query(AgentRunEvent).filter(
            AgentRunEvent.run_id == run.id,
            AgentRunEvent.event_type.in_(["provider_cost_recorded", "provider_cost_unknown"]),
        ).count() == 6

        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE image_generation_provider_attempts SET actual_cost = 9 WHERE id = :id"), {"id": rows[0].id})
            session.commit()
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(text("DELETE FROM image_generation_provider_attempts WHERE id = :id"), {"id": rows[0].id})
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_postgres_provider_failure_persists_only_bounded_error_state(journal_db, monkeypatch):
    """A real worker failure must not retain provider exception text at rest."""

    import src.services.image_generation_worker as image_generation_worker
    from src.services.generation_status_service import GenerationStatusService

    raw_markers = (
        "PROMPT_SECRET_7F3A",
        "https://signed.example/private?token=SECRET_TOKEN_9C2",
        "customer@example.com",
    )

    class FailingFakeImageProvider:
        def generate(self, _request):
            raise RuntimeError(f"TIMEOUT: {' '.join(raw_markers)}")

    monkeypatch.setattr(image_generation_worker, "DurableFakeImageProvider", FailingFakeImageProvider)
    session = journal_db()
    try:
        run = _run(session)
        delivery = _delivery(session, run)
        delivery.status = "leased"
        delivery.lease_owner = "pg-provider-privacy"
        delivery.lease_expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=1)
        delivery.delivery_attempts = 1
        session.commit()

        result = process_image_delivery(delivery.id, "pg-provider-privacy", session)
        assert result["status"] == "retry_wait"
        assert result["error_code"] == "PROVIDER_TIMEOUT"

        session.expire_all()
        job = session.get(ImageGenerationJobRecord, delivery.image_job_id)
        outbox = session.get(ImageGenerationOutboxRecord, delivery.id)
        attempts = session.query(ImageGenerationProviderAttemptRecord).filter_by(image_job_id=job.id).all()
        events = session.query(AgentRunEvent).filter_by(run_id=run.id).all()
        persisted = json.dumps(
            {
                "job": {
                    "error_code": job.error_code,
                    "warnings": job.warnings,
                    "usage_metadata": job.usage_metadata,
                    "input_snapshot": job.input_snapshot,
                    "validation_result": job.validation_result,
                },
                "outbox": {
                    "last_error_code": outbox.last_error_code,
                    "last_error_message": outbox.last_error_message,
                },
                "provider_attempts": [
                    {"outcome_code": row.outcome_code, "usage_json": row.usage_json}
                    for row in attempts
                ],
                "journal": [event.payload_json for event in events],
                "run_projection": session.get(AgentRun, run.id).outputs_json,
            },
            default=str,
        )
        assert all(marker not in persisted for marker in raw_markers)
        _code, _detail, action = image_generation_worker.normalize_image_error(
            RuntimeError(f"TIMEOUT: {' '.join(raw_markers)}")
        )
        assert job.error_code == "PROVIDER_TIMEOUT"
        assert job.warnings and job.warnings[0] == action
        assert outbox.last_error_code == "PROVIDER_TIMEOUT"
        assert outbox.last_error_message == action
        assert len(attempts) == 2
        assert {row.outcome_code for row in attempts} == {"TIMEOUT"}
        public_status = GenerationStatusService(session).get_project_status(run.project_id, run.workspace_id)
        assert all(marker not in json.dumps(public_status, default=str) for marker in raw_markers)
        assert session.execute(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"), {"thread_id": run.id}
        ).scalar_one() == 0
    finally:
        session.close()


def test_postgres_paid_unknown_cost_recovery_is_idempotent_and_rebuildable(journal_db):
    session = journal_db()
    try:
        run = _run(session)
        now = datetime.datetime.utcnow()
        delivery = _delivery(
            session, run, status="leased", provider_mode="real", lease_owner="crashed-paid",
            lease_expires_at=now - datetime.timedelta(seconds=1), provider_dispatch_count=1,
        )
        assert recover_expired_image_work(session, now=now, workspace_id=run.workspace_id) == {"recovered": 0, "dead_lettered": 1}
        job = session.get(ImageGenerationJobRecord, delivery.image_job_id)
        first = record_unknown_provider_attempt_for_delivery(job, session)
        second = record_unknown_provider_attempt_for_delivery(job, session)
        session.commit()
        assert first is not None and second is not None and first.id == second.id
        rows = session.query(ImageGenerationProviderAttemptRecord).filter_by(run_id=run.id).all()
        assert len(rows) == 1 and rows[0].cost_state == "UNKNOWN_AFTER_DISPATCH" and rows[0].actual_cost is None
        rebuilt = AgentRunEventJournal.rebuild_projection(session.get(AgentRun, run.id), session, thread_id=run.id)
        assert rebuilt.actual_cost == 0
        assert rebuilt.outputs_json["provider_cost_projection"]["has_unknown_cost"] is True
        assert session.query(AgentRunEvent).filter_by(run_id=run.id, event_type="provider_cost_unknown").count() == 1
    finally:
        session.close()


def test_postgres_provider_result_crash_reconciles_cost_journal_once(journal_db):
    """A committed provider fact without its event is repaired without redispatching."""

    session = journal_db()
    try:
        run = _run(session)
        delivery = _delivery(session, run)
        job = session.get(ImageGenerationJobRecord, delivery.image_job_id)
        session.add(ImageGenerationProviderAttemptRecord(
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            run_id=run.id,
            thread_id=run.graph_thread_id or run.id,
            image_job_id=job.id,
            outbox_id=delivery.id,
            job_id=job.job_id,
            scene_id=job.scene_id,
            seller_generation_attempt=1,
            delivery_attempt=delivery.delivery_attempts,
            provider_adapter_attempt=1,
            provider="fake_provider",
            model="fake-cost-v1",
            semantic_idempotency_key=hashlib.sha256(f"provider-result-crash:{run.id}".encode("utf-8")).hexdigest(),
            dispatch_state="DISPATCHED",
            cost_state="KNOWN",
            estimated_cost_at_dispatch=job.estimated_cost,
            actual_cost=0.17,
            currency="credit",
            usage_json={"availability": "reported", "provider_reported_cost": 0.17},
            outcome_code="SUCCESS",
            started_at=datetime.datetime.utcnow(),
            completed_at=datetime.datetime.utcnow(),
        ))
        session.commit()

        assert reconcile_provider_cost_projection(run.id, session) is True
        session.commit()
        assert reconcile_provider_cost_projection(run.id, session) is False
        session.commit()
        rebuilt = AgentRunEventJournal.rebuild_projection(session.get(AgentRun, run.id), session, thread_id=run.id)
        assert rebuilt.actual_cost == pytest.approx(0.17)
        assert rebuilt.outputs_json["provider_cost_projection"] == {
            "known_actual_cost": pytest.approx(0.17),
            "has_unknown_cost": False,
            "actual_cost_complete": True,
            "attempt_count": 1,
            "unknown_attempt_count": 0,
        }
        assert session.query(AgentRunEvent).filter_by(run_id=run.id, event_type="provider_cost_recorded").count() == 1
    finally:
        session.close()


def test_postgres_provider_cost_attempt_concurrency_and_pre_dispatch_zero(journal_db, monkeypatch):
    seed = journal_db()
    try:
        run = _run(seed)
        delivery = _delivery(seed, run, status="leased", provider_mode="real", lease_owner="cost-worker")
        job_id, run_id = delivery.image_job_id, run.id
    finally:
        seed.close()

    barrier = Barrier(2)

    def persist_unknown() -> str:
        session = journal_db()
        try:
            job = session.get(ImageGenerationJobRecord, job_id)
            barrier.wait()
            row = record_unknown_provider_attempt_for_delivery(job, session)
            session.commit()
            return str(row.id)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _value: persist_unknown(), range(2)))
    assert ids[0] == ids[1]

    session = journal_db()
    try:
        assert session.query(ImageGenerationProviderAttemptRecord).filter_by(run_id=run_id).count() == 1
        assert session.query(AgentRunEvent).filter_by(run_id=run_id, event_type="provider_cost_unknown").count() == 1

        delivery = _delivery(session, _run(session))
        job = session.get(ImageGenerationJobRecord, delivery.image_job_id)
        job.provider = "unsupported"
        job.model = "none"
        session.commit()
        monkeypatch.setattr("src.services.image_generation_service.settings.SELLFORM_IMAGE_GENERATION_MODE", "real")
        monkeypatch.setattr("src.services.image_generation_service.get_image_generation_adapter", lambda *_args: (_ for _ in ()).throw(RuntimeError("not configured")))
        with pytest.raises(RuntimeError, match="not configured"):
            execute_image_generation(job.project_id, job.job_id, session, cost_approved=True)
        pre_dispatch = session.query(ImageGenerationProviderAttemptRecord).filter_by(image_job_id=job.id).one()
        assert pre_dispatch.dispatch_state == "NOT_DISPATCHED"
        assert pre_dispatch.cost_state == "NOT_DISPATCHED" and pre_dispatch.actual_cost == 0
    finally:
        session.close()


def test_postgres_slo_timing_uses_db_clock_and_replay_deduplicates(
    journal_db, clean_lg13_slo_recovery_state,
):
    session = journal_db()
    try:
        run = _run(session, mode="mock")
        before = session.execute(text("SELECT clock_timestamp()")).scalar_one()
        first, inserted, _ = AgentRunEventJournal.append_timing_event(
            run, session, event_type="main_execution_started", timing={"execution_profile": "production"},
        )
        duplicate, duplicated, _ = AgentRunEventJournal.append_timing_event(
            run, session, event_type="main_execution_started", timing={"execution_profile": "production"},
        )
        session.commit()
        after = session.execute(text("SELECT clock_timestamp()")).scalar_one()
        assert inserted is True and duplicated is False and first.id == duplicate.id
        assert before <= first.occurred_at <= after
        assert session.query(AgentRunEvent).filter_by(run_id=run.id, event_type="main_execution_started").count() == 1
        rebuilt = AgentRunEventJournal.rebuild_projection(session.get(AgentRun, run.id), session, thread_id=run.id)
        assert rebuilt.last_applied_event_sequence == first.sequence
    finally:
        session.close()


def test_postgres_slo_percentiles_use_stage_boundaries_and_execution_profile(
    journal_db, clean_lg13_slo_recovery_state,
):
    session = journal_db()
    try:
        now = session.execute(text("SELECT clock_timestamp()")).scalar_one()
        workspace_id = None
        for index in range(30):
            run = _run(session, workspace_id=workspace_id, mode="mock")
            workspace_id = run.workspace_id
            started = now - datetime.timedelta(hours=2, minutes=index)
            _slo_event(session, run, "main_execution_started", started, {"execution_profile": "production"})
            _slo_event(session, run, "product_understanding_completed", started + datetime.timedelta(seconds=30), {})
            _slo_event(session, run, "planning_copy_completed", started + datetime.timedelta(seconds=150), {})
            _slo_event(session, run, "first_usable_draft_ready", started + datetime.timedelta(seconds=240), {})
            _slo_event(session, run, "quality_promotion_ready", started + datetime.timedelta(seconds=780), {})
        excluded = _run(session, workspace_id=workspace_id, mode="mock")
        started = now - datetime.timedelta(hours=3)
        _slo_event(session, excluded, "main_execution_started", started, {"execution_profile": "test"})
        _slo_event(session, excluded, "quality_promotion_ready", started + datetime.timedelta(days=1), {})
        session.commit()

        metrics = AgentRunEventJournal.slo_summary(session, workspace_id=workspace_id)["milestones"]
        assert metrics["product_understanding"]["sample_count"] == 30
        assert metrics["product_understanding"]["p90_seconds"] == pytest.approx(30)
        assert metrics["planning_copy"]["p90_seconds"] == pytest.approx(120)
        assert metrics["first_usable_draft"]["p90_seconds"] == pytest.approx(240)
        assert metrics["high_quality_final"]["p90_seconds"] == pytest.approx(780)
        assert metrics["normal_run"]["p90_seconds"] == pytest.approx(780)
        assert metrics["normal_run"]["compliance_status"] == "pass"
    finally:
        session.close()


def test_postgres_slo_review_wait_and_retry_attribution(
    journal_db, clean_lg13_slo_recovery_state,
):
    session = journal_db()
    try:
        now = session.execute(text("SELECT clock_timestamp()")).scalar_one()
        review_run = _run(session, mode="mock")
        workspace_id = review_run.workspace_id
        started = now - datetime.timedelta(days=2)
        _slo_event(session, review_run, "main_execution_started", started, {"execution_profile": "production"})
        _slo_event(session, review_run, "review_wait_started", started + datetime.timedelta(seconds=100), {"review_cycle": "a" * 64})
        _slo_event(session, review_run, "review_wait_resolved", started + datetime.timedelta(seconds=1300), {"review_cycle": "a" * 64})
        _slo_event(session, review_run, "quality_promotion_ready", started + datetime.timedelta(seconds=1500), {})

        retry_run = _run(session, workspace_id=workspace_id, mode="mock")
        started = now - datetime.timedelta(days=3)
        outbox = {"id": "slo-outbox", "version": 1, "hash": "b" * 64}
        _slo_event(session, retry_run, "main_execution_started", started, {"execution_profile": "production"})
        _slo_event(session, retry_run, "retry_scheduled", started + datetime.timedelta(seconds=10), {"outbox": outbox, "attempt": 1})
        _slo_event(session, retry_run, "delivery_leased", started + datetime.timedelta(seconds=1250), {"outbox": outbox, "attempt": 2})
        _slo_event(session, retry_run, "quality_promotion_ready", started + datetime.timedelta(seconds=1300), {})
        session.commit()

        normal = AgentRunEventJournal.slo_summary(session, workspace_id=workspace_id)["milestones"]["normal_run"]
        assert normal["sample_count"] == 2 and normal["insufficient_sample"] is True
        assert normal["breach_count"] == 1
        assert normal["seller_review_only_overage_count"] == 1
        assert normal["delay_cause_counts"] == {"retry_backoff": 1}
    finally:
        session.close()


def test_postgres_seller_delay_context_is_scoped_replay_safe_and_pauses_for_review(
    journal_db, clean_lg13_slo_recovery_state,
):
    from src.services.langgraph_run_service import _browser_checkpoint_values

    session = journal_db()
    try:
        now = session.execute(text("SELECT clock_timestamp()")).scalar_one()
        workspace_id = None
        for index in range(30):
            sample = _run(session, workspace_id=workspace_id, mode="mock")
            workspace_id = sample.workspace_id
            started = now - datetime.timedelta(hours=2, minutes=index)
            _slo_event(session, sample, "main_execution_started", started, {"execution_profile": "production"})
            _slo_event(session, sample, "product_understanding_completed", started + datetime.timedelta(seconds=30), {})
            _slo_event(session, sample, "planning_copy_completed", started + datetime.timedelta(seconds=150), {})
            _slo_event(session, sample, "first_usable_draft_ready", started + datetime.timedelta(seconds=240), {})
            _slo_event(session, sample, "quality_promotion_ready", started + datetime.timedelta(seconds=780), {})

        run = _run(session, workspace_id=workspace_id, mode="mock")
        run.current_stage = "image_generation"
        outbox = {"id": "seller-delay-outbox", "version": 1, "hash": "d" * 64}
        started = now - datetime.timedelta(seconds=80)
        _slo_event(session, run, "main_execution_started", started, {"execution_profile": "production"})
        _slo_event(session, run, "product_understanding_completed", started + datetime.timedelta(seconds=30), {})
        _slo_event(session, run, "planning_copy_completed", started + datetime.timedelta(seconds=40), {})
        _slo_event(session, run, "delivery_enqueued", now - datetime.timedelta(seconds=20), {"outbox": outbox, "attempt": 1})
        session.commit()

        queued = AgentRunEventJournal.seller_delay_context(run, session, observed_at=now)
        assert queued["delay_cause"] == "queue_wait"
        assert queued["eta_status"] == "estimated" and queued["eta_range_seconds"]
        assert queued["seller_guidance"]["cause_ko"] == queued["delay_cause_ko"]
        assert "seller-delay-outbox" not in repr(queued)

        _slo_event(session, run, "delivery_leased", now - datetime.timedelta(seconds=10), {"outbox": outbox, "attempt": 1})
        session.commit()
        assert AgentRunEventJournal.seller_delay_context(run, session, observed_at=now)["delay_cause"] == "provider_execution"

        _slo_event(session, run, "retry_scheduled", now - datetime.timedelta(seconds=5), {"outbox": outbox, "attempt": 1})
        session.commit()
        before = AgentRunEventJournal.seller_delay_context(run, session, observed_at=now)
        assert before["delay_cause"] == "retry_backoff" and before["seller_guidance"]["retryable"] is True
        rebuilt = AgentRunEventJournal.rebuild_projection(session.get(AgentRun, run.id), session, thread_id=run.id)
        after = AgentRunEventJournal.seller_delay_context(rebuilt, session, observed_at=now)
        assert after == before
        graph = _browser_checkpoint_values(rebuilt, SimpleNamespace(values={}), delay_context=after)
        assert graph["execution"]["delay_context"] == after
        assert GenerationStatusService(session).get_project_status(run.project_id, workspace_id)["delay_context"]["delay_cause"] == "retry_backoff"

        review = _run(session, workspace_id=workspace_id, mode="mock")
        review.current_stage = "copywriting"
        _slo_event(session, review, "main_execution_started", started, {"execution_profile": "production"})
        _slo_event(session, review, "product_understanding_completed", started + datetime.timedelta(seconds=30), {})
        review.status = "awaiting_review"
        _slo_event(session, review, "review_wait_started", now - datetime.timedelta(seconds=20), {"review_cycle": "e" * 64})
        session.commit()
        paused = AgentRunEventJournal.seller_delay_context(review, session, observed_at=now)
        assert paused["delay_cause"] == "seller_review_wait" and paused["eta_status"] == "paused_for_review"
        review.status = "running"
        _slo_event(session, review, "review_wait_resolved", now - datetime.timedelta(seconds=10), {"review_cycle": "e" * 64})
        session.commit()
        assert AgentRunEventJournal.seller_delay_context(review, session, observed_at=now)["eta_status"] == "estimated"
    finally:
        session.close()


def test_postgres_intake_operational_metrics_are_scoped_replay_safe_and_bounded(journal_db):
    session = journal_db()
    try:
        url_run = _run(session, mode="lg12i_intake")
        url_run.input_snapshot = {"unified_product_intake": {"input_mode": "owned_product_url"}}
        photo_run = _run(session, workspace_id=url_run.workspace_id, mode="lg12i_intake")
        photo_run.input_snapshot = {"unified_product_intake": {"input_mode": "photo_only"}}
        manual_run = _run(session, workspace_id=url_run.workspace_id, mode="lg12i_intake")
        manual_run.input_snapshot = {"unified_product_intake": {"input_mode": "manual"}}
        session.commit()

        _ops12_event(session, url_run, "intake_envelope_accepted", _ops12_payload("manual_input_adapter", input_mode="owned_product_url"), age_seconds=300)
        _ops12_event(session, url_run, "source_snapshot_ready", _ops12_payload("owned_url_source_snapshot_ready", input_mode="owned_product_url", source_fidelity="captured"), age_seconds=290)
        _ops12_event(session, url_run, "truth_ready", _ops12_payload("seller_confirmation_not_required", input_mode="owned_product_url", unknown_fact_count=1), age_seconds=280)
        _ops12_event(session, url_run, "commerce_creative_master_ready", _ops12_payload("master_ready", input_mode="owned_product_url"), age_seconds=210)

        _ops12_event(session, photo_run, "intake_envelope_accepted", _ops12_payload("photo_input_adapter", input_mode="photo_only"), age_seconds=400)
        _ops12_event(session, photo_run, "source_snapshot_ready", _ops12_payload("photo_source_snapshot_ready", input_mode="photo_only", source_fidelity="ready"), age_seconds=390)
        _ops12_event(session, photo_run, "truth_review_required", _ops12_payload("seller_confirmation_required", input_mode="photo_only", prohibited_inference_count=1, clarification_count=2), age_seconds=380)
        _ops12_event(session, photo_run, "graph_node_updated", _ops12_payload("commerce_creative_master_blocked", input_mode="photo_only", prohibited_inference_count=1, clarification_count=2), age_seconds=250)

        _ops12_event(session, manual_run, "intake_envelope_accepted", _ops12_payload("manual_input_adapter", input_mode="manual"), age_seconds=500)
        _ops12_event(session, manual_run, "source_snapshot_ready", _ops12_payload("manual_source_snapshot_ready", input_mode="manual", source_fidelity="seller_entered"), age_seconds=490)
        _ops12_event(session, manual_run, "truth_ready", _ops12_payload("seller_confirmation_not_required", input_mode="manual", unknown_fact_count=2, clarification_count=1), age_seconds=480)
        _ops12_event(session, manual_run, "graph_node_updated", _ops12_payload("creative_brief_blocked", input_mode="manual", unknown_fact_count=2, clarification_count=1), age_seconds=450)
        session.commit()

        metrics = AgentRunEventJournal.intake_operational_summary(session, workspace_id=url_run.workspace_id)["modes"]
        assert metrics["owned_product_url"] == {
            "started_run_count": 1, "terminal_intake_run_count": 1, "successful_intake_run_count": 1,
            "success_rate": 1.0, "confirmation_request_count": 0,
            "unsupported_inference_blocked_run_count": 0, "unsupported_inference_blocked_rate": 0.0,
            "source_fidelity_counts": {"captured": 1}, "unknown_fact_count": 1,
            "prohibited_inference_count": 0, "clarification_count": 0, "completed_intake_count": 1,
            "p50_completion_seconds": pytest.approx(90, abs=1), "p90_completion_seconds": pytest.approx(90, abs=1),
            "failure_reason_counts": {},
        }
        assert metrics["photo_only"] == {
            "started_run_count": 1, "terminal_intake_run_count": 1, "successful_intake_run_count": 0,
            "success_rate": 0.0, "confirmation_request_count": 1,
            "unsupported_inference_blocked_run_count": 1, "unsupported_inference_blocked_rate": 1.0,
            "source_fidelity_counts": {"ready": 1}, "unknown_fact_count": 0,
            "prohibited_inference_count": 1, "clarification_count": 2, "completed_intake_count": 0,
            "p50_completion_seconds": None, "p90_completion_seconds": None,
            "failure_reason_counts": {"PROHIBITED_INFERENCE_BLOCKED": 1},
        }
        assert metrics["manual"] == {
            "started_run_count": 1, "terminal_intake_run_count": 1, "successful_intake_run_count": 0,
            "success_rate": 0.0, "confirmation_request_count": 0,
            "unsupported_inference_blocked_run_count": 0, "unsupported_inference_blocked_rate": 0.0,
            "source_fidelity_counts": {"seller_entered": 1}, "unknown_fact_count": 2,
            "prohibited_inference_count": 0, "clarification_count": 1, "completed_intake_count": 0,
            "p50_completion_seconds": None, "p90_completion_seconds": None,
            "failure_reason_counts": {"CREATIVE_BRIEF_BLOCKED": 1},
        }
        assert "PROMPT_SECRET_OPS12" not in str(metrics)
        assert "OPS12_SECRET" not in str(metrics)
        assert "ops12-private@example.com" not in str(metrics)

        project_only = AgentRunEventJournal.intake_operational_summary(
            session, workspace_id=url_run.workspace_id, project_id=url_run.project_id,
        )["modes"]
        assert project_only["owned_product_url"]["started_run_count"] == 1
        assert project_only["photo_only"]["started_run_count"] == 0
        mismatched = AgentRunEventJournal.intake_operational_summary(
            session, workspace_id=url_run.workspace_id, project_id=str(uuid4()), run_id=url_run.id,
        )["modes"]
        assert all(mode["started_run_count"] == 0 for mode in mismatched.values())

        replay_run = _run(session, mode="lg12i_intake")
        replay_run.input_snapshot = {"unified_product_intake": {"input_mode": "manual"}}
        session.commit()
        payload = _ops12_payload("manual_input_adapter", input_mode="manual")
        first, appended, _ = AgentRunEventJournal.append(
            replay_run, session, event_type="intake_envelope_accepted", payload=payload,
            workspace_id=replay_run.workspace_id, project_id=replay_run.project_id,
        )
        duplicate, duplicated, _ = AgentRunEventJournal.append(
            replay_run, session, event_type="intake_envelope_accepted", payload=payload,
            workspace_id=replay_run.workspace_id, project_id=replay_run.project_id,
        )
        session.commit()
        assert appended is True and duplicated is False and first.id == duplicate.id
        LangGraphRunService._mark_execution_failed(
            replay_run.id,
            session,
            RuntimeError("PROMPT_SECRET_OPS12 https://signed.example/private?token=OPS12_SECRET ops12-private@example.com"),
        )
        replay_metrics = AgentRunEventJournal.intake_operational_summary(
            session, workspace_id=replay_run.workspace_id,
        )["modes"]
        assert replay_metrics["manual"]["started_run_count"] == 1
        assert replay_metrics["manual"]["confirmation_request_count"] == 0
        assert replay_metrics["manual"]["failure_reason_counts"] == {"GRAPH_EXECUTION_FAILED": 1}
        replay_events = session.query(AgentRunEvent).filter_by(run_id=replay_run.id).all()
        assert "PROMPT_SECRET_OPS12" not in str([event.payload_json for event in replay_events])
        assert "OPS12_SECRET" not in str([event.payload_json for event in replay_events])
        assert "ops12-private@example.com" not in str([event.payload_json for event in replay_events])
    finally:
        session.close()
