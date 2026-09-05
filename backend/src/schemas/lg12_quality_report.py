"""Deterministic, reference-only LG-12 quality report contracts.

TASK-12.2 deliberately defines data contracts only.  Evaluators and the final
quality-gate decision are introduced by later tasks; this module never calls a
provider or derives a verdict from a score.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from src.services.channel_export_service import supported_channel_keys
from src.services.prompt_intelligence_service import canonical_hash


QUALITY_ASSESSMENT_REPORT_SCHEMA_VERSION = "lg12-quality-assessment-report-v1"
QUALITY_THRESHOLD_PROFILE_SCHEMA_VERSION = "lg12-quality-threshold-profile-v1"
QUALITY_REPORT_TARGET_ARTIFACT_TYPE = "DetailPageVersion"
QUALITY_REPORT_DOMAIN_PARENT_REF_TYPE = "QualityAssessmentReportVersion"
QUALITY_REPORT_DOMAIN_BINDING_SCHEMA_VERSION = "lg12-quality-report-domain-binding-v1"
QUALITY_DOMAIN_IDS = frozenset({
    "factual_rights_policy",
    "image_identity_quality",
    "korean_copy_readability",
    "layout_typography_brand_flow",
    "channel_preview_export_parity",
})
QUALITY_SEVERITIES = frozenset({"critical", "major", "minor", "info"})
QUALITY_ROUTING_CODES = frozenset({
    "COPY_REWORK", "PLAN_REWORK", "VISUAL_REWORK", "IMAGE_REWORK",
    "SELLER_REVIEW", "BLOCKED_POLICY", "PASS",
})
QUALITY_INPUT_MODES = frozenset({"owned_product_url", "photo_only", "manual"})
QUALITY_THRESHOLD_PROFILE_V1_OVERALL_MINIMUM = 85
QUALITY_THRESHOLD_PROFILE_V1_DOMAIN_MINIMUM = 70
QUALITY_THRESHOLD_PROFILE_V1_MAX_CRITICAL = 0
_SHA256_CHARS = set("0123456789abcdef")
_REF_KEYS = {"id", "version", "hash", "schema_version", "artifact_key", "type"}
_RAW_BODY_KEYS = frozenset({
    "raw_html", "html", "html_body", "raw_image", "image_bytes", "raw_ocr",
    "ocr_text", "provider_response", "provider_body", "raw_body", "body",
})

# QA reports are an immutable index of evaluator results, never an alternate
# store for page, master, OCR, or image payloads.  These limits match the
# bounded scalar/reference role of this contract rather than accepting a
# generic JSON "details" escape hatch.
_MAX_REFERENCE_ID_LENGTH = 160
_MAX_REFERENCE_VERSION_LENGTH = 80
_MAX_REFERENCE_METADATA_LENGTH = 100
_MAX_SCALAR_TEXT_LENGTH = 512
_MAX_SHORT_TEXT_LENGTH = 128
_MAX_SCALAR_LIST_ITEMS = 16
_MAX_REFERENCE_LIST_ITEMS = 32
_MAX_FINDINGS_PER_REPORT = 64
_MAX_SUBMETRICS_PER_DOMAIN = 32
_MAX_QUALITY_REPORT_SERIALIZED_BYTES = 256 * 1024
_COMPARISON_VALUES = frozenset({"equals", "not_equals", "contains", "present", "absent", "gte", "lte"})
_FIDELITY_STATUSES = frozenset({"complete", "partial", "unknown", "mismatch", "unavailable"})
_METRIC_ID_RE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")
_MARKUP_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s+[^<>]*)?/?>", re.IGNORECASE)
_MARKUP_DECLARATION_RE = re.compile(r"<(?:![A-Za-z][^<>]*|\?[A-Za-z][^<>]*)>", re.IGNORECASE)
_DISALLOWED_URI_SCHEME_RE = re.compile(r"^(?:data|javascript|vbscript|file)\s*:", re.IGNORECASE)
_BARE_BASE64_RE = re.compile(r"[A-Za-z0-9+/_-]+={0,2}$")


class QualityAssessmentContractError(ValueError):
    """Raised when an immutable LG-12 report/profile is not contract-safe."""


def _require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _SHA256_CHARS for char in value):
        raise QualityAssessmentContractError(f"{label} must be a lowercase SHA-256 hash.")
    return value


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_REFERENCE_ID_LENGTH:
        raise QualityAssessmentContractError(f"{label} is required.")
    return value


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise QualityAssessmentContractError(f"{label} must be an object.")
    return deepcopy(dict(value))


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise QualityAssessmentContractError(f"{label} must be a list.")
    return deepcopy(value)


def _reference(value: Any, label: str) -> dict[str, Any]:
    ref = _mapping(value, label)
    if set(ref) - _REF_KEYS:
        raise QualityAssessmentContractError(f"{label} must be an ID/version/hash reference, not copied content.")
    _require_id(ref.get("id"), f"{label}.id")
    version = ref.get("version")
    if (
        not isinstance(version, (str, int))
        or isinstance(version, bool)
        or not str(version)
        or len(str(version)) > _MAX_REFERENCE_VERSION_LENGTH
    ):
        raise QualityAssessmentContractError(f"{label}.version is required.")
    _require_hash(ref.get("hash"), f"{label}.hash")
    for key in ("schema_version", "artifact_key", "type"):
        if key in ref and (
            not isinstance(ref[key], str) or not ref[key] or len(ref[key]) > _MAX_REFERENCE_METADATA_LENGTH
        ):
            raise QualityAssessmentContractError(f"{label}.{key} must be bounded text.")
    return ref


def _references(value: Any, label: str, *, maximum: int = _MAX_REFERENCE_LIST_ITEMS) -> list[dict[str, Any]]:
    values = _list(value, label)
    if len(values) > maximum:
        raise QualityAssessmentContractError(f"{label} exceeds its bounded reference limit.")
    return [_reference(item, f"{label}[{index}]") for index, item in enumerate(values)]


def _typed_references(value: Any, label: str, *, maximum: int = _MAX_REFERENCE_LIST_ITEMS) -> list[dict[str, Any]]:
    refs = _references(value, label, maximum=maximum)
    for index, reference in enumerate(refs):
        if not reference.get("type"):
            raise QualityAssessmentContractError(f"{label}[{index}] must include a typed reference identity.")
    return refs


def _sort_key(value: Any) -> tuple[str, str, str, str]:
    if isinstance(value, Mapping):
        return (
            str(value.get("id") or value.get("finding_id") or value.get("violation_id") or ""),
            str(value.get("version") or ""),
            str(value.get("hash") or value.get("finding_hash") or value.get("canonical_hash") or ""),
            canonical_hash(dict(value)),
        )
    return (str(value), "", "", canonical_hash(value))


def _canonicalize(value: Any, *, field_name: str | None = None) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        normalized = [_canonicalize(item) for item in value]
        if field_name in {
            "target_channels", "applicable_channels", "evidence_refs", "findings",
            "critical_violations", "warnings", "rework_targets", "domain_scores", "submetrics",
        }:
            return sorted(normalized, key=_sort_key)
        return normalized
    return value


def _reject_raw_body(value: Any, *, label: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _RAW_BODY_KEYS:
                raise QualityAssessmentContractError(f"{label}.{key} may not contain raw or provider body content.")
            _reject_raw_body(item, label=f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_raw_body(item, label=f"{label}[{index}]")


def _bounded_text(value: Any, label: str, *, maximum: int = _MAX_SCALAR_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise QualityAssessmentContractError(f"{label} must be bounded non-empty text.")
    compact = value.strip()
    if _MARKUP_TAG_RE.search(compact) or _MARKUP_DECLARATION_RE.search(compact):
        raise QualityAssessmentContractError(f"{label} may not contain HTML or executable markup.")
    if _DISALLOWED_URI_SCHEME_RE.match(compact):
        raise QualityAssessmentContractError(f"{label} may not contain executable or data URI content.")
    if (
        len(compact) >= 128
        and _BARE_BASE64_RE.fullmatch(compact)
    ):
        raise QualityAssessmentContractError(f"{label} may not contain base64-like binary data.")
    return value


def _bounded_scalar(value: Any, label: str) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise QualityAssessmentContractError(f"{label} must be a finite scalar.")
        return value
    if isinstance(value, str):
        return _bounded_text(value, label)
    raise QualityAssessmentContractError(f"{label} must be a scalar value.")


def _bounded_value(value: Any, label: str) -> Any:
    """Normalize the only evaluator value forms allowed in a QA report."""

    if not isinstance(value, (Mapping, list)):
        return _bounded_scalar(value, label)
    if isinstance(value, list):
        if len(value) > _MAX_SCALAR_LIST_ITEMS:
            raise QualityAssessmentContractError(f"{label} exceeds its bounded scalar-list limit.")
        return [_bounded_scalar(item, f"{label}[{index}]") for index, item in enumerate(value)]

    item = _mapping(value, label)
    if set(item).issubset(_REF_KEYS) and {"id", "version", "hash"}.issubset(item):
        return _reference(item, label)
    allowed = {"value", "unit", "comparison"}
    if set(item) - allowed or "value" not in item:
        raise QualityAssessmentContractError(f"{label} must be a scalar, typed reference, or bounded measurement object.")
    normalized = {"value": _bounded_scalar(item["value"], f"{label}.value")}
    if "unit" in item:
        normalized["unit"] = _bounded_text(item["unit"], f"{label}.unit", maximum=_MAX_SHORT_TEXT_LENGTH)
    if "comparison" in item:
        comparison = item["comparison"]
        if comparison not in _COMPARISON_VALUES:
            raise QualityAssessmentContractError(f"{label}.comparison is unsupported.")
        normalized["comparison"] = comparison
    return normalized


def _normalize_source_fidelity(value: Any, *, source_reference: Mapping[str, Any]) -> dict[str, Any]:
    fidelity = _mapping(value, "quality_report.source_fidelity")
    allowed = {"source_kind", "source_ref", "fidelity_status", "code", "confidence", "metric"}
    if set(fidelity) - allowed or {"source_kind", "source_ref", "fidelity_status"} - set(fidelity):
        raise QualityAssessmentContractError("quality_report.source_fidelity must contain only bounded source metadata.")
    normalized = {
        "source_kind": _bounded_text(fidelity["source_kind"], "quality_report.source_fidelity.source_kind", maximum=_MAX_SHORT_TEXT_LENGTH),
        "source_ref": _reference(fidelity["source_ref"], "quality_report.source_fidelity.source_ref"),
        "fidelity_status": fidelity["fidelity_status"],
    }
    if normalized["fidelity_status"] not in _FIDELITY_STATUSES:
        raise QualityAssessmentContractError("quality_report.source_fidelity.fidelity_status is unsupported.")
    if normalized["source_ref"] != dict(source_reference):
        raise QualityAssessmentContractError("quality_report.source_fidelity must reference the frozen source lineage.")
    if "code" in fidelity:
        normalized["code"] = _bounded_text(fidelity["code"], "quality_report.source_fidelity.code", maximum=_MAX_SHORT_TEXT_LENGTH)
    if "confidence" in fidelity:
        confidence = fidelity["confidence"]
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise QualityAssessmentContractError("quality_report.source_fidelity.confidence must be within 0..1.")
        normalized["confidence"] = confidence
    if "metric" in fidelity:
        normalized["metric"] = _bounded_value(fidelity["metric"], "quality_report.source_fidelity.metric")
    return normalized


def _normalize_submetrics(value: Any, label: str) -> list[dict[str, Any]]:
    items = _list(value, label)
    if len(items) > _MAX_SUBMETRICS_PER_DOMAIN:
        raise QualityAssessmentContractError(f"{label} exceeds its bounded metric limit.")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        metric = _mapping(item, f"{label}[{index}]")
        allowed = {"metric_id", "value", "unit", "threshold", "status"}
        if set(metric) - allowed or {"metric_id", "value"} - set(metric):
            raise QualityAssessmentContractError(f"{label}[{index}] must be a bounded scalar metric.")
        metric_id = metric["metric_id"]
        if not isinstance(metric_id, str) or not _METRIC_ID_RE.fullmatch(metric_id):
            raise QualityAssessmentContractError(f"{label}[{index}].metric_id is unsupported.")
        entry = {"metric_id": metric_id, "value": _bounded_scalar(metric["value"], f"{label}[{index}].value")}
        if "unit" in metric:
            entry["unit"] = _bounded_text(metric["unit"], f"{label}[{index}].unit", maximum=_MAX_SHORT_TEXT_LENGTH)
        if "threshold" in metric:
            entry["threshold"] = _bounded_scalar(metric["threshold"], f"{label}[{index}].threshold")
        if "status" in metric:
            entry["status"] = _bounded_text(metric["status"], f"{label}[{index}].status", maximum=_MAX_SHORT_TEXT_LENGTH)
        normalized.append(entry)
    if len({item["metric_id"] for item in normalized}) != len(normalized):
        raise QualityAssessmentContractError(f"{label} metric IDs must be unique.")
    return _canonicalize(normalized, field_name="submetrics")


def _require_bounded_report_size(value: Mapping[str, Any]) -> None:
    serialized = json.dumps(_canonicalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(serialized) > _MAX_QUALITY_REPORT_SERIALIZED_BYTES:
        raise QualityAssessmentContractError("quality_report exceeds its bounded serialized payload limit.")


def normalize_target_channels(value: Any, label: str = "target_channels") -> list[str]:
    channels = _list(value, label)
    if not channels:
        raise QualityAssessmentContractError(f"{label} must not be empty.")
    if any(not isinstance(channel, str) for channel in channels):
        raise QualityAssessmentContractError(f"{label} must contain channel identities.")
    normalized = [channel.strip().lower() for channel in channels]
    if any(channel not in supported_channel_keys() for channel in normalized):
        raise QualityAssessmentContractError(f"{label} contains an unsupported production channel.")
    if len(set(normalized)) != len(normalized):
        raise QualityAssessmentContractError(f"{label} must not contain duplicate channels.")
    return sorted(normalized)


def canonical_quality_finding_hash(finding: Mapping[str, Any]) -> str:
    payload = _mapping(finding, "finding")
    payload.pop("finding_hash", None)
    return canonical_hash(_canonicalize(payload))


def _normalize_finding(value: Any, *, label: str) -> dict[str, Any]:
    finding = _mapping(value, label)
    allowed = {
        "finding_id", "domain", "severity", "rule_id", "code", "message", "target_refs",
        "evidence_refs", "expected", "observed", "remediation_hint", "finding_hash",
    }
    if set(finding) - allowed:
        raise QualityAssessmentContractError(f"{label} contains unsupported raw/evaluator fields.")
    _require_id(finding.get("finding_id"), f"{label}.finding_id")
    if finding.get("domain") not in QUALITY_DOMAIN_IDS:
        raise QualityAssessmentContractError(f"{label}.domain is unsupported.")
    if finding.get("severity") not in QUALITY_SEVERITIES:
        raise QualityAssessmentContractError(f"{label}.severity is unsupported.")
    _require_id(finding.get("rule_id"), f"{label}.rule_id")
    _require_id(finding.get("code"), f"{label}.code")
    finding["message"] = _bounded_text(finding.get("message"), f"{label}.message")
    finding["target_refs"] = _typed_references(finding.get("target_refs", []), f"{label}.target_refs")
    finding["evidence_refs"] = _typed_references(finding.get("evidence_refs", []), f"{label}.evidence_refs")
    for key in ("expected", "observed"):
        if key not in finding:
            raise QualityAssessmentContractError(f"{label}.{key} is required.")
        finding[key] = _bounded_value(finding[key], f"{label}.{key}")
    finding["remediation_hint"] = _bounded_text(finding.get("remediation_hint"), f"{label}.remediation_hint")
    expected_hash = canonical_quality_finding_hash(finding)
    if finding.get("finding_hash") not in {None, expected_hash}:
        raise QualityAssessmentContractError(f"{label}.finding_hash does not match its canonical finding content.")
    finding["finding_hash"] = expected_hash
    _reject_raw_body(finding, label=label)
    return _canonicalize(finding)


def _quality_report_domain_parent_ref(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return the non-circular immutable report identity pinned by a domain.

    A report's final canonical hash commits its domain results, so a domain
    cannot itself contain that final hash without creating a hash cycle.  This
    deterministic seed commits the report ID/version and frozen report scope
    before domains are finalized.  The final report hash then commits this
    typed parent reference together with every domain result.
    """

    binding_body = {
        "schema_version": QUALITY_REPORT_DOMAIN_BINDING_SCHEMA_VERSION,
        "report_id": str(report["report_id"]),
        "report_version": report["report_version"],
        "report_schema_version": str(report["schema_version"]),
        "evaluator_bundle_version": str(report["evaluator_bundle_version"]),
        "frozen_target_ref": dict(report["target_artifact"]),
        "approved_asset_manifest_hash": str(report["approved_asset_manifest_hash"]),
        "workspace_id": str(report["workspace_id"]),
        "project_id": str(report["project_id"]),
        "creator_run_id": str(report["creator_run_id"]),
    }
    return {
        "id": str(report["report_id"]),
        "version": report["report_version"],
        "hash": canonical_hash(_canonicalize(binding_body)),
        "type": QUALITY_REPORT_DOMAIN_PARENT_REF_TYPE,
    }


def _frozen_domain_target_binding(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return the compact report/target identity every persisted domain must pin.

    A domain score is not an interchangeable scalar: it is evidence for one
    exact immutable report as well as one frozen page and its report scope.
    The enclosing persisted report remains the final authority; this binding
    prevents a valid domain from a sibling report being substituted before
    TASK-12.8 aggregation.
    """

    return {
        "report_ref": _quality_report_domain_parent_ref(report),
        "frozen_target_ref": dict(report["target_artifact"]),
        "approved_asset_manifest_hash": str(report["approved_asset_manifest_hash"]),
        "workspace_id": str(report["workspace_id"]),
        "project_id": str(report["project_id"]),
        "creator_run_id": str(report["creator_run_id"]),
    }


def _normalize_domain(
    value: Any,
    *,
    label: str,
    expected_target_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    domain = _mapping(value, label)
    allowed = {
        "domain_id", "score", "status", "evaluator_version", "findings", "critical_count",
        "warning_count", "evidence_refs", "evaluated_at", "evaluation_hash", "weight", "submetrics",
        "metric_source", "human_rubric", "frozen_target_ref",
        "approved_asset_manifest_hash", "workspace_id", "project_id",
        "creator_run_id", "report_ref",
    }
    if set(domain) - allowed:
        raise QualityAssessmentContractError(f"{label} contains unsupported evaluator body fields.")
    if domain.get("domain_id") not in QUALITY_DOMAIN_IDS:
        raise QualityAssessmentContractError(f"{label}.domain_id is unsupported.")
    binding_keys = {
        "report_ref", "frozen_target_ref", "approved_asset_manifest_hash", "workspace_id",
        "project_id", "creator_run_id",
    }
    has_binding = binding_keys.issubset(domain)
    if binding_keys.intersection(domain) and not has_binding:
        raise QualityAssessmentContractError(f"{label} frozen target identity is incomplete.")
    if expected_target_binding is not None and not has_binding:
        raise QualityAssessmentContractError(f"{label} must pin the report's exact frozen target identity.")
    if has_binding:
        report_ref = _reference(domain["report_ref"], f"{label}.report_ref")
        if report_ref.get("type") != QUALITY_REPORT_DOMAIN_PARENT_REF_TYPE:
            raise QualityAssessmentContractError(
                f"{label}.report_ref must be a QualityAssessmentReportVersion reference."
            )
        domain["report_ref"] = report_ref
        target = _reference(domain["frozen_target_ref"], f"{label}.frozen_target_ref")
        if target.get("type") != QUALITY_REPORT_TARGET_ARTIFACT_TYPE:
            raise QualityAssessmentContractError(f"{label}.frozen_target_ref must be a DetailPageVersion reference.")
        domain["frozen_target_ref"] = target
        _require_hash(domain["approved_asset_manifest_hash"], f"{label}.approved_asset_manifest_hash")
        for key in ("workspace_id", "project_id", "creator_run_id"):
            _require_id(domain[key], f"{label}.{key}")
        if expected_target_binding is not None and {
            key: domain[key] for key in binding_keys
        } != dict(expected_target_binding):
            raise QualityAssessmentContractError(f"{label} frozen target identity does not match its persisted report.")
    score = domain.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
        raise QualityAssessmentContractError(f"{label}.score must be within 0..100.")
    domain["status"] = _bounded_text(domain.get("status"), f"{label}.status", maximum=_MAX_SHORT_TEXT_LENGTH)
    _bounded_text(domain.get("evaluator_version"), f"{label}.evaluator_version", maximum=_MAX_REFERENCE_METADATA_LENGTH)
    if domain.get("metric_source") not in {"automatic", "human", "hybrid"}:
        raise QualityAssessmentContractError(f"{label}.metric_source must distinguish automatic and human rubric results.")
    if "human_rubric" in domain:
        rubric = _mapping(domain["human_rubric"], f"{label}.human_rubric")
        if set(rubric) - {"status", "rubric_ref"} or "status" not in rubric:
            raise QualityAssessmentContractError(f"{label}.human_rubric must be a bounded status/reference contract.")
        rubric["status"] = _bounded_text(
            rubric["status"], f"{label}.human_rubric.status", maximum=_MAX_SHORT_TEXT_LENGTH,
        )
        if rubric["status"] not in {"not_requested", "pending", "completed"}:
            raise QualityAssessmentContractError(f"{label}.human_rubric.status is unsupported.")
        if "rubric_ref" in rubric:
            rubric["rubric_ref"] = _reference(rubric["rubric_ref"], f"{label}.human_rubric.rubric_ref")
        if rubric["status"] == "completed" and "rubric_ref" not in rubric:
            raise QualityAssessmentContractError(f"{label}.human_rubric.completed requires a typed rubric_ref.")
        domain["human_rubric"] = rubric
    domain["evaluated_at"] = _bounded_text(domain.get("evaluated_at"), f"{label}.evaluated_at", maximum=_MAX_SHORT_TEXT_LENGTH)
    if "weight" in domain:
        weight = domain["weight"]
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(weight) or not 0 <= weight <= 1:
            raise QualityAssessmentContractError(f"{label}.weight must be a finite 0..1 scalar.")
        domain["weight"] = weight
    domain_finding_values = _list(domain.get("findings"), f"{label}.findings")
    if len(domain_finding_values) > _MAX_FINDINGS_PER_REPORT:
        raise QualityAssessmentContractError(f"{label}.findings exceeds its bounded finding limit.")
    domain["findings"] = [_normalize_finding(item, label=f"{label}.findings[{index}]") for index, item in enumerate(domain_finding_values)]
    domain["evidence_refs"] = _references(domain.get("evidence_refs"), f"{label}.evidence_refs")
    if "submetrics" in domain:
        domain["submetrics"] = _normalize_submetrics(domain["submetrics"], f"{label}.submetrics")
    for count_name, severity in (("critical_count", "critical"), ("warning_count", None)):
        count = domain.get(count_name)
        if not isinstance(count, int) or count < 0:
            raise QualityAssessmentContractError(f"{label}.{count_name} must be a non-negative integer.")
        expected = sum(1 for item in domain["findings"] if item["severity"] == severity) if severity else sum(
            1 for item in domain["findings"] if item["severity"] in {"major", "minor", "info"}
        )
        if count != expected:
            raise QualityAssessmentContractError(f"{label}.{count_name} does not match its findings.")
    hash_body = deepcopy(domain)
    hash_body.pop("evaluation_hash", None)
    expected_hash = canonical_hash(_canonicalize(hash_body))
    if domain.get("evaluation_hash") not in {None, expected_hash}:
        raise QualityAssessmentContractError(f"{label}.evaluation_hash does not match its canonical domain content.")
    domain["evaluation_hash"] = expected_hash
    _reject_raw_body(domain, label=label)
    return _canonicalize(domain)


def normalize_quality_threshold_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    profile = _mapping(value, "threshold_profile")
    allowed = {
        "profile_id", "profile_version", "schema_version", "applicable_artifact_type", "applicable_channels",
        "overall_minimum", "per_domain_minimum", "max_critical_violations", "max_major_findings",
        "max_warning_findings", "status", "effective_from", "parent_profile_ref", "canonical_hash",
    }
    if set(profile) - allowed:
        raise QualityAssessmentContractError("threshold_profile contains unsupported fields.")
    _require_id(profile.get("profile_id"), "threshold_profile.profile_id")
    if not isinstance(profile.get("profile_version"), int) or profile["profile_version"] < 1:
        raise QualityAssessmentContractError("threshold_profile.profile_version must be positive.")
    if profile.get("schema_version") != QUALITY_THRESHOLD_PROFILE_SCHEMA_VERSION:
        raise QualityAssessmentContractError("threshold_profile.schema_version is unsupported.")
    if profile.get("applicable_artifact_type") != QUALITY_REPORT_TARGET_ARTIFACT_TYPE:
        raise QualityAssessmentContractError("threshold_profile only applies to frozen DetailPageVersion artifacts.")
    profile["applicable_channels"] = normalize_target_channels(profile.get("applicable_channels"), "threshold_profile.applicable_channels")
    if not isinstance(profile.get("overall_minimum"), (int, float)) or not 0 <= profile["overall_minimum"] <= 100:
        raise QualityAssessmentContractError("threshold_profile.overall_minimum must be within 0..100.")
    minimums = _mapping(profile.get("per_domain_minimum"), "threshold_profile.per_domain_minimum")
    if set(minimums) != QUALITY_DOMAIN_IDS:
        raise QualityAssessmentContractError("threshold_profile must define every quality domain exactly once.")
    if any(not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100 for score in minimums.values()):
        raise QualityAssessmentContractError("threshold_profile per-domain minimums must be within 0..100.")
    profile["per_domain_minimum"] = {domain: minimums[domain] for domain in sorted(QUALITY_DOMAIN_IDS)}
    if not isinstance(profile.get("max_critical_violations"), int) or profile["max_critical_violations"] < 0:
        raise QualityAssessmentContractError("threshold_profile.max_critical_violations must be a non-negative integer.")
    if profile["profile_version"] == 1 and (
        profile["overall_minimum"] != QUALITY_THRESHOLD_PROFILE_V1_OVERALL_MINIMUM
        or any(score != QUALITY_THRESHOLD_PROFILE_V1_DOMAIN_MINIMUM for score in profile["per_domain_minimum"].values())
        or profile["max_critical_violations"] != QUALITY_THRESHOLD_PROFILE_V1_MAX_CRITICAL
    ):
        raise QualityAssessmentContractError("Threshold profile v1 must pin 85 overall, 70 per-domain, and zero critical violations.")
    for optional in ("max_major_findings", "max_warning_findings"):
        if optional in profile and profile[optional] is not None and (
            not isinstance(profile[optional], int) or profile[optional] < 0
        ):
            raise QualityAssessmentContractError(f"threshold_profile.{optional} must be a non-negative integer.")
    if not isinstance(profile.get("status"), str) or not profile["status"]:
        raise QualityAssessmentContractError("threshold_profile.status is required.")
    if not isinstance(profile.get("effective_from"), str) or not profile["effective_from"]:
        raise QualityAssessmentContractError("threshold_profile.effective_from is required.")
    if profile.get("parent_profile_ref") is not None:
        profile["parent_profile_ref"] = _reference(profile["parent_profile_ref"], "threshold_profile.parent_profile_ref")
    hash_body = deepcopy(profile)
    hash_body.pop("canonical_hash", None)
    expected_hash = canonical_hash(_canonicalize(hash_body))
    if profile.get("canonical_hash") not in {None, expected_hash}:
        raise QualityAssessmentContractError("threshold_profile.canonical_hash does not match its content.")
    profile["canonical_hash"] = expected_hash
    return _canonicalize(profile)


def normalize_quality_assessment_report(value: Mapping[str, Any]) -> dict[str, Any]:
    report = _mapping(value, "quality_report")
    allowed = {
        "report_id", "report_version", "schema_version", "evaluator_bundle_version", "target_artifact",
        "approved_asset_manifest_hash", "project_id", "workspace_id", "creator_run_id", "target_channels",
        "created_at", "input_lineage", "dataset_ref", "input_mode", "source_fidelity", "prohibited_inference_count",
        "unknown_fact_count", "clarification_count", "overall_score", "domain_scores", "critical_violations",
        "warnings", "findings", "threshold_profile_ref", "verdict", "routing_code", "rework_targets",
        "canonical_hash",
    }
    if set(report) - allowed:
        raise QualityAssessmentContractError("quality_report contains unsupported raw/evaluator fields.")
    _require_id(report.get("report_id"), "quality_report.report_id")
    if not isinstance(report.get("report_version"), int) or report["report_version"] < 1:
        raise QualityAssessmentContractError("quality_report.report_version must be positive.")
    if report.get("schema_version") != QUALITY_ASSESSMENT_REPORT_SCHEMA_VERSION:
        raise QualityAssessmentContractError("quality_report.schema_version is unsupported.")
    report["evaluator_bundle_version"] = _bounded_text(
        report.get("evaluator_bundle_version"), "quality_report.evaluator_bundle_version", maximum=_MAX_REFERENCE_METADATA_LENGTH
    )
    target = _mapping(report.get("target_artifact"), "quality_report.target_artifact")
    if target.get("type") != QUALITY_REPORT_TARGET_ARTIFACT_TYPE:
        raise QualityAssessmentContractError("quality_report must target a frozen DetailPageVersion.")
    report["target_artifact"] = _reference(target, "quality_report.target_artifact")
    report["target_artifact"]["type"] = QUALITY_REPORT_TARGET_ARTIFACT_TYPE
    _require_hash(report.get("approved_asset_manifest_hash"), "quality_report.approved_asset_manifest_hash")
    for field in ("project_id", "workspace_id", "creator_run_id"):
        _require_id(report.get(field), f"quality_report.{field}")
    report["target_channels"] = normalize_target_channels(report.get("target_channels"))
    report["created_at"] = _bounded_text(report.get("created_at"), "quality_report.created_at", maximum=_MAX_SHORT_TEXT_LENGTH)
    lineage = _mapping(report.get("input_lineage"), "quality_report.input_lineage")
    if set(lineage) != {"source_snapshot_ref", "truth_ref", "confirmation_ref", "master_ref"}:
        raise QualityAssessmentContractError("quality_report input lineage must pin source/truth/confirmation/master references.")
    report["input_lineage"] = {key: _reference(lineage[key], f"quality_report.input_lineage.{key}") for key in sorted(lineage)}
    report["source_fidelity"] = _normalize_source_fidelity(
        report.get("source_fidelity"), source_reference=report["input_lineage"]["source_snapshot_ref"]
    )
    report["dataset_ref"] = _reference(report.get("dataset_ref"), "quality_report.dataset_ref")
    if report.get("input_mode") not in QUALITY_INPUT_MODES:
        raise QualityAssessmentContractError("quality_report.input_mode is unsupported.")
    for field in ("prohibited_inference_count", "unknown_fact_count", "clarification_count"):
        if not isinstance(report.get(field), int) or report[field] < 0:
            raise QualityAssessmentContractError(f"quality_report.{field} must be a non-negative integer.")
    score = report.get("overall_score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
        raise QualityAssessmentContractError("quality_report.overall_score must be within 0..100.")
    domain_target_binding = _frozen_domain_target_binding(report)
    domains = [
        _normalize_domain(
            item, label=f"quality_report.domain_scores[{index}]",
            expected_target_binding=domain_target_binding,
        )
        for index, item in enumerate(_list(report.get("domain_scores"), "quality_report.domain_scores"))
    ]
    if {item["domain_id"] for item in domains} != QUALITY_DOMAIN_IDS or len(domains) != len(QUALITY_DOMAIN_IDS):
        raise QualityAssessmentContractError("quality_report must include every quality domain exactly once.")
    report["domain_scores"] = domains
    finding_values = _list(report.get("findings"), "quality_report.findings")
    if len(finding_values) > _MAX_FINDINGS_PER_REPORT:
        raise QualityAssessmentContractError("quality_report.findings exceeds its bounded finding limit.")
    findings = [_normalize_finding(item, label=f"quality_report.findings[{index}]") for index, item in enumerate(finding_values)]
    if len({item["finding_id"] for item in findings}) != len(findings):
        raise QualityAssessmentContractError("quality_report finding IDs must be unique.")
    report["findings"] = findings
    warning_values = _list(report.get("warnings"), "quality_report.warnings")
    if len(warning_values) > _MAX_FINDINGS_PER_REPORT:
        raise QualityAssessmentContractError("quality_report.warnings exceeds its bounded finding limit.")
    report["warnings"] = [_normalize_finding(item, label=f"quality_report.warnings[{index}]") for index, item in enumerate(warning_values)]
    criticals: list[dict[str, Any]] = []
    critical_values = _list(report.get("critical_violations"), "quality_report.critical_violations")
    if len(critical_values) > _MAX_FINDINGS_PER_REPORT:
        raise QualityAssessmentContractError("quality_report.critical_violations exceeds its bounded violation limit.")
    for index, item in enumerate(critical_values):
        violation = _mapping(item, f"quality_report.critical_violations[{index}]")
        allowed_critical = {"violation_id", "domain", "rule_id", "target_ref", "evidence_refs", "reason_code", "blocking", "canonical_hash"}
        if set(violation) - allowed_critical or violation.get("domain") not in QUALITY_DOMAIN_IDS:
            raise QualityAssessmentContractError("critical violation contract is invalid.")
        _require_id(violation.get("violation_id"), "critical_violation.violation_id")
        _require_id(violation.get("rule_id"), "critical_violation.rule_id")
        _require_id(violation.get("reason_code"), "critical_violation.reason_code")
        if violation.get("blocking") is not True:
            raise QualityAssessmentContractError("critical violations must always be blocking.")
        violation["target_ref"] = _typed_references([violation.get("target_ref")], "critical_violation.target_ref")[0]
        violation["evidence_refs"] = _typed_references(violation.get("evidence_refs"), "critical_violation.evidence_refs")
        hash_body = deepcopy(violation); hash_body.pop("canonical_hash", None)
        digest = canonical_hash(_canonicalize(hash_body))
        if violation.get("canonical_hash") not in {None, digest}:
            raise QualityAssessmentContractError("critical violation canonical_hash does not match its content.")
        violation["canonical_hash"] = digest
        criticals.append(_canonicalize(violation))
    report["critical_violations"] = criticals
    report["threshold_profile_ref"] = _reference(report.get("threshold_profile_ref"), "quality_report.threshold_profile_ref")
    # Gate evaluation belongs to TASK-12.8.  The report records only that no
    # final decision has been computed yet, including for high-score reports.
    if report.get("verdict") != "not_evaluated":
        raise QualityAssessmentContractError("TASK-12.2 quality reports must not compute a final verdict.")
    if report.get("routing_code") not in QUALITY_ROUTING_CODES:
        raise QualityAssessmentContractError("quality_report.routing_code is unsupported.")
    if criticals and report["routing_code"] == "PASS":
        raise QualityAssessmentContractError("A blocking critical violation may never use PASS routing.")
    report["rework_targets"] = _typed_references(report.get("rework_targets"), "quality_report.rework_targets")
    hash_body = deepcopy(report); hash_body.pop("canonical_hash", None)
    _require_bounded_report_size(hash_body)
    digest = canonical_hash(_canonicalize(hash_body))
    if report.get("canonical_hash") not in {None, digest}:
        raise QualityAssessmentContractError("quality_report.canonical_hash does not match its content.")
    report["canonical_hash"] = digest
    _reject_raw_body(report)
    return _canonicalize(report)


def quality_assessment_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """The one bounded serialization shared by report persistence and recovery."""
    normalized = normalize_quality_assessment_report(report)
    return {
        "quality_assessment": {
            "report_ref": {
                "id": normalized["report_id"], "version": normalized["report_version"],
                "hash": normalized["canonical_hash"],
            },
            "target_artifact": normalized["target_artifact"],
            "target_channels": normalized["target_channels"],
            "threshold_profile_ref": normalized["threshold_profile_ref"],
            "verdict": normalized["verdict"],
            "routing_code": normalized["routing_code"],
            "critical_violations": normalized["critical_violations"],
        }
    }
