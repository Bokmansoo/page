"""TASK-12.12 final release-matrix checks over immutable TASK-12.11 baselines."""

from __future__ import annotations

import json

import pytest

from lg12_golden_comparator import GOLDEN_ROOT
from src.schemas.lg12_golden_dataset import load_golden_dataset
from src.schemas.lg12_product_intake_golden_dataset import load_product_intake_golden_dataset


pytestmark = pytest.mark.lg12_fake_quality_gate

REQUIRED_SCENARIOS = {
    "PASS": ("persisted-pass", "PASS", "PASS", "ready"),
    "COPY_REWORK_TO_PASS": ("copy-rework-pass", "PASS", "PASS", "ready"),
    "VISUAL_REWORK_TO_PASS": ("visual-rework-pass", "PASS", "PASS", "ready"),
    "PLAN_REWORK_TO_PASS": ("plan-rework-pass", "PASS", "PASS", "ready"),
    "IMAGE_REWORK_TO_PASS": ("image-rework-pass", "PASS", "PASS", "ready"),
    "NEEDS_REVIEW": ("needs-review", "NEEDS_REVIEW", "VISUAL_REWORK", "blocked"),
    "FAIL_POLICY_BLOCK": ("policy-fail", "FAIL", "BLOCKED_POLICY", "blocked"),
    "MAX_TWO_EXHAUSTED": ("retry-exhausted", "FAIL", "IMAGE_REWORK", "blocked"),
    "STALE_PROMOTION_EXPORT_BLOCKED": ("stale-gate", "PASS", "PASS", "ready"),
}
REQUIRED_DOMAINS = {
    "factual_rights_policy", "image_identity_quality", "korean_copy_readability",
    "layout_typography_brand_flow", "channel_preview_export_parity",
}


def _baseline(name: str) -> dict:
    return json.loads((GOLDEN_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def test_final_matrix_binds_both_intake_datasets_and_required_scenarios():
    v1, v2 = load_golden_dataset(), load_product_intake_golden_dataset()
    matrix = _baseline("dataset-scenario-matrix")
    assert matrix["contract_v1"]["version"] == v1["dataset_version"] == "v1"
    assert matrix["intake_v2"]["version"] == v2["dataset_version"] == "v2"
    assert len(v1["cases"]) == len(v2["cases"]) == 15
    assert set(matrix["coverage"]["modes"]) == {"owned_product_url", "photo_only", "manual"}
    assert len(matrix["coverage"]["categories"]) == 5
    assert matrix["coverage"]["scenarios"] == list(REQUIRED_SCENARIOS)


def test_final_matrix_baselines_cover_quality_routing_retry_and_export_contracts():
    for requirement_id, (scenario, verdict, route, readiness) in REQUIRED_SCENARIOS.items():
        snapshot = _baseline(scenario)
        assert snapshot["quality_bar"]["verdict"] == verdict, requirement_id
        assert snapshot["quality_bar"]["routing_code"] == route, requirement_id
        assert snapshot["graph"]["promotion_export_readiness"] == readiness, requirement_id
        assert snapshot["quality_report"]["threshold_profile_ref"], requirement_id
        assert {domain["domain_id"] for domain in snapshot["quality_report"]["domains"]} == REQUIRED_DOMAINS
    assert _baseline("image-rework-pass")["scenario_details"]["provider_output_sha256"]
    assert _baseline("needs-review")["scenario_details"] == {"export": False, "promotion": False, "review_required": True}
    assert _baseline("retry-exhausted")["scenario_details"]["exhausted"] is True
    assert _baseline("stale-gate")["scenario_details"]["blocked_operations"] == [
        "promotion", "standalone_export", "download", "generic_html", "generic_zip",
    ]
