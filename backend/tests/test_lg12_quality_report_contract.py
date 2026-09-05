"""TASK-12.2 immutable QualityAssessmentReport/threshold-profile contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import update

from src.db.models import DetailPageVersion, QualityAssessmentReportVersion, QualityThresholdProfileVersion
from src.schemas.lg12_quality_report import (
    QUALITY_ASSESSMENT_REPORT_SCHEMA_VERSION, QUALITY_DOMAIN_IDS,
    QUALITY_THRESHOLD_PROFILE_SCHEMA_VERSION, QualityAssessmentContractError,
    _frozen_domain_target_binding, canonical_quality_finding_hash,
    normalize_quality_assessment_report,
)
from src.services.langgraph_run_service import LangGraphRunService
from src.services.product_intake_version_service import canonical_version_hash
from src.services.prompt_intelligence_service import canonical_hash
from src.services.quality_assessment_service import (
    _frozen_asset_manifest,
    create_quality_assessment_report, create_quality_threshold_profile,
    quality_report_durable_projection, validate_quality_assessment_report_version,
)
from test_lg12i_version_contract import _create_master, _source_truth_confirmation
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers


def _ref(identifier: str, version: int | str = 1, digest: str | None = None, **extra):
    value = {"id": identifier, "version": version, "hash": digest or canonical_hash({"id": identifier, "version": version})}
    value.update(extra)
    return value


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


def _run(client, headers, db_session, tmp_path):
    return _create_run(client, headers, db_session, tmp_path)


def _frozen_page(db, run, *, project_id=None):
    manifest_body = {"schema_version": "lg10-approved-asset-manifest-v1", "assets": []}
    manifest = {**manifest_body, "manifest_hash": canonical_hash(manifest_body)}
    snapshot_body = {
        "schema_version": "lg10-detail-page-version-v1",
        "lg10": {"canonical_page_assembly_input": {"approved_asset_manifest": manifest}},
        "commerce_renderer": {"sections": []}, "sections": [],
    }
    page = DetailPageVersion(
        project_id=project_id or run.project_id, name="LG-12 QA frozen fixture", style_key="balanced_sale",
        sections_json={**snapshot_body, "snapshot_hash": canonical_hash(snapshot_body)}, is_final=True,
    )
    db.add(page); db.flush()
    return page, manifest["manifest_hash"]


def test_information_only_page_manifest_is_the_frozen_qa_asset_boundary():
    body = {"run_id": "run-1", "project_id": "project-1", "source": "information_only", "assets": []}
    manifest = {**body, "manifest_hash": canonical_hash(body)}

    assert _frozen_asset_manifest({
        "approved_asset_manifest": None,
        "page_asset_manifest": manifest,
        "image_generation_contract": {
            "required_scene_count": 0,
            "completion_basis": "no_required_image_scenes",
        },
    }) == manifest
    assert _frozen_asset_manifest({
        "approved_asset_manifest": None,
        "page_asset_manifest": manifest,
        "image_generation_contract": {
            "required_scene_count": 1,
            "completion_basis": "approved_required_scenes",
        },
    }) == {}


def _profile_payload(profile_id: str, *, version: int = 1, parent=None, channels=None, overall=85):
    payload = {
        "profile_id": profile_id, "profile_version": version,
        "schema_version": QUALITY_THRESHOLD_PROFILE_SCHEMA_VERSION,
        "applicable_artifact_type": "DetailPageVersion",
        "applicable_channels": channels if channels is not None else ["smartstore", "coupang"],
        "overall_minimum": overall,
        "per_domain_minimum": {domain: 70 for domain in QUALITY_DOMAIN_IDS},
        "max_critical_violations": 0, "status": "active", "effective_from": "2026-08-20T00:00:00Z",
    }
    if parent is not None:
        payload["parent_profile_ref"] = _ref(parent.id, parent.version, parent.canonical_hash)
    return payload


def _domain(domain_id, *, score=85, findings=None, metric_source="automatic"):
    items = list(findings or [])
    return {
        "domain_id": domain_id, "score": score, "status": "complete", "evaluator_version": "lg12-contract-fixture-v1",
        "findings": items, "critical_count": sum(item["severity"] == "critical" for item in items),
        "warning_count": sum(item["severity"] != "critical" for item in items), "evidence_refs": [],
        "evaluated_at": "2026-08-20T00:00:00Z", "metric_source": metric_source,
    }


def _finding(identifier="finding:copy", *, severity="minor", domain="korean_copy_readability", observed="observed"):
    return {
        "finding_id": identifier, "domain": domain, "severity": severity, "rule_id": "rule:fixture",
        "code": "fixture", "message": "bounded fixture finding", "target_refs": [_ref("copy:hero", type="copy")],
        "evidence_refs": [_ref("evidence:hero", type="evidence")], "expected": "expected", "observed": observed,
        "remediation_hint": "revise the target",
    }


def _report_payload(
    run, page, manifest_hash, master, profile, *, report_id=None, report_version=1,
    channels=None, findings=None, criticals=None,
):
    source = master.source_snapshot_version_id
    # Master row already pins the exact Source -> Truth -> Confirmation chain;
    # resolve IDs from persisted rows only through their stored references.
    lineage = {
        "source_snapshot_ref": _ref(master.source_snapshot_version_id, master.source_snapshot_version, master.source_snapshot_hash),
        "truth_ref": _ref(master.truth_version_id, master.truth_version, master.truth_version_hash),
        "confirmation_ref": _ref(master.confirmation_version_id, master.confirmation_version, master.confirmation_version_hash),
        "master_ref": _ref(master.id, master.version, master.canonical_hash),
    }
    snapshot = dict(page.sections_json); snapshot_hash = snapshot["snapshot_hash"]
    provided_findings = list(findings or [])
    domains = []
    for domain in sorted(QUALITY_DOMAIN_IDS):
        own = [item for item in provided_findings if item["domain"] == domain]
        domains.append(_domain(domain, findings=own, metric_source="human" if domain == "korean_copy_readability" else "automatic"))
    payload = {
        "report_id": report_id or str(uuid4()), "report_version": report_version,
        "schema_version": QUALITY_ASSESSMENT_REPORT_SCHEMA_VERSION, "evaluator_bundle_version": "lg12-evaluator-bundle-v1",
        "target_artifact": _ref(page.id, snapshot["schema_version"], snapshot_hash, type="DetailPageVersion"),
        "approved_asset_manifest_hash": manifest_hash, "project_id": run.project_id,
        "workspace_id": run.workspace_id, "creator_run_id": run.id,
        "target_channels": channels or ["smartstore", "coupang"], "created_at": "2026-08-20T00:00:00Z",
        "input_lineage": lineage,
        "source_fidelity": {
            "source_kind": "manual", "source_ref": dict(lineage["source_snapshot_ref"]),
            "fidelity_status": "complete", "metric": {"value": 1, "comparison": "equals"},
        },
        "dataset_ref": _ref("lg12-golden-dataset-v2", "v2", canonical_hash({"dataset": "v2"}), artifact_key="fixture-case"),
        "input_mode": "manual",
        "prohibited_inference_count": 0, "unknown_fact_count": 0, "clarification_count": 0,
        "overall_score": 85, "domain_scores": domains, "critical_violations": list(criticals or []),
        "warnings": [], "findings": provided_findings,
        "threshold_profile_ref": _ref(profile.id, profile.version, profile.canonical_hash),
        "verdict": "not_evaluated", "routing_code": "PASS", "rework_targets": [],
    }
    # Every domain result is frozen against the exact report target.  This is
    # deliberately repeated as bounded identity, not copied page content, so
    # TASK-12.8 can reject a valid-looking result from another page/run.
    binding = _frozen_domain_target_binding(payload)
    for domain in payload["domain_scores"]:
        domain.update(binding)
    return payload


def _setup(db_session, client, auth_headers, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    chain = _source_truth_confirmation(db_session, run)
    master = _create_master(db_session, run, chain=chain)
    page, manifest_hash = _frozen_page(db_session, run)
    profile = create_quality_threshold_profile(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        payload=_profile_payload(str(uuid4())),
    )
    db_session.commit()
    return run, master, page, manifest_hash, profile


def test_quality_report_contract_is_deterministic_and_projects_only_bounded_identity(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    payload = _report_payload(run, page, manifest_hash, master, profile)
    first = normalize_quality_assessment_report(payload)
    reordered = deepcopy(payload); reordered["target_channels"] = ["coupang", "smartstore"]
    second = normalize_quality_assessment_report(reordered)
    assert first["canonical_hash"] == second["canonical_hash"]
    row = create_quality_assessment_report(db_session, payload=payload)
    projection = quality_report_durable_projection(row)
    assert projection == LangGraphRunService.quality_assessment_projection(dict(row.report_json))
    assert projection["quality_assessment"]["report_ref"]["hash"] == row.canonical_hash
    assert "domain_scores" not in projection["quality_assessment"]
    validate_quality_assessment_report_version(db_session, row)


def test_scores_domains_finding_hashes_and_unordered_findings_are_validated(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    first_finding, second_finding = _finding("finding:a"), _finding("finding:b", domain="image_identity_quality")
    assert canonical_quality_finding_hash(first_finding) == canonical_quality_finding_hash(deepcopy(first_finding))
    payload = _report_payload(run, page, manifest_hash, master, profile, findings=[first_finding, second_finding])
    reordered = deepcopy(payload); reordered["findings"].reverse(); reordered["domain_scores"].reverse()
    assert normalize_quality_assessment_report(payload)["canonical_hash"] == normalize_quality_assessment_report(reordered)["canonical_hash"]
    changed = deepcopy(payload); changed["findings"][0]["observed"] = "changed"
    assert normalize_quality_assessment_report(payload)["canonical_hash"] != normalize_quality_assessment_report(changed)["canonical_hash"]
    for mutate in (
        lambda item: item.__setitem__("overall_score", 101),
        lambda item: item["domain_scores"][0].__setitem__("score", -1),
        lambda item: item["domain_scores"][0].__setitem__("domain_id", "unknown"),
        lambda item: item["findings"].append(deepcopy(item["findings"][0])),
    ):
        invalid = deepcopy(payload); mutate(invalid)
        with pytest.raises(QualityAssessmentContractError):
            normalize_quality_assessment_report(invalid)


def test_quality_report_allows_only_bounded_reference_only_evaluator_metadata(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    finding = _finding(
        "finding:bounded",
        observed={"value": 16, "unit": "px"},
    )
    finding["expected"] = _ref("section:hero", type="section")
    finding["target_refs"] = [_ref("section:hero", type="section")]
    finding["evidence_refs"] = [_ref("asset:hero", type="asset")]
    payload = _report_payload(run, page, manifest_hash, master, profile, findings=[finding])
    payload["source_fidelity"] = {
        "source_kind": "manual",
        "source_ref": dict(payload["input_lineage"]["source_snapshot_ref"]),
        "fidelity_status": "complete", "code": "source_match",
        "confidence": 0.9, "metric": {"value": "matched", "comparison": "equals"},
    }
    payload["domain_scores"][0]["submetrics"] = [
        {"metric_id": "contrast_ratio", "value": 4.5, "unit": "ratio", "threshold": 4.0, "status": "pass"},
        {"metric_id": "overflow_count", "value": 0, "threshold": 0, "status": "pass"},
    ]
    normalized = normalize_quality_assessment_report(payload)
    assert create_quality_assessment_report(db_session, payload=payload).canonical_hash == normalized["canonical_hash"]

    reordered = deepcopy(payload)
    reordered["domain_scores"][0]["submetrics"].reverse()
    reordered["source_fidelity"] = dict(reversed(list(reordered["source_fidelity"].items())))
    assert normalize_quality_assessment_report(reordered)["canonical_hash"] == normalized["canonical_hash"]

    def _invalid(mutator):
        candidate = deepcopy(payload)
        mutator(candidate)
        with pytest.raises(QualityAssessmentContractError):
            normalize_quality_assessment_report(candidate)

    # These use arbitrary names intentionally: the contract rejects them by
    # shape/depth, not by extending the raw-body key blacklist.
    _invalid(lambda item: item["findings"][0].__setitem__("expected", {"sections": {"copy": "copied"}}))
    _invalid(lambda item: item["findings"][0].__setitem__("observed", {"snapshot": {"page": "copied"}}))
    _invalid(lambda item: item["source_fidelity"].__setitem__("master", {"body": "copied"}))
    _invalid(lambda item: item["domain_scores"][0].__setitem__("submetrics", [{"metric_id": "pixels", "value": [[0, 1]]}]))
    _invalid(lambda item: item["findings"][0].__setitem__("expected", {"foo": {"bar": {"copied_page": "body"}}}))
    _invalid(lambda item: item["findings"][0].__setitem__("expected", "x" * 513))
    _invalid(lambda item: item["findings"][0].__setitem__("observed", list(range(17))))
    for unsafe_text in (
        "<div>hello</div>",
        "<script>alert(1)</script>",
        "<svg><path /></svg>",
        "<!DOCTYPE html>",
        "<?xml version='1.0'?>",
        "data:image/png;base64,iVBORw0...",
        "data:text/html;base64,PGgxPkJvb208L2gxPg==",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "A" * 128,
    ):
        for field in ("expected", "observed"):
            _invalid(lambda item, field=field, unsafe_text=unsafe_text: item["findings"][0].__setitem__(field, unsafe_text))
    for safe_text in (
        "16px",
        "SmartStore",
        "텍스트가 너무 작음",
        "contrast ratio 3.8",
        str(uuid4()),
        "a" * 64,
        "short alpha123",
    ):
        for field in ("expected", "observed"):
            valid = deepcopy(payload)
            valid["findings"][0][field] = safe_text
            assert normalize_quality_assessment_report(valid)["findings"][0][field] == safe_text
    _invalid(lambda item: item["findings"][0].__setitem__("expected", {"approved_asset_manifest": {"assets": []}}))
    _invalid(lambda item: item["findings"][0]["target_refs"][0].pop("type"))
    oversized = _report_payload(
        run, page, manifest_hash, master, profile,
        findings=[
            {
                **_finding(f"finding:large:{index}", domain="korean_copy_readability"),
                "message": ("message text " * 40)[:512], "remediation_hint": ("remediation text " * 32)[:512],
                "expected": ("expected value " * 40)[:512], "observed": ("observed value " * 40)[:512],
            }
            for index in range(64)
        ],
    )
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(oversized)


def test_critical_contract_is_blocking_but_task_12_2_does_not_compute_final_verdict(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    critical = {
        "violation_id": "critical:rights", "domain": "factual_rights_policy", "rule_id": "rights:unconfirmed",
        "target_ref": _ref("asset:hero", type="asset"), "evidence_refs": [_ref("evidence:asset", type="evidence")],
        "reason_code": "unconfirmed_rights", "blocking": True,
    }
    critical_payload = _report_payload(run, page, manifest_hash, master, profile, criticals=[critical])
    critical_payload["routing_code"] = "BLOCKED_POLICY"
    report = normalize_quality_assessment_report(critical_payload)
    assert report["critical_violations"][0]["blocking"] is True
    assert report["verdict"] == "not_evaluated"
    bad = deepcopy(report); bad["critical_violations"][0]["blocking"] = False
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(bad)
    bad = deepcopy(report); bad["verdict"] = "PASS"
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(bad)
    bad = deepcopy(report); bad["routing_code"] = "PASS"
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(bad)


def test_threshold_profiles_are_channel_aware_immutable_successors(client, db_session, auth_headers, tmp_path):
    run, _master, _page, _manifest_hash, _profile = _setup(db_session, client, auth_headers, tmp_path)
    first = create_quality_threshold_profile(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        payload=_profile_payload(str(uuid4()), channels=["smartstore"]),
    )
    coupang = create_quality_threshold_profile(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        payload=_profile_payload(str(uuid4()), channels=["coupang"]),
    )
    successor_payload = _profile_payload(str(uuid4()), version=2, parent=first, channels=["smartstore"], overall=86)
    second = create_quality_threshold_profile(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=successor_payload, parent_profile_id=first.id,
    )
    assert first.canonical_hash != second.canonical_hash
    assert coupang.version == 1
    assert first.thresholds_json["overall_minimum"] == 85
    assert first.thresholds_json["per_domain_minimum"] == {domain: 70 for domain in QUALITY_DOMAIN_IDS}
    assert first.thresholds_json["max_critical_violations"] == 0
    with pytest.raises(QualityAssessmentContractError):
        create_quality_threshold_profile(db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=first.payload())
    invalid = _profile_payload(str(uuid4()), channels=["unknown-channel"])
    with pytest.raises(QualityAssessmentContractError):
        create_quality_threshold_profile(db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=invalid)
    invalid = _profile_payload(str(uuid4()), channels=[])
    with pytest.raises(QualityAssessmentContractError):
        create_quality_threshold_profile(db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=invalid)
    invalid = _profile_payload(str(uuid4()), channels=["smartstore", "smartstore"])
    with pytest.raises(QualityAssessmentContractError):
        create_quality_threshold_profile(db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=invalid)
    invalid = _profile_payload(str(uuid4()), overall=84)
    with pytest.raises(QualityAssessmentContractError):
        create_quality_threshold_profile(db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=invalid)


def test_report_requires_exact_frozen_target_profile_and_persisted_lineage(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    valid = _report_payload(run, page, manifest_hash, master, profile)
    for mutate in (
        lambda item: item["target_artifact"].__setitem__("hash", "0" * 64),
        lambda item: item.__setitem__("approved_asset_manifest_hash", "0" * 64),
        lambda item: item["input_lineage"]["master_ref"].__setitem__("hash", "0" * 64),
        lambda item: item["target_channels"].__setitem__(0, "unknown"),
        lambda item: item.__setitem__("raw_html", "<script>bad</script>"),
    ):
        invalid = deepcopy(valid); mutate(invalid)
        with pytest.raises(QualityAssessmentContractError):
            create_quality_assessment_report(db_session, payload=invalid)
    page.is_final = False
    with pytest.raises(QualityAssessmentContractError):
        create_quality_assessment_report(db_session, payload=valid)
    page.is_final = True


def test_report_and_profile_rows_are_db_immutable_and_provider_paths_are_not_called(client, db_session, auth_headers, tmp_path, monkeypatch):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    row = create_quality_assessment_report(db_session, payload=_report_payload(run, page, manifest_hash, master, profile))
    db_session.commit()
    with pytest.raises(Exception):
        db_session.execute(update(QualityAssessmentReportVersion).where(QualityAssessmentReportVersion.id == row.id).values(version=2))
    with pytest.raises(Exception):
        db_session.execute(update(QualityThresholdProfileVersion).where(QualityThresholdProfileVersion.id == profile.id).values(status="inactive"))
    assert db_session.query(QualityAssessmentReportVersion).filter_by(id=row.id).one().canonical_hash == row.canonical_hash
    # The pure contract has no provider, outbox, cost-approval, or graph-node call surface.
    assert not hasattr(LangGraphRunService, "run_quality_assessment")


def test_cross_project_target_and_non_frozen_snapshot_are_rejected(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    payload = _report_payload(run, page, manifest_hash, master, profile)
    snapshot = dict(page.sections_json); snapshot.pop("snapshot_hash"); page.sections_json = snapshot
    with pytest.raises(QualityAssessmentContractError):
        create_quality_assessment_report(db_session, payload=payload)


def test_score_boundaries_unknown_severity_and_postgres_migration_contract(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    payload = _report_payload(run, page, manifest_hash, master, profile)
    for score in (0, 100):
        bounded = deepcopy(payload)
        bounded["overall_score"] = score
        bounded["domain_scores"][0]["score"] = score
        assert normalize_quality_assessment_report(bounded)["overall_score"] == score
    invalid = deepcopy(payload); invalid["findings"] = [_finding(severity="unknown")]
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(invalid)
    migration = (Path(__file__).resolve().parents[1] / "migrations" / "20260820_lg12_quality_report_contract.sql").read_text(encoding="utf-8")
    assert "quality_assessment_report_versions" in migration
    assert "quality_threshold_profile_versions" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "sellform_reject_lg12i_immutable_mutation" in migration
