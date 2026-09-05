"""TASK-12.8 deterministic final Quality Bar aggregation."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from src.schemas.lg12_quality_report import (
    QUALITY_DOMAIN_IDS,
    QualityAssessmentContractError,
    normalize_quality_assessment_report,
)
from src.services.quality_assessment_service import (
    create_quality_assessment_report,
    create_quality_threshold_profile,
    evaluate_factual_rights_policy_domain,
    evaluate_image_identity_quality_domain,
)
from src.services.quality_bar_service import (
    QualityBarContractError,
    _require_domain_bundle,
    aggregate_quality_bar,
)
from src.db.models import AgentRun, CommerceCreativeMasterVersion, DetailPageVersion
from test_lg12_fact_rights_quality import _setup as _setup_factual
from test_lg12_image_identity_quality import _setup as _setup_image
from test_lg12_quality_report_contract import _finding, _profile_payload, _report_payload, _setup
from test_lg5_image_generation_subgraph import auth_headers as _lg5_auth_headers


_VERSIONS = {
    "factual_rights_policy": "lg12-factual-rights-policy-v1",
    "image_identity_quality": "lg12-image-identity-quality-v1",
    "korean_copy_readability": "lg12-korean-copy-readability-v2",
    "layout_typography_brand_flow": "lg12-layout-typography-brand-flow-v2",
    "channel_preview_export_parity": "lg12-channel-preview-export-parity-v1",
}


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


def _persist_report(
    db_session, run, page, manifest_hash, master, profile, *, report_id=None,
    report_version=1, overall=90, scores=None, statuses=None, findings=None,
    criticals=None, human_rubrics=None,
):
    payload = _report_payload(
        run, page, manifest_hash, master, profile, report_id=report_id,
        report_version=report_version, findings=findings, criticals=criticals,
    )
    payload["overall_score"] = overall
    for domain in payload["domain_scores"]:
        domain_id = domain["domain_id"]
        domain["evaluator_version"] = _VERSIONS[domain_id]
        domain["score"] = (scores or {}).get(domain_id, 90)
        domain["status"] = (statuses or {}).get(domain_id, "complete")
        if domain_id in (human_rubrics or {}):
            domain["human_rubric"] = (human_rubrics or {})[domain_id]
    row = create_quality_assessment_report(db_session, payload=payload)
    db_session.commit()
    return row


def _ref(row):
    return {"id": row.id, "version": row.version, "hash": row.canonical_hash}


def _setup_report(db_session, client, auth_headers, tmp_path, **kwargs):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    return _persist_report(db_session, run, page, manifest_hash, master, profile, **kwargs), profile


def _persist_actual_blocked_domain(db_session, run, master, page, manifest_hash, profile, evaluator):
    """Persist one real evaluator result alongside the other frozen domains."""
    payload = _report_payload(run, page, manifest_hash, master, profile)
    payload["overall_score"] = 100
    # The evaluator must receive the exact report that will persist its result;
    # a domain from a separately constructed sibling report is not reusable.
    actual_result = evaluator(db_session, report_payload=payload)
    actual_domain = dict(actual_result["domain"])
    for domain in payload["domain_scores"]:
        domain["evaluator_version"] = _VERSIONS[domain["domain_id"]]
        if domain["domain_id"] == actual_domain["domain_id"]:
            domain.clear()
            domain.update(actual_domain)
    payload["critical_violations"] = list(actual_result["critical_violations"])
    payload["routing_code"] = {
        "factual_rights_policy": "BLOCKED_POLICY",
        "image_identity_quality": "IMAGE_REWORK",
    }[actual_domain["domain_id"]]
    row = create_quality_assessment_report(db_session, payload=payload)
    db_session.commit()
    return row, actual_result


def test_pass_boundaries_and_determinism_are_frozen_report_projections(client, db_session, auth_headers, tmp_path):
    row, _profile = _setup_report(db_session, client, auth_headers, tmp_path, overall=85, scores={domain: 70 for domain in QUALITY_DOMAIN_IDS})
    first = aggregate_quality_bar(db_session, report_ref=_ref(row))
    second = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert first["verdict"] == "PASS"
    assert first["overall_score"] == 85
    assert all(first["per_domain_threshold_result"].values())
    assert first["canonical_hash"] == second["canonical_hash"]
    assert first["routing_code"] == "PASS"
    assert {item["id"].rsplit(":", 1)[-1] for item in first["domain_result_refs"]} == QUALITY_DOMAIN_IDS
    assert not first["blocking_reasons"] and not first["rework_targets"]


@pytest.mark.parametrize(
    ("overall", "scores", "expected"),
    [
        (84.99, None, "overall_below_threshold"),
        (95, {"channel_preview_export_parity": 69.99}, "domain_below_threshold"),
    ],
)
def test_threshold_failures_are_not_needs_review(client, db_session, auth_headers, tmp_path, overall, scores, expected):
    row, _profile = _setup_report(db_session, client, auth_headers, tmp_path, overall=overall, scores=scores)
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["verdict"] == "FAIL"
    assert expected in {item["code"] for item in result["blocking_reasons"]}


def test_critical_hard_blocker_and_same_root_cause_dedupe(client, db_session, auth_headers, tmp_path):
    finding = _finding("finding:logo", severity="critical", domain="factual_rights_policy")
    duplicate = deepcopy(finding); duplicate["finding_id"] = "finding:logo-image"; duplicate["domain"] = "image_identity_quality"
    row, _profile = _setup_report(db_session, client, auth_headers, tmp_path, overall=100, findings=[finding, duplicate])
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["verdict"] == "FAIL"
    assert result["critical_count"] == 1
    assert {item["code"] for item in result["blocking_reasons"]} == {"critical_violation_present"}


def test_different_critical_root_causes_remain_separate(client, db_session, auth_headers, tmp_path):
    first = _finding("finding:first", severity="critical", domain="factual_rights_policy")
    second = _finding("finding:second", severity="critical", domain="image_identity_quality")
    second["rule_id"] = "rule:distinct-root-cause"
    row, _profile = _setup_report(db_session, client, auth_headers, tmp_path, overall=100, findings=[first, second])
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["verdict"] == "FAIL"
    assert result["critical_count"] == 2


def test_actual_factual_blocked_evaluator_result_aggregates_to_fail(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup_factual(
        db_session, client, auth_headers, tmp_path, confirmed=(),
        sections=[{"section_id": "hero", "title": "최저가 상품", "copy_ref": {"fact_ids": []}}],
    )
    row, actual = _persist_actual_blocked_domain(
        db_session, run, master, page, manifest_hash, profile,
        evaluate_factual_rights_policy_domain,
    )
    assert actual["domain"]["status"] == "blocked" and actual["domain"]["critical_count"] > 0
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["verdict"] == "FAIL" and result["routing_code"] == "BLOCKED_POLICY"


def test_actual_image_blocked_evaluator_result_aggregates_to_fail(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile, _asset = _setup_image(
        db_session, client, auth_headers, tmp_path, identity_status="blocked",
    )
    row, actual = _persist_actual_blocked_domain(
        db_session, run, master, page, manifest_hash, profile,
        evaluate_image_identity_quality_domain,
    )
    assert actual["domain"]["status"] == "blocked" and actual["domain"]["critical_count"] > 0
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["verdict"] == "FAIL" and result["routing_code"] == "IMAGE_REWORK"


@pytest.mark.parametrize("status", ["needs_review", "not_evaluable"])
def test_unevaluable_domain_precedes_threshold_failure(client, db_session, auth_headers, tmp_path, status):
    row, _profile = _setup_report(
        db_session, client, auth_headers, tmp_path, overall=100,
        statuses={"image_identity_quality": status}, scores={"image_identity_quality": 100},
    )
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["verdict"] == "NEEDS_REVIEW"
    assert result["evaluability_state"] == "needs_review"
    assert result["blocking_reasons"][0]["code"] in {"domain_needs_review", "domain_not_evaluable"}


def test_pending_human_rubric_is_needs_review(client, db_session, auth_headers, tmp_path):
    row, _profile = _setup_report(
        db_session, client, auth_headers, tmp_path,
        human_rubrics={"korean_copy_readability": {"status": "pending"}},
    )
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["verdict"] == "NEEDS_REVIEW"
    assert {item["code"] for item in result["blocking_reasons"]} == {"human_review_pending"}


def test_missing_or_incompatible_frozen_domain_input_fails_closed(client, db_session, auth_headers, tmp_path):
    row, _profile = _setup_report(db_session, client, auth_headers, tmp_path)
    tampered = deepcopy(row.report_json)
    tampered["domain_scores"].pop()
    row.report_json = tampered
    with pytest.raises(QualityBarContractError):
        aggregate_quality_bar(db_session, report_ref=_ref(row))


def test_profile_and_report_reference_injection_are_rejected(client, db_session, auth_headers, tmp_path):
    row, _profile = _setup_report(db_session, client, auth_headers, tmp_path)
    bad = _ref(row); bad["hash"] = "0" * 64
    with pytest.raises(QualityBarContractError):
        aggregate_quality_bar(db_session, report_ref=bad)
    with pytest.raises(QualityAssessmentContractError):
        aggregate_quality_bar(db_session, report_ref={"id": row.id, "version": row.version, "hash": row.canonical_hash, "type": "bad"})


def test_domain_results_are_bound_to_one_exact_report_before_aggregation(client, db_session, auth_headers, tmp_path):
    """A valid result from Report A is never reusable by sibling Report B."""
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    report_a = _persist_report(db_session, run, page, manifest_hash, master, profile, overall=90)
    payload_b = _report_payload(run, page, manifest_hash, master, profile)
    for domain in payload_b["domain_scores"]:
        domain["evaluator_version"] = _VERSIONS[domain["domain_id"]]
        domain["score"] = 90

    source_domain = next(item for item in report_a.report_json["domain_scores"] if item["domain_id"] == "factual_rights_policy")
    valid_b_domain = next(
        item for item in normalize_quality_assessment_report(payload_b)["domain_scores"]
        if item["domain_id"] == "factual_rights_policy"
    )
    # Same frozen target and evaluator semantics have distinct immutable
    # domain identity because the parent report identity is part of its hash.
    assert valid_b_domain["evaluation_hash"] != source_domain["evaluation_hash"]
    injected = next(item for item in payload_b["domain_scores"] if item["domain_id"] == "factual_rights_policy")
    injected.clear()
    injected.update(deepcopy(source_domain))

    # The substituted result is byte-for-byte the valid immutable domain from
    # Report A.  The sole defect is its parent report binding.
    assert injected["evaluation_hash"] == source_domain["evaluation_hash"]
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(payload_b)


@pytest.mark.parametrize(
    ("field", "value"),
    [("version", 2), ("hash", "0" * 64)],
)
def test_domain_report_ref_requires_exact_id_version_and_non_circular_identity_hash(
    client, db_session, auth_headers, tmp_path, field, value,
):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    payload = _report_payload(run, page, manifest_hash, master, profile)
    domain = payload["domain_scores"][0]
    domain["report_ref"][field] = value
    domain.pop("evaluation_hash", None)
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(payload)


def test_quality_bar_rejects_one_cross_report_domain_even_with_the_same_page_run_and_manifest(
    client, db_session, auth_headers, tmp_path,
):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    report_a = _persist_report(db_session, run, page, manifest_hash, master, profile, overall=90)
    report_b = _persist_report(db_session, run, page, manifest_hash, master, profile, overall=90)
    assert aggregate_quality_bar(db_session, report_ref=_ref(report_b))["verdict"] == "PASS"

    injected = deepcopy(report_b.report_json)
    factual_a = next(item for item in report_a.report_json["domain_scores"] if item["domain_id"] == "factual_rights_policy")
    for index, domain in enumerate(injected["domain_scores"]):
        if domain["domain_id"] == "factual_rights_policy":
            injected["domain_scores"][index] = deepcopy(factual_a)
            break
    with pytest.raises(QualityBarContractError):
        _require_domain_bundle(injected)

    # Exercise the public aggregate's persisted-input boundary as well.  This
    # is intentionally not flushed: immutable DB rows are never rewritten.
    report_b.report_json = injected
    with db_session.no_autoflush:
        with pytest.raises(QualityBarContractError):
            aggregate_quality_bar(db_session, report_ref=_ref(report_b))
    db_session.rollback()


def test_report_successor_version_cannot_reuse_prior_version_domains(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    report_id = str(uuid4())
    v1 = _report_payload(run, page, manifest_hash, master, profile, report_id=report_id, report_version=1)
    normalized_v1 = normalize_quality_assessment_report(v1)
    v2 = _report_payload(run, page, manifest_hash, master, profile, report_id=report_id, report_version=2)
    v2["domain_scores"] = deepcopy(normalized_v1["domain_scores"])
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(v2)


def test_bundle_version_and_semantic_score_change_change_result_identity(client, db_session, auth_headers, tmp_path):
    first, profile = _setup_report(db_session, client, auth_headers, tmp_path, overall=90)
    first_result = aggregate_quality_bar(db_session, report_ref=_ref(first))
    # A separately persisted report with a changed score has a distinct frozen
    # report and therefore a distinct immutable Quality Bar identity.  Reuse
    # the frozen page/run instead of attempting a second overlapping mock
    # generation in this test transaction.
    payload = first.report_json
    run = db_session.query(AgentRun).filter_by(id=first.creator_run_id).one()
    master = db_session.query(CommerceCreativeMasterVersion).filter_by(
        id=payload["input_lineage"]["master_ref"]["id"],
    ).one()
    page = db_session.query(DetailPageVersion).filter_by(
        id=payload["target_artifact"]["id"],
    ).one()
    manifest_hash = payload["approved_asset_manifest_hash"]
    second = _persist_report(db_session, run, page, manifest_hash, master, profile, overall=91)
    second_result = aggregate_quality_bar(db_session, report_ref=_ref(second))
    assert first_result["canonical_hash"] != second_result["canonical_hash"]


def test_profile_successor_changes_the_frozen_quality_bar_identity(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    first = _persist_report(db_session, run, page, manifest_hash, master, profile, overall=90)
    successor = create_quality_threshold_profile(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        parent_profile_id=profile.id,
        payload=_profile_payload(str(uuid4()), version=2, parent=profile, overall=86),
    )
    db_session.commit()
    second = _persist_report(db_session, run, page, manifest_hash, master, successor, overall=90)
    first_result = aggregate_quality_bar(db_session, report_ref=_ref(first))
    second_result = aggregate_quality_bar(db_session, report_ref=_ref(second))
    assert first_result["threshold_profile_ref"] != second_result["threshold_profile_ref"]
    assert first_result["canonical_hash"] != second_result["canonical_hash"]


@pytest.mark.parametrize(
    ("domain_id", "expected_route"),
    [
        ("factual_rights_policy", "BLOCKED_POLICY"),
        ("image_identity_quality", "IMAGE_REWORK"),
    ],
)
def test_real_blocked_critical_domain_status_is_a_normal_fail_input(
    client, db_session, auth_headers, tmp_path, domain_id, expected_route,
):
    finding = _finding(f"finding:{domain_id}:critical", severity="critical", domain=domain_id)
    row, _profile = _setup_report(
        db_session, client, auth_headers, tmp_path, overall=100,
        statuses={domain_id: "blocked"}, findings=[finding],
    )
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["verdict"] == "FAIL"
    assert result["routing_code"] == expected_route
    assert result["primary_blocking_domain"] == domain_id


def test_review_verdict_does_not_hide_a_higher_priority_blocked_route(client, db_session, auth_headers, tmp_path):
    finding = _finding("finding:factual:critical", severity="critical", domain="factual_rights_policy")
    row, _profile = _setup_report(
        db_session, client, auth_headers, tmp_path, overall=100,
        statuses={"factual_rights_policy": "blocked", "korean_copy_readability": "needs_review"},
        findings=[finding],
    )
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["verdict"] == "NEEDS_REVIEW"
    assert result["routing_code"] == "BLOCKED_POLICY"
    assert result["primary_blocking_domain"] == "factual_rights_policy"


def test_blocked_domain_without_critical_evidence_is_rejected(client, db_session, auth_headers, tmp_path):
    row, _profile = _setup_report(
        db_session, client, auth_headers, tmp_path,
        statuses={"factual_rights_policy": "blocked"},
    )
    with pytest.raises(QualityBarContractError):
        aggregate_quality_bar(db_session, report_ref=_ref(row))


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("frozen_target_ref", {"id": "other-page", "version": "v999", "hash": "0" * 64, "type": "DetailPageVersion"}),
        ("approved_asset_manifest_hash", "0" * 64),
        ("workspace_id", "other-workspace"),
        ("project_id", "other-project"),
        ("creator_run_id", "other-run"),
    ],
)
def test_each_domain_is_pinned_to_the_exact_root_report_target(
    client, db_session, auth_headers, tmp_path, field, replacement,
):
    row, _profile = _setup_report(db_session, client, auth_headers, tmp_path)
    payload = deepcopy(row.report_json)
    image_domain = next(item for item in payload["domain_scores"] if item["domain_id"] == "image_identity_quality")
    image_domain[field] = replacement
    image_domain.pop("evaluation_hash", None)
    payload.pop("canonical_hash", None)
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(payload)


@pytest.mark.parametrize("target_key", ["id", "version", "hash"])
def test_domain_target_id_version_and_hash_each_require_exact_parity(
    client, db_session, auth_headers, tmp_path, target_key,
):
    row, _profile = _setup_report(db_session, client, auth_headers, tmp_path)
    payload = deepcopy(row.report_json)
    domain = next(item for item in payload["domain_scores"] if item["domain_id"] == "image_identity_quality")
    domain["frozen_target_ref"][target_key] = "wrong-target-identity" if target_key != "hash" else "0" * 64
    domain.pop("evaluation_hash", None)
    payload.pop("canonical_hash", None)
    with pytest.raises(QualityAssessmentContractError):
        normalize_quality_assessment_report(payload)


@pytest.mark.parametrize(
    ("scores", "statuses", "findings", "expected_route", "expected_domain"),
    [
        ({"factual_rights_policy": 69}, None, None, "BLOCKED_POLICY", "factual_rights_policy"),
        ({"image_identity_quality": 69}, None, None, "IMAGE_REWORK", "image_identity_quality"),
        ({"korean_copy_readability": 69}, None, None, "COPY_REWORK", "korean_copy_readability"),
        ({"layout_typography_brand_flow": 69}, None, None, "VISUAL_REWORK", "layout_typography_brand_flow"),
        ({"channel_preview_export_parity": 69}, None, None, "VISUAL_REWORK", "channel_preview_export_parity"),
        (None, {"channel_preview_export_parity": "needs_review"}, None, "SELLER_REVIEW", None),
    ],
)
def test_routing_code_is_deterministic_from_the_existing_taxonomy(
    client, db_session, auth_headers, tmp_path, scores, statuses, findings, expected_route, expected_domain,
):
    row, _profile = _setup_report(
        db_session, client, auth_headers, tmp_path,
        scores=scores, statuses=statuses, findings=findings,
    )
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["routing_code"] == expected_route
    assert result["primary_blocking_domain"] == expected_domain


def test_routing_priority_and_rework_order_are_stable(client, db_session, auth_headers, tmp_path):
    factual = _finding("finding:factual", severity="critical", domain="factual_rights_policy")
    image = _finding("finding:image", severity="critical", domain="image_identity_quality")
    image["rule_id"] = "rule:image-root"
    row, _profile = _setup_report(
        db_session, client, auth_headers, tmp_path, overall=100,
        statuses={"factual_rights_policy": "blocked", "image_identity_quality": "blocked"},
        findings=[image, factual],
    )
    result = aggregate_quality_bar(db_session, report_ref=_ref(row))
    assert result["routing_code"] == "BLOCKED_POLICY"
    assert [item["domain"] for item in result["rework_targets"]][:2] == [
        "factual_rights_policy", "image_identity_quality",
    ]
