"""TASK-12.11 PostgreSQL proof using existing persisted Golden scenarios."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from lg12_golden_comparator import assert_matches_golden, build_lg12_snapshot
from scripts.postgres_test_environment import require_local_postgres_test_url
from src.agents.langgraph_runtime import open_postgres_checkpointer
from src.app import app
from src.db.database import SessionLocal
from src.db.models import DetailPageVersion, ImageGenerationJobRecord, ImageGenerationOutboxRecord, QualityAssessmentReportVersion
from src.services.quality_bar_service import aggregate_quality_bar
from src.services.quality_promotion_service import promote_current_quality_page
from test_lg12_fake_quality_gate import _persisted_pass_fixture
from test_lg12_fake_quality_gate_scenarios import _lineage_from_page, _quality_bar_for, _scenario_snapshot
from test_lg12_final_promotion_gate import _current_stale_successor, _pass_fixture as _stale_pass_fixture
from test_lg12_quality_graph_integration import (
    _invoke_compiled_quality_pass_path,
    attach_valid_lg12_channel_parity_evidence,
    attach_valid_lg12_copy_evidence,
    attach_valid_lg12_layout_evidence,
    build_copy_spacing_failure_fixture,
    evaluate_all_lg12_quality_domains,
    test_compiled_graph_executes_real_image_rework_cost_outbox_worker_and_reqa as _run_image_rework,
    test_projection_rebuild_preserves_exhausted_retry_budget as _run_retry_exhaustion,
)
from seed_lg12_quality_promotion_e2e import _seed_fail_or_needs_review


pytestmark = [pytest.mark.postgres, pytest.mark.integration, pytest.mark.lg12_fake_quality_gate]


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {
        "X-Mock-User-Id": str(uuid4()),
        "X-Mock-Workspace-Id": str(uuid4()),
    }


@pytest.fixture
def postgres_runtime():
    """Guard the one local Docker database and the process-wide production session."""

    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    assert os.environ.get("DATABASE_URL") == url
    assert os.environ.get("SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL") == url
    engine = create_engine(url)
    previous_bind = SessionLocal.kw.get("bind")
    SessionLocal.configure(bind=engine)
    try:
        assert engine.dialect.name == "postgresql"
        with TestClient(app) as client:
            db = SessionLocal()
            try:
                assert db.get_bind().dialect.name == "postgresql"
                yield url, client, db
            finally:
                db.close()
    finally:
        SessionLocal.configure(bind=previous_bind)
        engine.dispose()


def _matches(scenario: str, snapshot: dict[str, Any]) -> None:
    assert_matches_golden(scenario=scenario, snapshot=snapshot, update=False)


def test_postgres_golden_persisted_pass(postgres_runtime, auth_headers, tmp_path):
    url, client, db = postgres_runtime
    with open_postgres_checkpointer(url) as checkpointer:
        lineage, page, report, bar = _persisted_pass_fixture(client, auth_headers, db, tmp_path)
        invocation = _invoke_compiled_quality_pass_path(
            run=lineage["run"], page=page, db_session=db, checkpointer=checkpointer,
        )
        checkpoint = invocation["checkpoint"]
        assert checkpoint.values["current_stage"] == "quality_promotion_ready"
        _matches("persisted-pass", _scenario_snapshot(
            lineage=lineage, page=page, report=report, quality_bar=bar, run=invocation["run"],
        ))


def test_postgres_golden_copy_rework_child(postgres_runtime, auth_headers, tmp_path, monkeypatch):
    url, client, db = postgres_runtime
    lineage, source_page, _report, _bar = _persisted_pass_fixture(client, auth_headers, db, tmp_path)
    failed = build_copy_spacing_failure_fixture(run=lineage["run"], page=source_page, db_session=db)["page"]
    attach_valid_lg12_copy_evidence(page=failed)
    attach_valid_lg12_layout_evidence(page=failed)
    attach_valid_lg12_channel_parity_evidence(page=failed, db_session=db, tmp_path=tmp_path)
    failed_report = evaluate_all_lg12_quality_domains(run=lineage["run"], page=failed, db_session=db)["qa_report"]
    assert aggregate_quality_bar(
        db, report_ref={"id": failed_report.id, "version": failed_report.version, "hash": failed_report.canonical_hash},
    )["routing_code"] == "COPY_REWORK"
    monkeypatch.chdir(tmp_path)
    with open_postgres_checkpointer(url) as checkpointer:
        invocation = _invoke_compiled_quality_pass_path(
            run=lineage["run"], page=failed, db_session=db, checkpointer=checkpointer,
        )
        quality = dict(invocation["checkpoint"].values["quality"])
        child = db.get(DetailPageVersion, quality["current_detail_page_ref"]["id"])
        report = db.get(QualityAssessmentReportVersion, quality["quality_report_ref"]["id"])
        assert child is not None and report is not None
        assert child.sections_json["lg11"]["parent_detail_page_version_id"] == failed.id
        assert [(item["node_family"], item["attempt_count"]) for item in quality["attempt_ledger"]] == [("copy_reassembly", 1)]
        _matches("copy-rework-pass", build_lg12_snapshot(
            lineage=lineage, page=child, report=report,
            quality_bar=_quality_bar_for(db_session=db, report=report), checkpoint=invocation["checkpoint"],
        ))


def test_postgres_golden_image_rework_cost_checkpoint(postgres_runtime, auth_headers, tmp_path, monkeypatch):
    url, client, db = postgres_runtime
    result: dict[str, Any] = {}
    with open_postgres_checkpointer(url) as checkpointer:
        _run_image_rework(
            client, auth_headers, db, tmp_path, monkeypatch,
            golden_result=result, checkpointer=checkpointer,
        )
    run, page, report = result["run"], result["page"], result["report"]
    _matches("image-rework-pass", _scenario_snapshot(
        lineage=_lineage_from_page(db_session=db, page=page), page=page, report=report,
        quality_bar=_quality_bar_for(db_session=db, report=report), run=run,
        initial_report=result["initial_report"], initial_quality_bar=result["initial_quality_bar"],
        details={
            "outbox_count": db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
            "provider_output_sha256": page.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]["assets"][0]["asset_content_hash"],
        },
    ))


def test_postgres_golden_needs_review_checkpoint(postgres_runtime, auth_headers, tmp_path):
    url, client, db = postgres_runtime
    with open_postgres_checkpointer(url) as checkpointer:
        lineage, page, report, bar = _seed_fail_or_needs_review(
            state="needs-review", client=client, headers=auth_headers, db=db,
            artifact_dir=Path(tmp_path), checkpointer=checkpointer,
        )
    assert bar["verdict"] == "NEEDS_REVIEW"
    _matches("needs-review", _scenario_snapshot(
        lineage=lineage, page=page, report=report, quality_bar=bar, run=lineage["run"],
        details={"review_required": True, "promotion": False, "export": False},
    ))


def test_postgres_golden_stale_promotion_export(postgres_runtime, auth_headers, tmp_path):
    url, client, db = postgres_runtime
    lineage, historical, report = _stale_pass_fixture(client, auth_headers, db, tmp_path)
    with open_postgres_checkpointer(url) as checkpointer:
        invocation = _invoke_compiled_quality_pass_path(
            run=lineage["run"], page=historical, db_session=db, checkpointer=checkpointer,
        )
        historical_checkpoint = invocation["checkpoint"]
    run = invocation["run"]
    promotion = promote_current_quality_page(
        db, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=historical.id,
    )
    db.commit()
    db.refresh(run)
    initial_export = client.post(
        f"/api/v1/projects/{run.project_id}/page/export/standalone",
        headers=auth_headers, json={"final_version_id": historical.id, "channel": "smartstore"},
    )
    assert initial_export.status_code == 200, initial_export.text
    html_asset_id = initial_export.json()["html_download_url"].rsplit("/", 1)[-1]
    zip_asset_id = initial_export.json()["zip_download_url"].rsplit("/", 1)[-1]
    current = _current_stale_successor(historical_page=historical, db_session=db)
    db.commit()
    responses = [
        client.post(f"/api/v1/projects/{run.project_id}/page/promotion", headers=auth_headers, json={"detail_page_version_id": historical.id}),
        client.post(f"/api/v1/projects/{run.project_id}/page/export/standalone", headers=auth_headers, json={"final_version_id": historical.id, "channel": "smartstore"}),
        client.get(f"/api/v1/projects/{run.project_id}/page/export/download/{html_asset_id}", headers=auth_headers),
        client.get(f"/api/v1/files/assets/{html_asset_id}", headers=auth_headers),
        client.get(f"/api/v1/files/assets/{zip_asset_id}", headers=auth_headers),
    ]
    assert all(response.status_code == 409 and response.json()["detail"]["code"] == "quality_gate_blocked" for response in responses)
    _matches("stale-gate", build_lg12_snapshot(
        lineage=lineage, page=historical, report=report,
        quality_bar=_quality_bar_for(db_session=db, report=report), checkpoint=historical_checkpoint,
        scenario_details={
            "historical_preserved": historical.is_final,
            "historical_promotion_id": promotion.id,
            "current_page_snapshot_hash": current.sections_json["snapshot_hash"],
            "promotion": False,
            "export": False,
            "blocked_operations": ["promotion", "standalone_export", "download", "generic_html", "generic_zip"],
        },
    ))
def test_postgres_golden_retry_exhaustion(postgres_runtime, auth_headers, tmp_path, monkeypatch):
    url, client, db = postgres_runtime
    result: dict[str, Any] = {}
    with open_postgres_checkpointer(url) as checkpointer:
        _run_retry_exhaustion(
            client, auth_headers, db, tmp_path, monkeypatch,
            golden_result=result, checkpointer=checkpointer,
        )
    run, page, report = result["run"], result["page"], result["report"]
    db.refresh(run)
    _matches("retry-exhausted", _scenario_snapshot(
        lineage=_lineage_from_page(db_session=db, page=page), page=page, report=report,
        quality_bar=_quality_bar_for(db_session=db, report=report), run=run,
        initial_report=result["initial_report"], initial_quality_bar=result["initial_quality_bar"],
        details={
            "exhausted": True,
            "manual_review_stage": "quality_review",
            "outbox_count": db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
            "attempts": list(result["attempt_ledger"]),
        },
    ))


def test_postgres_slo08_exhausted_image_fallback_uses_only_frozen_seller_asset(
    postgres_runtime, auth_headers, tmp_path, monkeypatch,
):
    """SLO-08: no third provider dispatch after the max-two logical target budget."""

    url, client, db = postgres_runtime
    result: dict[str, Any] = {}
    with open_postgres_checkpointer(url) as checkpointer:
        _run_retry_exhaustion(
            client, auth_headers, db, tmp_path, monkeypatch,
            golden_result=result, checkpointer=checkpointer, verify_public_ledger=False,
        )
        run = result["run"]
        db.refresh(run)
        pending = dict((run.outputs_json or {}).get("langgraph_review") or {}).get("pending") or {}
        assert pending["review_stage"] == "quality_review"
        assert pending["allowed_decisions"] == ["fallback", "wait"]
        before = db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count()
        public = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
        assert public.status_code == 200, public.text
        public_pending = public.json()["values"]["review"]["pending"]
        assert public_pending["seller_choice"] == {
            "choice_required": True, "available_actions": ["fallback", "wait"], "automatic_attempts": 2,
        }
        assert not set(dict(public_pending.get("context") or {})) & {
            "quality_bar_ref", "quality_report_ref", "current_page_ref", "routing_code", "slo08_choice",
        }
        status = client.get(f"/api/v1/operations/projects/{run.project_id}/generation-status", headers=auth_headers)
        assert status.status_code == 200, status.text
        assert status.json()["seller_choice"] == public_pending["seller_choice"]
        unattested = client.post(
            f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
            json={"thread_id": run.id, "mode": "respond", "response": {
                "schema_version": "lg12i-v1", "review_stage": "quality_review", "decision": "fallback",
            }},
        )
        assert unattested.status_code == 409
        waiting = client.post(
            f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
            json={"thread_id": run.id, "mode": "respond", "response": {
                "schema_version": "lg12i-v1", "review_stage": "quality_review", "decision": "wait",
            }},
        )
        assert waiting.status_code == 200, waiting.text
        assert waiting.json()["values"]["review"]["pending"]["seller_choice"] == public_pending["seller_choice"]
        assert db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == before == 2
        fallback = client.post(
            f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
            json={"thread_id": run.id, "mode": "respond", "response": {
                "schema_version": "lg12i-v1", "review_stage": "quality_review", "decision": "fallback",
                "seller_attested": True,
            }},
        )
        assert fallback.status_code == 200, fallback.text
        db.refresh(run)
        quality = dict((run.outputs_json or {}).get("langgraph_quality") or {})
        assert quality["slo08_fallback_attempt_key"]
        assert quality["rework_attempt_count"] == 2
        assert db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == before == 2
        manual = db.query(ImageGenerationJobRecord).filter_by(
            project_id=run.project_id, provider="manual_upload", status="approved",
        ).one()
        assert manual.output_asset_id in manual.source_asset_ids
        duplicate = client.post(
            f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
            json={"thread_id": run.id, "mode": "respond", "response": {
                "schema_version": "lg12i-v1", "review_stage": "quality_review", "decision": "fallback",
                "seller_attested": True,
            }},
        )
        assert duplicate.status_code == 422
        assert db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == before
