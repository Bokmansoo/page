"""Seed a disposable persisted LG-12 PASS project for local browser E2E.

This command is PostgreSQL-only: ORM persistence and the LangGraph checkpoint
share the guarded local test database.  It refuses SQLite, Supabase and normal
development URLs before it can write anything.
"""

from __future__ import annotations

import json
import os
import tempfile
from threading import Barrier, Lock, Thread
from argparse import ArgumentParser
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app import app
from src.agents.langgraph_runtime import _lg12_quality_review_payload, open_postgres_checkpointer
from src.db.database import SessionLocal
from src.services.langgraph_run_service import AgentRunGraphProjector
from src.services.quality_promotion_service import promote_current_quality_page
from scripts.postgres_test_environment import require_local_postgres_test_url
from test_lg12_final_promotion_gate import _current_stale_successor, _pass_fixture
from test_lg12_quality_graph_integration import (
    _build_quality_evidence_page,
    _invoke_compiled_quality_pass_path,
    _seed_compiled_quality_graph,
    aggregate_valid_lg12_quality_bar,
    attach_valid_lg12_channel_parity_evidence,
    attach_valid_lg12_copy_evidence,
    attach_valid_lg12_layout_evidence,
    build_copy_spacing_failure_fixture,
    build_valid_lg12_master_lineage,
    build_valid_lg12_page_plan,
    evaluate_all_lg12_quality_domains,
)


def _quality_ref(row) -> dict[str, object]:
    return {"id": row.id, "version": row.version, "hash": row.canonical_hash,
            "type": "QualityAssessmentReportVersion"}


def _bar_ref(bar: dict[str, object]) -> dict[str, object]:
    return {"id": bar["quality_bar_result_id"], "version": 1,
            "hash": bar["canonical_hash"], "type": "QualityBarResult"}


def _seed_fail_or_needs_review(*, state: str, client, headers, db, artifact_dir: Path, checkpointer):
    """Build a persisted QA/QB state through existing production fixtures."""

    # Each fixture receives its own project/run identity. Never mutate another
    # fixture to make room: that would overwrite a valid FAIL/rework projection
    # with an infrastructure-looking ``seed_reset`` error in the public UI.
    lineage = build_valid_lg12_master_lineage(
        client,
        headers,
        db,
        product_name=f"LG-12 quality E2E {state}",
    )
    page_plan = build_valid_lg12_page_plan(lineage, db)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=artifact_dir, db_session=db,
    )
    page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=page)
    attach_valid_lg12_layout_evidence(page=page)

    if state == "fail":
        attach_valid_lg12_channel_parity_evidence(
            page=page, db_session=db, tmp_path=artifact_dir,
        )
        page = build_copy_spacing_failure_fixture(
            run=lineage["run"], page=page, db_session=db,
        )["page"]
        attach_valid_lg12_copy_evidence(page=page)
        attach_valid_lg12_layout_evidence(page=page)
        attach_valid_lg12_channel_parity_evidence(
            page=page, db_session=db, tmp_path=artifact_dir,
        )
        expected_verdict, stage, status = "FAIL", "quality_selective_rework", "running"
    else:
        # A missing frozen channel-parity evidence block is intentionally
        # non-evaluable; the actual evaluator must produce NEEDS_REVIEW.
        expected_verdict, stage, status = "NEEDS_REVIEW", "quality_review", "awaiting_review"

    evaluation = evaluate_all_lg12_quality_domains(
        run=lineage["run"], page=page, db_session=db,
    )
    report = evaluation["qa_report"]
    bar = aggregate_valid_lg12_quality_bar(qa_report=report, db_session=db)["quality_bar"]
    if bar["verdict"] != expected_verdict:
        raise RuntimeError(f"Expected {expected_verdict} fixture, got {bar['verdict']}")

    seeded = _seed_compiled_quality_graph(
        run=lineage["run"], page=page, db_session=db, checkpointer=checkpointer,
    )
    quality = {
        "quality_report_ref": _quality_ref(report),
        "quality_bar_ref": _bar_ref(bar),
        "quality_bar_verdict": bar["verdict"],
        "routing_code": bar["routing_code"],
        "seller_review_required": state == "needs-review",
        "rework_targets": list(bar["rework_targets"]),
        "last_blocking_reasons": list(bar["blocking_reasons"]),
    }
    graph_state = {
        "run_id": lineage["run"].id,
        "thread_id": lineage["run"].graph_thread_id,
        "workspace_id": lineage["run"].workspace_id,
        "project_id": lineage["run"].project_id,
        "current_stage": stage,
        "status": status,
        "quality": quality,
        "rendering": {
            "detail_page_version": {
                "id": page.id,
                "schema_version": page.sections_json["schema_version"],
                "snapshot_hash": page.sections_json["snapshot_hash"],
            },
        },
    }
    pending = None
    if state == "needs-review":
        # Reuse the production bounded interrupt shape so the existing review
        # panel receives a real stage/title/action contract, never a fixture-
        # only ``kind`` object or raw QA body.
        pending = _lg12_quality_review_payload(graph_state)
        graph_state["review"] = {"pending": pending}
    seeded["graph"].update_state(seeded["config"], graph_state, as_node="quality_evaluation")
    run = lineage["run"]
    if pending is not None:
        run = AgentRunGraphProjector.apply_interrupt_wait(run, db, pending)
    else:
        run.current_stage = stage
        run.status = status
        db.commit()
        db.refresh(run)
    lineage["run"] = run
    return lineage, page, report, bar


def _seed_stale_pass(*, client, headers, db, artifact_dir: Path, checkpointer):
    """Persist a historical PASS/export and a separate newer current page.

    The successor intentionally has no inherited report or promotion. It is a
    real frozen current page which must therefore be re-evaluated before any
    final/export surface can use it.
    """

    lineage, historical, report = _pass_fixture(
        client,
        headers,
        db,
        artifact_dir,
        product_name="LG-12 quality E2E stale historical",
    )
    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=historical, db_session=db, checkpointer=checkpointer,
    )
    run = invocation["run"]
    promotion = promote_current_quality_page(
        db, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=historical.id,
    )
    db.commit()

    historical_export = client.post(
        f"/api/v1/projects/{run.project_id}/page/export/standalone",
        headers=headers,
        json={"final_version_id": historical.id, "channel": "smartstore"},
    )
    if historical_export.status_code != 200:
        raise RuntimeError(f"Historical standalone export seed failed: {historical_export.text}")
    historical_export_payload = historical_export.json()
    for key in ("html_download_url", "zip_download_url"):
        current_generic = client.get(
            historical_export_payload[key].replace(
                "/api/v1/projects/" + run.project_id + "/page/export/download/",
                "/api/v1/files/assets/",
            ),
            headers=headers,
        )
        if current_generic.status_code != 200:
            raise RuntimeError(f"Current promoted generic asset download failed: {current_generic.text}")
    current = _current_stale_successor(historical_page=historical, db_session=db)
    graph_state = {
        "run_id": run.id,
        "thread_id": run.graph_thread_id,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "current_stage": "quality_review",
        "status": "awaiting_review",
        "quality": {
            "quality_bar_verdict": "NEEDS_REVIEW",
            "routing_code": "SELLER_REVIEW",
            "seller_review_required": True,
            "last_blocking_reasons": ["최신 상세페이지는 새 품질 검토가 필요합니다."],
            "rework_targets": [],
        },
        "rendering": {
            "detail_page_version": {
                "id": current.id,
                "schema_version": current.sections_json["schema_version"],
                "snapshot_hash": current.sections_json["snapshot_hash"],
            },
        },
    }
    pending = _lg12_quality_review_payload(graph_state)
    graph_state["review"] = {"pending": pending}
    invocation["graph"].update_state(invocation["config"], graph_state, as_node="quality_evaluation")
    run = AgentRunGraphProjector.apply_interrupt_wait(run, db, pending)
    # Commit the successor before exercising the independent API session.
    # This proves that an old HTML/ZIP asset cannot bypass the quality gate via
    # generic file retrieval once a newer frozen page is current.
    db.commit()
    for key in ("html_download_url", "zip_download_url"):
        stale_generic = client.get(
            historical_export_payload[key].replace(
                "/api/v1/projects/" + run.project_id + "/page/export/download/",
                "/api/v1/files/assets/",
            ),
            headers=headers,
        )
        if stale_generic.status_code != 409 or stale_generic.json().get("detail", {}).get("code") != "quality_gate_blocked":
            raise RuntimeError(f"Stale generic asset download bypassed quality gate: {stale_generic.text}")
    lineage["run"] = run
    return lineage, historical, current, report, promotion, historical_export_payload


def _verify_two_connection_promotion(*, test_url: str, run, page) -> dict[str, object]:
    """Exercise the production idempotency path with two PostgreSQL sessions."""

    engine = create_engine(test_url, pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    barrier = Barrier(2)
    lock = Lock()
    promotion_ids: list[str] = []
    failures: list[str] = []

    def promote_once() -> None:
        session = sessions()
        try:
            barrier.wait(timeout=20)
            row = promote_current_quality_page(
                session,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                actor_id=run.created_by,
                requested_page_id=page.id,
            )
            session.commit()
            with lock:
                promotion_ids.append(row.id)
        except Exception as exc:  # surfaced below with both connection context
            session.rollback()
            with lock:
                failures.append(f"{type(exc).__name__}: {exc}")
        finally:
            session.close()

    threads = [Thread(target=promote_once, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    if any(thread.is_alive() for thread in threads):
        raise RuntimeError("PostgreSQL promotion race did not complete.")
    if failures:
        raise RuntimeError(f"PostgreSQL promotion race failed: {failures}")
    if len(promotion_ids) != 2 or len(set(promotion_ids)) != 1:
        raise RuntimeError(f"Promotion race was not idempotent: {promotion_ids}")
    verify = sessions()
    try:
        from src.db.models import QualityPromotionVersion

        row_count = verify.query(QualityPromotionVersion).filter_by(project_id=run.project_id).count()
    finally:
        verify.close()
        engine.dispose()
    if row_count != 1:
        raise RuntimeError(f"Promotion race created {row_count} immutable rows.")
    return {"promotion_id": promotion_ids[0], "row_count": row_count}


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--state", choices=("pass", "pass-ready", "promotion-race", "fail", "needs-review", "stale"), default="pass")
    state = parser.parse_args().state
    test_url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    if os.environ.get("DATABASE_URL") != test_url:
        raise RuntimeError(
            "DATABASE_URL must exactly equal TEST_DATABASE_URL for PostgreSQL E2E seeding."
        )
    if os.environ.get("SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL", test_url) != test_url:
        raise RuntimeError(
            "SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL must equal TEST_DATABASE_URL for E2E seeding."
        )
    artifact_dir = Path(tempfile.mkdtemp(prefix="sellform-lg12-promotion-e2e-"))
    headers = {
        "X-Mock-User-Id": os.environ.get(
            "SELLFORM_E2E_SEED_USER_ID", "00000000-0000-0000-0000-000000000001"
        ),
        "X-Mock-Workspace-Id": os.environ.get(
            "SELLFORM_E2E_SEED_WORKSPACE_ID", "00000000-0000-0000-0000-000000000002"
        ),
    }
    with TestClient(app) as client:
        db = SessionLocal()
        try:
            with open_postgres_checkpointer(test_url) as checkpointer:
                race_result = None
                if state in {"pass", "pass-ready", "promotion-race"}:
                    lineage, page, report = _pass_fixture(
                        client,
                        headers,
                        db,
                        artifact_dir,
                        product_name=f"LG-12 quality E2E {state}",
                    )
                    invocation = _invoke_compiled_quality_pass_path(
                        run=lineage["run"], page=page, db_session=db, checkpointer=checkpointer,
                    )
                    run = invocation["run"]
                    promotion = (
                        promote_current_quality_page(
                            db, workspace_id=run.workspace_id, project_id=run.project_id,
                            actor_id=run.created_by, requested_page_id=page.id,
                        )
                        if state == "pass"
                        else None
                    )
                    db.commit()
                    quality_state = "PASS"
                    if state == "promotion-race":
                        race_result = _verify_two_connection_promotion(
                            test_url=test_url, run=run, page=page,
                        )
                elif state in {"fail", "needs-review"}:
                    lineage, page, report, bar = _seed_fail_or_needs_review(
                        state=state, client=client, headers=headers, db=db,
                        artifact_dir=artifact_dir, checkpointer=checkpointer,
                    )
                    run = lineage["run"]
                    promotion = None
                    quality_state = str(bar["verdict"])
                else:
                    lineage, historical, page, report, promotion, historical_export = _seed_stale_pass(
                        client=client, headers=headers, db=db,
                        artifact_dir=artifact_dir, checkpointer=checkpointer,
                    )
                    run = lineage["run"]
                    quality_state = "STALE"
            print(json.dumps({
                "workspace_id": run.workspace_id,
                "project_id": run.project_id,
                "run_id": run.id,
                "detail_page_version_id": page.id,
                "quality_report_id": report.id,
                "quality_state": quality_state,
                "promotion_id": promotion.id if promotion else None,
                "historical_detail_page_version_id": historical.id if state == "stale" else None,
                "historical_export_html_url": historical_export["html_download_url"] if state == "stale" else None,
                "promotion_race": race_result,
                "browser_url": (
                    f"http://localhost:3000/workspace/projects/{run.project_id}"
                    f"/planning?runId={run.id}"
                ),
            }))
        finally:
            db.close()


if __name__ == "__main__":
    main()
