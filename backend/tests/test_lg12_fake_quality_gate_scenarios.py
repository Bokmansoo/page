"""Persisted TASK-12.11 route scenarios kept in the immutable Golden shape."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lg12_golden_comparator import assert_matches_golden, build_lg12_snapshot
from src.db.models import (
    AgentRun,
    BrandKitVersion,
    CommerceCreativeMasterVersion,
    DetailPageVersion,
    ImageGenerationOutboxRecord,
    ProductCreativeBriefVersion,
    ProductSourceSnapshotVersion,
    ProductTruthVersion,
    QualityAssessmentReportVersion,
    SellerConfirmationVersion,
)
from src.services.quality_assessment_service import evaluate_factual_rights_policy_domain
from src.services.quality_bar_service import aggregate_quality_bar
from test_lg12_fact_rights_quality import _setup as _setup_factual
from test_lg12_fake_quality_gate import _persisted_pass_fixture, _update_requested
from test_lg12_final_promotion_gate import _current_stale_successor, _pass_fixture, _quality_fixture
from test_lg12_quality_graph_integration import (
    _build_quality_evidence_page,
    _invoke_compiled_quality_pass_path,
    aggregate_valid_lg12_quality_bar,
    attach_valid_lg12_channel_parity_evidence,
    attach_valid_lg12_copy_evidence,
    attach_valid_lg12_layout_evidence,
    build_image_identity_failure_fixture,
    build_plan_order_failure_fixture,
    build_valid_lg12_frozen_detail_page,
    build_valid_lg12_master_lineage,
    build_valid_lg12_page_plan,
    build_style_brand_mismatch_failure_fixture,
    evaluate_all_lg12_quality_domains,
)
from test_lg12_visual_quality_bar import _persist_actual_blocked_domain


pytestmark = pytest.mark.lg12_fake_quality_gate


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def _attach_quality_evidence(*, page, db_session, tmp_path) -> None:
    attach_valid_lg12_copy_evidence(page=page)
    attach_valid_lg12_layout_evidence(page=page)
    attach_valid_lg12_channel_parity_evidence(page=page, db_session=db_session, tmp_path=tmp_path)


def _checkpoint_for(run: AgentRun, *, stage: str | None = None, status: str | None = None) -> SimpleNamespace:
    values = dict(run.outputs_json or {})
    values["current_stage"] = stage or run.current_stage
    values["status"] = status or run.status
    return SimpleNamespace(values=values)


def _lineage_from_master(*, db_session, master: CommerceCreativeMasterVersion) -> dict:
    source = db_session.get(ProductSourceSnapshotVersion, master.source_snapshot_version_id)
    truth = db_session.get(ProductTruthVersion, master.truth_version_id)
    confirmation = db_session.get(SellerConfirmationVersion, master.confirmation_version_id)
    brief = db_session.get(ProductCreativeBriefVersion, master.creative_brief_version_id)
    brand_kit = db_session.get(BrandKitVersion, master.brand_kit_version_id)
    assert all((source, truth, confirmation, brief, brand_kit))
    return {
        "source": source,
        "truth": truth,
        "confirmation": confirmation,
        "brief": brief,
        "master": master,
        "brand_kit": brand_kit,
        "run": db_session.get(AgentRun, master.creator_run_id),
    }


def _lineage_from_page(*, db_session, page: DetailPageVersion) -> dict:
    master_ref = dict(dict(page.sections_json or {}).get("lg12_quality_lineage") or {}).get("master_ref") or {}
    master = db_session.get(CommerceCreativeMasterVersion, master_ref.get("id"))
    assert master is not None
    return _lineage_from_master(db_session=db_session, master=master)


def _quality_bar_for(*, db_session, report: QualityAssessmentReportVersion) -> dict:
    return aggregate_valid_lg12_quality_bar(qa_report=report, db_session=db_session)["quality_bar"]


def _scenario_snapshot(*, lineage, page, report, quality_bar, run, initial_report=None, initial_quality_bar=None, details=None):
    return build_lg12_snapshot(
        lineage=lineage,
        page=page,
        report=report,
        quality_bar=quality_bar,
        checkpoint=_checkpoint_for(run),
        initial_report=initial_report,
        initial_quality_bar=initial_quality_bar,
        scenario_details=details,
    )


def _rework_setup(*, client, auth_headers, db_session, tmp_path, failure_builder):
    lineage, original_page, _report, _bar = _persisted_pass_fixture(client, auth_headers, db_session, tmp_path)
    failure = failure_builder(run=lineage["run"], page=original_page, db_session=db_session)
    failing_page = failure["page"]
    _attach_quality_evidence(page=failing_page, db_session=db_session, tmp_path=tmp_path)
    failed_report = evaluate_all_lg12_quality_domains(
        run=lineage["run"], page=failing_page, db_session=db_session,
    )["qa_report"]
    failed_bar = _quality_bar_for(db_session=db_session, report=failed_report)
    return lineage, failure, failed_report, failed_bar


def _final_rework_snapshot(*, lineage, failure, failed_report, failed_bar, db_session, tmp_path):
    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=failure["page"], db_session=db_session,
    )
    checkpoint = invocation["checkpoint"]
    quality = dict(checkpoint.values["quality"])
    child = db_session.get(DetailPageVersion, quality["current_detail_page_ref"]["id"])
    report = db_session.get(QualityAssessmentReportVersion, quality["quality_report_ref"]["id"])
    assert child is not None and report is not None
    bar = _quality_bar_for(db_session=db_session, report=report)
    assert checkpoint.values["current_stage"] == "quality_promotion_ready"
    assert bar["verdict"] == bar["routing_code"] == "PASS"
    return build_lg12_snapshot(
        lineage=lineage,
        page=child,
        report=report,
        quality_bar=bar,
        checkpoint=checkpoint,
        initial_report=failed_report,
        initial_quality_bar=failed_bar,
        scenario_details={
            "parent_child": {
                "parent_snapshot_hash": failure["page"].sections_json["snapshot_hash"],
                "child_parent_id": child.sections_json["lg11"]["parent_detail_page_version_id"],
            },
            "attempt_count": len(quality["attempt_ledger"]),
        },
    )


def test_lg12_fake_quality_gate_visual_rework_matches_persisted_baseline(
    client, auth_headers, db_session, tmp_path, monkeypatch, request,
):
    monkeypatch.chdir(tmp_path)
    lineage, failure, failed_report, failed_bar = _rework_setup(
        client=client,
        auth_headers=auth_headers,
        db_session=db_session,
        tmp_path=tmp_path,
        failure_builder=build_style_brand_mismatch_failure_fixture,
    )
    assert failed_bar["routing_code"] == "VISUAL_REWORK"
    assert_matches_golden(
        scenario="visual-rework-pass",
        snapshot=_final_rework_snapshot(
            lineage=lineage, failure=failure, failed_report=failed_report,
            failed_bar=failed_bar, db_session=db_session, tmp_path=tmp_path,
        ),
        update=_update_requested(request),
    )


def test_lg12_fake_quality_gate_plan_rework_matches_persisted_baseline(
    client, auth_headers, db_session, tmp_path, monkeypatch, request,
):
    monkeypatch.chdir(tmp_path)
    lineage, failure, failed_report, failed_bar = _rework_setup(
        client=client,
        auth_headers=auth_headers,
        db_session=db_session,
        tmp_path=tmp_path,
        failure_builder=build_plan_order_failure_fixture,
    )
    assert failed_bar["routing_code"] == "VISUAL_REWORK"
    snapshot = _final_rework_snapshot(
        lineage=lineage, failure=failure, failed_report=failed_report,
        failed_bar=failed_bar, db_session=db_session, tmp_path=tmp_path,
    )
    assert snapshot["frozen_page"]["page_plan_ref"]["artifact_version"] == 2
    assert_matches_golden(scenario="plan-rework-pass", snapshot=snapshot, update=_update_requested(request))


def test_lg12_fake_quality_gate_needs_review_matches_persisted_baseline(
    client, auth_headers, db_session, tmp_path, request,
):
    lineage, page, report, bar = _quality_fixture(client, auth_headers, db_session, tmp_path, verdict="NEEDS_REVIEW")
    run = lineage["run"]
    run.current_stage = "quality_review"
    run.status = "awaiting_review"
    db_session.flush()
    assert bar["verdict"] == "NEEDS_REVIEW"
    snapshot = _scenario_snapshot(
        lineage=lineage,
        page=page,
        report=report,
        quality_bar=bar,
        run=run,
        details={"review_required": True, "promotion": False, "export": False},
    )
    assert_matches_golden(scenario="needs-review", snapshot=snapshot, update=_update_requested(request))


def test_lg12_fake_quality_gate_policy_fail_matches_persisted_baseline(
    client, auth_headers, db_session, tmp_path, request,
):
    run, master, page, manifest_hash, profile = _setup_factual(
        db_session,
        client,
        auth_headers,
        tmp_path,
        confirmed=(),
        sections=[{"section_id": "hero", "title": "최저가 상품", "copy_ref": {"fact_ids": []}}],
    )
    report, result = _persist_actual_blocked_domain(
        db_session,
        run,
        master,
        page,
        manifest_hash,
        profile,
        evaluate_factual_rights_policy_domain,
    )
    bar = aggregate_quality_bar(
        db_session,
        report_ref={"id": report.id, "version": report.version, "hash": report.canonical_hash},
    )
    assert result["domain"]["status"] == "blocked"
    assert bar["verdict"] == "FAIL" and bar["routing_code"] == "BLOCKED_POLICY"
    snapshot = _scenario_snapshot(
        lineage=_lineage_from_master(db_session=db_session, master=master),
        page=page,
        report=report,
        quality_bar=bar,
        run=run,
        details={"promotion": False, "export": False, "critical_count": bar["critical_count"]},
    )
    assert_matches_golden(scenario="policy-fail", snapshot=snapshot, update=_update_requested(request))


def test_lg12_fake_quality_gate_stale_gate_matches_persisted_baseline(
    client, auth_headers, db_session, tmp_path, request,
):
    lineage, historical, report = _pass_fixture(client, auth_headers, db_session, tmp_path)
    run = lineage["run"]
    from src.services.quality_promotion_service import promote_current_quality_page

    promotion = promote_current_quality_page(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        actor_id=run.created_by,
        requested_page_id=historical.id,
    )
    initial_export = client.post(
        f"/api/v1/projects/{run.project_id}/page/export/standalone",
        headers=auth_headers,
        json={"final_version_id": historical.id, "channel": "smartstore"},
    )
    assert initial_export.status_code == 200, initial_export.text
    html_asset_id = initial_export.json()["html_download_url"].rsplit("/", 1)[-1]
    zip_asset_id = initial_export.json()["zip_download_url"].rsplit("/", 1)[-1]
    current = _current_stale_successor(historical_page=historical, db_session=db_session)
    responses = [
        client.post(f"/api/v1/projects/{run.project_id}/page/promotion", headers=auth_headers, json={"detail_page_version_id": historical.id}),
        client.post(f"/api/v1/projects/{run.project_id}/page/export/standalone", headers=auth_headers, json={"final_version_id": historical.id, "channel": "smartstore"}),
        client.get(f"/api/v1/projects/{run.project_id}/page/export/download/{html_asset_id}", headers=auth_headers),
        client.get(f"/api/v1/files/assets/{html_asset_id}", headers=auth_headers),
        client.get(f"/api/v1/files/assets/{zip_asset_id}", headers=auth_headers),
    ]
    assert all(response.status_code == 409 and response.json()["detail"]["code"] == "quality_gate_blocked" for response in responses)
    bar = _quality_bar_for(db_session=db_session, report=report)
    snapshot = _scenario_snapshot(
        lineage=lineage,
        page=historical,
        report=report,
        quality_bar=bar,
        run=run,
        details={
            "historical_preserved": historical.is_final,
            "historical_promotion_id": promotion.id,
            "current_page_snapshot_hash": current.sections_json["snapshot_hash"],
            "promotion": False,
            "export": False,
            "blocked_operations": ["promotion", "standalone_export", "download", "generic_html", "generic_zip"],
        },
    )
    assert_matches_golden(scenario="stale-gate", snapshot=snapshot, update=_update_requested(request))


def _run_after_existing_integration(*, db_session) -> AgentRun:
    runs = db_session.query(AgentRun).all()
    assert len(runs) == 1
    return runs[0]


def _report_for_page(*, db_session, page: DetailPageVersion) -> QualityAssessmentReportVersion:
    reports = db_session.query(QualityAssessmentReportVersion).filter_by(project_id=page.project_id).all()
    matches = [
        report for report in reports
        if str(dict(report.report_json or {}).get("target_artifact", {}).get("id") or "") == str(page.id)
    ]
    assert len(matches) == 1
    return matches[0]


def _blocked_image_report(*, db_session, project_id: str) -> QualityAssessmentReportVersion:
    reports = db_session.query(QualityAssessmentReportVersion).filter_by(project_id=project_id).all()
    matches = [
        report for report in reports
        if any(
            item.get("domain_id") == "image_identity_quality" and item.get("status") == "blocked"
            for item in list(dict(report.report_json or {}).get("domain_scores") or [])
        )
    ]
    assert matches
    return min(matches, key=lambda report: report.created_at)


def _latest_persisted_page_report(*, db_session, project_id: str) -> tuple[DetailPageVersion, QualityAssessmentReportVersion]:
    pages = db_session.query(DetailPageVersion).filter_by(project_id=project_id).all()
    for page in sorted(pages, key=lambda item: item.created_at, reverse=True):
        reports = [
            report for report in db_session.query(QualityAssessmentReportVersion).filter_by(project_id=project_id).all()
            if str(dict(report.report_json or {}).get("target_artifact", {}).get("id") or "") == str(page.id)
        ]
        if len(reports) == 1:
            return page, reports[0]
    raise AssertionError("no persisted DetailPageVersion with one QA report")


def test_lg12_fake_quality_gate_image_rework_matches_persisted_baseline(
    client, auth_headers, db_session, tmp_path, monkeypatch, request,
):
    # Reuse the existing verified real graph/provider-boundary integration flow;
    # cloning its cost approval, worker, and replay sequence would create a second test universe.
    from test_lg12_quality_graph_integration import test_compiled_graph_executes_real_image_rework_cost_outbox_worker_and_reqa

    result: dict[str, object] = {}
    test_compiled_graph_executes_real_image_rework_cost_outbox_worker_and_reqa(
        client, auth_headers, db_session, tmp_path, monkeypatch, golden_result=result,
    )
    db_session.expire_all()
    run, page, report = result["run"], result["page"], result["report"]
    initial_report = result["initial_report"]
    bar = _quality_bar_for(db_session=db_session, report=report)
    initial_bar = result["initial_quality_bar"]
    assert_matches_golden(
        scenario="image-rework-pass",
        snapshot=_scenario_snapshot(
            lineage=_lineage_from_page(db_session=db_session, page=page),
            page=page,
            report=report,
            quality_bar=bar,
            run=run,
            initial_report=initial_report,
            initial_quality_bar=initial_bar,
            details={
                "outbox_count": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
                "provider_output_sha256": page.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]["assets"][0]["asset_content_hash"],
            },
        ),
        update=_update_requested(request),
    )


def test_lg12_fake_quality_gate_retry_exhaustion_matches_persisted_baseline(
    client, auth_headers, db_session, tmp_path, monkeypatch, request,
):
    # This existing integration owns the two real worker attempts and checkpoint recovery.
    from test_lg12_quality_graph_integration import test_projection_rebuild_preserves_exhausted_retry_budget

    result: dict[str, object] = {}
    test_projection_rebuild_preserves_exhausted_retry_budget(client, auth_headers, db_session, tmp_path, monkeypatch, golden_result=result)
    db_session.expire_all()
    run, page, report = result["run"], result["page"], result["report"]
    initial_report = result["initial_report"]
    bar = _quality_bar_for(db_session=db_session, report=report)
    initial_bar = result["initial_quality_bar"]
    ledger = list(result["attempt_ledger"])
    assert len(ledger) == 1 and ledger[0]["attempt_count"] == 2
    assert_matches_golden(
        scenario="retry-exhausted",
        snapshot=_scenario_snapshot(
            lineage=_lineage_from_page(db_session=db_session, page=page),
            page=page,
            report=report,
            quality_bar=bar,
            run=run,
            initial_report=initial_report,
            initial_quality_bar=initial_bar,
            details={
                "exhausted": True,
                "manual_review_stage": "quality_review",
                "outbox_count": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
                "attempts": ledger,
            },
        ),
        update=_update_requested(request),
    )