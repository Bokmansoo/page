"""TASK-12.8 deterministic aggregation of frozen LG-12 QA domain results.

This layer deliberately consumes an already persisted
``QualityAssessmentReportVersion``.  It never re-runs a domain evaluator and
does not create a mutable gate record: the returned Quality Bar result is a
canonical, immutable projection of that frozen report and its pinned profile.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import QualityAssessmentReportVersion, QualityThresholdProfileVersion
from src.schemas.lg12_quality_report import (
    QUALITY_DOMAIN_IDS,
    QualityAssessmentContractError,
    _quality_report_domain_parent_ref,
)
from src.services.prompt_intelligence_service import canonical_hash
from src.services.quality_assessment_service import (
    CHANNEL_PREVIEW_EXPORT_PARITY_EVALUATOR_VERSION,
    FACTUAL_RIGHTS_POLICY_EVALUATOR_VERSION,
    IMAGE_IDENTITY_QUALITY_EVALUATOR_VERSION,
    KOREAN_COPY_READABILITY_EVALUATOR_VERSION,
    LAYOUT_TYPOGRAPHY_BRAND_FLOW_EVALUATOR_VERSION,
    validate_quality_assessment_report_version,
    validate_quality_threshold_profile_version,
)


QUALITY_BAR_SCHEMA_VERSION = "lg12-quality-bar-v1"
# TASK-12.2 already pins this immutable report-level bundle label.  TASK-12.8
# adds the canonical per-domain version map below instead of introducing a
# second incompatible bundle identity.
QUALITY_BAR_EVALUATOR_BUNDLE_ID = "lg12-evaluator-bundle-v1"

_EXPECTED_EVALUATOR_VERSIONS = {
    "factual_rights_policy": FACTUAL_RIGHTS_POLICY_EVALUATOR_VERSION,
    "image_identity_quality": IMAGE_IDENTITY_QUALITY_EVALUATOR_VERSION,
    "korean_copy_readability": KOREAN_COPY_READABILITY_EVALUATOR_VERSION,
    "layout_typography_brand_flow": LAYOUT_TYPOGRAPHY_BRAND_FLOW_EVALUATOR_VERSION,
    "channel_preview_export_parity": CHANNEL_PREVIEW_EXPORT_PARITY_EVALUATOR_VERSION,
}
_EVALUABLE_STATUS = "complete"
_BLOCKED_STATUS = "blocked"
_REVIEW_STATUSES = frozenset({"needs_review", "not_evaluable"})
_DOMAIN_ROUTE_PRIORITY = (
    "factual_rights_policy",
    "image_identity_quality",
    "korean_copy_readability",
    "layout_typography_brand_flow",
    "channel_preview_export_parity",
)
_ROUTING_CODE_BY_DOMAIN = {
    "factual_rights_policy": "BLOCKED_POLICY",
    "image_identity_quality": "IMAGE_REWORK",
    "korean_copy_readability": "COPY_REWORK",
    # Both frozen layout/Brand Kit and channel-parity failures require the
    # existing visual assembly path. TASK-12.9 alone maps this decision to a
    # graph node; TASK-12.8 never executes it.
    "layout_typography_brand_flow": "VISUAL_REWORK",
    "channel_preview_export_parity": "VISUAL_REWORK",
}
_DOMAIN_PRIORITY_INDEX = {domain_id: index for index, domain_id in enumerate(_DOMAIN_ROUTE_PRIORITY)}


_ACTIONABLE_TARGET_TYPES_BY_DOMAIN = {
    # A page reference is useful for lineage, but never authorises a broad
    # rewrite.  The Quality-Bar must retain the narrowest frozen target that
    # the existing LG-11 path can validate again.
    "image_identity_quality": ("scene", "asset"),
    "korean_copy_readability": ("copy_field", "frozen_section"),
    "layout_typography_brand_flow": ("PagePlanVersion", "frozen_canvas_element", "frozen_section", "BrandKitVersion", "scene"),
    "channel_preview_export_parity": ("frozen_canvas_element", "frozen_section", "scene", "PagePlanVersion"),
}


class QualityBarContractError(QualityAssessmentContractError):
    """Raised when frozen QA inputs cannot safely be aggregated."""


def _typed_reference(*, identifier: str, version: int | str, digest: str, artifact_type: str) -> dict[str, Any]:
    return {"id": str(identifier), "version": version, "hash": str(digest), "type": artifact_type}


def _reference_identity(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(value.get("id") or ""), str(value.get("version") or ""), str(value.get("hash") or ""))


def _canonical_ref_list(value: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(item) for item in value), key=lambda item: (
        str(item.get("type") or ""), str(item.get("id") or ""),
        str(item.get("version") or ""), str(item.get("hash") or ""),
    ))


def _critical_root_key(*, rule_id: str, target_refs: list[Mapping[str, Any]], evidence_refs: list[Mapping[str, Any]]) -> str:
    """Only collapse the same frozen rule and exact frozen reference set.

    A similar-looking finding with a different rule or evidence remains a
    separate violation.  This is intentionally narrower than a heuristic
    semantic dedupe.
    """

    return canonical_hash({
        "rule_id": rule_id,
        "target_refs": _canonical_ref_list(target_refs),
        "evidence_refs": _canonical_ref_list(evidence_refs),
    })


def _require_report(db: Session, report_ref: Mapping[str, Any]) -> tuple[QualityAssessmentReportVersion, dict[str, Any]]:
    if not isinstance(report_ref, Mapping) or set(report_ref) != {"id", "version", "hash"}:
        raise QualityBarContractError("Quality Bar requires an exact persisted QA report ID/version/hash reference.")
    row = db.query(QualityAssessmentReportVersion).filter_by(id=str(report_ref["id"])).one_or_none()
    if row is None:
        raise QualityBarContractError("Quality Bar QA report is not persisted.")
    if _reference_identity(report_ref) != (str(row.id), str(row.version), str(row.canonical_hash)):
        raise QualityBarContractError("Quality Bar QA report reference does not match the persisted immutable report.")
    try:
        validate_quality_assessment_report_version(db, row)
    except QualityAssessmentContractError as exc:
        raise QualityBarContractError("Quality Bar QA report integrity or lineage is invalid.") from exc
    return row, deepcopy(dict(row.report_json or {}))


def _require_profile(db: Session, *, report: Mapping[str, Any], report_row: QualityAssessmentReportVersion) -> tuple[QualityThresholdProfileVersion, dict[str, Any]]:
    reference = dict(report["threshold_profile_ref"])
    profile = db.query(QualityThresholdProfileVersion).filter_by(
        id=reference["id"], workspace_id=report_row.workspace_id, project_id=report_row.project_id,
    ).one_or_none()
    if profile is None or _reference_identity(reference) != (str(profile.id), str(profile.version), str(profile.canonical_hash)):
        raise QualityBarContractError("Quality Bar threshold profile is not the report's exact persisted profile.")
    try:
        validate_quality_threshold_profile_version(db, profile)
    except QualityAssessmentContractError as exc:
        raise QualityBarContractError("Quality Bar threshold profile integrity is invalid.") from exc
    return profile, profile.payload()


def _require_domain_bundle(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    if report.get("evaluator_bundle_version") != QUALITY_BAR_EVALUATOR_BUNDLE_ID:
        raise QualityBarContractError("Quality Bar report evaluator bundle identity is incompatible.")
    domains = [dict(item) for item in list(report.get("domain_scores") or [])]
    ids = [item.get("domain_id") for item in domains]
    if len(domains) != len(QUALITY_DOMAIN_IDS) or set(ids) != QUALITY_DOMAIN_IDS or len(set(ids)) != len(ids):
        raise QualityBarContractError("Quality Bar requires each of the five frozen domain results exactly once.")
    by_id = {str(item["domain_id"]): item for item in domains}
    expected_report_ref = _quality_report_domain_parent_ref(report)
    expected_target = dict(report["target_artifact"])
    expected_scope = {
        "approved_asset_manifest_hash": report["approved_asset_manifest_hash"],
        "workspace_id": report["workspace_id"], "project_id": report["project_id"],
        "creator_run_id": report["creator_run_id"],
    }
    for domain_id, expected_version in _EXPECTED_EVALUATOR_VERSIONS.items():
        item = by_id[domain_id]
        if item.get("evaluator_version") != expected_version:
            raise QualityBarContractError("Quality Bar evaluator bundle is incompatible with the frozen domain result.")
        if not str(item.get("evaluation_hash") or ""):
            raise QualityBarContractError("Quality Bar domain result is missing its immutable result hash.")
        if dict(item.get("report_ref") or {}) != expected_report_ref:
            raise QualityBarContractError(
                "Quality Bar domain result does not match the persisted report's exact immutable identity."
            )
        if dict(item.get("frozen_target_ref") or {}) != expected_target or any(
            item.get(key) != value for key, value in expected_scope.items()
        ):
            raise QualityBarContractError("Quality Bar domain result does not match the report's exact frozen target scope.")
    return [by_id[domain] for domain in sorted(QUALITY_DOMAIN_IDS)]


def _domain_result_ref(report_row: QualityAssessmentReportVersion, domain: Mapping[str, Any]) -> dict[str, Any]:
    domain_id = str(domain["domain_id"])
    return _typed_reference(
        identifier=f"{report_row.id}:{domain_id}", version=report_row.version,
        digest=str(domain["evaluation_hash"]), artifact_type="QualityDomainResult",
    )


def _finding_reference(finding: Mapping[str, Any]) -> dict[str, Any]:
    return _typed_reference(
        identifier=str(finding["finding_id"]), version=1,
        digest=str(finding["finding_hash"]), artifact_type="QualityFinding",
    )


def _actionable_target_for_finding(domain_id: str, targets: list[dict[str, Any]], fallback: dict[str, Any]) -> dict[str, Any]:
    """Choose the narrowest typed target, never the enclosing page by accident.

    The order of ``target_refs`` is evidence-oriented (the frozen page comes
    first).  Rework is target-oriented, so choosing index zero would turn a
    one-field QA finding into permission to regenerate the whole page.
    """

    preferred = _ACTIONABLE_TARGET_TYPES_BY_DOMAIN.get(domain_id, ())
    for target_type in preferred:
        for target in targets:
            if str(target.get("type") or "") == target_type:
                return dict(target)
    return dict(fallback)


def _review_reason(domain: Mapping[str, Any], *, reason_code: str) -> tuple[dict[str, Any], dict[str, Any]]:
    domain_ref = _typed_reference(
        identifier=str(domain["domain_id"]), version=1,
        digest=str(domain["evaluation_hash"]), artifact_type="QualityDomainResult",
    )
    reason = {
        "code": reason_code, "domain": str(domain["domain_id"]),
        "observed": str(domain.get("status") or ""), "threshold": None,
        "finding_ref": domain_ref,
    }
    target = {
        "domain": str(domain["domain_id"]), "finding_ref": domain_ref,
        "target_ref": domain_ref, "recommended_action": reason_code,
    }
    return reason, target


def aggregate_quality_bar(db: Session, *, report_ref: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic final verdict from one frozen persisted QA report.

    The report itself is the immutable result bundle.  Keeping this as a pure
    projection avoids a second mutable persistence authority before TASK-12.9
    introduces QA graph routing/rework.
    """

    report_row, report = _require_report(db, report_ref)
    _profile_row, profile = _require_profile(db, report=report, report_row=report_row)
    domains = _require_domain_bundle(report)

    thresholds = dict(profile.get("per_domain_minimum") or {})
    overall_minimum = profile.get("overall_minimum")
    max_critical = profile.get("max_critical_violations")
    if not isinstance(overall_minimum, (int, float)) or not isinstance(max_critical, int) or set(thresholds) != QUALITY_DOMAIN_IDS:
        raise QualityBarContractError("Quality Bar profile thresholds are incomplete.")

    # Critical findings are deduplicated only when the rule plus the complete
    # frozen target/evidence identity is identical.  Different root causes are
    # never collapsed just because they happen to occur in the same domain.
    criticals: list[tuple[str, str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]] = []
    for domain in domains:
        for finding in list(domain.get("findings") or []):
            if finding.get("severity") == "critical":
                targets = [dict(item) for item in list(finding.get("target_refs") or [])]
                evidence = [dict(item) for item in list(finding.get("evidence_refs") or [])]
                criticals.append((_critical_root_key(rule_id=str(finding["rule_id"]), target_refs=targets, evidence_refs=evidence), str(domain["domain_id"]), dict(finding), targets, evidence))
    for violation in list(report.get("critical_violations") or []):
        targets = [dict(violation["target_ref"])]
        evidence = [dict(item) for item in list(violation.get("evidence_refs") or [])]
        criticals.append((_critical_root_key(rule_id=str(violation["rule_id"]), target_refs=targets, evidence_refs=evidence), str(violation["domain"]), {
            "finding_id": str(violation["violation_id"]), "finding_hash": str(violation["canonical_hash"]),
            "rule_id": str(violation["rule_id"]), "code": str(violation["reason_code"]),
        }, targets, evidence))
    deduped_criticals = {key: value for key, *value in sorted(criticals, key=lambda item: item[0])}

    # Keep the pre-deduped domain membership for status validation: the same
    # root cause may legitimately be reported by two blocked domains even
    # though it counts only once toward the profile's critical limit.
    critical_domains = {domain_id for _key, domain_id, _finding, _targets, _evidence in criticals}
    review_reasons: list[dict[str, Any]] = []
    review_targets: list[dict[str, Any]] = []
    for domain in domains:
        domain_id = str(domain["domain_id"])
        status = str(domain.get("status") or "")
        human_status = str(dict(domain.get("human_rubric") or {}).get("status") or "not_requested")
        if status == _BLOCKED_STATUS:
            if domain_id not in critical_domains:
                raise QualityBarContractError("A blocked Quality Bar domain requires a persisted blocking critical violation.")
        elif status in _REVIEW_STATUSES:
            reason, target = _review_reason(domain, reason_code=("domain_not_evaluable" if status == "not_evaluable" else "domain_needs_review"))
            review_reasons.append(reason); review_targets.append(target)
        elif status != _EVALUABLE_STATUS:
            raise QualityBarContractError("Quality Bar domain status is neither complete, blocked, nor a supported review state.")
        if human_status == "pending":
            reason, target = _review_reason(domain, reason_code="human_review_pending")
            review_reasons.append(reason); review_targets.append(target)

    domain_scores = [
        {
            "domain_id": str(domain["domain_id"]), "score": domain["score"],
            "threshold": thresholds[str(domain["domain_id"])],
            "meets_threshold": bool(domain["score"] >= thresholds[str(domain["domain_id"])]),
            "status": str(domain["status"]),
        }
        for domain in domains
    ]
    bundle_versions = {domain_id: _EXPECTED_EVALUATOR_VERSIONS[domain_id] for domain_id in sorted(QUALITY_DOMAIN_IDS)}
    evaluator_bundle = {
        "bundle_id": QUALITY_BAR_EVALUATOR_BUNDLE_ID,
        "versions": bundle_versions,
        "canonical_hash": canonical_hash(bundle_versions),
    }

    failure_reasons: list[dict[str, Any]] = []
    failure_targets: list[dict[str, Any]] = []
    if len(deduped_criticals) > max_critical:
        for _key, (domain_id, finding, targets, _evidence) in deduped_criticals.items():
            finding_ref = _finding_reference(finding)
            failure_reasons.append({
                "code": "critical_violation_present", "domain": domain_id,
                "observed": 1, "threshold": max_critical, "finding_ref": finding_ref,
            })
            fallback = _domain_result_ref(report_row, next(item for item in domains if item["domain_id"] == domain_id))
            failure_targets.append({
                "domain": domain_id, "finding_ref": finding_ref,
                "target_ref": _actionable_target_for_finding(domain_id, targets, fallback),
                "recommended_action": str(finding["rule_id"]),
            })
    for score in domain_scores:
        if not score["meets_threshold"]:
            domain = next(item for item in domains if item["domain_id"] == score["domain_id"])
            domain_ref = _domain_result_ref(report_row, domain)
            # A score failure may be caused by a non-critical, but still
            # deterministic, frozen finding.  Preserve that narrow finding
            # target when available so TASK-12.9 can reuse the corresponding
            # production selective-rework path instead of receiving only a
            # broad domain reference.  Findings without an actionable typed
            # target deliberately retain the seller-review-safe domain ref.
            actionable = next(
                (
                    finding for finding in sorted(
                        (dict(item) for item in list(domain.get("findings") or [])),
                        key=lambda item: str(item.get("finding_id") or ""),
                    )
                    if _actionable_target_for_finding(
                        str(score["domain_id"]),
                        [dict(item) for item in list(finding.get("target_refs") or [])],
                        domain_ref,
                    ) != domain_ref
                ),
                None,
            )
            if actionable is None:
                selected_finding_ref = domain_ref
                selected_target_ref = domain_ref
                recommended_action = "domain_below_threshold"
            else:
                selected_finding_ref = _finding_reference(actionable)
                selected_target_ref = _actionable_target_for_finding(
                    str(score["domain_id"]),
                    [dict(item) for item in list(actionable.get("target_refs") or [])],
                    domain_ref,
                )
                recommended_action = str(actionable["rule_id"])
            failure_reasons.append({
                "code": "domain_below_threshold", "domain": score["domain_id"],
                "observed": score["score"], "threshold": score["threshold"], "finding_ref": domain_ref,
            })
            failure_targets.append({
                "domain": score["domain_id"], "finding_ref": selected_finding_ref,
                "target_ref": selected_target_ref, "recommended_action": recommended_action,
            })
    if report["overall_score"] < overall_minimum:
        failure_reasons.append({
            "code": "overall_below_threshold", "domain": None,
            "observed": report["overall_score"], "threshold": overall_minimum,
            "finding_ref": _typed_reference(identifier=str(report_row.id), version=report_row.version, digest=report_row.canonical_hash, artifact_type="QualityAssessmentReportVersion"),
        })

    if review_reasons:
        verdict = "NEEDS_REVIEW"
        evaluability_state = "needs_review"
    elif failure_reasons:
        verdict = "FAIL"
        evaluability_state = "evaluable"
    else:
        verdict = "PASS"
        evaluability_state = "evaluable"

    active_failure_domains = {
        str(reason["domain"]) for reason in failure_reasons if reason.get("domain") is not None
    }
    primary_domain = next((domain for domain in _DOMAIN_ROUTE_PRIORITY if domain in active_failure_domains), None)
    if verdict == "PASS":
        routing_code = "PASS"
    elif primary_domain is not None:
        routing_code = _ROUTING_CODE_BY_DOMAIN[primary_domain]
    else:
        # A score-only failure has no safe automatic rework target, and a
        # review-only result must remain seller-controlled.
        routing_code = "SELLER_REVIEW"

    blocking_reasons = review_reasons + failure_reasons
    rework_targets = review_targets + failure_targets

    result_body = {
        "quality_bar_result_id": f"quality-bar:{report_row.id}:{report_row.version}",
        "schema_version": QUALITY_BAR_SCHEMA_VERSION,
        "created_at": report["created_at"],
        "frozen_target_ref": {**dict(report["target_artifact"])},
        "approved_asset_manifest_hash": report["approved_asset_manifest_hash"],
        "workspace_id": report_row.workspace_id, "project_id": report_row.project_id,
        "creator_run_id": report_row.creator_run_id,
        "quality_report_ref": _typed_reference(identifier=str(report_row.id), version=report_row.version, digest=report_row.canonical_hash, artifact_type="QualityAssessmentReportVersion"),
        "threshold_profile_ref": _typed_reference(identifier=str(profile["profile_id"]), version=profile["profile_version"], digest=profile["canonical_hash"], artifact_type="QualityThresholdProfileVersion"),
        "evaluator_bundle": evaluator_bundle,
        "domain_result_refs": [_domain_result_ref(report_row, domain) for domain in domains],
        "domain_scores": domain_scores,
        "overall_score": report["overall_score"],
        "critical_count": len(deduped_criticals),
        "evaluability_state": evaluability_state,
        "per_domain_threshold_result": {item["domain_id"]: item["meets_threshold"] for item in domain_scores},
        "overall_threshold_result": bool(report["overall_score"] >= overall_minimum) if evaluability_state == "evaluable" else None,
        "verdict": verdict,
        "routing_code": routing_code,
        "primary_blocking_domain": primary_domain,
        "seller_review_required": routing_code == "SELLER_REVIEW",
        "blocking_reasons": sorted(
            blocking_reasons,
            key=lambda item: (
                _DOMAIN_PRIORITY_INDEX.get(str(item.get("domain") or ""), len(_DOMAIN_PRIORITY_INDEX)),
                str(item["code"]), str(item["finding_ref"]["id"]),
            ),
        ),
        "rework_targets": sorted(
            rework_targets,
            key=lambda item: (
                _DOMAIN_PRIORITY_INDEX.get(str(item["domain"]), len(_DOMAIN_PRIORITY_INDEX)),
                str(item["recommended_action"]), str(item["finding_ref"]["id"]),
            ),
        ),
    }
    return {**result_body, "canonical_hash": canonical_hash(result_body)}
