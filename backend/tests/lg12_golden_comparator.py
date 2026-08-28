"""TASK-12.11 semantic Golden baseline support.

The comparator deliberately records immutable *meaning*, not test-run noise:
database UUIDs, temporary paths and timestamps are redacted before a fixture is
compared.  Ordered page/scene/rework sequences remain ordered; collections
whose contract is set-like are canonicalized before comparison.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


GOLDEN_ROOT = Path(__file__).parent / "golden" / "lg12" / "expected_reports"
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{12}$", re.I)
_UUID_FRAGMENT_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
_GENERATED_FINDING_ID_RE = re.compile(r"^lg12-[a-z0-9-]+:[0-9a-f]{32}$", re.I)
_GENERATED_PAGE_PLAN_ID_RE = re.compile(r"^page-plan:[0-9a-f]{24}$", re.I)
_VOLATILE_KEYS = {
    "created_at", "updated_at", "captured_at", "completed_at", "started_at",
    "timestamp", "file_path", "storage_path", "temporary_path", "download_url",
}
_ORDERLESS_LIST_KEYS = {
    "target_channels", "findings", "critical_violations", "submetrics",
    "source_refs", "evidence_refs", "asset_refs", "fact_refs", "warning_refs",
    "rework_targets", "blocking_reasons",
}
_ORDERED_LIST_KEYS = {
    "sections", "scene_plan", "section_scene_contract", "events", "attempt_ledger",
    "redirect_chain", "history", "route_history",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _redact_scalar(value: Any, *, key: str | None = None) -> Any:
    if not isinstance(value, str):
        return value
    if key == "id" and _GENERATED_FINDING_ID_RE.fullmatch(value):
        return "<generated-finding>"
    if key == "artifact_id" and _GENERATED_PAGE_PLAN_ID_RE.fullmatch(value):
        return "page-plan:<fixture>"
    if _UUID_RE.fullmatch(value):
        return "<uuid>"
    if _SHA256_RE.fullmatch(value):
        return "<sha256>"
    # Stable logical prefixes (for example ``quality-bar:<run uuid>:1``)
    # remain useful, while the per-test persisted UUID must not become a
    # baseline input.
    return _UUID_FRAGMENT_RE.sub("<uuid>", value)


def normalize_lg12_semantics(value: Any, *, key: str | None = None) -> Any:
    """Canonicalize only contractually unordered collections.

    This is intentionally not a generic list sort.  A changed section, scene,
    route or retry order is semantic drift and must remain visible in a diff.
    """

    if isinstance(value, dict):
        return {
            str(item_key): normalize_lg12_semantics(item_value, key=str(item_key))
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
            if str(item_key) not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        normalized = [normalize_lg12_semantics(item) for item in value]
        if key in _ORDERLESS_LIST_KEYS:
            return sorted(normalized, key=_canonical_json)
        # Explicitly leave ordered flows untouched, including unknown lists.
        return normalized
    # Fake-provider output/file SHA is deliberately deterministic and is a
    # semantic Golden signal. Other canonical row hashes may include an
    # ephemeral persisted UUID and are represented structurally above.
    if key in {"artifact_sha256", "provider_output_sha256"} and isinstance(value, str) and _SHA256_RE.fullmatch(value):
        return value
    return _redact_scalar(value, key=key)


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(normalize_lg12_semantics(value)).encode("utf-8")).hexdigest()


def _quality_bar_snapshot(quality_bar: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": quality_bar["verdict"],
        "routing_code": quality_bar["routing_code"],
        "blocking_domains": sorted({str(item.get("domain") or "") for item in quality_bar.get("blocking_reasons") or []}),
        "rework_target_types": sorted(
            {
                f"{str(item.get('domain') or '')}:{str(dict(item.get('target_ref') or {}).get('type') or '')}"
                for item in quality_bar.get("rework_targets") or []
            },
        ),
    }


def _domain_snapshot(domain: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain_id": domain["domain_id"],
        "evaluator_version": domain["evaluator_version"],
        "status": domain["status"],
        "score": domain["score"],
        "critical_count": domain["critical_count"],
        "finding_rule_ids": sorted(str(item["rule_id"]) for item in domain.get("findings") or []),
        "critical_rule_ids": sorted(str(item["rule_id"]) for item in domain.get("critical_violations") or []),
        "evaluation_hash": domain["evaluation_hash"],
        "frozen_target_ref": domain["frozen_target_ref"],
        "approved_asset_manifest_hash": domain["approved_asset_manifest_hash"],
    }


def build_lg12_snapshot(
    *,
    lineage: dict[str, Any],
    page: Any,
    report: Any,
    quality_bar: dict[str, Any],
    checkpoint: Any | None = None,
    initial_report: Any | None = None,
    initial_quality_bar: dict[str, Any] | None = None,
    scenario_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract the reference-only, persisted QA baseline required by TASK-12.11."""

    page_snapshot = dict(page.sections_json or {})
    canonical_input = dict(dict(page_snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {})
    manifest = dict(canonical_input.get("approved_asset_manifest") or {})
    planning_refs = dict(canonical_input.get("planning_refs") or {})
    domains = list(dict(report.report_json or {}).get("domain_scores") or [])
    quality = dict(getattr(checkpoint, "values", {}).get("quality") or {}) if checkpoint is not None else {}
    source = lineage["source"]
    truth = lineage["truth"]
    confirmation = lineage["confirmation"]
    brief = lineage["brief"]
    master = lineage["master"]
    brand_kit = lineage["brand_kit"]
    snapshot = {
        "schema_version": "lg12-quality-golden-baseline-v1",
        "lineage": {
            "source": {"id": source.id, "version": source.version, "hash": source.canonical_hash},
            "truth": {"id": truth.id, "version": truth.version, "hash": truth.canonical_hash},
            "confirmation": {"id": confirmation.id, "version": confirmation.version, "hash": confirmation.canonical_hash},
            "brief": {"id": brief.id, "version": brief.version, "hash": brief.output_hash},
            "master": {"id": master.id, "version": master.version, "hash": master.canonical_hash},
            "brand_kit": {"id": brand_kit.id, "version": brand_kit.version, "hash": brand_kit.content_hash},
        },
        "frozen_page": {
            "id": page.id,
            "snapshot_hash": page_snapshot["snapshot_hash"],
            "manifest_hash": manifest.get("manifest_hash"),
            "page_plan_ref": planning_refs.get("page_plan"),
            "brand_kit_ref": canonical_input.get("brand_kit_ref"),
            "section_ids": [str(item["section_id"]) for item in canonical_input.get("sections") or []],
            "artifact_sha256": next(
                (str(item.get("asset_content_hash")) for item in manifest.get("assets") or [] if item.get("asset_content_hash")),
                None,
            ),
        },
        "quality_report": {
            "id": report.id,
            "version": report.version,
            "canonical_hash": report.canonical_hash,
            "threshold_profile_ref": dict(report.report_json or {}).get("threshold_profile_ref"),
            "domains": sorted((_domain_snapshot(domain) for domain in domains), key=lambda item: item["domain_id"]),
        },
        "quality_bar": {
            **_quality_bar_snapshot(quality_bar),
            "canonical_hash": quality_bar["canonical_hash"],
        },
        "graph": {
            "stage": getattr(checkpoint, "values", {}).get("current_stage") if checkpoint is not None else None,
            "status": getattr(checkpoint, "values", {}).get("status") if checkpoint is not None else None,
            "attempt_ledger": quality.get("attempt_ledger") or [],
            "promotion_export_readiness": "ready" if getattr(checkpoint, "values", {}).get("current_stage") == "quality_promotion_ready" else "blocked",
        },
    }
    if initial_report is not None and initial_quality_bar is not None:
        snapshot["initial_quality"] = {
            "domains": sorted(
                (_domain_snapshot(domain) for domain in list(dict(initial_report.report_json or {}).get("domain_scores") or [])),
                key=lambda item: item["domain_id"],
            ),
            **_quality_bar_snapshot(initial_quality_bar),
        }
    if scenario_details:
        snapshot["scenario_details"] = scenario_details
    normalized = normalize_lg12_semantics(snapshot)
    return {**normalized, "semantic_hash": semantic_hash(normalized)}


def _first_diff(expected: Any, actual: Any, path: str = "$") -> str | None:
    if type(expected) is not type(actual):
        return f"{path}: expected {type(expected).__name__} {expected!r}, actual {type(actual).__name__} {actual!r}"
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                return f"{path}.{key}: unexpected actual value {actual[key]!r}"
            if key not in actual:
                return f"{path}.{key}: expected value missing ({expected[key]!r})"
            difference = _first_diff(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: expected list length {len(expected)}, actual {len(actual)}"
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            difference = _first_diff(left, right, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if expected != actual:
        return f"{path}: expected {expected!r}, actual {actual!r}"
    return None


def semantic_difference(expected: Any, actual: Any) -> str | None:
    """Public, descriptive detector used by Golden drift regression tests."""

    return _first_diff(normalize_lg12_semantics(expected), normalize_lg12_semantics(actual))


def assert_matches_golden(*, scenario: str, snapshot: dict[str, Any], update: bool = False) -> None:
    """Compare a scenario with its checked-in baseline, or explicitly refresh it."""

    path = GOLDEN_ROOT / f"{scenario}.json"
    actual = normalize_lg12_semantics(snapshot)
    if update:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    if not path.is_file():
        raise AssertionError(
            f"LG-12 Golden baseline missing: scenario={scenario!r}, path={path}. "
            "Refresh deliberately with pytest --update-lg12-golden."
        )
    expected = json.loads(path.read_text(encoding="utf-8"))
    difference = _first_diff(expected, actual)
    if difference:
        raise AssertionError(f"LG-12 Golden regression: scenario={scenario!r}, path={path}; {difference}")
