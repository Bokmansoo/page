"""Immutable LG-12 Product Intake Golden Dataset v2 contract.

This successor dataset freezes the three first-class LG-12I intake modes.
It deliberately describes expected version identities and reference-only
source material; it does not fetch URLs, invoke OCR/VLM, normalize facts, or
run providers.  LG-12 Contract Golden Dataset v1 remains in its own module
and registry unchanged.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
from collections import Counter
from collections.abc import Mapping
from typing import Any

from src.schemas.lg12_golden_dataset import (
    GOLDEN_CATEGORIES,
    GOLDEN_DATASET_V1_CONTENT_HASH,
    GOLDEN_DATASET_VERSION,
    GoldenDatasetContractError,
    validate_golden_dataset,
)
from src.services.channel_export_service import supported_channel_keys
from src.services.product_intake_version_service import (
    UNIFIED_PRODUCT_INTAKE_SCHEMA_VERSION,
    canonical_unified_intake_input_hash,
    validate_unified_product_intake_envelope,
)
from src.services.prompt_intelligence_service import canonical_hash


PRODUCT_INTAKE_GOLDEN_DATASET_ID = "lg12-product-intake-golden-dataset"
PRODUCT_INTAKE_GOLDEN_DATASET_SCHEMA_VERSION = "lg12-product-intake-golden-dataset-v2"
PRODUCT_INTAKE_GOLDEN_CASE_SCHEMA_VERSION = "lg12-product-intake-golden-case-v2"
PRODUCT_INTAKE_GOLDEN_FIXTURE_SCHEMA_VERSION = "lg12-product-intake-fixture-v2"
PRODUCT_INTAKE_GOLDEN_DATASET_VERSION = "v2"
PRODUCT_INTAKE_GOLDEN_PARENT_VERSION = GOLDEN_DATASET_VERSION
PRODUCT_INTAKE_GOLDEN_INPUT_MODES = ("owned_product_url", "photo_only", "manual")


class ProductIntakeGoldenDatasetContractError(GoldenDatasetContractError):
    """Raised when the immutable Product Intake Golden Dataset is invalid."""


_CATEGORY_SLUGS = {
    GOLDEN_CATEGORIES[0]: "household",
    GOLDEN_CATEGORIES[1]: "beauty",
    GOLDEN_CATEGORIES[2]: "food",
    GOLDEN_CATEGORIES[3]: "fashion",
    GOLDEN_CATEGORIES[4]: "electronics",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _identity(kind: str, case_id: str, role: str, *, version: int = 1, digest: str | None = None) -> dict[str, Any]:
    return {
        "id": f"golden-intake:{kind}:{case_id}:{role}",
        "version": version,
        "hash": digest or canonical_hash({"kind": kind, "case_id": case_id, "role": role, "dataset": "v2"}),
    }


def _fixture_material(case_id: str, mode: str) -> dict[str, Any]:
    kind = {
        "owned_product_url": "url_capture_request",
        "photo_only": "asset_ref",
        "manual": "manual_payload_artifact",
    }[mode]
    payload = f"sellform/lg12/intake/v2/{case_id}/{mode}/frozen-source".encode("utf-8")
    digest = _sha256_bytes(payload)
    material: dict[str, Any] = {
        "schema_version": PRODUCT_INTAKE_GOLDEN_FIXTURE_SCHEMA_VERSION,
        "id": f"golden-intake-fixture:{case_id}:{mode}",
        "kind": kind,
        "version": 1,
        "hash": digest,
        "fixture_bytes_b64": base64.b64encode(payload).decode("ascii"),
        "source_kind": "frozen_fixture",
        "provenance_id": f"golden-intake-provenance:{case_id}:{mode}",
    }
    if mode == "photo_only":
        material["rights_status"] = "rights_confirmed"
        material["usage_status"] = "rights_confirmed"
    else:
        material["rights_status"] = "seller_confirmed"
    return material


def _source_reference(material: Mapping[str, Any]) -> dict[str, Any]:
    reference = {
        "id": material["id"],
        "kind": material["kind"],
        "version": material["version"],
        "hash": material["hash"],
        "schema_version": material["schema_version"],
    }
    if material["kind"] == "asset_ref":
        reference["rights_status"] = material["rights_status"]
    return reference


def _fact_reference(case_id: str, role: str, *, provenance: Mapping[str, Any]) -> dict[str, Any]:
    fact = _identity("fact", case_id, role)
    return {
        "fact_id": fact["id"],
        "fact_version": fact["version"],
        "fact_hash": fact["hash"],
        "provenance_ref": dict(provenance),
    }


def _case(*, category: str, mode: str, category_index: int) -> dict[str, Any]:
    slug = _CATEGORY_SLUGS[category]
    case_id = f"lg12-intake-v2:{slug}:{mode}"
    material = _fixture_material(case_id, mode)
    source_ref = _source_reference(material)
    channels_by_mode = {
        "owned_product_url": ["smartstore"],
        "photo_only": ["coupang"],
        "manual": ["smartstore", "coupang"],
    }
    generation_by_mode = {
        "owned_product_url": "quick",
        "photo_only": "expert",
        "manual": "quick",
    }
    requested_channels = channels_by_mode[mode]
    envelope = {
        "schema_version": UNIFIED_PRODUCT_INTAKE_SCHEMA_VERSION,
        "project_id": f"golden-intake-project:{slug}",
        "run_identity": {"run_id": f"golden-intake-run:{case_id}", "thread_id": f"golden-intake-run:{case_id}"},
        "input_mode": mode,
        "source_payload_refs": [source_ref],
        "requested_generation_mode": generation_by_mode[mode],
        "target_channels": list(requested_channels),
        "actor_workspace_identity": {
            "actor_id": f"golden-intake-actor:{slug}",
            "workspace_id": f"golden-intake-workspace:{slug}",
        },
        "created_at": "2026-08-18T00:00:00Z",
    }
    envelope["input_hash"] = canonical_unified_intake_input_hash(envelope)
    envelope = validate_unified_product_intake_envelope(envelope)

    source = _identity("ProductSourceSnapshotVersion", case_id, "source")
    evidence = _identity("evidence", case_id, "source-evidence")
    truth = _identity("ProductTruthVersion", case_id, "truth")
    confirmed_fact = _fact_reference(case_id, "confirmed", provenance=evidence)
    rejected_fact = _fact_reference(case_id, "rejected", provenance=evidence)
    unknown_fact = _fact_reference(case_id, "unknown", provenance=evidence)
    prohibited_inference = _fact_reference(case_id, "prohibited-inference", provenance=evidence)
    confirmation = _identity("SellerConfirmationVersion", case_id, "confirmation")
    brief = _identity("ProductCreativeBriefVersion", case_id, "brief")
    brand_kit = _identity("BrandKitVersion", case_id, "brand-kit")
    approved_fact_snapshot = _identity("approved-fact-snapshot", case_id, "facts")
    approved_asset_manifest = _identity("approved-asset-manifest", case_id, "assets")
    copy_artifact = _identity("copywriting", case_id, "copy")
    page_plan_artifact = _identity("page_planning", case_id, "page-plan")
    creative_direction = _identity("creative-direction", case_id, "manual-direction")

    source_expectation = {
        "source_snapshot": source,
        "source_fidelity": "fixture_verified",
        "rights_provenance": {
            "state": material["rights_status"],
            "provenance_id": material["provenance_id"],
        },
        "expected_source_refs": [source_ref],
        "fixture_materials": [material],
    }
    truth_expectation = {
        "identity": truth,
        "fact_candidates": [confirmed_fact],
        "unknown_facts": [unknown_fact],
        "prohibited_inferences": [prohibited_inference],
        "evidence_refs": [evidence],
    }
    confirmation_expectation = {
        "identity": confirmation,
        "confirmed_fact_refs": [confirmed_fact],
        "rejected_fact_refs": [rejected_fact],
        "unknown_fact_refs": [unknown_fact],
        "max_clarification_questions": 3,
        "clarification_questions": [
            {"question_id": f"golden-intake-question:{case_id}:1", "fact_id": unknown_fact["fact_id"]}
        ],
        "rights_confirmation_state": "confirmed",
    }
    master_references = {
        "source": source,
        "truth": truth,
        "confirmation": confirmation,
        "creative_brief": brief,
        "brand_kit": brand_kit,
        "evidence": evidence,
        "approved_fact_snapshot": approved_fact_snapshot,
        "approved_asset_manifest": approved_asset_manifest,
        "copy_artifact": copy_artifact,
        "page_plan_artifact": page_plan_artifact,
    }
    master_body = {
        "references": master_references,
        "target_channels": list(envelope["target_channels"]),
        "downstream_output_refs": [],
    }
    master = {
        "identity": _identity(
            "CommerceCreativeMasterVersion",
            case_id,
            "master",
            digest=canonical_hash(master_body),
        ),
        **master_body,
    }
    if mode == "owned_product_url":
        mode_expectation = {
            "source_ref_kind": "url_capture_request",
            "actual_url_fetch": False,
            "source_absent_fact_policy": "unknown_or_prohibited_only",
        }
    elif mode == "photo_only":
        mode_expectation = {
            "source_ref_kind": "asset_ref",
            "required_rights_status": "rights_confirmed",
            "actual_ocr_or_vlm_call": False,
            "observable_fact_candidates": [confirmed_fact],
            "unknown_or_prohibited_inferences": [unknown_fact, prohibited_inference],
        }
    else:
        mode_expectation = {
            "source_ref_kind": "manual_payload_artifact",
            "actual_manual_normalization": False,
            "seller_entered_fact_candidates": [confirmed_fact],
            "creative_direction_ref": creative_direction,
            "creative_direction_is_fact": False,
        }
    body = {
        "schema_version": PRODUCT_INTAKE_GOLDEN_CASE_SCHEMA_VERSION,
        "case_id": case_id,
        "category": category,
        "input_mode": mode,
        "provider_mode": "fake",
        "unified_intake_envelope_expectation": envelope,
        "source_expectation": source_expectation,
        "truth_expectation": truth_expectation,
        "seller_confirmation_expectation": confirmation_expectation,
        "commerce_creative_master_expectation": master,
        "mode_specific_expectation": mode_expectation,
    }
    return {**body, "case_hash": canonical_hash(body)}


def build_product_intake_golden_dataset_v2() -> dict[str, Any]:
    """Build the deterministic, reference-only LG-12I v2 fixture payload."""

    cases = [
        _case(category=category, mode=mode, category_index=index)
        for index, category in enumerate(GOLDEN_CATEGORIES)
        for mode in PRODUCT_INTAKE_GOLDEN_INPUT_MODES
    ]
    body = {
        "schema_version": PRODUCT_INTAKE_GOLDEN_DATASET_SCHEMA_VERSION,
        "dataset_id": PRODUCT_INTAKE_GOLDEN_DATASET_ID,
        "dataset_version": PRODUCT_INTAKE_GOLDEN_DATASET_VERSION,
        "parent_version": PRODUCT_INTAKE_GOLDEN_PARENT_VERSION,
        "parent_trusted_hash": GOLDEN_DATASET_V1_CONTENT_HASH,
        "previous_dataset_hash": GOLDEN_DATASET_V1_CONTENT_HASH,
        "categories": GOLDEN_CATEGORIES,
        "input_modes": PRODUCT_INTAKE_GOLDEN_INPUT_MODES,
        "cases": cases,
    }
    return {**body, "content_hash": canonical_hash(body)}


# Checked-in v2 trust anchor.  It is intentionally distinct from the v1
# registry: adding v2 must never rewrite the Contract Golden Dataset v1 anchor.
PRODUCT_INTAKE_GOLDEN_DATASET_V2_CONTENT_HASH = "66fc0cb7b9f39d0c562db85d0fef97227500d56c8aca6a6b9b1819e4e8388609"
TRUSTED_PRODUCT_INTAKE_GOLDEN_DATASET_VERSION_HASHES = {
    PRODUCT_INTAKE_GOLDEN_DATASET_VERSION: PRODUCT_INTAKE_GOLDEN_DATASET_V2_CONTENT_HASH,
}


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ProductIntakeGoldenDatasetContractError(f"{label} must be a lowercase SHA-256 digest.")
    return value


def _require_identity(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductIntakeGoldenDatasetContractError(f"{label} must be an identity reference.")
    identity = dict(value)
    if set(identity) != {"id", "version", "hash"}:
        raise ProductIntakeGoldenDatasetContractError(f"{label} must contain only id/version/hash.")
    if not isinstance(identity["id"], str) or not identity["id"]:
        raise ProductIntakeGoldenDatasetContractError(f"{label}.id is required.")
    if not isinstance(identity["version"], int) or identity["version"] < 1:
        raise ProductIntakeGoldenDatasetContractError(f"{label}.version must be a positive integer.")
    _require_sha256(identity["hash"], f"{label}.hash")
    return identity


def _validate_fixture_material(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductIntakeGoldenDatasetContractError(f"{label} must be a frozen fixture material.")
    material = dict(value)
    allowed = {
        "schema_version", "id", "kind", "version", "hash", "fixture_bytes_b64",
        "source_kind", "provenance_id", "rights_status", "usage_status",
    }
    if set(material) - allowed or material.get("schema_version") != PRODUCT_INTAKE_GOLDEN_FIXTURE_SCHEMA_VERSION:
        raise ProductIntakeGoldenDatasetContractError(f"{label} has an unsupported fixture contract.")
    for field in ("id", "kind", "source_kind", "provenance_id", "rights_status"):
        if not isinstance(material.get(field), str) or not material[field]:
            raise ProductIntakeGoldenDatasetContractError(f"{label}.{field} is required.")
    if material["source_kind"] != "frozen_fixture":
        raise ProductIntakeGoldenDatasetContractError(f"{label} must not use mutable or external source state.")
    if not isinstance(material.get("version"), int) or material["version"] < 1:
        raise ProductIntakeGoldenDatasetContractError(f"{label}.version must be positive.")
    digest = _require_sha256(material.get("hash"), f"{label}.hash")
    try:
        payload = base64.b64decode(str(material.get("fixture_bytes_b64") or ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProductIntakeGoldenDatasetContractError(f"{label}.fixture_bytes_b64 is invalid.") from exc
    if _sha256_bytes(payload) != digest:
        raise ProductIntakeGoldenDatasetContractError(f"{label} hash does not match frozen fixture bytes.")
    return material


def _validate_fact_refs(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ProductIntakeGoldenDatasetContractError(f"{label} must contain structured fact references.")
    result = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise ProductIntakeGoldenDatasetContractError(f"{label}[{index}] must be a fact reference.")
        ref = dict(raw)
        if set(ref) != {"fact_id", "fact_version", "fact_hash", "provenance_ref"}:
            raise ProductIntakeGoldenDatasetContractError(f"{label}[{index}] has unsupported fact fields.")
        if not isinstance(ref["fact_id"], str) or not ref["fact_id"]:
            raise ProductIntakeGoldenDatasetContractError(f"{label}[{index}].fact_id is required.")
        if not isinstance(ref["fact_version"], int) or ref["fact_version"] < 1:
            raise ProductIntakeGoldenDatasetContractError(f"{label}[{index}].fact_version is invalid.")
        _require_sha256(ref["fact_hash"], f"{label}[{index}].fact_hash")
        _require_identity(ref["provenance_ref"], f"{label}[{index}].provenance_ref")
        result.append(ref)
    return result


def _validate_case(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ProductIntakeGoldenDatasetContractError("Each Product Intake Golden case must be an object.")
    case = dict(value)
    required = {
        "schema_version", "case_id", "category", "input_mode", "provider_mode",
        "unified_intake_envelope_expectation", "source_expectation", "truth_expectation",
        "seller_confirmation_expectation", "commerce_creative_master_expectation",
        "mode_specific_expectation", "case_hash",
    }
    if set(case) != required or case.get("schema_version") != PRODUCT_INTAKE_GOLDEN_CASE_SCHEMA_VERSION:
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden case has an unsupported schema.")
    if not isinstance(case["case_id"], str) or not case["case_id"]:
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden case ID is required.")
    if case["category"] not in GOLDEN_CATEGORIES or case["input_mode"] not in PRODUCT_INTAKE_GOLDEN_INPUT_MODES:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} has an unsupported category or input mode.")
    if case["provider_mode"] != "fake":
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} must be a fake-provider fixture.")
    case_body = {key: value for key, value in case.items() if key != "case_hash"}
    if case["case_hash"] != canonical_hash(case_body):
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} case hash does not match canonical content.")

    envelope = validate_unified_product_intake_envelope(case["unified_intake_envelope_expectation"])
    if envelope["input_mode"] != case["input_mode"]:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} envelope input mode does not match its case.")
    if set(envelope["target_channels"]) - supported_channel_keys():
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} has unsupported production target channels.")

    source = case["source_expectation"]
    if not isinstance(source, Mapping) or set(source) != {
        "source_snapshot", "source_fidelity", "rights_provenance", "expected_source_refs", "fixture_materials"
    }:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} source expectation is incomplete.")
    _require_identity(source["source_snapshot"], f"{case['case_id']}.source_snapshot")
    if source["source_fidelity"] != "fixture_verified" or not isinstance(source["rights_provenance"], Mapping):
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} source fidelity/provenance is invalid.")
    if source["expected_source_refs"] != envelope["source_payload_refs"]:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} source refs must match its intake envelope.")
    if not isinstance(source["fixture_materials"], list) or len(source["fixture_materials"]) != len(envelope["source_payload_refs"]):
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} must pin each source ref to fixture bytes.")
    materials = [_validate_fixture_material(item, f"{case['case_id']}.fixture_material") for item in source["fixture_materials"]]
    material_identity = {(item["id"], item["kind"], item["version"], item["hash"]) for item in materials}
    for reference in envelope["source_payload_refs"]:
        if (reference["id"], reference["kind"], reference["version"], reference["hash"]) not in material_identity:
            raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} source ref does not match fixture bytes.")

    truth = case["truth_expectation"]
    if not isinstance(truth, Mapping) or set(truth) != {
        "identity", "fact_candidates", "unknown_facts", "prohibited_inferences", "evidence_refs"
    }:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} truth expectation is incomplete.")
    _require_identity(truth["identity"], f"{case['case_id']}.truth.identity")
    confirmed = _validate_fact_refs(truth["fact_candidates"], f"{case['case_id']}.truth.fact_candidates")
    unknown = _validate_fact_refs(truth["unknown_facts"], f"{case['case_id']}.truth.unknown_facts")
    prohibited = _validate_fact_refs(truth["prohibited_inferences"], f"{case['case_id']}.truth.prohibited_inferences")
    if not isinstance(truth["evidence_refs"], list) or not truth["evidence_refs"]:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} must pin evidence refs.")
    for evidence in truth["evidence_refs"]:
        _require_identity(evidence, f"{case['case_id']}.truth.evidence_ref")

    confirmation = case["seller_confirmation_expectation"]
    if not isinstance(confirmation, Mapping) or set(confirmation) != {
        "identity", "confirmed_fact_refs", "rejected_fact_refs", "unknown_fact_refs",
        "max_clarification_questions", "clarification_questions", "rights_confirmation_state",
    }:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} confirmation expectation is incomplete.")
    _require_identity(confirmation["identity"], f"{case['case_id']}.confirmation.identity")
    confirmed_states = _validate_fact_refs(confirmation["confirmed_fact_refs"], f"{case['case_id']}.confirmation.confirmed")
    rejected_states = _validate_fact_refs(confirmation["rejected_fact_refs"], f"{case['case_id']}.confirmation.rejected")
    unknown_states = _validate_fact_refs(confirmation["unknown_fact_refs"], f"{case['case_id']}.confirmation.unknown")
    state_ids = [item["fact_id"] for state in (confirmed_states, rejected_states, unknown_states) for item in state]
    if len(set(state_ids)) != len(state_ids):
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} cannot assign one fact to multiple seller states.")
    if [item["fact_id"] for item in confirmed_states] != [item["fact_id"] for item in confirmed]:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} confirmation must preserve approved fact provenance.")
    if [item["fact_id"] for item in unknown_states] != [item["fact_id"] for item in unknown]:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} confirmation must preserve unknown fact provenance.")
    if confirmation["max_clarification_questions"] != 3 or not isinstance(confirmation["clarification_questions"], list) or len(confirmation["clarification_questions"]) > 3:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} clarification contract must allow at most three questions.")
    if confirmation["rights_confirmation_state"] != "confirmed":
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} must pin its expected rights confirmation state.")

    master = case["commerce_creative_master_expectation"]
    if not isinstance(master, Mapping) or set(master) != {"identity", "references", "target_channels", "downstream_output_refs"}:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} master expectation is incomplete.")
    expected_master_keys = {
        "source", "truth", "confirmation", "creative_brief", "brand_kit", "evidence",
        "approved_fact_snapshot", "approved_asset_manifest", "copy_artifact", "page_plan_artifact",
    }
    if not isinstance(master["references"], Mapping) or set(master["references"]) != expected_master_keys:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} master must contain only complete identity references.")
    _require_identity(master["identity"], f"{case['case_id']}.master.identity")
    for name, reference in master["references"].items():
        _require_identity(reference, f"{case['case_id']}.master.{name}")
    if master["references"]["source"] != source["source_snapshot"] or master["references"]["truth"] != truth["identity"] or master["references"]["confirmation"] != confirmation["identity"]:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} master must pin source/truth/confirmation identity parity.")
    if master["target_channels"] != envelope["target_channels"]:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} master target channels must match intake channels.")
    if master["downstream_output_refs"] != []:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} initial Master cannot contain downstream output refs.")
    expected_master_hash = canonical_hash(
        {
            "references": master["references"],
            "target_channels": master["target_channels"],
            "downstream_output_refs": master["downstream_output_refs"],
        }
    )
    if master["identity"]["hash"] != expected_master_hash:
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} master identity must hash its immutable reference index.")

    mode_expectation = case["mode_specific_expectation"]
    if not isinstance(mode_expectation, Mapping):
        raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} mode expectation is required.")
    if case["input_mode"] == "owned_product_url":
        if mode_expectation.get("source_ref_kind") != "url_capture_request" or mode_expectation.get("actual_url_fetch") is not False or mode_expectation.get("source_absent_fact_policy") != "unknown_or_prohibited_only":
            raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} URL fixture must remain capture-only.")
    elif case["input_mode"] == "photo_only":
        if mode_expectation.get("source_ref_kind") != "asset_ref" or mode_expectation.get("required_rights_status") != "rights_confirmed" or mode_expectation.get("actual_ocr_or_vlm_call") is not False:
            raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} photo fixture must remain observation-only and rights-confirmed.")
    else:
        if mode_expectation.get("source_ref_kind") != "manual_payload_artifact" or mode_expectation.get("actual_manual_normalization") is not False or mode_expectation.get("creative_direction_is_fact") is not False:
            raise ProductIntakeGoldenDatasetContractError(f"{case['case_id']} manual fixture must keep creative direction separate from facts.")


def validate_product_intake_golden_dataset(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate v2's self-hash, trusted anchor, matrix, and lineage contract."""

    if not isinstance(document, Mapping):
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset must be an object.")
    data = copy.deepcopy(dict(document))
    if data.get("schema_version") != PRODUCT_INTAKE_GOLDEN_DATASET_SCHEMA_VERSION or data.get("dataset_id") != PRODUCT_INTAKE_GOLDEN_DATASET_ID:
        raise ProductIntakeGoldenDatasetContractError("Unsupported Product Intake Golden Dataset identity or schema.")
    if not isinstance(data.get("dataset_version"), str) or not data["dataset_version"]:
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset version is required.")
    stored_hash = _require_sha256(data.get("content_hash"), "dataset.content_hash")
    if stored_hash != canonical_hash({key: value for key, value in data.items() if key != "content_hash"}):
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset content hash does not match canonical payload.")
    trusted_hash = TRUSTED_PRODUCT_INTAKE_GOLDEN_DATASET_VERSION_HASHES.get(data["dataset_version"])
    if trusted_hash is not None and stored_hash != trusted_hash:
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset registered version does not match its trusted canonical hash.")
    if data.get("parent_version") != PRODUCT_INTAKE_GOLDEN_PARENT_VERSION or data.get("parent_trusted_hash") != GOLDEN_DATASET_V1_CONTENT_HASH or data.get("previous_dataset_hash") != GOLDEN_DATASET_V1_CONTENT_HASH:
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset must pin the trusted v1 parent lineage.")
    if tuple(data.get("categories") or ()) != GOLDEN_CATEGORIES or tuple(data.get("input_modes") or ()) != PRODUCT_INTAKE_GOLDEN_INPUT_MODES:
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset must pin the fixed category and mode matrix.")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) != 15:
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset v2 must contain exactly fifteen cases.")
    case_ids = [case.get("case_id") if isinstance(case, Mapping) else None for case in cases]
    if len(set(case_ids)) != len(case_ids) or any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden case IDs must be stable and globally unique.")
    matrix = Counter((case.get("category"), case.get("input_mode")) for case in cases if isinstance(case, Mapping))
    if any(matrix[(category, mode)] != 1 for category in GOLDEN_CATEGORIES for mode in PRODUCT_INTAKE_GOLDEN_INPUT_MODES):
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset must contain one case for every category and input mode.")
    for case in cases:
        _validate_case(case)
    return data


def load_product_intake_golden_dataset(version: str = PRODUCT_INTAKE_GOLDEN_DATASET_VERSION) -> dict[str, Any]:
    """Load the registered v2 fixture without reading mutable production state."""

    if version not in TRUSTED_PRODUCT_INTAKE_GOLDEN_DATASET_VERSION_HASHES:
        raise ProductIntakeGoldenDatasetContractError(f"Unknown Product Intake Golden Dataset version: {version}.")
    return validate_product_intake_golden_dataset(build_product_intake_golden_dataset_v2())


def validate_product_intake_dataset_successor(
    document: Mapping[str, Any], *, parent_document: Mapping[str, Any]
) -> dict[str, Any]:
    """Anchor a v2-shaped successor to the externally trusted v1 parent."""

    try:
        parent = validate_golden_dataset(parent_document)
    except GoldenDatasetContractError as exc:
        raise ProductIntakeGoldenDatasetContractError(
            "Product Intake Golden Dataset parent does not match the trusted v1 contract."
        ) from exc
    candidate = validate_product_intake_golden_dataset(document)
    if parent["dataset_version"] != PRODUCT_INTAKE_GOLDEN_PARENT_VERSION or parent["content_hash"] != GOLDEN_DATASET_V1_CONTENT_HASH:
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset parent does not match the trusted v1 contract.")
    if candidate["dataset_version"] == parent["dataset_version"]:
        raise ProductIntakeGoldenDatasetContractError("Product Intake Golden Dataset successor must use a new version.")
    return candidate
