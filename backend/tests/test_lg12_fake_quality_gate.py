"""TASK-12.11 zero-cost semantic Golden regression suite.

This suite owns comparison and baseline immutability; the persisted builders
and compiled graph remain the existing production TASK-12.9/TASK-12.10 path.
Use ``pytest --update-lg12-golden`` deliberately to refresh checked-in files.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from lg12_golden_comparator import (
    assert_matches_golden,
    build_lg12_snapshot,
    normalize_lg12_semantics,
    semantic_difference,
)
from src.db.models import (
    DetailPageVersion,
    ImageGenerationCostApprovalRecord,
    ImageGenerationOutboxRecord,
    QualityAssessmentReportVersion,
)
from src.schemas.lg12_golden_dataset import load_golden_dataset
from src.schemas.lg12_product_intake_golden_dataset import load_product_intake_golden_dataset
from src.services.quality_promotion_service import (
    QualityPromotionGateError,
    promote_current_quality_page,
    require_current_quality_promotion,
)
from test_lg12_final_promotion_gate import _current_stale_successor, _pass_fixture  # type: ignore[import-not-found]
from test_lg12_quality_graph_integration import (  # type: ignore[import-not-found]
    _build_quality_evidence_page,
    _invoke_compiled_quality_pass_path,
    aggregate_valid_lg12_quality_bar,
    attach_valid_lg12_channel_parity_evidence,
    attach_valid_lg12_copy_evidence,
    attach_valid_lg12_layout_evidence,
    build_copy_spacing_failure_fixture,
    build_valid_lg12_frozen_detail_page,
    build_valid_lg12_master_lineage,
    build_valid_lg12_page_plan,
    evaluate_all_lg12_quality_domains,
)


pytestmark = pytest.mark.lg12_fake_quality_gate


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def _update_requested(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-lg12-golden"))


def _persisted_pass_fixture(client, auth_headers, db_session, tmp_path):
    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    page = evidence["page"]
    attach_valid_lg12_copy_evidence(page=page)
    attach_valid_lg12_layout_evidence(page=page)
    attach_valid_lg12_channel_parity_evidence(page=page, db_session=db_session, tmp_path=tmp_path)
    report = evaluate_all_lg12_quality_domains(run=lineage["run"], page=page, db_session=db_session)["qa_report"]
    quality_bar = aggregate_valid_lg12_quality_bar(qa_report=report, db_session=db_session)["quality_bar"]
    assert quality_bar["verdict"] == "PASS"
    return lineage, page, report, quality_bar


def test_lg12_fake_quality_gate_persisted_pass_matches_immutable_baseline(
    client, auth_headers, db_session, tmp_path, request,
):
    """Real persisted lineage -> five evaluators -> QB -> compiled PASS path."""

    lineage, page, report, quality_bar = _persisted_pass_fixture(
        client, auth_headers, db_session, tmp_path,
    )
    before = {
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count(),
    }
    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=page, db_session=db_session,
    )
    checkpoint = invocation["checkpoint"]
    assert checkpoint.values["current_stage"] == "quality_promotion_ready"
    assert checkpoint.values["quality"]["quality_bar_verdict"] == "PASS"
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count() == before["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count() == before["cost"]

    snapshot = build_lg12_snapshot(
        lineage=lineage, page=page, report=report, quality_bar=quality_bar, checkpoint=checkpoint,
    )
    assert_matches_golden(
        scenario="persisted-pass", snapshot=snapshot, update=_update_requested(request),
    )


def test_lg12_fake_quality_gate_copy_rework_reaches_pass_and_matches_baseline(
    client, auth_headers, db_session, tmp_path, monkeypatch, request,
):
    """COPY_REWORK uses the real compiled graph and creates one immutable child."""

    lineage, source_page, _report, _bar = _persisted_pass_fixture(client, auth_headers, db_session, tmp_path)
    failed = build_copy_spacing_failure_fixture(
        run=lineage["run"], page=source_page, db_session=db_session,
    )["page"]
    attach_valid_lg12_copy_evidence(page=failed)
    attach_valid_lg12_layout_evidence(page=failed)
    attach_valid_lg12_channel_parity_evidence(page=failed, db_session=db_session, tmp_path=tmp_path)
    failed_report = evaluate_all_lg12_quality_domains(run=lineage["run"], page=failed, db_session=db_session)["qa_report"]
    failed_bar = aggregate_valid_lg12_quality_bar(qa_report=failed_report, db_session=db_session)["quality_bar"]
    assert failed_bar["routing_code"] == "COPY_REWORK"

    monkeypatch.chdir(tmp_path)
    invocation = _invoke_compiled_quality_pass_path(run=lineage["run"], page=failed, db_session=db_session)
    checkpoint = invocation["checkpoint"]
    quality = dict(checkpoint.values["quality"])
    child = db_session.get(DetailPageVersion, quality["current_detail_page_ref"]["id"])
    report = db_session.get(QualityAssessmentReportVersion, quality["quality_report_ref"]["id"])
    assert child is not None and report is not None
    assert child.id != failed.id
    assert child.sections_json["lg11"]["parent_detail_page_version_id"] == failed.id
    assert quality["quality_bar_verdict"] == "PASS"
    assert [(item["node_family"], item["attempt_count"]) for item in quality["attempt_ledger"]] == [
        ("copy_reassembly", 1),
    ]
    bar = aggregate_valid_lg12_quality_bar(qa_report=report, db_session=db_session)["quality_bar"]
    snapshot = build_lg12_snapshot(lineage=lineage, page=child, report=report, quality_bar=bar, checkpoint=checkpoint)
    assert_matches_golden(scenario="copy-rework-pass", snapshot=snapshot, update=_update_requested(request))


def test_lg12_fake_quality_gate_dataset_and_scenario_matrix_matches_baseline(request):
    """Keep both immutable datasets and all required fake-gate scenarios visible."""

    v1 = load_golden_dataset()
    v2 = load_product_intake_golden_dataset()
    assert len(v1["cases"]) == len(v2["cases"]) == 15
    categories = {case["category"] for case in v2["cases"]}
    modes = {case["input_mode"] for case in v2["cases"]}
    matrix = {
        "contract_v1": {"version": v1["dataset_version"], "case_count": len(v1["cases"]), "content_hash": v1["content_hash"]},
        "intake_v2": {"version": v2["dataset_version"], "case_count": len(v2["cases"]), "content_hash": v2["content_hash"], "parent": {"version": v2["parent_version"], "hash": v2["parent_trusted_hash"]}},
        "coverage": {
            "categories": sorted(categories),
            "modes": sorted(modes),
            "design_directions": ["safe_information", "image_centric", "balanced_sale"],
            "channels": ["smartstore", "coupang"],
            "scenarios": [
                "PASS", "COPY_REWORK_TO_PASS", "VISUAL_REWORK_TO_PASS", "PLAN_REWORK_TO_PASS",
                "IMAGE_REWORK_TO_PASS", "NEEDS_REVIEW", "FAIL_POLICY_BLOCK", "MAX_TWO_EXHAUSTED",
                "STALE_PROMOTION_EXPORT_BLOCKED",
            ],
        },
    }
    assert len(categories) == 5 and modes == {"owned_product_url", "photo_only", "manual"}
    assert_matches_golden(scenario="dataset-scenario-matrix", snapshot=matrix, update=_update_requested(request))


def test_lg12_fake_quality_gate_stale_promotion_and_export_authority_remain_blocked(
    client, auth_headers, db_session, tmp_path,
):
    """A historical PASS is not a reusable export authority after a child exists."""

    lineage, historical, _report = _pass_fixture(client, auth_headers, db_session, tmp_path)
    run = lineage["run"]
    promote_current_quality_page(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=historical.id,
    )
    current = _current_stale_successor(historical_page=historical, db_session=db_session)
    assert current.id != historical.id
    with pytest.raises(QualityPromotionGateError):
        require_current_quality_promotion(
            db_session, workspace_id=run.workspace_id, project_id=run.project_id,
            page_id=historical.id, channel="smartstore",
        )


def test_lg12_fake_quality_gate_comparator_is_semantic_and_drift_visible(tmp_path):
    """Orderless refs normalize; scene order and any semantic mutation do not."""

    baseline = {
        "target_channels": ["smartstore", "coupang"],
        "findings": [{"rule_id": "a"}, {"rule_id": "b"}],
        "sections": [{"id": "hero"}, {"id": "detail"}],
    }
    reordered = {
        "target_channels": ["coupang", "smartstore"],
        "findings": [{"rule_id": "b"}, {"rule_id": "a"}],
        "sections": [{"id": "hero"}, {"id": "detail"}],
    }
    assert normalize_lg12_semantics(baseline) == normalize_lg12_semantics(reordered)
    assert normalize_lg12_semantics({"id": "lg12-critical:" + "a" * 32, "artifact_id": "page-plan:" + "b" * 24}) == normalize_lg12_semantics({"id": "lg12-critical:" + "c" * 32, "artifact_id": "page-plan:" + "d" * 24})
    drifted = deepcopy(reordered)
    drifted["sections"].reverse()
    assert normalize_lg12_semantics(baseline) != normalize_lg12_semantics(drifted)


def test_lg12_fake_quality_gate_comparator_detects_quality_lineage_artifact_and_promotion_drift():
    """Every operational Golden signal fails with a path-specific semantic diff."""

    expected = {
        "quality": {"score": 100, "status": "complete", "routing_code": "PASS"},
        "lineage": {"source": {"version": 1, "type": "ProductSourceSnapshotVersion"}},
        "artifact_sha256": "a" * 64,
        "promotion_export_readiness": "ready",
    }
    mutations = {
        "score": ("quality.score", {**expected, "quality": {**expected["quality"], "score": 68}}),
        "status": ("quality.status", {**expected, "quality": {**expected["quality"], "status": "blocked"}}),
        "route": ("quality.routing_code", {**expected, "quality": {**expected["quality"], "routing_code": "COPY_REWORK"}}),
        "lineage": ("lineage.source.version", {**expected, "lineage": {"source": {"version": 2, "type": "ProductSourceSnapshotVersion"}}}),
        "provider_sha": ("artifact_sha256", {**expected, "artifact_sha256": "b" * 64}),
        "promotion": ("promotion_export_readiness", {**expected, "promotion_export_readiness": "blocked"}),
    }
    for expected_path, actual in mutations.values():
        difference = semantic_difference(expected, actual)
        assert difference is not None and expected_path in difference
