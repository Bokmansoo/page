"""Immutable LG-12I Product Intake versions and bounded source adapters.

Routing remains in the compiled production LangGraph runtime.  This service
owns the durable version/hash contract and only the reference-based adapters
that create source snapshots; it never stores raw source bodies in graph state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import datetime
import re
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    Asset,
    BrandKitVersion,
    CommerceCreativeMasterVersion,
    FactSnapshot,
    ProductCreativeBriefVersion,
    ProductProject,
    ProductSourceSnapshotVersion,
    ProductTruthVersion,
    ReferenceInputVersion,
    SellerConfirmationVersion,
)
from src.services.prompt_intelligence_service import canonical_hash
from src.services.channel_export_service import supported_channel_keys
from src.services.commerce_policy import SELLER_OWNED_SOURCE_TYPES, resolved_asset_usage_status
from src.services.image_asset_inspector import inspect_asset
from src.services.asset_understanding_service import ANALYZER_VERSION, extract_ocr_blocks
from src.services.url_evidence_collector import (
    OwnedProductURLCapture,
    UnsafeSourceURLError,
    capture_owned_product_url,
    normalize_public_http_url,
)


PRODUCT_SOURCE_SNAPSHOT_SCHEMA_VERSION = "lg12i-product-source-snapshot-v1"
PRODUCT_TRUTH_SCHEMA_VERSION = "lg12i-product-truth-v1"
PRODUCT_TRUTH_NORMALIZATION_SCHEMA_VERSION = "lg12i-product-truth-normalization-v1"
# Seller-confirmation v3 adds seller-supplied value provenance to bounded
# clarification cycles.  v4 additionally pins a public-resume identity and
# answer-bundle hash, so an interrupted HTTP response can be replayed without
# applying a later cycle.  Keep older immutable payloads readable so their
# hashes remain verifiable after additive contract migrations.
LEGACY_SELLER_CONFIRMATION_SCHEMA_VERSION = "lg12i-seller-confirmation-v1"
SELLER_CONFIRMATION_CYCLE_SCHEMA_VERSION = "lg12i-seller-confirmation-v2"
SELLER_CONFIRMATION_VALUE_PROVENANCE_SCHEMA_VERSION = "lg12i-seller-confirmation-v3"
SELLER_CONFIRMATION_SCHEMA_VERSION = "lg12i-seller-confirmation-v4"
COMMERCE_CREATIVE_MASTER_SCHEMA_VERSION = "lg12i-commerce-creative-master-v1"
LG12I_CREATIVE_BRIEF_COMPILER_VERSION = "lg12i-product-creative-brief-v1"
LG12I_PENDING_PRODUCTION_ARTIFACT_SCHEMA_VERSION = "lg12i-pending-production-artifact-v1"
LG12I_APPROVED_ASSET_MANIFEST_SCHEMA_VERSION = "lg12i-approved-asset-manifest-v1"
UNIFIED_PRODUCT_INTAKE_SCHEMA_VERSION = "lg12i-unified-product-intake-v1"
UNIFIED_PRODUCT_INTAKE_MODES = frozenset({"owned_product_url", "photo_only", "manual"})
UNIFIED_PRODUCT_INTAKE_GENERATION_MODES = frozenset({"quick", "expert"})
_SHA256_CHARS = set("0123456789abcdef")
_MASTER_REFERENCE_KEYS = {"id", "version", "hash", "schema_version", "artifact_key"}
_DOWNSTREAM_KINDS = {"DetailPageVersion", "SocialKitVersion", "VideoProjectVersion"}
MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION = "lg12i-manual-input-artifact-v1"
MANUAL_SOURCE_CANDIDATES_SCHEMA_VERSION = "lg12i-manual-source-candidates-v1"
OWNED_PRODUCT_URL_CAPTURE_REQUEST_SCHEMA_VERSION = "lg12i-owned-product-url-capture-request-v1"
OWNED_PRODUCT_URL_CAPTURE_ARTIFACT_SCHEMA_VERSION = "lg12i-owned-product-url-capture-artifact-v1"
OWNED_PRODUCT_URL_SOURCE_CANDIDATES_SCHEMA_VERSION = "lg12i-owned-product-url-source-candidates-v1"
PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION = "lg12i-photo-observation-artifact-v1"
PHOTO_ONLY_SOURCE_CANDIDATES_SCHEMA_VERSION = "lg12i-photo-source-candidates-v1"
PHOTO_ONLY_VLM_EXTRACTOR_VERSION = "lg12i-deterministic-photo-observer-v1"
_MANUAL_METADATA_KEYS = {
    "manual_payload_schema_version",
    "seller_entered_fields",
    "unknown_fact_field_ids",
    "conflict_fact_candidates",
    "rights_confirmation_state",
}
_MANUAL_FIELD_KEYS = {"field_id", "classification", "label", "value", "unit"}
_MANUAL_CONFLICT_CANDIDATE_KEYS = {"field_id", "label", "observations"}
_MANUAL_CONFLICT_OBSERVATION_KEYS = {"value", "unit"}
_MANUAL_FIELD_CLASSIFICATIONS = {"fact_candidate", "creative_direction"}
_UNSAFE_MANUAL_CONTENT = re.compile(
    r"<\s*/?\s*(?:script|html|iframe|object|embed)\b|javascript\s*:|data\s*:\s*text/html",
    re.IGNORECASE,
)
_OWNED_URL_RIGHTS_STATES = frozenset({"seller_owned", "rights_confirmed", "unconfirmed"})
_PHOTO_ONLY_RIGHTS_STATES = frozenset({"seller_owned", "rights_confirmed", "unconfirmed"})
_PHOTO_PROHIBITED_INFERENCE_FIELDS = (
    "exact_weight", "material_grade", "certification", "performance",
    "ingredients", "waterproof_rating", "battery_capacity", "warranty_period",
    "usage_duration", "medical_claim", "unseen_components",
)
_PRICE_ADVANTAGE_CUE = re.compile(
    # Only explicit comparative/superlative price claims are prohibited here.
    # Observed price or promotion text (for example ``19,900원`` or ``10% 할인``)
    # deliberately does not match this taxonomy and remains an observation.
    r"(?:"
    r"동급\s*(?:제품\s*)?(?:대비|보다)\s*(?:더\s*)?(?:저렴(?:하다)?|싸다)|"
    r"(?:타사|경쟁사)\s*(?:제품\s*)?보다\s*(?:더\s*)?(?:저렴(?:하다)?|싸다)|"
    r"가장\s*(?:저렴(?:하다)?|싸다)|제일\s*(?:저렴(?:하다)?|싸다)|최저가|"
    r"가격\s*대비\s*최고|가성비\s*(?:최고|1위)"
    r")",
    re.IGNORECASE,
)
_PRICE_ADVANTAGE_POLICY_ID = "lg12i-prohibited-inference-price-advantage-v1"
_PHOTO_OCR_SUCCESS_STATUSES = frozenset({
    "success", "completed", "source_ocr", "local_tesseract", "ocr_no_text_detected", "no_text_detected",
})
_PHOTO_OCR_FAILURE_STATUSES = frozenset({
    "ocr_engine_not_configured", "ocr_image_not_available", "ocr_image_not_local",
    "ocr_engine_failed", "timeout", "invalid_image",
})
_PHOTO_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("qr_code", re.compile(r"(?:\bqr(?:\s*(?:code|scan))?\b|큐알)", re.IGNORECASE)),
    ("watermark", re.compile(r"(?:watermark|샘플|견본)", re.IGNORECASE)),
    ("third_party_logo", re.compile(r"(?:\blogo\b|상표|trademark)", re.IGNORECASE)),
    ("price_or_promotion", re.compile(r"(?:[₩$¥€]|\b\d{1,3}(?:,\d{3})*\s*원\b|할인|쿠폰|무료\s*배송|특가|\bsale\b|%\s*(?:off|할인))", re.IGNORECASE)),
    ("suspicious_foreign_brand_text", re.compile(r"(?:\b(?:official|brand|旗舰店|正品)\b|[A-Z]{3,}(?:\s+[A-Z]{2,})+)", re.IGNORECASE)),
)
_OWNED_URL_REQUEST_METADATA_KEYS = {
    "owned_product_url_capture_request_schema_version",
    "normalized_url",
    "rights_state",
    "provenance",
}
_UNORDERED_REFERENCE_COLLECTION_FIELDS = frozenset({
    "source_refs", "fact_refs", "evidence_refs", "unknown_refs", "conflict_refs",
    "prohibited_inference_refs", "confirmed_fact_refs", "rejected_fact_refs",
    "unknown_fact_refs", "evidence_artifacts", "asset_refs", "artifact_refs",
    "rights_confirmations", "target_channels", "downstream_outputs", "source_payload_refs",
})


class IntakeVersionContractError(ValueError):
    """An immutable LG-12I version or its lineage is invalid."""


class UnifiedProductIntakeContractError(ValueError):
    """A LG-12I intake envelope is unsafe or incomplete for routing."""


class ManualIntakeContractError(ValueError):
    """A seller-entered manual artifact cannot be used as an intake source."""


class OwnedProductURLIntakeContractError(ValueError):
    """An owned-product URL capture request or capture artifact is invalid."""


class SellerConfirmationContractError(ValueError):
    """A bounded seller-confirmation command is unsafe or inconsistent."""


VersionRow = TypeVar(
    "VersionRow",
    ProductSourceSnapshotVersion,
    ProductTruthVersion,
    SellerConfirmationVersion,
    CommerceCreativeMasterVersion,
)


def canonical_version_hash(payload: Mapping[str, Any]) -> str:
    """Hash a version payload without trusting or including its self-hash."""

    if not isinstance(payload, Mapping):
        raise IntakeVersionContractError("Version canonical payload must be an object.")
    return canonical_hash(_canonicalize_version_value({key: value for key, value in payload.items() if key != "canonical_hash"}))


def canonical_unified_intake_input_hash(payload: Mapping[str, Any]) -> str:
    """Return the idempotency identity for a routed intake request.

    A run/thread and creation time identify one durable execution, not the
    seller's requested intake content.  Excluding them keeps a retry of the
    same project input idempotent while the persisted envelope still pins its
    actual run/thread identity after creation.
    """

    if not isinstance(payload, Mapping):
        raise UnifiedProductIntakeContractError("Unified intake envelope must be an object.")
    identity_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"input_hash", "created_at", "run_identity"}
    }
    return canonical_hash(_canonicalize_version_value(identity_payload))


def _require_intake_reference(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UnifiedProductIntakeContractError(f"{label} must be a reference object.")
    item = deepcopy(dict(value))
    prohibited = {
        "raw_image_bytes", "image_bytes", "bytes", "raw_html", "html", "ocr_text",
        "raw_body", "body", "data_uri", "external_url", "script", "raw_html_body",
    }
    if prohibited.intersection(item):
        raise UnifiedProductIntakeContractError(f"{label} must contain only a safe artifact reference.")
    allowed = {"id", "kind", "version", "hash", "rights_status", "schema_version"}
    if set(item) - allowed:
        raise UnifiedProductIntakeContractError(f"{label} must not embed source content outside its stable reference identity.")
    if not isinstance(item.get("id"), str) or not item["id"]:
        raise UnifiedProductIntakeContractError(f"{label}.id is required.")
    if not isinstance(item.get("kind"), str) or not item["kind"]:
        raise UnifiedProductIntakeContractError(f"{label}.kind is required.")
    if not isinstance(item.get("version"), int) or item["version"] < 1:
        raise UnifiedProductIntakeContractError(f"{label}.version must be a positive integer.")
    _require_hash(item.get("hash"), f"{label}.hash")
    if any(isinstance(value, str) and len(value) > 4096 for value in item.values()):
        raise UnifiedProductIntakeContractError(f"{label} must not embed a large raw payload.")
    return item


def validate_unified_product_intake_envelope(
    payload: Mapping[str, Any], *, require_run_identity: bool = True
) -> dict[str, Any]:
    """Validate the reference-only LG-12I routing envelope.

    This is intentionally a contract boundary: it does not fetch a URL,
    inspect an image, normalize manual facts, or create any immutable source
    row.  Later adapter tasks consume the compact references it returns.
    """

    if not isinstance(payload, Mapping):
        raise UnifiedProductIntakeContractError("Unified intake envelope must be an object.")
    envelope = deepcopy(dict(payload))
    required = {
        "schema_version", "project_id", "input_mode", "source_payload_refs",
        "requested_generation_mode", "target_channels", "actor_workspace_identity",
        "input_hash", "created_at",
    }
    allowed = {*required, "run_identity"}
    unexpected = sorted(key for key in envelope if key not in allowed)
    if unexpected:
        raise UnifiedProductIntakeContractError(
            f"Unified intake envelope contains unsupported fields: {', '.join(unexpected)}."
        )
    missing = sorted(key for key in required if key not in envelope)
    if missing:
        raise UnifiedProductIntakeContractError(f"Unified intake envelope is missing: {', '.join(missing)}.")
    if envelope.get("schema_version") != UNIFIED_PRODUCT_INTAKE_SCHEMA_VERSION:
        raise UnifiedProductIntakeContractError("Unsupported unified intake schema_version.")
    if not isinstance(envelope.get("project_id"), str) or not envelope["project_id"]:
        raise UnifiedProductIntakeContractError("Unified intake project_id is required.")
    mode = envelope.get("input_mode")
    if mode not in UNIFIED_PRODUCT_INTAKE_MODES:
        raise UnifiedProductIntakeContractError("Unknown unified intake input_mode.")
    if envelope.get("requested_generation_mode") not in UNIFIED_PRODUCT_INTAKE_GENERATION_MODES:
        raise UnifiedProductIntakeContractError("requested_generation_mode must be quick or expert.")
    identity = envelope.get("actor_workspace_identity")
    if not isinstance(identity, Mapping) or not all(isinstance(identity.get(key), str) and identity[key] for key in ("actor_id", "workspace_id")):
        raise UnifiedProductIntakeContractError("actor_workspace_identity must pin actor_id and workspace_id.")
    if require_run_identity:
        run_identity = envelope.get("run_identity")
        if not isinstance(run_identity, Mapping) or not all(isinstance(run_identity.get(key), str) and run_identity[key] for key in ("run_id", "thread_id")):
            raise UnifiedProductIntakeContractError("run_identity must pin run_id and thread_id.")
        if run_identity["run_id"] != run_identity["thread_id"]:
            raise UnifiedProductIntakeContractError("Unified intake run_id and thread_id must match.")
    refs = envelope.get("source_payload_refs")
    if not isinstance(refs, list) or not refs:
        raise UnifiedProductIntakeContractError("source_payload_refs must contain at least one reference.")
    refs = [_require_intake_reference(item, f"source_payload_refs[{index}]") for index, item in enumerate(refs)]
    kinds = {str(item["kind"]).lower() for item in refs}
    if mode == "owned_product_url":
        if not kinds or any("url" not in kind and "capture" not in kind for kind in kinds):
            raise UnifiedProductIntakeContractError("owned_product_url accepts only URL/source capture request references.")
    if mode == "photo_only":
        if not 1 <= len(refs) <= 2:
            raise UnifiedProductIntakeContractError("photo_only requires one or two asset references.")
        eligible = [
            item for item in refs
            if "asset" in str(item["kind"]).lower()
            and item.get("rights_status") in _PHOTO_ONLY_RIGHTS_STATES
        ]
        if not eligible:
            raise UnifiedProductIntakeContractError(
                "photo_only requires a seller-owned, rights-confirmed, or unconfirmed asset reference."
            )
        if any("asset" not in kind for kind in kinds):
            raise UnifiedProductIntakeContractError("photo_only accepts only asset references.")
    if mode == "manual":
        if not kinds or any("manual" not in kind and "artifact" not in kind for kind in kinds):
            raise UnifiedProductIntakeContractError("manual accepts only manual payload artifact references.")
    channels = envelope.get("target_channels")
    if not isinstance(channels, list) or not channels or any(not isinstance(channel, str) or not channel for channel in channels):
        raise UnifiedProductIntakeContractError("target_channels must contain channel identities.")
    if len(set(channels)) != len(channels):
        raise UnifiedProductIntakeContractError("target_channels must not contain duplicates.")
    if any(channel not in supported_channel_keys() for channel in channels):
        raise UnifiedProductIntakeContractError("target_channels must use supported production channel identities.")
    # Channels are a set-like production target contract. Persist the
    # canonical order too, so a restart/projection does not preserve an
    # arbitrary request order for the same envelope identity.
    channels = sorted(channels)
    envelope["target_channels"] = channels
    if not isinstance(envelope.get("created_at"), str) or not envelope["created_at"]:
        raise UnifiedProductIntakeContractError("Unified intake created_at is required.")
    expected_hash = canonical_unified_intake_input_hash(envelope)
    if envelope.get("input_hash") != expected_hash:
        raise UnifiedProductIntakeContractError("Unified intake input_hash does not match canonical content.")
    envelope["source_payload_refs"] = refs
    return envelope


def _safe_manual_text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ManualIntakeContractError(f"{label} must be text.")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ManualIntakeContractError(f"{label} is required.")
    if len(normalized) > 4096:
        raise ManualIntakeContractError(f"{label} is too large for a manual source field.")
    if _UNSAFE_MANUAL_CONTENT.search(normalized):
        raise ManualIntakeContractError(f"{label} contains executable or raw HTML content.")
    return normalized


def _manual_field_id(value: Any, label: str) -> str:
    field_id = _safe_manual_text(value, label)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", field_id):
        raise ManualIntakeContractError(f"{label} is invalid.")
    return field_id


def _optional_manual_observation(value: Any, label: str) -> str | None:
    """Normalize an observed fact value without inventing a missing one."""

    if value is None:
        return None
    normalized = _safe_manual_text(value, label, allow_empty=True)
    return normalized or None


def normalize_manual_input_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the compact seller-entered metadata kept beside a manual artifact.

    The immutable artifact may retain a seller's original text for audit, but
    the graph receives only these bounded, structured candidate fields.  This
    deliberately does not infer, approve, or normalize any product fact.
    """

    if not isinstance(value, Mapping):
        raise ManualIntakeContractError("manual artifact metadata must be an object.")
    metadata = deepcopy(dict(value))
    unexpected = sorted(set(metadata) - _MANUAL_METADATA_KEYS)
    if unexpected:
        raise ManualIntakeContractError(
            "manual artifact metadata contains unsupported fields: " + ", ".join(unexpected) + "."
        )
    if metadata.get("manual_payload_schema_version") != MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION:
        raise ManualIntakeContractError("manual artifact metadata has an unsupported schema version.")
    fields = metadata.get("seller_entered_fields")
    if not isinstance(fields, list) or not fields:
        raise ManualIntakeContractError("manual artifact requires one or more seller_entered_fields.")
    normalized_fields: list[dict[str, Any]] = []
    fact_ids: set[str] = set()
    creative_ids: set[str] = set()
    for index, raw in enumerate(fields):
        if not isinstance(raw, Mapping):
            raise ManualIntakeContractError(f"seller_entered_fields[{index}] must be an object.")
        field = dict(raw)
        extras = sorted(set(field) - _MANUAL_FIELD_KEYS)
        if extras:
            raise ManualIntakeContractError(
                f"seller_entered_fields[{index}] contains unsupported fields: {', '.join(extras)}."
            )
        field_id = _manual_field_id(field.get("field_id"), f"seller_entered_fields[{index}].field_id")
        classification = field.get("classification")
        if classification not in _MANUAL_FIELD_CLASSIFICATIONS:
            raise ManualIntakeContractError(
                f"seller_entered_fields[{index}].classification must be fact_candidate or creative_direction."
            )
        normalized: dict[str, Any] = {
            "field_id": field_id,
            "classification": str(classification),
            "label": _safe_manual_text(field.get("label"), f"seller_entered_fields[{index}].label"),
        }
        if classification == "fact_candidate":
            normalized["value"] = _optional_manual_observation(
                field.get("value"), f"seller_entered_fields[{index}].value"
            )
        else:
            normalized["value"] = _safe_manual_text(
                field.get("value"), f"seller_entered_fields[{index}].value"
            )
        if field.get("unit") is not None:
            normalized["unit"] = _safe_manual_text(field["unit"], f"seller_entered_fields[{index}].unit")
        destination = fact_ids if classification == "fact_candidate" else creative_ids
        if field_id in destination:
            raise ManualIntakeContractError(f"seller_entered field {field_id} is duplicated.")
        destination.add(field_id)
        normalized_fields.append(normalized)
    overlap = fact_ids.intersection(creative_ids)
    if overlap:
        raise ManualIntakeContractError(
            "A seller-entered field cannot be both a fact candidate and creative direction: "
            + ", ".join(sorted(overlap))
            + "."
        )
    unknown_ids = metadata.get("unknown_fact_field_ids", [])
    if not isinstance(unknown_ids, list) or any(not isinstance(item, str) for item in unknown_ids):
        raise ManualIntakeContractError("unknown_fact_field_ids must be a list of field IDs.")
    normalized_unknown = sorted({_manual_field_id(item, "unknown_fact_field_id") for item in unknown_ids})
    if len(normalized_unknown) != len(unknown_ids):
        raise ManualIntakeContractError("unknown_fact_field_ids must not contain duplicates.")
    empty_fact_ids = {
        str(item["field_id"])
        for item in normalized_fields
        if item["classification"] == "fact_candidate" and item["value"] is None
    }
    unknown_ids_set = set(normalized_unknown).union(empty_fact_ids)
    declared_fact_ids = fact_ids.difference(empty_fact_ids)
    if set(normalized_unknown).intersection(declared_fact_ids.union(creative_ids)):
        raise ManualIntakeContractError(
            "unknown_fact_field_ids cannot duplicate a declared seller-entered field."
        )

    raw_conflicts = metadata.get("conflict_fact_candidates", [])
    if not isinstance(raw_conflicts, list):
        raise ManualIntakeContractError("conflict_fact_candidates must be a list.")
    normalized_conflicts: list[dict[str, Any]] = []
    conflict_ids: set[str] = set()
    for index, raw in enumerate(raw_conflicts):
        if not isinstance(raw, Mapping):
            raise ManualIntakeContractError(f"conflict_fact_candidates[{index}] must be an object.")
        candidate = dict(raw)
        extras = sorted(set(candidate) - _MANUAL_CONFLICT_CANDIDATE_KEYS)
        if extras:
            raise ManualIntakeContractError(
                f"conflict_fact_candidates[{index}] contains unsupported fields: {', '.join(extras)}."
            )
        field_id = _manual_field_id(candidate.get("field_id"), f"conflict_fact_candidates[{index}].field_id")
        if field_id in conflict_ids:
            raise ManualIntakeContractError(f"conflict fact candidate {field_id} is duplicated.")
        observations = candidate.get("observations")
        if not isinstance(observations, list) or len(observations) < 2:
            raise ManualIntakeContractError(
                f"conflict_fact_candidates[{index}].observations requires at least two observations."
            )
        normalized_observations: list[dict[str, str]] = []
        seen_observations: set[tuple[str, str]] = set()
        for observation_index, raw_observation in enumerate(observations):
            if not isinstance(raw_observation, Mapping):
                raise ManualIntakeContractError(
                    f"conflict_fact_candidates[{index}].observations[{observation_index}] must be an object."
                )
            observation = dict(raw_observation)
            observation_extras = sorted(set(observation) - _MANUAL_CONFLICT_OBSERVATION_KEYS)
            if observation_extras:
                raise ManualIntakeContractError(
                    f"conflict_fact_candidates[{index}].observations[{observation_index}] contains unsupported fields: "
                    + ", ".join(observation_extras)
                    + "."
                )
            normalized_observation = {
                "value": _safe_manual_text(
                    observation.get("value"),
                    f"conflict_fact_candidates[{index}].observations[{observation_index}].value",
                ),
            }
            if observation.get("unit") is not None:
                normalized_observation["unit"] = _safe_manual_text(
                    observation["unit"],
                    f"conflict_fact_candidates[{index}].observations[{observation_index}].unit",
                )
            key = (normalized_observation["value"], normalized_observation.get("unit", ""))
            if key in seen_observations:
                raise ManualIntakeContractError(
                    f"conflict_fact_candidates[{index}] contains duplicate observations."
                )
            seen_observations.add(key)
            normalized_observations.append(normalized_observation)
        conflict_ids.add(field_id)
        normalized_conflicts.append({
            "field_id": field_id,
            "label": _safe_manual_text(
                candidate.get("label"), f"conflict_fact_candidates[{index}].label"
            ),
            "observations": sorted(
                normalized_observations,
                key=lambda item: (item["value"], item.get("unit", "")),
            ),
        })
    overlap_states = (
        conflict_ids.intersection(declared_fact_ids)
        .union(conflict_ids.intersection(unknown_ids_set))
        .union(conflict_ids.intersection(creative_ids))
    )
    if overlap_states:
        raise ManualIntakeContractError(
            "A seller-entered fact cannot be both observed, unknown, or conflict: "
            + ", ".join(sorted(overlap_states))
            + "."
        )
    rights = metadata.get("rights_confirmation_state", "unconfirmed")
    if rights == "unknown":  # Normalize the pre-TASK-12I.3 spelling without granting approval.
        rights = "unconfirmed"
    if rights not in {"confirmed", "unconfirmed", "conflict"}:
        raise ManualIntakeContractError("rights_confirmation_state must be confirmed, unconfirmed, or conflict.")
    return {
        "manual_payload_schema_version": MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION,
        "seller_entered_fields": sorted(
            normalized_fields,
            key=lambda item: (item["classification"], item["field_id"]),
        ),
        "unknown_fact_field_ids": sorted(unknown_ids_set),
        "conflict_fact_candidates": sorted(normalized_conflicts, key=lambda item: item["field_id"]),
        "rights_confirmation_state": rights,
    }


def canonical_manual_input_artifact_hash(*, raw_body: str, source_metadata: Mapping[str, Any]) -> str:
    """Pin both manual metadata and the audit body without copying either to graph state."""

    return canonical_hash(
        {
            "kind": "manual_product_input_artifact",
            "raw_body": _safe_manual_text(raw_body, "manual raw_body", allow_empty=True),
            "source_metadata": normalize_manual_input_metadata(source_metadata),
        }
    )


def create_manual_input_artifact(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    created_by: str,
    raw_body: str,
    source_metadata: Mapping[str, Any],
) -> ReferenceInputVersion:
    """Create the immutable-reference-shaped artifact consumed by the manual adapter.

    This helper only fixes seller input into a version/hash.  It does not
    create a source snapshot, truth, confirmation, brief, or provider work.
    """

    normalized_metadata = normalize_manual_input_metadata(source_metadata)
    normalized_body = _safe_manual_text(raw_body, "manual raw_body", allow_empty=True)
    latest = (
        db.query(ReferenceInputVersion)
        .filter_by(project_id=project_id)
        .order_by(ReferenceInputVersion.version.desc())
        .first()
    )
    row = ReferenceInputVersion(
        workspace_id=workspace_id,
        project_id=project_id,
        version=int(latest.version) + 1 if latest is not None else 1,
        input_kind="text",
        content_text=normalized_body or None,
        source_metadata=normalized_metadata,
        rights_status="unverified",
        usage_scope="analysis_only",
        content_hash=canonical_manual_input_artifact_hash(
            raw_body=normalized_body,
            source_metadata=normalized_metadata,
        ),
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def _manual_artifact_reference(row: ReferenceInputVersion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "version": int(row.version),
        "hash": str(row.content_hash),
        "schema_version": MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION,
        "artifact_key": "manual_product_input",
    }


def _resolve_manual_input_artifact(
    db: Session, *, workspace_id: str, project_id: str, actor_id: str, source_refs: Sequence[Mapping[str, Any]]
) -> tuple[ReferenceInputVersion, dict[str, Any], dict[str, Any]]:
    if len(source_refs) != 1:
        raise ManualIntakeContractError("manual intake requires exactly one immutable manual artifact reference.")
    source_ref = dict(source_refs[0])
    artifact = (
        db.query(ReferenceInputVersion)
        .filter_by(
            id=str(source_ref.get("id") or ""),
            workspace_id=workspace_id,
            project_id=project_id,
        )
        .one_or_none()
    )
    if artifact is None:
        raise ManualIntakeContractError("manual artifact does not belong to this workspace and project.")
    if artifact.input_kind != "text" or artifact.created_by != actor_id:
        raise ManualIntakeContractError("manual artifact is not a seller-entered text artifact for this actor.")
    metadata = normalize_manual_input_metadata(dict(artifact.source_metadata or {}))
    body = str(artifact.content_text or "")
    expected_hash = canonical_manual_input_artifact_hash(raw_body=body, source_metadata=metadata)
    actual_reference = _manual_artifact_reference(artifact)
    if artifact.content_hash != expected_hash:
        raise ManualIntakeContractError("manual artifact content hash does not match its immutable payload.")
    if (
        source_ref.get("version") != actual_reference["version"]
        or source_ref.get("hash") != actual_reference["hash"]
    ):
        raise ManualIntakeContractError("manual artifact ID/version/hash does not match the persisted artifact.")
    return artifact, actual_reference, metadata


def _find_existing_manual_source_snapshot(
    db: Session, *, project_id: str, artifact_reference: Mapping[str, Any]
) -> ProductSourceSnapshotVersion | None:
    for row in (
        db.query(ProductSourceSnapshotVersion)
        .filter_by(project_id=project_id, input_mode="manual")
        .order_by(ProductSourceSnapshotVersion.version.asc())
        .all()
    ):
        if row.source_refs_json != [dict(artifact_reference)]:
            continue
        if dict(row.provenance_json or {}).get("manual_artifact_ref") != dict(artifact_reference):
            continue
        validate_immutable_version(db, row)
        return row
    return None


def adapt_manual_input_to_source_snapshot(
    db: Session,
    *,
    run: AgentRun,
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    """Use a pinned manual artifact to create/reuse an immutable source snapshot.

    Returned graph data contains bounded field candidates and immutable
    identities only.  It never exposes the manual artifact's free-form body,
    and it intentionally stops before ProductTruth normalization.
    """

    validated = validate_unified_product_intake_envelope(envelope)
    if validated["input_mode"] != "manual":
        raise ManualIntakeContractError("manual adapter accepts only manual input mode.")
    if (
        run.id != validated["run_identity"]["run_id"]
        or run.workspace_id != validated["actor_workspace_identity"]["workspace_id"]
        or run.project_id != validated["project_id"]
    ):
        raise ManualIntakeContractError("manual intake envelope identity does not match its graph run.")
    actor_id = str(validated["actor_workspace_identity"]["actor_id"])
    _artifact, artifact_reference, metadata = _resolve_manual_input_artifact(
        db,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        actor_id=actor_id,
        source_refs=validated["source_payload_refs"],
    )
    snapshot = _find_existing_manual_source_snapshot(
        db,
        project_id=run.project_id,
        artifact_reference=artifact_reference,
    )
    if snapshot is None:
        snapshot = create_product_source_snapshot_version(
            db,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            creator_run_id=run.id,
            created_by=actor_id,
            input_mode="manual",
            source_refs=[artifact_reference],
            provenance={
                "source": "seller_entered",
                "manual_artifact_ref": artifact_reference,
            },
            rights={
                "provenance": "seller_entered",
                "confirmation_state": metadata["rights_confirmation_state"],
                "final_use_status": "not_approved",
            },
            source_fidelity={
                "source_kind": "manual_artifact",
                "fact_candidate_count": sum(
                    item["classification"] == "fact_candidate" and item["value"] is not None
                    for item in metadata["seller_entered_fields"]
                ),
                "creative_direction_count": sum(
                    item["classification"] == "creative_direction"
                    for item in metadata["seller_entered_fields"]
                ),
                "unknown_fact_field_ids": list(metadata["unknown_fact_field_ids"]),
                "conflict_fact_field_ids": [
                    item["field_id"] for item in metadata["conflict_fact_candidates"]
                ],
            },
        )
        # The immutable input must outlive the next graph checkpoint.  The
        # node's projection can be replayed from checkpoint history later.
        db.commit()
        db.refresh(snapshot)
    fact_candidates: list[dict[str, Any]] = []
    unknown_candidates: list[dict[str, Any]] = []
    creative_directions: list[dict[str, Any]] = []
    unknown_ids = set(metadata["unknown_fact_field_ids"])
    for field in metadata["seller_entered_fields"]:
        base = {
            **field,
            "provenance": "seller_entered",
            "source_artifact_ref": artifact_reference,
        }
        if field["classification"] == "fact_candidate":
            if field["value"] is None:
                unknown_candidates.append({
                    **base,
                    "observed_value": None,
                    "observation_state": "unknown",
                    "approval_status": "not_approved",
                })
            else:
                fact_candidates.append({
                    **base,
                    "observed_value": field["value"],
                    "observation_state": "candidate_not_approved",
                    "approval_status": "candidate_not_approved",
                })
        else:
            creative_directions.append({**base, "fact_promotion_status": "prohibited"})
    for field_id in sorted(unknown_ids.difference(item["field_id"] for item in unknown_candidates)):
        unknown_candidates.append({
            "field_id": field_id,
            "value": None,
            "observed_value": None,
            "observation_state": "unknown",
            "approval_status": "not_approved",
            "provenance": "seller_entered",
            "source_artifact_ref": artifact_reference,
        })
    conflict_candidates = []
    for candidate in metadata["conflict_fact_candidates"]:
        conflict_candidates.append({
            "field_id": candidate["field_id"],
            "label": candidate["label"],
            # A conflict intentionally has no selected scalar value.  The
            # individual seller observations below are the complete source
            # record for a later truth/confirmation stage.
            "observed_value": None,
            "observation_state": "conflict",
            "approval_status": "not_approved",
            "provenance": "seller_entered",
            "source_artifact_ref": artifact_reference,
            "observations": [
                {
                    **observation,
                    "observed_value": observation["value"],
                    "provenance": "seller_entered",
                    "source_artifact_ref": artifact_reference,
                }
                for observation in candidate["observations"]
            ],
        })
    unknown_candidates.sort(key=lambda item: str(item["field_id"]))
    return {
        "schema_version": MANUAL_SOURCE_CANDIDATES_SCHEMA_VERSION,
        "source_snapshot": _row_reference(snapshot),
        "manual_artifact_ref": artifact_reference,
        "fact_candidates": fact_candidates,
        "unknown_candidates": unknown_candidates,
        "conflict_candidates": conflict_candidates,
        "creative_directions": creative_directions,
        "unknown_fact_field_ids": list(metadata["unknown_fact_field_ids"]),
        "rights": {
            "provenance": "seller_entered",
            "confirmation_state": metadata["rights_confirmation_state"],
            "final_use_status": "not_approved",
        },
    }


def _safe_owned_url_text(value: Any, label: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str):
        raise OwnedProductURLIntakeContractError(f"{label} must be text.")
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise OwnedProductURLIntakeContractError(f"{label} is too large for an owned URL capture observation.")
    return normalized


def normalize_owned_product_url_request_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the immutable request that distinguishes product URLs from LG-7 references."""

    if not isinstance(value, Mapping):
        raise OwnedProductURLIntakeContractError("owned product URL request metadata must be an object.")
    metadata = deepcopy(dict(value))
    unexpected = sorted(set(metadata) - _OWNED_URL_REQUEST_METADATA_KEYS)
    if unexpected:
        raise OwnedProductURLIntakeContractError(
            "owned product URL request metadata contains unsupported fields: " + ", ".join(unexpected) + "."
        )
    if metadata.get("owned_product_url_capture_request_schema_version") != OWNED_PRODUCT_URL_CAPTURE_REQUEST_SCHEMA_VERSION:
        raise OwnedProductURLIntakeContractError("owned product URL request has an unsupported schema version.")
    normalized_url = normalize_public_http_url(str(metadata.get("normalized_url") or ""))
    rights_state = metadata.get("rights_state")
    if rights_state not in _OWNED_URL_RIGHTS_STATES:
        raise OwnedProductURLIntakeContractError("owned product URL rights_state is unsupported.")
    if metadata.get("provenance") != "seller_submitted_owned_product_url":
        raise OwnedProductURLIntakeContractError("owned product URL provenance must be seller_submitted_owned_product_url.")
    return {
        "owned_product_url_capture_request_schema_version": OWNED_PRODUCT_URL_CAPTURE_REQUEST_SCHEMA_VERSION,
        "normalized_url": normalized_url,
        "rights_state": str(rights_state),
        "provenance": "seller_submitted_owned_product_url",
    }


def canonical_owned_product_url_capture_request_hash(*, normalized_url: str, source_metadata: Mapping[str, Any]) -> str:
    metadata = normalize_owned_product_url_request_metadata(source_metadata)
    if metadata["normalized_url"] != normalize_public_http_url(normalized_url):
        raise OwnedProductURLIntakeContractError("owned product URL request URL and metadata identity do not match.")
    return canonical_hash({
        "kind": "owned_product_url_capture_request",
        "normalized_url": metadata["normalized_url"],
        "source_metadata": metadata,
    })


def create_owned_product_url_capture_request(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    created_by: str,
    source_url: str,
    source_metadata: Mapping[str, Any],
) -> ReferenceInputVersion:
    """Pin a seller-owned product URL request without invoking remote capture.

    The request row is intentionally an analysis-only reference.  It is not a
    LG-7 inspiration/reference input, and it cannot become a final-use asset.
    """

    metadata = normalize_owned_product_url_request_metadata(source_metadata)
    normalized_url = normalize_public_http_url(source_url)
    if metadata["normalized_url"] != normalized_url:
        raise OwnedProductURLIntakeContractError("owned product URL request URL does not match normalized_url metadata.")
    content_hash = canonical_owned_product_url_capture_request_hash(
        normalized_url=normalized_url,
        source_metadata=metadata,
    )
    existing = (
        db.query(ReferenceInputVersion)
        .filter_by(
            workspace_id=workspace_id,
            project_id=project_id,
            created_by=created_by,
            content_hash=content_hash,
        )
        .order_by(ReferenceInputVersion.version.asc())
        .first()
    )
    if existing is not None:
        if (
            existing.input_kind != "url"
            or existing.source_url != normalized_url
            or existing.content_text
            or dict(existing.source_metadata or {}) != metadata
            or existing.usage_scope != "analysis_only"
        ):
            raise OwnedProductURLIntakeContractError("owned product URL request conflicts with its immutable hash.")
        return existing
    latest = (
        db.query(ReferenceInputVersion)
        .filter_by(project_id=project_id)
        .order_by(ReferenceInputVersion.version.desc())
        .first()
    )
    row = ReferenceInputVersion(
        workspace_id=workspace_id,
        project_id=project_id,
        version=int(latest.version) + 1 if latest is not None else 1,
        input_kind="url",
        source_url=normalized_url,
        content_text=None,
        source_metadata=metadata,
        # Keep the existing reference model's field for discovery/auditing;
        # the dedicated metadata field is the LG-12I source-level rights SoT.
        rights_status="seller_owned" if metadata["rights_state"] == "seller_owned" else "unverified",
        usage_scope="analysis_only",
        content_hash=content_hash,
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def _owned_capture_request_reference(row: ReferenceInputVersion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "version": int(row.version),
        "hash": str(row.content_hash),
        "schema_version": OWNED_PRODUCT_URL_CAPTURE_REQUEST_SCHEMA_VERSION,
        "artifact_key": "owned_product_url_capture_request",
    }


def _resolve_owned_product_url_capture_request(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    actor_id: str,
    source_refs: Sequence[Mapping[str, Any]],
) -> tuple[ReferenceInputVersion, dict[str, Any], dict[str, Any]]:
    if len(source_refs) != 1:
        raise OwnedProductURLIntakeContractError("owned product URL intake requires exactly one capture request reference.")
    source_ref = dict(source_refs[0])
    request = (
        db.query(ReferenceInputVersion)
        .filter_by(id=str(source_ref.get("id") or ""), workspace_id=workspace_id, project_id=project_id)
        .one_or_none()
    )
    if request is None:
        raise OwnedProductURLIntakeContractError("owned product URL capture request does not belong to this workspace and project.")
    if request.input_kind != "url" or request.created_by != actor_id or request.content_text:
        raise OwnedProductURLIntakeContractError("reference input is not an owned product URL capture request for this actor.")
    metadata = normalize_owned_product_url_request_metadata(dict(request.source_metadata or {}))
    if not request.source_url or metadata["normalized_url"] != normalize_public_http_url(request.source_url):
        raise OwnedProductURLIntakeContractError("owned product URL capture request URL identity is invalid.")
    expected_hash = canonical_owned_product_url_capture_request_hash(
        normalized_url=request.source_url,
        source_metadata=metadata,
    )
    actual_reference = _owned_capture_request_reference(request)
    if request.content_hash != expected_hash:
        raise OwnedProductURLIntakeContractError("owned product URL capture request hash does not match its immutable payload.")
    if (
        source_ref.get("version") != actual_reference["version"]
        or source_ref.get("hash") != actual_reference["hash"]
        or source_ref.get("schema_version") not in {None, OWNED_PRODUCT_URL_CAPTURE_REQUEST_SCHEMA_VERSION}
        or source_ref.get("kind") != "owned_product_url_capture_request"
    ):
        raise OwnedProductURLIntakeContractError("owned product URL capture request ID/version/hash does not match the persisted artifact.")
    return request, actual_reference, metadata


def validate_owned_product_url_capture_request_reference(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    actor_id: str,
    source_refs: Sequence[Mapping[str, Any]],
) -> None:
    """Validate a durable owned URL request before an AgentRun is allocated."""

    _resolve_owned_product_url_capture_request(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        actor_id=actor_id,
        source_refs=source_refs,
    )


def _bounded_capture_observation(value: str, *, limit: int) -> str:
    return " ".join(value.split())[:limit]


def _owned_capture_artifact_payload(
    *,
    request_reference: Mapping[str, Any],
    rights_state: str,
    capture: OwnedProductURLCapture,
) -> dict[str, Any]:
    """Build a hashable, bounded observation record without retaining HTML."""

    return {
        "kind": "owned_product_url_capture_artifact",
        "capture_request_ref": dict(request_reference),
        "normalized_url": capture.normalized_url,
        "final_url": capture.final_url,
        "redirect_chain": list(capture.redirect_chain),
        "captured_at": capture.captured_at,
        "capture_version": capture.capture_version,
        "parser_version": capture.parser_version,
        "source_content_hash": capture.source_content_hash,
        "rights_state": rights_state,
        "observations": {
            "title": _bounded_capture_observation(capture.title, limit=512),
            "description": _bounded_capture_observation(capture.description, limit=2048),
            "image_urls": list(capture.image_urls[:50]),
            "specs": [
                {
                    "label": _bounded_capture_observation(str(item.get("label") or ""), limit=256),
                    "value": _bounded_capture_observation(str(item.get("value") or ""), limit=512),
                }
                for item in capture.specs[:100]
            ],
        },
    }


def canonical_owned_product_url_capture_artifact_hash(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise OwnedProductURLIntakeContractError("owned product URL capture artifact must be an object.")
    if payload.get("kind") != "owned_product_url_capture_artifact":
        raise OwnedProductURLIntakeContractError("owned product URL capture artifact kind is invalid.")
    _require_hash(payload.get("source_content_hash"), "capture.source_content_hash")
    return canonical_hash(_canonicalize_version_value(dict(payload)))


def _capture_artifact_reference(row: ReferenceInputVersion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "version": int(row.version),
        "hash": str(row.content_hash),
        "schema_version": OWNED_PRODUCT_URL_CAPTURE_ARTIFACT_SCHEMA_VERSION,
        "artifact_key": "owned_product_url_capture_artifact",
    }


def _create_owned_product_url_capture_artifact(
    db: Session,
    *,
    request: ReferenceInputVersion,
    request_reference: Mapping[str, Any],
    rights_state: str,
    capture: OwnedProductURLCapture,
) -> tuple[ReferenceInputVersion, dict[str, Any], dict[str, Any]]:
    payload = _owned_capture_artifact_payload(
        request_reference=request_reference,
        rights_state=rights_state,
        capture=capture,
    )
    content_hash = canonical_owned_product_url_capture_artifact_hash(payload)
    existing = (
        db.query(ReferenceInputVersion)
        .filter_by(project_id=request.project_id, content_hash=content_hash)
        .order_by(ReferenceInputVersion.version.asc())
        .first()
    )
    if existing is not None:
        if dict(existing.source_metadata or {}) != payload or existing.usage_scope != "analysis_only":
            raise OwnedProductURLIntakeContractError("owned product URL capture artifact conflicts with its immutable hash.")
        return existing, _capture_artifact_reference(existing), payload
    latest = (
        db.query(ReferenceInputVersion)
        .filter_by(project_id=request.project_id)
        .order_by(ReferenceInputVersion.version.desc())
        .first()
    )
    artifact = ReferenceInputVersion(
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        version=int(latest.version) + 1 if latest is not None else 1,
        input_kind="url",
        source_url=capture.final_url,
        content_text=None,
        source_metadata=payload,
        rights_status="seller_owned" if rights_state == "seller_owned" else "unverified",
        usage_scope="analysis_only",
        content_hash=content_hash,
        created_by=request.created_by,
    )
    db.add(artifact)
    db.flush()
    return artifact, _capture_artifact_reference(artifact), payload


def _capture_observation_reference(
    artifact_reference: Mapping[str, Any], *, artifact_key: str, content: Any
) -> dict[str, Any]:
    return {
        "id": str(artifact_reference["id"]),
        "version": int(artifact_reference["version"]),
        "hash": canonical_hash(content),
        "schema_version": OWNED_PRODUCT_URL_CAPTURE_ARTIFACT_SCHEMA_VERSION,
        "artifact_key": artifact_key,
    }


def _owned_product_url_source_input_hash(
    *,
    capture: OwnedProductURLCapture,
    rights_state: str,
    capture_request_reference: Mapping[str, Any],
    capture_artifact_reference: Mapping[str, Any],
    observations: Mapping[str, Any],
    title_meta_reference: Mapping[str, Any],
    image_observation_references: Sequence[Mapping[str, Any]],
) -> tuple[str, str, str]:
    """Return the immutable identity of one owned-URL capture observation.

    Snapshot reuse is valid only when this complete provenance input matches.
    In particular, a new parser, capture artifact, redirect provenance, or
    bounded observation result cannot be silently attached to an older source
    snapshot merely because the remote HTML bytes happened to be identical.
    """

    redirect_provenance_hash = canonical_hash(list(capture.redirect_chain))
    bounded_observation_hash = canonical_hash(_canonicalize_version_value(dict(observations)))
    payload = {
        "normalized_url": capture.normalized_url,
        "final_url": capture.final_url,
        "redirect_provenance_hash": redirect_provenance_hash,
        "source_content_hash": capture.source_content_hash,
        "rights_state": rights_state,
        "capture_version": capture.capture_version,
        "parser_version": capture.parser_version,
        "capture_request_ref": dict(capture_request_reference),
        "capture_artifact_ref": dict(capture_artifact_reference),
        "bounded_observation_hash": bounded_observation_hash,
        "title_meta_observation_ref": dict(title_meta_reference),
        "image_asset_refs": [dict(item) for item in image_observation_references],
    }
    return (
        canonical_hash(_canonicalize_version_value(payload)),
        redirect_provenance_hash,
        bounded_observation_hash,
    )


def _find_existing_owned_product_url_source_snapshot(
    db: Session,
    *,
    project_id: str,
    source_input_hash: str,
) -> ProductSourceSnapshotVersion | None:
    for row in (
        db.query(ProductSourceSnapshotVersion)
        .filter_by(project_id=project_id, input_mode="owned_product_url")
        .order_by(ProductSourceSnapshotVersion.version.asc())
        .all()
    ):
        provenance = dict(row.provenance_json or {})
        if provenance.get("source_input_hash") != source_input_hash:
            continue
        validate_immutable_version(db, row)
        return row
    return None


def adapt_owned_product_url_to_source_snapshot(
    db: Session,
    *,
    run: AgentRun,
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture an owned URL into an immutable, reference-only source snapshot.

    This is deliberately before ProductTruth.  Every observed title/spec/image
    remains an unapproved source observation and no remote image is copied or
    promoted into a final-use asset here.
    """

    validated = validate_unified_product_intake_envelope(envelope)
    if validated["input_mode"] != "owned_product_url":
        raise OwnedProductURLIntakeContractError("owned URL adapter accepts only owned_product_url input mode.")
    if (
        run.id != validated["run_identity"]["run_id"]
        or run.workspace_id != validated["actor_workspace_identity"]["workspace_id"]
        or run.project_id != validated["project_id"]
    ):
        raise OwnedProductURLIntakeContractError("owned URL intake envelope identity does not match its graph run.")
    actor_id = str(validated["actor_workspace_identity"]["actor_id"])
    request, request_reference, request_metadata = _resolve_owned_product_url_capture_request(
        db,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        actor_id=actor_id,
        source_refs=validated["source_payload_refs"],
    )
    try:
        capture = capture_owned_product_url(request_metadata["normalized_url"])
    except UnsafeSourceURLError:
        # A source that is unsafe is never an eligible fallback observation.
        raise
    artifact, artifact_reference, artifact_payload = _create_owned_product_url_capture_artifact(
        db,
        request=request,
        request_reference=request_reference,
        rights_state=request_metadata["rights_state"],
        capture=capture,
    )
    observations = dict(artifact_payload["observations"])
    title_meta_ref = _capture_observation_reference(
        artifact_reference,
        artifact_key="title_meta_observation",
        content={"title": observations["title"], "description": observations["description"]},
    )
    image_observation_refs = [
        _capture_observation_reference(
            artifact_reference,
            artifact_key=f"image_observation:{index}",
            content={"url": value},
        )
        for index, value in enumerate(observations["image_urls"])
    ]
    source_input_hash, redirect_provenance_hash, bounded_observation_hash = _owned_product_url_source_input_hash(
        capture=capture,
        rights_state=request_metadata["rights_state"],
        capture_request_reference=request_reference,
        capture_artifact_reference=artifact_reference,
        observations=observations,
        title_meta_reference=title_meta_ref,
        image_observation_references=image_observation_refs,
    )
    existing = _find_existing_owned_product_url_source_snapshot(
        db,
        project_id=run.project_id,
        source_input_hash=source_input_hash,
    )
    if existing is None:
        snapshot = create_product_source_snapshot_version(
            db,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            creator_run_id=run.id,
            created_by=actor_id,
            input_mode="owned_product_url",
            source_refs=[artifact_reference],
            provenance={
                "source": "seller_submitted_owned_product_url",
                "capture_request_ref": request_reference,
                "capture_artifact_ref": artifact_reference,
                "normalized_url": capture.normalized_url,
                "final_url": capture.final_url,
                "final_host": normalize_public_http_url(capture.final_url).split("//", 1)[1].split("/", 1)[0],
                "redirect_chain": list(capture.redirect_chain),
                "captured_at": capture.captured_at,
                "capture_version": capture.capture_version,
                "parser_version": capture.parser_version,
                "source_content_hash": capture.source_content_hash,
                "redirect_provenance_hash": redirect_provenance_hash,
                "bounded_observation_hash": bounded_observation_hash,
                "source_input_hash": source_input_hash,
            },
            rights={
                "provenance": "seller_submitted_owned_product_url",
                "confirmation_state": request_metadata["rights_state"],
                "final_use_status": "not_approved",
            },
            source_fidelity={
                "capture_status": "captured",
                "content_document_ref": artifact_reference,
                "title_meta_observation_ref": title_meta_ref,
                # These are capture observations, never final-use assets.
                "image_asset_refs": image_observation_refs,
                "spec_observation_count": len(observations["specs"]),
            },
        )
        db.commit()
        db.refresh(snapshot)
    else:
        snapshot = existing
    frozen_provenance = dict(snapshot.provenance_json or {})
    frozen_fidelity = dict(snapshot.source_fidelity_json or {})
    frozen_artifact_reference = dict(frozen_provenance["capture_artifact_ref"])
    return {
        "schema_version": OWNED_PRODUCT_URL_SOURCE_CANDIDATES_SCHEMA_VERSION,
        "source_snapshot": _row_reference(snapshot),
        "capture_request_ref": request_reference,
        # Never pair a reused frozen snapshot with a newly captured artifact.
        "capture_artifact_ref": frozen_artifact_reference,
        "normalized_url": capture.normalized_url,
        "final_url": capture.final_url,
        "redirect_chain": list(capture.redirect_chain),
        "captured_at": capture.captured_at,
        "capture_version": capture.capture_version,
        "parser_version": capture.parser_version,
        "source_content_hash": capture.source_content_hash,
        "title_meta_observation_ref": dict(frozen_fidelity["title_meta_observation_ref"]),
        "image_asset_refs": list(frozen_fidelity["image_asset_refs"]),
        "rights": {
            "provenance": "seller_submitted_owned_product_url",
            "confirmation_state": request_metadata["rights_state"],
            "final_use_status": "not_approved",
        },
    }


class PhotoOnlyIntakeContractError(ValueError):
    """A photo-only observation input is unsafe or does not match its asset."""


class PhotoOnlyObservationRecoverableError(ValueError):
    """An image observation failed without corrupting the durable intake run."""

    def __init__(
        self,
        code: str,
        *,
        extractor_status: str | None = None,
        source_asset_refs: Sequence[Mapping[str, Any]] = (),
        observation_artifact_ref: Mapping[str, Any] | None = None,
    ):
        self.code = code
        self.extractor_status = extractor_status or code
        self.source_asset_refs = [dict(item) for item in source_asset_refs]
        self.observation_artifact_ref = (
            dict(observation_artifact_ref) if observation_artifact_ref is not None else None
        )
        super().__init__(code)


def _photo_asset_reference(asset: Asset, *, asset_hash: str, rights_state: str) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "version": 1,
        "hash": asset_hash,
        "schema_version": "lg12i-photo-asset-ref-v1",
        "artifact_key": "photo_asset",
        "rights_status": rights_state,
    }


def validate_photo_only_asset_eligibility(
    db: Session,
    *,
    asset: Asset | None,
    reference: Mapping[str, Any],
    project_id: str,
) -> dict[str, Any]:
    """Use one fail-closed picker/adapter contract for photo source assets.

    A caller label alone must never turn supplier, reference, competitor, or
    blocked material into a seller photo observation.  The persisted source
    provenance, resolved usage state, and immutable file hash are all needed.
    """

    if asset is None or str(asset.project_id) != str(project_id):
        raise PhotoOnlyIntakeContractError("photo source asset must belong to this project.")
    if not str(asset.mime_type or "").startswith("image/"):
        raise PhotoOnlyIntakeContractError("photo source asset must be an image from this project.")
    if reference.get("version") != 1:
        raise PhotoOnlyIntakeContractError("photo source asset version does not match the persisted asset contract.")
    declared_rights = str(reference.get("rights_status") or "").strip().lower()
    if declared_rights not in _PHOTO_ONLY_RIGHTS_STATES:
        raise PhotoOnlyIntakeContractError("photo source asset rights state is unsupported.")
    source_type = str(asset.source_type or "").strip().lower()
    usage_status = resolved_asset_usage_status(asset)
    if source_type not in SELLER_OWNED_SOURCE_TYPES or usage_status != "seller_owned":
        raise PhotoOnlyIntakeContractError(
            "photo_only accepts only seller-uploaded or seller-owned source assets; supplier, reference, competitor, and blocked assets are analysis-only."
        )
    inspection = inspect_asset(asset, db)
    if inspection.content_hash is None:
        raise PhotoOnlyObservationRecoverableError("unsupported_image")
    if reference.get("hash") != inspection.content_hash:
        raise PhotoOnlyIntakeContractError("photo source asset ID/version/hash does not match actual persisted bytes.")
    return _photo_asset_reference(asset, asset_hash=inspection.content_hash, rights_state=declared_rights)


def validate_lg12i_brand_kit_scope(
    brand_kit: BrandKitVersion | None,
    *,
    workspace_id: str,
    project_id: str,
) -> BrandKitVersion:
    """Enforce the one Brand Kit tenancy rule shared by Brief and Master.

    Project kits are never portable between projects merely because their
    workspace matches.  A workspace kit is reusable only when its persisted
    row is genuinely global (``scope=workspace`` and no project binding).
    """

    if brand_kit is None or str(brand_kit.workspace_id) != str(workspace_id):
        raise IntakeVersionContractError("Brand Kit is unavailable in this workspace.")
    scope = str(brand_kit.scope or "").strip().lower()
    if scope == "project":
        if str(brand_kit.project_id or "") != str(project_id):
            raise IntakeVersionContractError("Project-scoped Brand Kit belongs to a different project.")
    elif scope == "workspace":
        if brand_kit.project_id is not None:
            raise IntakeVersionContractError("Workspace-global Brand Kit cannot be project-bound.")
    else:
        raise IntakeVersionContractError("Brand Kit scope is unsupported.")
    return brand_kit


def resolve_lg12i_final_use_assets(
    db: Session,
    *,
    project_id: str,
    source: ProductSourceSnapshotVersion,
    confirmation: SellerConfirmationVersion,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve final-use assets from frozen source refs with live byte checks.

    The returned assets retain only immutable ID/version/hash identities.  A
    rejected candidate is retained as bounded diagnostics so a Brief can show
    why it excluded an asset without copying any source body or file bytes.
    """

    source_rights = dict(source.rights_json or {})
    source_rights_state = str(
        source_rights.get("confirmation_state") or source_rights.get("status") or ""
    ).lower()
    confirmation_rights = [
        dict(item) for item in confirmation.rights_confirmations_json or [] if isinstance(item, Mapping)
    ]
    source_is_confirmed = source_rights_state in {"seller_owned", "rights_confirmed", "confirmed"} or any(
        str(item.get("status") or "").lower() in {"seller_owned", "rights_confirmed", "confirmed"}
        for item in confirmation_rights
    )
    references: dict[str, dict[str, Any]] = {}
    for item in [
        *(source.source_refs_json or []),
        *list(dict(source.provenance_json or {}).get("source_asset_refs") or []),
    ]:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("artifact_key") or item.get("kind") or "").lower() not in {"asset", "photo_asset"}:
            continue
        identifier = item.get("id")
        if isinstance(identifier, str) and identifier:
            references[identifier] = dict(item)

    usable: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for asset_id in sorted(references):
        reference = references[asset_id]
        bounded = {
            key: reference[key]
            for key in {"id", "version", "hash", "schema_version", "artifact_key", "rights_status"}
            if key in reference
        }
        reason: str | None = None
        asset = db.query(Asset).filter_by(id=asset_id, project_id=project_id).one_or_none()
        declared_rights = str(reference.get("rights_status") or "").lower()
        if not source_is_confirmed:
            reason = "source_rights_not_confirmed"
        elif declared_rights not in {"seller_owned", "rights_confirmed", "confirmed"}:
            reason = "asset_rights_not_confirmed"
        else:
            try:
                exact = validate_photo_only_asset_eligibility(
                    db, asset=asset, reference=bounded, project_id=project_id
                )
            except PhotoOnlyObservationRecoverableError:
                reason = "asset_storage_unavailable"
            except PhotoOnlyIntakeContractError as exc:
                text = str(exc).lower()
                reason = "asset_actual_hash_mismatch" if "hash" in text else "asset_provenance_ineligible"
            else:
                # Photo observation accepts a legacy asset before its stored
                # hash is populated.  Final use is stricter: its persisted
                # Asset hash, live storage bytes, and frozen source ref must
                # all agree.
                if asset is None or str(asset.content_hash or "") != str(exact["hash"]):
                    reason = "asset_actual_hash_mismatch"
                else:
                    usable.append({
                        "id": exact["id"], "version": exact["version"], "hash": exact["hash"],
                        "schema_version": "asset-sha256-v1",
                    })
        if reason is not None:
            exclusions.append({
                "asset_ref": {key: bounded[key] for key in ("id", "version", "hash") if key in bounded},
                "reason": reason,
            })
    usable.sort(key=_canonical_collection_sort_key)
    exclusions.sort(key=lambda item: (str(item["asset_ref"].get("id") or ""), item["reason"]))
    return usable, exclusions


def _bounded_photo_text(value: Any) -> str | None:
    """Keep only bounded visible text; never turn markup into graph data."""

    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if _UNSAFE_MANUAL_CONTENT.search(normalized):
        return None
    return normalized[:256]


def _photo_observation_id(payload: Mapping[str, Any]) -> str:
    return "photo-observation-" + canonical_hash(payload)[:32]


def _normalized_photo_observation(
    *,
    observation_type: str,
    normalized_field: str,
    observed_value: str | None,
    confidence: float | None,
    source_asset_ref: Mapping[str, Any],
    region: Mapping[str, Any],
    extractor_type: str,
    extractor_version: str,
    risk_type: str | None = None,
) -> dict[str, Any]:
    if observation_type not in {"ocr_text", "visible_visual", "risk_signal"}:
        raise PhotoOnlyIntakeContractError("photo observation type is unsupported.")
    if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,127}", normalized_field):
        raise PhotoOnlyIntakeContractError("photo observation normalized_field is invalid.")
    value = _bounded_photo_text(observed_value)
    if value is None and observation_type != "risk_signal":
        raise PhotoOnlyIntakeContractError("photo observation must contain a bounded observed value.")
    if observation_type == "risk_signal" and not risk_type:
        raise PhotoOnlyIntakeContractError("photo risk observation requires a risk type.")
    if confidence is not None and (not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1):
        raise PhotoOnlyIntakeContractError("photo observation confidence must be between zero and one.")
    source = _reference(
        {key: value for key, value in source_asset_ref.items() if key != "rights_status"},
        "photo observation source asset",
    )
    # Asset ownership belongs to the source reference; retain it alongside the
    # strict reference rather than copying a mutable Asset row into state.
    if source_asset_ref.get("rights_status") not in _PHOTO_ONLY_RIGHTS_STATES:
        raise PhotoOnlyIntakeContractError("photo observation source rights state is unsupported.")
    identity = {
        "type": observation_type,
        "field": normalized_field,
        "value": value,
        "region": dict(region),
        "extractor_type": extractor_type,
        "extractor_version": extractor_version,
        "risk_type": risk_type,
    }
    return {
        "observation_id": _photo_observation_id(identity),
        "observation_type": observation_type,
        "normalized_field": normalized_field,
        "observed_value": value,
        "confidence": round(float(confidence), 4) if confidence is not None else None,
        "source_asset_refs": [{**source, "rights_status": source_asset_ref["rights_status"]}],
        "region": dict(region),
        "extractor_type": extractor_type,
        "extractor_version": extractor_version,
        "risk_type": risk_type,
        "observation_hash": canonical_hash(identity),
        "approval_status": "not_approved",
    }


def _photo_ocr_outcome(status: Any) -> tuple[str, str]:
    normalized = str(status or "").strip().lower()
    if normalized in _PHOTO_OCR_SUCCESS_STATUSES:
        return "ready", normalized
    if normalized in _PHOTO_OCR_FAILURE_STATUSES:
        if normalized == "ocr_engine_failed":
            return "failed", "ocr_failed"
        if normalized == "ocr_image_not_local":
            return "failed", "ocr_image_not_available"
        return "failed", normalized
    # An unrecognised extractor state is never silently treated as source-ready.
    return "failed", "ocr_failed"


def _photo_ocr_risk_types(text: str) -> list[str]:
    return [risk_type for risk_type, pattern in _PHOTO_RISK_PATTERNS if pattern.search(text)]


def _photo_observations_for_asset(
    asset: Asset, *, source_asset_ref: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Produce bounded source observations without producing product facts.

    The existing local asset inspection/OCR stack is deliberately reused.  It
    is deterministic and provider-free by default.  A future opt-in real VLM
    may write a separate inspection record, but this intake contract accepts
    only these strict, whitelisted observation shapes.
    """

    observations: list[dict[str, Any]] = []
    risk_signals: list[dict[str, Any]] = []
    try:
        ocr_blocks, ocr_version = extract_ocr_blocks(asset)
        ocr_state, ocr_reason = _photo_ocr_outcome(ocr_version)
    except Exception:  # Local OCR unavailability is a structured recoverable outcome.
        ocr_blocks, ocr_version, ocr_state, ocr_reason = [], "ocr_engine_exception", "failed", "ocr_failed"
    if ocr_state == "ready":
        for index, block in enumerate(ocr_blocks[:12]):
            text = _bounded_photo_text(block.get("text"))
            if text is None:
                risk_signals.append(_normalized_photo_observation(
                    observation_type="risk_signal",
                    normalized_field="unsafe_ocr_text_omitted",
                    observed_value=None,
                    confidence=None,
                    source_asset_ref=source_asset_ref,
                    region=dict(block.get("bbox") or {}),
                    extractor_type="OCR",
                    extractor_version=str(ocr_version),
                    risk_type="unsafe_ocr_markup",
                ))
                continue
            observations.append(_normalized_photo_observation(
                observation_type="ocr_text",
                normalized_field=f"visible_text_{index}",
                observed_value=text,
                confidence=(float(block["confidence"]) / 100.0 if isinstance(block.get("confidence"), (int, float)) and block["confidence"] > 1 else block.get("confidence")),
                source_asset_ref=source_asset_ref,
                region=dict(block.get("bbox") or {}),
                extractor_type="OCR",
                extractor_version=str(ocr_version),
            ))
            for risk_type in _photo_ocr_risk_types(text):
                risk_signals.append(_normalized_photo_observation(
                    observation_type="risk_signal",
                    normalized_field=f"ocr_risk_{risk_type}_{index}",
                    observed_value=text,
                    confidence=(float(block["confidence"]) / 100.0 if isinstance(block.get("confidence"), (int, float)) and block["confidence"] > 1 else block.get("confidence")),
                    source_asset_ref=source_asset_ref,
                    region=dict(block.get("bbox") or {}),
                    extractor_type="OCR",
                    extractor_version=str(ocr_version),
                    risk_type=risk_type,
                ))
    # This is a constrained visual observation, not a factual interpretation.
    # Asset role, dimensions, and the visible product shape remain evidence for
    # TASK-12I.6; values such as material/weight/certification are intentionally
    # absent here.
    role = str(asset.asset_role or "unknown").strip().lower()
    vlm_state = "unavailable"
    if role and role != "unknown":
        vlm_state = "ready"
        observations.append(_normalized_photo_observation(
            observation_type="visible_visual",
            normalized_field="visible_product_role",
            observed_value=role,
            confidence=float(asset.role_confidence or 0.0),
            source_asset_ref=source_asset_ref,
            region={"x": 0, "y": 0, "width": int(asset.width or 0), "height": int(asset.height or 0), "coordinate_space": "asset_pixels", "precision": "asset_scope"},
            extractor_type="VLM",
            extractor_version=PHOTO_ONLY_VLM_EXTRACTOR_VERSION,
        ))
    return observations, risk_signals, {
        "ocr": {"state": ocr_state, "status": str(ocr_version), "reason": ocr_reason},
        "vlm": {"state": vlm_state, "status": "deterministic_asset_role" if vlm_state == "ready" else "identity_uncertain"},
    }


def _dedupe_and_conflict_photo_observations(
    observations: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dedupe identical visible observations and retain conflicting values."""

    deduped: dict[tuple[str, str, str | None, str, str], dict[str, Any]] = {}
    for raw in observations:
        item = deepcopy(dict(raw))
        key = (
            str(item["observation_type"]), str(item["normalized_field"]), item.get("observed_value"),
            str(item["extractor_type"]), str(item["extractor_version"]),
        )
        current = deduped.get(key)
        if current is None:
            deduped[key] = item
            continue
        current_refs = [dict(value) for value in current["source_asset_refs"]]
        current_refs.extend(dict(value) for value in item["source_asset_refs"])
        current["source_asset_refs"] = sorted(
            {canonical_hash(value): value for value in current_refs}.values(),
            key=_canonical_collection_sort_key,
        )
        current["observation_hash"] = canonical_hash({
            "type": current["observation_type"], "field": current["normalized_field"],
            "value": current.get("observed_value"), "region": current["region"],
            "extractor_type": current["extractor_type"], "extractor_version": current["extractor_version"],
            "risk_type": current.get("risk_type"),
            "source_asset_refs": current["source_asset_refs"],
        })
    normalized = sorted(deduped.values(), key=lambda value: (value["normalized_field"], str(value.get("observed_value") or ""), value["observation_id"]))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for observation in normalized:
        if observation["observation_type"] == "risk_signal" or observation.get("observed_value") is None:
            continue
        grouped.setdefault((observation["observation_type"], observation["normalized_field"]), []).append(observation)
    conflicts: list[dict[str, Any]] = []
    for (observation_type, field_id), values in sorted(grouped.items()):
        distinct = {str(item.get("observed_value")) for item in values}
        if len(distinct) > 1:
            conflicts.append({
                "field_id": field_id,
                "observation_type": observation_type,
                "observation_state": "conflict",
                "approval_status": "not_approved",
                "observations": [
                    {
                        "observation_id": item["observation_id"], "observed_value": item["observed_value"],
                        "source_asset_refs": item["source_asset_refs"], "observation_hash": item["observation_hash"],
                    }
                    for item in values
                ],
            })
    return normalized, conflicts


def _photo_observation_artifact_payload(
    *, asset_refs: Sequence[Mapping[str, Any]], observations: Sequence[Mapping[str, Any]],
    risk_signals: Sequence[Mapping[str, Any]], conflicts: Sequence[Mapping[str, Any]],
    observation_status: str = "ready", extractor_statuses: Sequence[Mapping[str, Any]] = (),
    failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    observation_refs = [
        {
            "id": item["observation_id"], "hash": item["observation_hash"],
            "extractor_type": item["extractor_type"], "extractor_version": item["extractor_version"],
        }
        for item in observations
    ]
    source_refs = sorted([dict(value) for value in asset_refs], key=_canonical_collection_sort_key)
    unknown_candidates = []
    for field in _PHOTO_PROHIBITED_INFERENCE_FIELDS:
        state = "unknown" if field in {"unseen_components", "warranty_period", "usage_duration"} else "prohibited_inference"
        provenance = {
            "field_id": field,
            "state": state,
            "source_asset_refs": source_refs,
            "source_observation_refs": observation_refs,
            "extractor_identities": [dict(item) for item in extractor_statuses],
        }
        unknown_candidates.append({
            "candidate_id": "photo-candidate-" + canonical_hash(provenance)[:32],
            **provenance,
            "approval_status": "not_approved",
            "provenance_hash": canonical_hash(provenance),
        })
    return {
        "schema_version": PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION,
        "source_asset_refs": source_refs,
        "observations": [dict(value) for value in observations],
        "risk_signals": [dict(value) for value in risk_signals],
        "conflict_candidates": [dict(value) for value in conflicts],
        "unknown_candidates": unknown_candidates,
        "prohibited_inference_fields": list(_PHOTO_PROHIBITED_INFERENCE_FIELDS),
        "observation_status": observation_status,
        "extractor_statuses": [dict(item) for item in extractor_statuses],
        "failure": dict(failure) if failure is not None else None,
        "extractors": {
            "ocr": ANALYZER_VERSION,
            "vlm": PHOTO_ONLY_VLM_EXTRACTOR_VERSION,
        },
    }


def _photo_observation_artifact_reference(row: ReferenceInputVersion) -> dict[str, Any]:
    return {
        "id": str(row.id), "version": int(row.version), "hash": str(row.content_hash),
        "schema_version": PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION,
        "artifact_key": "photo_observation_artifact",
    }


def _create_or_reuse_photo_observation_artifact(
    db: Session, *, workspace_id: str, project_id: str, created_by: str, payload: Mapping[str, Any]
) -> tuple[ReferenceInputVersion, dict[str, Any]]:
    canonical_payload = _photo_observation_artifact_payload(
        asset_refs=payload["source_asset_refs"], observations=payload["observations"],
        risk_signals=payload["risk_signals"], conflicts=payload["conflict_candidates"],
        observation_status=str(payload.get("observation_status") or "ready"),
        extractor_statuses=list(payload.get("extractor_statuses") or []),
        failure=payload.get("failure"),
    )
    digest = canonical_hash(canonical_payload)
    row = (
        db.query(ReferenceInputVersion)
        .filter_by(project_id=project_id, content_hash=digest, input_kind="image")
        .order_by(ReferenceInputVersion.version.asc())
        .first()
    )
    if row is None:
        latest = db.query(ReferenceInputVersion).filter_by(project_id=project_id).order_by(ReferenceInputVersion.version.desc()).first()
        row = ReferenceInputVersion(
            workspace_id=workspace_id, project_id=project_id,
            version=int(latest.version) + 1 if latest is not None else 1,
            input_kind="image", content_text=None, source_metadata=canonical_payload,
            rights_status="unverified", usage_scope="analysis_only", content_hash=digest,
            created_by=created_by,
        )
        db.add(row)
        db.flush()
    if canonical_hash(dict(row.source_metadata or {})) != row.content_hash:
        raise PhotoOnlyIntakeContractError("photo observation artifact hash does not match its persisted observations.")
    return row, _photo_observation_artifact_reference(row)


def _resolve_photo_only_assets(
    db: Session, *, run: AgentRun, refs: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    if not 1 <= len(refs) <= 2:
        raise PhotoOnlyIntakeContractError("photo_only requires one or two source assets.")
    resolved: list[dict[str, Any]] = []
    for raw_ref in refs:
        ref = dict(raw_ref)
        asset = db.query(Asset).filter_by(id=str(ref.get("id") or ""), project_id=run.project_id).one_or_none()
        frozen_ref = validate_photo_only_asset_eligibility(
            db, asset=asset, reference=ref, project_id=run.project_id,
        )
        resolved.append({
            "asset": asset,
            "reference": frozen_ref,
        })
    if len({item["reference"]["id"] for item in resolved}) != len(resolved):
        raise PhotoOnlyIntakeContractError("photo_only source assets must not contain duplicates.")
    return sorted(resolved, key=lambda item: _canonical_collection_sort_key(item["reference"]))


def _find_existing_photo_only_source_snapshot(
    db: Session, *, project_id: str, source_input_hash: str
) -> ProductSourceSnapshotVersion | None:
    for row in (
        db.query(ProductSourceSnapshotVersion)
        .filter_by(project_id=project_id, input_mode="photo_only")
        .order_by(ProductSourceSnapshotVersion.version.asc())
        .all()
    ):
        if dict(row.provenance_json or {}).get("source_input_hash") != source_input_hash:
            continue
        validate_immutable_version(db, row)
        return row
    return None


def adapt_photo_only_input_to_source_snapshot(
    db: Session, *, run: AgentRun, envelope: Mapping[str, Any]
) -> dict[str, Any]:
    """Create/reuse a photo-only source snapshot from strict observations only."""

    validated = validate_unified_product_intake_envelope(envelope)
    if validated["input_mode"] != "photo_only":
        raise PhotoOnlyIntakeContractError("photo adapter accepts only photo_only input mode.")
    if (
        run.id != validated["run_identity"]["run_id"]
        or run.workspace_id != validated["actor_workspace_identity"]["workspace_id"]
        or run.project_id != validated["project_id"]
    ):
        raise PhotoOnlyIntakeContractError("photo intake envelope identity does not match its graph run.")
    actor_id = str(validated["actor_workspace_identity"]["actor_id"])
    resolved = _resolve_photo_only_assets(db, run=run, refs=validated["source_payload_refs"])
    observations: list[dict[str, Any]] = []
    risk_signals: list[dict[str, Any]] = []
    extractor_statuses: list[dict[str, Any]] = []
    for item in resolved:
        extracted, risks, statuses = _photo_observations_for_asset(item["asset"], source_asset_ref=item["reference"])
        observations.extend(extracted)
        risk_signals.extend(risks)
        extractor_statuses.append({"asset_id": item["reference"]["id"], **statuses})
    observations, conflicts = _dedupe_and_conflict_photo_observations(observations)
    any_ready = any(
        status.get("ocr", {}).get("state") == "ready" or status.get("vlm", {}).get("state") == "ready"
        for status in extractor_statuses
    )
    any_failed = any(status.get("ocr", {}).get("state") == "failed" for status in extractor_statuses)
    failure_codes = [
        str(status.get("ocr", {}).get("reason") or status.get("ocr", {}).get("status") or "ocr_failed")
        for status in extractor_statuses
        if status.get("ocr", {}).get("state") == "failed"
    ]
    observation_status = (
        "recovery" if not any_ready else "partial_observation_ready" if any_failed else "ready"
    )
    artifact_payload = _photo_observation_artifact_payload(
        asset_refs=[item["reference"] for item in resolved], observations=observations,
        risk_signals=risk_signals, conflicts=conflicts,
        observation_status=observation_status, extractor_statuses=extractor_statuses,
        failure={"code": failure_codes[0]} if not any_ready and failure_codes else None,
    )
    _artifact, artifact_reference = _create_or_reuse_photo_observation_artifact(
        db, workspace_id=run.workspace_id, project_id=run.project_id,
        created_by=actor_id, payload=artifact_payload,
    )
    if not any_ready:
        raise PhotoOnlyObservationRecoverableError(
            failure_codes[0] if failure_codes else "photo_observation_failed",
            extractor_status=failure_codes[0] if failure_codes else "photo_observation_failed",
            source_asset_refs=artifact_payload["source_asset_refs"],
            observation_artifact_ref=artifact_reference,
        )
    source_input_hash = canonical_hash({
        "input_mode": "photo_only", "asset_refs": artifact_payload["source_asset_refs"],
        "observation_artifact_ref": artifact_reference,
        "observation_hash": canonical_hash(artifact_payload),
    })
    snapshot = _find_existing_photo_only_source_snapshot(
        db, project_id=run.project_id, source_input_hash=source_input_hash,
    )
    if snapshot is None:
        rights_states = [item["reference"]["rights_status"] for item in resolved]
        confirmation_state = (
            "unconfirmed" if "unconfirmed" in rights_states
            else "rights_confirmed" if "rights_confirmed" in rights_states
            else "seller_owned"
        )
        snapshot = create_product_source_snapshot_version(
            db, workspace_id=run.workspace_id, project_id=run.project_id,
            creator_run_id=run.id, created_by=actor_id, input_mode="photo_only",
            source_refs=[artifact_reference],
            provenance={
                "source": "seller_submitted_photo_only", "source_asset_refs": artifact_payload["source_asset_refs"],
                "observation_artifact_ref": artifact_reference, "source_input_hash": source_input_hash,
                "extractor_versions": dict(artifact_payload["extractors"]),
                "extractor_statuses": list(artifact_payload["extractor_statuses"]),
            },
            rights={
                "source_asset_rights": rights_states,
                "confirmation_state": confirmation_state,
                "final_use_status": "not_approved",
            },
            source_fidelity={
                "source_kind": "photo_observation_artifact", "observation_count": len(observations),
                "conflict_count": len(conflicts), "unknown_count": len(artifact_payload["unknown_candidates"]),
                "prohibited_inference_fields": list(_PHOTO_PROHIBITED_INFERENCE_FIELDS),
                "observation_status": observation_status,
            },
        )
        db.commit()
        db.refresh(snapshot)
    return {
        "schema_version": PHOTO_ONLY_SOURCE_CANDIDATES_SCHEMA_VERSION,
        "source_snapshot": _row_reference(snapshot), "photo_observation_artifact_ref": artifact_reference,
        "source_asset_refs": artifact_payload["source_asset_refs"],
        "observations": observations, "conflict_candidates": conflicts,
        "unknown_candidates": artifact_payload["unknown_candidates"],
        "prohibited_inference_fields": list(_PHOTO_PROHIBITED_INFERENCE_FIELDS),
        "risk_signals": artifact_payload["risk_signals"],
        "observation_status": observation_status,
        "extractor_statuses": artifact_payload["extractor_statuses"],
        "rights": dict(snapshot.rights_json or {}),
    }


def _canonical_collection_sort_key(value: Any) -> tuple[str, int, str, str]:
    """Sort set-like reference collections by stable identity, not display order."""

    if isinstance(value, Mapping):
        raw_version = value.get("version")
        return (
            str(value.get("id") or value.get("kind") or ""),
            raw_version if isinstance(raw_version, int) else -1,
            str(value.get("hash") or ""),
            canonical_hash(dict(value)),
        )
    return (str(value), -1, "", canonical_hash(value))


def _canonicalize_version_value(value: Any, *, field_name: str | None = None) -> Any:
    """Normalize only unordered contract fields; user/history order remains meaningful."""

    if isinstance(value, Mapping):
        return {key: _canonicalize_version_value(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        normalized = [_canonicalize_version_value(item) for item in value]
        if field_name in _UNORDERED_REFERENCE_COLLECTION_FIELDS:
            return sorted(normalized, key=_canonical_collection_sort_key)
        return normalized
    return value


def _require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _SHA256_CHARS for char in value):
        raise IntakeVersionContractError(f"{label} must be a lowercase SHA-256 hash.")
    return value


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise IntakeVersionContractError(f"{label} is required.")
    return value


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise IntakeVersionContractError(f"{label} must be an object.")
    return deepcopy(dict(value))


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise IntakeVersionContractError(f"{label} must be a list.")
    return deepcopy(list(value))


def _next_version(db: Session, model: type[VersionRow], project_id: str) -> int:
    latest = db.query(model).filter_by(project_id=project_id).order_by(model.version.desc()).first()
    return int(latest.version) + 1 if latest else 1


def _require_run(db: Session, *, run_id: str, workspace_id: str, project_id: str) -> AgentRun:
    run = db.query(AgentRun).filter_by(id=run_id, workspace_id=workspace_id, project_id=project_id).first()
    if run is None:
        raise IntakeVersionContractError("creator_run_id must belong to the same workspace and project.")
    return run


def _row_reference(row: Any, *, hash_field: str = "canonical_hash") -> dict[str, Any]:
    return {"id": str(row.id), "version": int(row.version), "hash": str(getattr(row, hash_field))}


def _validate_parent(
    db: Session, model: type[VersionRow], *, project_id: str, parent_version_id: str | None
) -> tuple[str | None, int | None, str | None]:
    if parent_version_id is None:
        return None, None, None
    parent = db.query(model).filter_by(id=parent_version_id, project_id=project_id).first()
    if parent is None:
        raise IntakeVersionContractError("A successor parent must be a version from the same project.")
    validate_immutable_version(db, parent)
    return str(parent.id), int(parent.version), str(parent.canonical_hash)


def _check_registered_hash(
    db: Session, model: type[VersionRow], *, project_id: str, digest: str
) -> None:
    if db.query(model).filter_by(project_id=project_id, canonical_hash=digest).first() is not None:
        raise IntakeVersionContractError("Immutable version content is already registered; create no overwrite.")


def _reference(value: Any, label: str) -> dict[str, Any]:
    item = _require_mapping(value, label)
    if set(item) - _MASTER_REFERENCE_KEYS:
        raise IntakeVersionContractError(f"{label} must be a reference, not a copied artifact body.")
    _require_id(item.get("id"), f"{label}.id")
    if not isinstance(item.get("version"), int) or item["version"] < 1:
        raise IntakeVersionContractError(f"{label}.version must be a positive integer.")
    _require_hash(item.get("hash"), f"{label}.hash")
    if "schema_version" in item and (not isinstance(item["schema_version"], str) or not item["schema_version"]):
        raise IntakeVersionContractError(f"{label}.schema_version must be a non-empty string.")
    if "artifact_key" in item and (not isinstance(item["artifact_key"], str) or not item["artifact_key"]):
        raise IntakeVersionContractError(f"{label}.artifact_key must be a non-empty string.")
    return item


def _reference_list(value: Any, label: str) -> list[dict[str, Any]]:
    return [_reference(item, f"{label}[{index}]") for index, item in enumerate(_require_list(value, label))]


def _confirmation_identity_ref(identifier: Any, digest: Any, label: str, *, schema_version: str) -> dict[str, Any]:
    """Return a bounded immutable identity for a clarification or answer."""

    return _reference(
        {"id": _require_id(identifier, f"{label}.id"), "version": 1, "hash": _require_hash(digest, f"{label}.hash"), "schema_version": schema_version},
        label,
    )


def _confirmed_fact_reference(value: Any, label: str) -> dict[str, Any]:
    """Validate the immutable, value-bearing seller confirmation record.

    ``answers_json`` remains an audit trail.  This record is deliberately
    self-sufficient so a later approved-fact consumer never has to reinterpret
    mutable UI answers to learn the seller-confirmed value.
    """

    item = _require_mapping(value, label)
    allowed = {
        "id", "version", "hash", "provenance_ref", "confirmed_fact_id", "fact_id", "field_id",
        "normalized_value", "unit", "value_structure", "source_kind", "original_truth_item_ref",
        "clarification_ref", "answer_ref", "seller_actor_id", "confirmation_cycle", "source_refs",
        "evidence_refs", "selected_observation_ref", "conflicting_observation_refs", "provenance_hash",
        "decision_status",
    }
    extras = set(item) - allowed
    if extras:
        raise IntakeVersionContractError(f"{label} contains unsupported confirmed-fact fields.")
    fact = _reference({key: item.get(key) for key in ("id", "version", "hash")}, label)
    original = _reference(item.get("original_truth_item_ref"), f"{label}.original_truth_item_ref")
    if {key: fact[key] for key in ("id", "version", "hash")} != {
        key: original[key] for key in ("id", "version", "hash")
    }:
        raise IntakeVersionContractError(f"{label} must pin its original Product Truth item identity.")
    fact_id = _require_id(item.get("fact_id"), f"{label}.fact_id")
    field_id = _require_id(item.get("field_id"), f"{label}.field_id")
    if not isinstance(item.get("normalized_value"), str) or not item["normalized_value"].strip():
        raise IntakeVersionContractError(f"{label}.normalized_value is required.")
    normalized_value = _confirmation_text(item["normalized_value"], f"{label}.normalized_value", allow_empty=False)
    unit = item.get("unit")
    if unit is not None:
        unit = _confirmation_text(unit, f"{label}.unit", allow_empty=False)
    structure = _require_mapping(item.get("value_structure"), f"{label}.value_structure")
    if set(structure) != {"value", "unit"} or structure.get("value") != normalized_value or structure.get("unit") != unit:
        raise IntakeVersionContractError(f"{label}.value_structure must match normalized value and unit.")
    source_kind = str(item.get("source_kind") or "")
    if source_kind not in {"product_truth_candidate", "seller_confirmation", "selected_observation"}:
        raise IntakeVersionContractError(f"{label}.source_kind is unsupported.")
    clarification = _confirmation_identity_ref(
        item.get("clarification_ref", {}).get("id") if isinstance(item.get("clarification_ref"), Mapping) else None,
        item.get("clarification_ref", {}).get("hash") if isinstance(item.get("clarification_ref"), Mapping) else None,
        f"{label}.clarification_ref", schema_version="lg12i-seller-clarification-v1",
    )
    answer = _confirmation_identity_ref(
        item.get("answer_ref", {}).get("id") if isinstance(item.get("answer_ref"), Mapping) else None,
        item.get("answer_ref", {}).get("hash") if isinstance(item.get("answer_ref"), Mapping) else None,
        f"{label}.answer_ref", schema_version="lg12i-seller-answer-v1",
    )
    actor = _require_id(item.get("seller_actor_id"), f"{label}.seller_actor_id")
    cycle = item.get("confirmation_cycle")
    if not isinstance(cycle, int) or cycle < 1:
        raise IntakeVersionContractError(f"{label}.confirmation_cycle must be a positive integer.")
    source_refs = _reference_list(item.get("source_refs"), f"{label}.source_refs")
    evidence_refs = _reference_list(item.get("evidence_refs"), f"{label}.evidence_refs")
    if not source_refs and not evidence_refs:
        raise IntakeVersionContractError(f"{label} requires source or evidence provenance.")
    provenance = _reference(item.get("provenance_ref"), f"{label}.provenance_ref")
    selected = item.get("selected_observation_ref")
    selected_ref = _reference(selected, f"{label}.selected_observation_ref") if selected is not None else None
    conflict_refs = _reference_list(item.get("conflicting_observation_refs", []), f"{label}.conflicting_observation_refs")
    if source_kind == "selected_observation" and selected_ref is None:
        raise IntakeVersionContractError(f"{label} must pin the selected conflict observation.")
    if source_kind == "seller_confirmation" and selected_ref is not None:
        raise IntakeVersionContractError(f"{label} corrected seller values cannot claim a selected observation.")
    if item.get("decision_status") != "confirmed":
        raise IntakeVersionContractError(f"{label}.decision_status must be confirmed.")
    provenance_identity = {
        "original_truth_item_ref": original,
        "fact_id": fact_id,
        "field_id": field_id,
        "normalized_value": normalized_value,
        "unit": unit,
        "source_kind": source_kind,
        "clarification_ref": clarification,
        "answer_ref": answer,
        "seller_actor_id": actor,
        "confirmation_cycle": cycle,
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "selected_observation_ref": selected_ref,
        "conflicting_observation_refs": conflict_refs,
        "decision_status": "confirmed",
    }
    provenance_hash = canonical_hash(_canonicalize_version_value(provenance_identity))
    if item.get("provenance_hash") != provenance_hash:
        raise IntakeVersionContractError(f"{label}.provenance_hash does not match its immutable confirmation provenance.")
    confirmed_fact_id = "seller-confirmed-fact:" + canonical_hash(_canonicalize_version_value(provenance_identity))[:24]
    if item.get("confirmed_fact_id") != confirmed_fact_id:
        raise IntakeVersionContractError(f"{label}.confirmed_fact_id does not match its immutable confirmation provenance.")
    return {
        **fact,
        "provenance_ref": provenance,
        "confirmed_fact_id": confirmed_fact_id,
        "fact_id": fact_id,
        "field_id": field_id,
        "normalized_value": normalized_value,
        "unit": unit,
        "value_structure": {"value": normalized_value, "unit": unit},
        "source_kind": source_kind,
        "original_truth_item_ref": original,
        "clarification_ref": clarification,
        "answer_ref": answer,
        "seller_actor_id": actor,
        "confirmation_cycle": cycle,
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "selected_observation_ref": selected_ref,
        "conflicting_observation_refs": conflict_refs,
        "provenance_hash": provenance_hash,
        "decision_status": "confirmed",
    }


def _fact_state_reference(value: Any, label: str, *, require_confirmed_value: bool = False) -> dict[str, Any]:
    """Pin a seller decision to its Truth identity and immutable provenance."""

    item = dict(_require_mapping(value, label))
    if "confirmed_fact_id" in item:
        return _confirmed_fact_reference(item, label)
    if require_confirmed_value:
        raise IntakeVersionContractError(f"{label} must include the immutable seller-confirmed value provenance.")
    provenance = item.pop("provenance_ref", None)
    fact = _reference(item, label)
    if provenance is None:
        raise IntakeVersionContractError(f"{label}.provenance_ref is required.")
    fact["provenance_ref"] = _reference(provenance, f"{label}.provenance_ref")
    return fact


def _fact_state_reference_list(value: Any, label: str, *, require_confirmed_value: bool = False) -> list[dict[str, Any]]:
    return [
        _fact_state_reference(item, f"{label}[{index}]", require_confirmed_value=require_confirmed_value)
        for index, item in enumerate(_require_list(value, label))
    ]


def _validate_confirmation_fact_states(row: SellerConfirmationVersion, truth: ProductTruthVersion) -> None:
    states = {
        "confirmed": _fact_state_reference_list(
            row.confirmed_fact_refs_json,
            "confirmation.confirmed_fact_refs",
            require_confirmed_value=row.schema_version in {
                SELLER_CONFIRMATION_VALUE_PROVENANCE_SCHEMA_VERSION,
                SELLER_CONFIRMATION_SCHEMA_VERSION,
            },
        ),
        "rejected": _fact_state_reference_list(row.rejected_fact_refs_json, "confirmation.rejected_fact_refs"),
        "unknown": _fact_state_reference_list(row.unknown_fact_refs_json, "confirmation.unknown_fact_refs"),
    }
    # A response may confirm a seller-supplied value for an unknown/conflict
    # Truth item.  Pin it to a Truth reference, rather than inventing a new
    # mutable fact record, while keeping prohibited inferences non-promotable.
    known_truth_facts = {
        (item["id"], item["version"], item["hash"])
        for collection, label in (
            (truth.fact_refs_json, "truth.fact_refs"),
            (truth.unknown_refs_json, "truth.unknown_refs"),
            (truth.conflict_refs_json, "truth.conflict_refs"),
            (truth.prohibited_inference_refs_json, "truth.prohibited_inference_refs"),
        )
        for item in _reference_list(collection, label)
    }
    prohibited = {
        (item["id"], item["version"], item["hash"])
        for item in _reference_list(truth.prohibited_inference_refs_json, "truth.prohibited_inference_refs")
    }
    assigned: dict[tuple[str, int, str], str] = {}
    for state, references in states.items():
        for reference in references:
            identity = (reference["id"], reference["version"], reference["hash"])
            if identity not in known_truth_facts:
                raise IntakeVersionContractError("Seller confirmation fact state must reference a fact pinned by Product Truth.")
            if state == "confirmed" and identity in prohibited:
                raise IntakeVersionContractError("A prohibited inference cannot be promoted by seller confirmation alone.")
            if identity in assigned:
                raise IntakeVersionContractError("A seller-confirmed fact cannot belong to more than one state.")
            assigned[identity] = state


def _snapshot_fact_ids(fact_snapshot: FactSnapshot) -> set[str]:
    facts = _require_list(fact_snapshot.facts_json, "approved fact snapshot.facts")
    identifiers: set[str] = set()
    for index, fact in enumerate(facts):
        if isinstance(fact, Mapping):
            identifiers.add(_require_id(fact.get("id"), f"approved fact snapshot.facts[{index}].id"))
        else:
            identifiers.add(_require_id(fact, f"approved fact snapshot.facts[{index}]"))
    return identifiers


def _validate_master_approved_fact_states(
    fact_snapshot: FactSnapshot, confirmation: SellerConfirmationVersion
) -> None:
    snapshot_fact_ids = _snapshot_fact_ids(fact_snapshot)
    confirmed = {item["id"] for item in _fact_state_reference_list(confirmation.confirmed_fact_refs_json, "confirmation.confirmed_fact_refs")}
    rejected = {item["id"] for item in _fact_state_reference_list(confirmation.rejected_fact_refs_json, "confirmation.rejected_fact_refs")}
    unknown = {item["id"] for item in _fact_state_reference_list(confirmation.unknown_fact_refs_json, "confirmation.unknown_fact_refs")}
    if snapshot_fact_ids & (rejected | unknown):
        raise IntakeVersionContractError("Rejected or unknown facts cannot be promoted into an approved fact snapshot.")
    if not snapshot_fact_ids.issubset(confirmed):
        raise IntakeVersionContractError("Only seller-confirmed facts can be promoted into an approved fact snapshot.")


def lg12i_approved_asset_manifest_reference(
    *, source_reference: Mapping[str, Any], usable_asset_refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the bounded, canonical identity of an LG-12I approved-asset manifest.

    The Master stores this identity only.  The full manifest remains owned by
    the later image/page artifact that materializes it, so this task never
    copies asset metadata or image bytes into the Master index.
    """

    source = _reference(source_reference, "asset_manifest.source")
    assets = _reference_list(usable_asset_refs, "asset_manifest.assets")
    assets = sorted(assets, key=_canonical_collection_sort_key)
    digest = canonical_hash(_canonicalize_version_value({
        "schema_version": LG12I_APPROVED_ASSET_MANIFEST_SCHEMA_VERSION,
        "source": source,
        "assets": assets,
    }))
    return {
        "id": "approved-asset-manifest:" + digest[:24], "version": 1, "hash": digest,
        "schema_version": LG12I_APPROVED_ASSET_MANIFEST_SCHEMA_VERSION,
        "artifact_key": "approved_asset_manifest",
    }


def lg12i_pending_production_artifact_reference(
    *, artifact_key: str, creative_brief_reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Pin an explicit empty identity until a later planning task materializes it."""

    if artifact_key not in {"copywriting", "page_planning"}:
        raise IntakeVersionContractError("Only copywriting and page_planning can be pending Master artifacts.")
    brief = _reference(creative_brief_reference, f"pending.{artifact_key}.brief")
    digest = canonical_hash(_canonicalize_version_value({
        "schema_version": LG12I_PENDING_PRODUCTION_ARTIFACT_SCHEMA_VERSION,
        "artifact_key": artifact_key, "creative_brief": brief,
    }))
    return {
        "id": f"pending:{artifact_key}:" + digest[:24], "version": 1, "hash": digest,
        "schema_version": LG12I_PENDING_PRODUCTION_ARTIFACT_SCHEMA_VERSION,
        "artifact_key": artifact_key,
    }


def _validate_lg12i_creative_brief_links(
    *, brief: ProductCreativeBriefVersion, source: ProductSourceSnapshotVersion,
    truth: ProductTruthVersion, confirmation: SellerConfirmationVersion,
    brand_kit: BrandKitVersion, creator_run_id: str, target_channels: Sequence[str],
) -> None:
    """Ensure the Brief was compiled from the same frozen intake lineage."""

    if brief.compiler_version != LG12I_CREATIVE_BRIEF_COMPILER_VERSION:
        raise IntakeVersionContractError("Commerce Creative Master requires an LG-12I Product Creative Brief.")
    if brief.run_id != creator_run_id or brief.workspace_id != source.workspace_id:
        raise IntakeVersionContractError("Creative Brief run/workspace does not match the Master lineage.")
    expected = (
        (brief.source_snapshot_version_id, brief.source_snapshot_version, brief.source_snapshot_hash, source.id, source.version, source.canonical_hash),
        (brief.truth_version_id, brief.truth_version, brief.truth_version_hash, truth.id, truth.version, truth.canonical_hash),
        (brief.confirmation_version_id, brief.confirmation_version, brief.confirmation_version_hash, confirmation.id, confirmation.version, confirmation.canonical_hash),
        (brief.brand_kit_version_id, None, brief.brand_kit_hash, brand_kit.id, None, brand_kit.content_hash),
    )
    if any(actual_id != expected_id or (actual_version is not None and actual_version != expected_version) or actual_hash != expected_hash
           for actual_id, actual_version, actual_hash, expected_id, expected_version, expected_hash in expected):
        raise IntakeVersionContractError("Creative Brief source/truth/confirmation/Brand Kit reference is stale or tampered.")
    expected_channels = sorted(set(str(item) for item in target_channels))
    if list(brief.target_channels or []) != expected_channels:
        raise IntakeVersionContractError("Creative Brief target channel identity does not match the Master.")
    if canonical_hash(_canonicalize_version_value(dict(brief.brief_json or {}))) != brief.output_hash:
        raise IntakeVersionContractError("Creative Brief output hash does not match its persisted content.")
    if _contains_lg12i_raw_body(dict(brief.brief_json or {})):
        raise IntakeVersionContractError("Creative Brief must not embed a raw source body.")
    source_rights = dict(source.rights_json or {})
    rights_state = str(source_rights.get("confirmation_state") or source_rights.get("status") or "").lower()
    if rights_state == "unconfirmed":
        decisions = [dict(item) for item in confirmation.rights_confirmations_json or [] if isinstance(item, Mapping)]
        if not any(str(item.get("status") or "").lower() in {"confirmed", "rights_confirmed", "seller_owned"} for item in decisions):
            raise IntakeVersionContractError("Unconfirmed source rights cannot enter a Commerce Creative Master.")


def _contains_lg12i_raw_body(value: Any) -> bool:
    """Reject raw source payload keys at every Brief level, not just top-level."""

    forbidden = {"raw_html", "html", "raw_body", "body", "ocr_text", "image_bytes", "raw_image_bytes"}
    if isinstance(value, Mapping):
        return any(str(key).lower() in forbidden or _contains_lg12i_raw_body(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_lg12i_raw_body(item) for item in value)
    return False


def _source_payload(row: ProductSourceSnapshotVersion) -> dict[str, Any]:
    return {
        "kind": "ProductSourceSnapshotVersion", "schema_version": row.schema_version,
        "workspace_id": row.workspace_id, "project_id": row.project_id, "creator_run_id": row.creator_run_id,
        "version": row.version, "input_mode": row.input_mode,
        "parent": {"id": row.parent_version_id, "version": row.parent_version, "hash": row.parent_version_hash} if row.parent_version_id else None,
        "source_refs": row.source_refs_json, "provenance": row.provenance_json,
        "rights": row.rights_json, "source_fidelity": row.source_fidelity_json,
    }


def _truth_payload(row: ProductTruthVersion) -> dict[str, Any]:
    return {
        "kind": "ProductTruthVersion", "schema_version": row.schema_version,
        "workspace_id": row.workspace_id, "project_id": row.project_id, "creator_run_id": row.creator_run_id,
        "version": row.version,
        "source": {
            "id": row.source_snapshot_version_id,
            "version": row.source_snapshot_version,
            "hash": row.source_snapshot_hash,
        },
        "parent": {"id": row.parent_version_id, "version": row.parent_version, "hash": row.parent_version_hash} if row.parent_version_id else None,
        "fact_refs": row.fact_refs_json, "evidence_refs": row.evidence_refs_json,
        "unknown_refs": row.unknown_refs_json, "conflict_refs": row.conflict_refs_json,
        "prohibited_inference_refs": row.prohibited_inference_refs_json,
        "normalization": dict(row.normalization_json or {}),
    }


def _confirmation_payload(row: SellerConfirmationVersion) -> dict[str, Any]:
    payload = {
        "kind": "SellerConfirmationVersion", "schema_version": row.schema_version,
        "workspace_id": row.workspace_id, "project_id": row.project_id, "creator_run_id": row.creator_run_id,
        "version": row.version,
        "truth": {
            "id": row.truth_version_id,
            "version": row.truth_version,
            "hash": row.truth_version_hash,
        },
        "parent": {"id": row.parent_version_id, "version": row.parent_version, "hash": row.parent_version_hash} if row.parent_version_id else None,
        "answers": row.answers_json, "confirmed_fact_refs": row.confirmed_fact_refs_json,
        "rejected_fact_refs": row.rejected_fact_refs_json,
        "unknown_fact_refs": row.unknown_fact_refs_json,
        "rights_confirmations": row.rights_confirmations_json,
    }
    if row.schema_version in {
        SELLER_CONFIRMATION_CYCLE_SCHEMA_VERSION,
        SELLER_CONFIRMATION_VALUE_PROVENANCE_SCHEMA_VERSION,
        SELLER_CONFIRMATION_SCHEMA_VERSION,
    }:
        payload.update({
            "confirmation_cycle": row.confirmation_cycle,
            "clarifications": row.clarification_refs_json,
            "unresolved_refs": row.unresolved_refs_json,
            "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        })
    if row.schema_version == SELLER_CONFIRMATION_SCHEMA_VERSION:
        payload.update({
            "resume_request_hash": row.resume_request_hash,
            "resume_answer_bundle_hash": row.resume_answer_bundle_hash,
        })
    return payload


def _master_payload(row: CommerceCreativeMasterVersion) -> dict[str, Any]:
    return {
        "kind": "CommerceCreativeMasterVersion", "schema_version": row.schema_version,
        "workspace_id": row.workspace_id, "project_id": row.project_id, "creator_run_id": row.creator_run_id,
        "version": row.version,
        "parent": {"id": row.parent_version_id, "version": row.parent_version, "hash": row.parent_version_hash} if row.parent_version_id else None,
        "source": {"id": row.source_snapshot_version_id, "version": row.source_snapshot_version, "hash": row.source_snapshot_hash},
        "truth": {"id": row.truth_version_id, "version": row.truth_version, "hash": row.truth_version_hash},
        "confirmation": {"id": row.confirmation_version_id, "version": row.confirmation_version, "hash": row.confirmation_version_hash},
        "creative_brief": {"id": row.creative_brief_version_id, "version": row.creative_brief_version, "hash": row.creative_brief_hash},
        "brand_kit": {"id": row.brand_kit_version_id, "version": row.brand_kit_version, "hash": row.brand_kit_hash},
        "evidence_artifacts": row.evidence_artifact_refs_json,
        "approved_fact_snapshot": row.approved_fact_snapshot_ref_json,
        "approved_asset_manifest": row.approved_asset_manifest_ref_json,
        "copy_artifact": row.copy_artifact_ref_json,
        "page_plan_artifact": row.page_plan_artifact_ref_json,
        "target_channels": row.target_channels,
        "downstream_outputs": row.downstream_output_refs_json,
    }


def _master_idempotency_hash(payload: Mapping[str, Any]) -> str:
    """Semantic Master identity deliberately excludes its allocated version.

    The immutable canonical hash still includes ``version``.  This separate
    comparison key lets a retry find the already-frozen initial Master before
    allocating another version for identical inputs.
    """

    identity = deepcopy(dict(payload))
    identity.pop("version", None)
    return canonical_hash(_canonicalize_version_value(identity))


def _payload_for(row: VersionRow) -> dict[str, Any]:
    if isinstance(row, ProductSourceSnapshotVersion):
        return _source_payload(row)
    if isinstance(row, ProductTruthVersion):
        return _truth_payload(row)
    if isinstance(row, SellerConfirmationVersion):
        return _confirmation_payload(row)
    if isinstance(row, CommerceCreativeMasterVersion):
        return _master_payload(row)
    raise IntakeVersionContractError("Unsupported immutable LG-12I version type.")


def _linked_row(
    db: Session, model: type[VersionRow], *, project_id: str, reference: Mapping[str, Any], label: str
) -> VersionRow:
    expected = _reference(reference, label)
    row = db.query(model).filter_by(id=expected["id"], project_id=project_id).first()
    if row is None:
        raise IntakeVersionContractError(f"{label} must reference an immutable version in the same project.")
    validate_immutable_version(db, row)
    actual = _row_reference(row)
    if expected != actual:
        raise IntakeVersionContractError(f"{label} ID/version/hash does not match its frozen version.")
    return row


def validate_immutable_version(db: Session, row: VersionRow, _visited: set[tuple[str, str]] | None = None) -> None:
    """Validate canonical self-hash and anchored predecessor/source lineage."""

    marker = (type(row).__name__, str(row.id))
    visited = _visited if _visited is not None else set()
    if marker in visited:
        raise IntakeVersionContractError("Immutable version lineage cannot contain a cycle.")
    visited.add(marker)
    try:
        if not isinstance(row.version, int) or row.version < 1:
            raise IntakeVersionContractError("Immutable version number must be a positive integer.")
        expected_schema = {
            ProductSourceSnapshotVersion: PRODUCT_SOURCE_SNAPSHOT_SCHEMA_VERSION,
            ProductTruthVersion: PRODUCT_TRUTH_SCHEMA_VERSION,
            SellerConfirmationVersion: SELLER_CONFIRMATION_SCHEMA_VERSION,
            CommerceCreativeMasterVersion: COMMERCE_CREATIVE_MASTER_SCHEMA_VERSION,
        }.get(type(row))
        supported_confirmation_schema = (
            isinstance(row, SellerConfirmationVersion)
            and row.schema_version in {
                LEGACY_SELLER_CONFIRMATION_SCHEMA_VERSION,
                SELLER_CONFIRMATION_CYCLE_SCHEMA_VERSION,
                SELLER_CONFIRMATION_VALUE_PROVENANCE_SCHEMA_VERSION,
                SELLER_CONFIRMATION_SCHEMA_VERSION,
            }
        )
        if row.schema_version != expected_schema and not supported_confirmation_schema:
            raise IntakeVersionContractError("Immutable version schema version is unsupported.")
        if canonical_version_hash(_payload_for(row)) != row.canonical_hash:
            raise IntakeVersionContractError("Immutable version canonical hash does not match its persisted content.")
        if row.parent_version_id:
            parent = db.query(type(row)).filter_by(id=row.parent_version_id, project_id=row.project_id).first()
            if parent is None:
                raise IntakeVersionContractError("Immutable successor parent is missing.")
            validate_immutable_version(db, parent, visited)
            if row.parent_version != parent.version or row.parent_version >= row.version or row.parent_version_hash != parent.canonical_hash:
                raise IntakeVersionContractError("Immutable successor parent hash no longer matches its pinned lineage.")
        elif row.parent_version is not None or row.parent_version_hash is not None:
            raise IntakeVersionContractError("Initial immutable version must not pin parent lineage.")

        if isinstance(row, ProductSourceSnapshotVersion):
            if row.input_mode not in {"owned_product_url", "photo_only", "manual"}:
                raise IntakeVersionContractError("Product source snapshot input_mode is unsupported.")
            if not row.source_refs_json:
                raise IntakeVersionContractError("Product source snapshot requires at least one immutable source reference.")
            _reference_list(row.source_refs_json, "source_refs")
        elif isinstance(row, ProductTruthVersion):
            _reference_list(row.fact_refs_json, "truth.fact_refs")
            _reference_list(row.evidence_refs_json, "truth.evidence_refs")
            _reference_list(row.unknown_refs_json, "truth.unknown_refs")
            _reference_list(row.conflict_refs_json, "truth.conflict_refs")
            _reference_list(row.prohibited_inference_refs_json, "truth.prohibited_inference_refs")
            source = db.query(ProductSourceSnapshotVersion).filter_by(id=row.source_snapshot_version_id, project_id=row.project_id).first()
            if source is None:
                raise IntakeVersionContractError("Product truth source snapshot is missing.")
            validate_immutable_version(db, source, visited)
            if row.source_snapshot_version != source.version or row.source_snapshot_hash != source.canonical_hash:
                raise IntakeVersionContractError("Product truth source snapshot hash is stale or tampered.")
        elif isinstance(row, SellerConfirmationVersion):
            truth = db.query(ProductTruthVersion).filter_by(id=row.truth_version_id, project_id=row.project_id).first()
            if truth is None:
                raise IntakeVersionContractError("Seller confirmation truth version is missing.")
            validate_immutable_version(db, truth, visited)
            if row.truth_version != truth.version or row.truth_version_hash != truth.canonical_hash:
                raise IntakeVersionContractError("Seller confirmation truth hash is stale or tampered.")
            if row.schema_version in {
                SELLER_CONFIRMATION_CYCLE_SCHEMA_VERSION,
                SELLER_CONFIRMATION_VALUE_PROVENANCE_SCHEMA_VERSION,
                SELLER_CONFIRMATION_SCHEMA_VERSION,
            }:
                if not isinstance(row.confirmation_cycle, int) or row.confirmation_cycle < 1:
                    raise IntakeVersionContractError("Seller confirmation cycle is invalid.")
                clarifications = _require_list(row.clarification_refs_json, "confirmation.clarifications")
                if len(clarifications) > _CONFIRMATION_MAX_CLARIFICATIONS:
                    raise IntakeVersionContractError("Seller confirmation stores more than three clarifications in one cycle.")
                for index, clarification in enumerate(clarifications):
                    item = _require_mapping(clarification, f"confirmation.clarifications[{index}]")
                    if not item.get("clarification_id") or not item.get("clarification_hash"):
                        raise IntakeVersionContractError("Seller confirmation clarification identity is missing.")
                    _reference(item.get("truth_item_ref"), f"confirmation.clarifications[{index}].truth_item_ref")
                for index, unresolved in enumerate(_require_list(row.unresolved_refs_json, "confirmation.unresolved_refs")):
                    item = _require_mapping(unresolved, f"confirmation.unresolved_refs[{index}]")
                    if not item.get("clarification_id") or not item.get("clarification_hash"):
                        raise IntakeVersionContractError("Seller confirmation unresolved clarification identity is missing.")
                    _reference(item.get("truth_item_ref"), f"confirmation.unresolved_refs[{index}].truth_item_ref")
                parent = None
                if row.parent_version_id:
                    parent = db.query(SellerConfirmationVersion).filter_by(
                        id=row.parent_version_id,
                        project_id=row.project_id,
                    ).first()
                    if parent is None:
                        raise IntakeVersionContractError("Seller confirmation parent is missing.")
                    if (
                        parent.workspace_id != row.workspace_id
                        or parent.creator_run_id != row.creator_run_id
                        or parent.created_by != row.created_by
                        or parent.truth_version_id != row.truth_version_id
                        or parent.truth_version != row.truth_version
                        or parent.truth_version_hash != row.truth_version_hash
                        or parent.confirmation_cycle != row.confirmation_cycle - 1
                    ):
                        raise IntakeVersionContractError("Seller confirmation parent does not match the immediate run/truth/cycle lineage.")
                if row.confirmation_cycle == 1 and parent is not None:
                    raise IntakeVersionContractError("Initial seller confirmation cycle cannot have a parent.")
                if row.confirmation_cycle > 1 and parent is None:
                    raise IntakeVersionContractError("Seller confirmation successor must pin its immediate predecessor.")
                if row.schema_version == SELLER_CONFIRMATION_SCHEMA_VERSION:
                    _require_hash(row.resume_request_hash, "confirmation.resume_request_hash")
                    _require_hash(row.resume_answer_bundle_hash, "confirmation.resume_answer_bundle_hash")
            _validate_confirmation_fact_states(row, truth)
        elif isinstance(row, CommerceCreativeMasterVersion):
            _validate_master_links(db, row, visited)
    finally:
        visited.remove(marker)


def _validate_master_links(db: Session, row: CommerceCreativeMasterVersion, visited: set[tuple[str, str]]) -> None:
    source = db.query(ProductSourceSnapshotVersion).filter_by(id=row.source_snapshot_version_id, project_id=row.project_id).first()
    truth = db.query(ProductTruthVersion).filter_by(id=row.truth_version_id, project_id=row.project_id).first()
    confirmation = db.query(SellerConfirmationVersion).filter_by(id=row.confirmation_version_id, project_id=row.project_id).first()
    if not source or not truth or not confirmation:
        raise IntakeVersionContractError("Commerce Creative Master must reference source, truth, and confirmation versions.")
    for expected, linked, label in (
        ({"id": row.source_snapshot_version_id, "version": row.source_snapshot_version, "hash": row.source_snapshot_hash}, source, "master.source"),
        ({"id": row.truth_version_id, "version": row.truth_version, "hash": row.truth_version_hash}, truth, "master.truth"),
        ({"id": row.confirmation_version_id, "version": row.confirmation_version, "hash": row.confirmation_version_hash}, confirmation, "master.confirmation"),
    ):
        validate_immutable_version(db, linked, visited)
        if expected != _row_reference(linked):
            raise IntakeVersionContractError(f"{label} ID/version/hash does not match its frozen version.")
    if truth.source_snapshot_version_id != source.id or confirmation.truth_version_id != truth.id:
        raise IntakeVersionContractError("Commerce Creative Master requires Source -> Truth -> Confirmation lineage.")

    brief = db.query(ProductCreativeBriefVersion).filter_by(id=row.creative_brief_version_id, project_id=row.project_id).first()
    brand_kit = db.query(BrandKitVersion).filter_by(id=row.brand_kit_version_id, workspace_id=row.workspace_id).first()
    if not brief or not brand_kit:
        raise IntakeVersionContractError("Commerce Creative Master must reference an existing Creative Brief and Brand Kit version.")
    validate_lg12i_brand_kit_scope(
        brand_kit, workspace_id=row.workspace_id, project_id=row.project_id
    )
    if (row.creative_brief_version, row.creative_brief_hash) != (brief.version, brief.output_hash):
        raise IntakeVersionContractError("Commerce Creative Master Creative Brief reference is stale or tampered.")
    if (row.brand_kit_version, row.brand_kit_hash) != (brand_kit.version, brand_kit.content_hash):
        raise IntakeVersionContractError("Commerce Creative Master Brand Kit reference is stale or tampered.")
    _validate_lg12i_creative_brief_links(
        brief=brief, source=source, truth=truth, confirmation=confirmation,
        brand_kit=brand_kit, creator_run_id=row.creator_run_id, target_channels=row.target_channels,
    )

    fact_ref = _reference(row.approved_fact_snapshot_ref_json, "master.approved_fact_snapshot")
    fact_snapshot = db.query(FactSnapshot).filter_by(id=fact_ref["id"], project_id=row.project_id).first()
    if fact_snapshot is None or fact_ref["version"] != 1 or fact_snapshot.snapshot_hash != fact_ref["hash"]:
        raise IntakeVersionContractError("Commerce Creative Master approved fact snapshot reference is invalid.")
    _validate_master_approved_fact_states(fact_snapshot, confirmation)

    live_assets, _asset_exclusions = resolve_lg12i_final_use_assets(
        db, project_id=row.project_id, source=source, confirmation=confirmation,
    )
    if live_assets != list(brief.usable_asset_refs_json or []):
        raise IntakeVersionContractError("Creative Brief usable assets no longer pass final-use integrity validation.")
    expected_manifest = lg12i_approved_asset_manifest_reference(
        source_reference=_row_reference(source), usable_asset_refs=live_assets,
    )
    if _reference(row.approved_asset_manifest_ref_json, "master.approved_asset_manifest") != expected_manifest:
        raise IntakeVersionContractError("Commerce Creative Master approved asset manifest reference is stale or tampered.")
    for key, reference in (("copywriting", row.copy_artifact_ref_json), ("page_planning", row.page_plan_artifact_ref_json)):
        supplied = _reference(reference, f"master.{key}")
        expected_pending = lg12i_pending_production_artifact_reference(
            artifact_key=key, creative_brief_reference=_row_reference(brief, hash_field="output_hash"),
        )
        if supplied.get("schema_version") == LG12I_PENDING_PRODUCTION_ARTIFACT_SCHEMA_VERSION and supplied != expected_pending:
            raise IntakeVersionContractError(f"Commerce Creative Master pending {key} reference is stale or tampered.")
    evidence_refs = sorted(_reference_list(row.evidence_artifact_refs_json, "master.evidence_artifacts"), key=_canonical_collection_sort_key)
    expected_evidence_refs = sorted(_reference_list(truth.evidence_refs_json, "truth.evidence_refs"), key=_canonical_collection_sort_key)
    if not evidence_refs or evidence_refs != expected_evidence_refs:
        raise IntakeVersionContractError("Commerce Creative Master must pin evidence artifact references.")
    if not isinstance(row.target_channels, list) or not row.target_channels or not all(isinstance(item, str) and item in supported_channel_keys() for item in row.target_channels):
        raise IntakeVersionContractError("Commerce Creative Master must pin one or more target channels.")
    _validate_downstream_refs(row)


def _validate_downstream_refs(row: CommerceCreativeMasterVersion) -> None:
    refs = _require_list(row.downstream_output_refs_json, "master.downstream_outputs")
    if not row.parent_version_id and refs:
        raise IntakeVersionContractError("An initial Commerce Creative Master cannot contain downstream output references.")
    for index, value in enumerate(refs):
        item = dict(_require_mapping(value, f"master.downstream_outputs[{index}]"))
        kind = item.pop("kind", None)
        if kind not in _DOWNSTREAM_KINDS:
            raise IntakeVersionContractError("Commerce Creative Master downstream output type is unsupported.")
        _reference(item, f"master.downstream_outputs[{index}]")


def create_product_source_snapshot_version(
    db: Session, *, workspace_id: str, project_id: str, creator_run_id: str, created_by: str,
    input_mode: str, source_refs: Sequence[Mapping[str, Any]], provenance: Mapping[str, Any],
    rights: Mapping[str, Any], source_fidelity: Mapping[str, Any], parent_version_id: str | None = None,
    schema_version: str = PRODUCT_SOURCE_SNAPSHOT_SCHEMA_VERSION,
) -> ProductSourceSnapshotVersion:
    if schema_version != PRODUCT_SOURCE_SNAPSHOT_SCHEMA_VERSION:
        raise IntakeVersionContractError("Product source snapshot schema version is unsupported.")
    if input_mode not in {"owned_product_url", "photo_only", "manual"}:
        raise IntakeVersionContractError("Product source snapshot input_mode is unsupported.")
    _require_run(db, run_id=creator_run_id, workspace_id=workspace_id, project_id=project_id)
    parent_id, parent_version, parent_hash = _validate_parent(db, ProductSourceSnapshotVersion, project_id=project_id, parent_version_id=parent_version_id)
    row = ProductSourceSnapshotVersion(
        workspace_id=workspace_id, project_id=project_id, creator_run_id=creator_run_id, created_by=created_by,
        version=_next_version(db, ProductSourceSnapshotVersion, project_id), schema_version=schema_version,
        input_mode=input_mode, parent_version_id=parent_id, parent_version=parent_version, parent_version_hash=parent_hash,
        source_refs_json=_reference_list(source_refs, "source_refs"), provenance_json=_require_mapping(provenance, "provenance"),
        rights_json=_require_mapping(rights, "rights"), source_fidelity_json=_require_mapping(source_fidelity, "source_fidelity"),
        canonical_hash="",
    )
    row.canonical_hash = canonical_version_hash(_source_payload(row))
    _check_registered_hash(db, ProductSourceSnapshotVersion, project_id=project_id, digest=row.canonical_hash)
    db.add(row); db.flush(); validate_immutable_version(db, row)
    return row


def create_product_truth_version(
    db: Session, *, workspace_id: str, project_id: str, creator_run_id: str, created_by: str,
    source_reference: Mapping[str, Any], fact_refs: Sequence[Mapping[str, Any]], evidence_refs: Sequence[Mapping[str, Any]],
    unknown_refs: Sequence[Mapping[str, Any]] = (), conflict_refs: Sequence[Mapping[str, Any]] = (),
    prohibited_inference_refs: Sequence[Mapping[str, Any]] = (), parent_version_id: str | None = None,
    normalization: Mapping[str, Any] | None = None,
    schema_version: str = PRODUCT_TRUTH_SCHEMA_VERSION,
) -> ProductTruthVersion:
    if schema_version != PRODUCT_TRUTH_SCHEMA_VERSION:
        raise IntakeVersionContractError("Product truth schema version is unsupported.")
    _require_run(db, run_id=creator_run_id, workspace_id=workspace_id, project_id=project_id)
    source = _linked_row(db, ProductSourceSnapshotVersion, project_id=project_id, reference=source_reference, label="truth.source")
    parent_id, parent_version, parent_hash = _validate_parent(db, ProductTruthVersion, project_id=project_id, parent_version_id=parent_version_id)
    row = ProductTruthVersion(
        workspace_id=workspace_id, project_id=project_id, creator_run_id=creator_run_id, created_by=created_by,
        version=_next_version(db, ProductTruthVersion, project_id), schema_version=schema_version,
        source_snapshot_version_id=source.id, source_snapshot_version=source.version, source_snapshot_hash=source.canonical_hash,
        parent_version_id=parent_id, parent_version=parent_version, parent_version_hash=parent_hash,
        fact_refs_json=_reference_list(fact_refs, "truth.fact_refs"), evidence_refs_json=_reference_list(evidence_refs, "truth.evidence_refs"),
        unknown_refs_json=_reference_list(unknown_refs, "truth.unknown_refs"), conflict_refs_json=_reference_list(conflict_refs, "truth.conflict_refs"),
        prohibited_inference_refs_json=_reference_list(prohibited_inference_refs, "truth.prohibited_inference_refs"),
        normalization_json=_require_mapping(normalization or {}, "truth.normalization"), canonical_hash="",
    )
    row.canonical_hash = canonical_version_hash(_truth_payload(row))
    _check_registered_hash(db, ProductTruthVersion, project_id=project_id, digest=row.canonical_hash)
    db.add(row); db.flush(); validate_immutable_version(db, row)
    return row


def _truth_internal_reference(*, kind: str, identity: Mapping[str, Any]) -> dict[str, Any]:
    """Create a bounded, deterministic reference for a Truth sub-artifact."""

    digest = canonical_hash(_canonicalize_version_value(dict(identity)))
    return {
        "id": f"product-truth-{kind}-{digest[:32]}",
        "version": 1,
        "hash": digest,
        "schema_version": PRODUCT_TRUTH_NORMALIZATION_SCHEMA_VERSION,
        "artifact_key": kind,
    }


def _truth_safe_value(value: Any) -> str | None:
    """A Truth item may retain a bounded observed scalar, never source markup."""

    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized or _UNSAFE_MANUAL_CONTENT.search(normalized):
        return None
    return normalized[:512]


def _recompute_truth_source_artifact_hash(
    *, artifact: ReferenceInputVersion, reference: Mapping[str, Any]
) -> str:
    """Recompute the pinned source artifact hash before Truth consumes it.

    A source snapshot pins an artifact reference, but the reference alone is
    insufficient if a persisted artifact row has been modified out of band.
    This single dispatcher keeps all intake modes on their existing canonical
    artifact contracts rather than trusting ``ReferenceInputVersion.content_hash``.
    """

    schema_version = str(reference.get("schema_version") or "")
    artifact_key = str(reference.get("artifact_key") or "")
    if not isinstance(artifact.source_metadata, Mapping):
        raise IntakeVersionContractError("Product Truth source artifact metadata is invalid.")
    metadata = dict(artifact.source_metadata)
    try:
        if schema_version == MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION:
            if artifact.input_kind != "text" or artifact_key != "manual_product_input":
                raise IntakeVersionContractError("Product Truth manual source artifact contract is invalid.")
            return canonical_manual_input_artifact_hash(
                raw_body=str(artifact.content_text or ""),
                source_metadata=metadata,
            )
        if schema_version == OWNED_PRODUCT_URL_CAPTURE_ARTIFACT_SCHEMA_VERSION:
            if artifact.input_kind != "url" or artifact_key != "owned_product_url_capture_artifact":
                raise IntakeVersionContractError("Product Truth owned URL capture artifact contract is invalid.")
            return canonical_owned_product_url_capture_artifact_hash(metadata)
        if schema_version == PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION:
            if artifact.input_kind != "image" or artifact_key != "photo_observation_artifact":
                raise IntakeVersionContractError("Product Truth photo observation artifact contract is invalid.")
            # The photo adapter's persisted contract is precisely the bounded,
            # canonical observation payload.  It never contains image bytes.
            return canonical_hash(_canonicalize_version_value(metadata))
    except (ManualIntakeContractError, OwnedProductURLIntakeContractError, PhotoOnlyIntakeContractError) as exc:
        raise IntakeVersionContractError("Product Truth source artifact canonical content is invalid.") from exc
    raise IntakeVersionContractError("Product Truth source artifact schema is unsupported.")


def _truth_source_artifact(
    db: Session, *, source: ProductSourceSnapshotVersion
) -> tuple[dict[str, Any], ReferenceInputVersion, dict[str, Any]]:
    """Load and hash-check the source artifact without exposing its body."""

    validate_immutable_version(db, source)
    refs = _reference_list(source.source_refs_json, "truth.source.source_refs")
    if len(refs) != 1:
        raise IntakeVersionContractError("Product Truth requires exactly one pinned source artifact.")
    reference = refs[0]
    artifact = (
        db.query(ReferenceInputVersion)
        .filter_by(
            id=reference["id"], workspace_id=source.workspace_id, project_id=source.project_id,
            version=reference["version"],
        )
        .one_or_none()
    )
    if artifact is None:
        raise IntakeVersionContractError("Product Truth source artifact ID/version/hash is stale or tampered.")
    recomputed_hash = _recompute_truth_source_artifact_hash(artifact=artifact, reference=reference)
    if artifact.content_hash != recomputed_hash or reference["hash"] != recomputed_hash:
        raise IntakeVersionContractError("Product Truth source artifact ID/version/hash is stale or tampered.")
    metadata = dict(artifact.source_metadata or {})
    if not isinstance(artifact.source_metadata, Mapping):
        raise IntakeVersionContractError("Product Truth source artifact metadata is invalid.")
    return reference, artifact, metadata


def _truth_item(
    *, field_id: str, field_type: str, value: str | None, unit: str | None,
    source_refs: Sequence[Mapping[str, Any]], observation_refs: Sequence[Mapping[str, Any]],
    evidence_refs: Sequence[Mapping[str, Any]], state: str = "candidate_not_approved",
    observations: Sequence[Mapping[str, Any]] = (),
    inference_type: str | None = None, attempted_claim: str | None = None,
    prohibition_reason: str | None = None, policy_rule_id: str | None = None,
) -> dict[str, Any]:
    if state not in {"candidate_not_approved", "unknown", "conflict", "prohibited_inference"}:
        raise IntakeVersionContractError("Product Truth item state is unsupported.")
    sources = _reference_list(source_refs, "truth.item.source_refs")
    observation_identities = _reference_list(observation_refs, "truth.item.observation_refs")
    evidence_identities = _reference_list(evidence_refs, "truth.item.evidence_refs")
    conflicting_observations = [dict(item) for item in observations] if state == "conflict" else []
    if state != "prohibited_inference" and any(
        value is not None for value in (inference_type, attempted_claim, prohibition_reason, policy_rule_id)
    ):
        raise IntakeVersionContractError("Only prohibited inferences may include inference metadata.")
    if inference_type is not None and inference_type != "price_advantage":
        raise IntakeVersionContractError("Product Truth prohibited inference type is unsupported.")
    provenance = {
        "field_id": field_id,
        "field_type": field_type,
        "value": value,
        "unit": unit,
        "state": state,
        "source_refs": sources,
        "observation_refs": observation_identities,
        "evidence_refs": evidence_identities,
        "conflicting_observations": conflicting_observations,
        "resolution_status": "unresolved" if state == "conflict" else None,
        "inference_type": inference_type,
        "attempted_claim": attempted_claim,
        "prohibition_reason": prohibition_reason,
        "policy_rule_id": policy_rule_id,
    }
    reference = _truth_internal_reference(kind="fact" if state == "candidate_not_approved" else state, identity=provenance)
    item = {
        "fact_id": reference["id"],
        "field_id": field_id,
        "field_type": field_type,
        "value": value,
        "value_structure": {"value": value, "unit": unit},
        "source_refs": sources,
        "observation_refs": observation_identities,
        "evidence_refs": evidence_identities,
        "provenance_hash": canonical_hash(_canonicalize_version_value(provenance)),
        "approval_status": "candidate_not_approved" if state == "candidate_not_approved" else "not_approved",
        "state": state,
        "reference": reference,
        # Retain the legacy generic key while exposing the explicit conflict
        # contract consumed by confirmation/review in the next task.
        "observations": [dict(item) for item in observations],
    }
    if state == "conflict":
        item["resolution_status"] = "unresolved"
        item["conflicting_observations"] = conflicting_observations
    if state == "prohibited_inference":
        item["inference_id"] = reference["id"]
        item["status"] = "prohibited_not_approved"
        if inference_type is not None:
            item["inference_type"] = inference_type
            item["attempted_claim"] = attempted_claim
            item["prohibition_reason"] = prohibition_reason
            item["policy_rule_id"] = policy_rule_id
    return item


def _truth_observation_reference(
    source_ref: Mapping[str, Any], *, key: str, content: Mapping[str, Any]
) -> dict[str, Any]:
    return _truth_internal_reference(
        kind=f"observation:{key}",
        identity={"source_artifact": dict(source_ref), "key": key, "content": dict(content)},
    )


def _truth_normalization_from_source(
    db: Session, *, source: ProductSourceSnapshotVersion
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize the three source modes with no inference or approval step."""

    source_ref, artifact, metadata = _truth_source_artifact(db, source=source)
    source_refs = [source_ref]
    candidates: list[dict[str, Any]] = []
    unknowns: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    prohibited: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    product_identity: dict[str, Any] | None = None

    def add_candidate(field_id: str, value: Any, *, field_type: str = "source_observation", unit: str | None = None, observation: Mapping[str, Any] | None = None) -> None:
        nonlocal product_identity
        safe_value = _truth_safe_value(value)
        observation_refs = [
            _truth_observation_reference(source_ref, key=field_id, content=dict(observation or {"value": safe_value}))
        ]
        if safe_value is None:
            unknowns.append(_truth_item(
                field_id=field_id, field_type=field_type, value=None, unit=unit,
                source_refs=source_refs, observation_refs=observation_refs, evidence_refs=source_refs,
                state="unknown",
            ))
            return
        item = _truth_item(
            field_id=field_id, field_type=field_type, value=safe_value, unit=unit,
            source_refs=source_refs, observation_refs=observation_refs, evidence_refs=source_refs,
        )
        if field_type == "seller_entered_fact" and _PRICE_ADVANTAGE_CUE.search(safe_value):
            prohibited.append(_truth_item(
                field_id="price_advantage", field_type="price_advantage", value=None, unit=None,
                source_refs=source_refs, observation_refs=observation_refs, evidence_refs=source_refs,
                state="prohibited_inference", inference_type="price_advantage",
                attempted_claim=safe_value,
                prohibition_reason="Comparative price advantage requires independent price evidence.",
                policy_rule_id=_PRICE_ADVANTAGE_POLICY_ID,
            ))
            return
        candidates.append(item)
        if product_identity is None and field_id in {"product_identity", "product_name", "model_name", "title"}:
            product_identity = item

    mode = source.input_mode
    if mode == "manual":
        manual = normalize_manual_input_metadata(metadata)
        for field in manual["seller_entered_fields"]:
            if field["classification"] != "fact_candidate":
                continue
            add_candidate(
                str(field["field_id"]), field.get("value"), field_type="seller_entered_fact",
                unit=field.get("unit"), observation={"label": field["label"], "value": field.get("value")},
            )
        seen_unknown = {item["field_id"] for item in unknowns}
        for field_id in manual["unknown_fact_field_ids"]:
            if field_id not in seen_unknown:
                add_candidate(str(field_id), None, field_type="seller_entered_fact")
        for conflict in manual["conflict_fact_candidates"]:
            observations = [
                {
                    "value": _truth_safe_value(item.get("value")), "unit": item.get("unit"),
                    "provenance": "seller_entered", "source_ref": source_ref,
                }
                for item in conflict["observations"]
            ]
            observation_refs = [
                _truth_observation_reference(source_ref, key=f"conflict:{conflict['field_id']}:{index}", content=item)
                for index, item in enumerate(observations)
            ]
            conflicts.append(_truth_item(
                field_id=str(conflict["field_id"]), field_type="seller_entered_fact", value=None, unit=None,
                source_refs=source_refs, observation_refs=observation_refs, evidence_refs=source_refs,
                state="conflict", observations=observations,
            ))
    elif mode == "owned_product_url":
        if metadata.get("kind") != "owned_product_url_capture_artifact":
            raise IntakeVersionContractError("Owned URL source artifact has an unsupported capture schema.")
        observations = dict(metadata.get("observations") or {})
        add_candidate("product_identity", observations.get("title"), field_type="captured_title")
        for index, spec in enumerate(observations.get("specs") or []):
            if not isinstance(spec, Mapping):
                raise IntakeVersionContractError("Owned URL spec observation is malformed.")
            add_candidate(
                f"captured_spec_{index}", spec.get("value"), field_type="captured_spec",
                observation={"label": _truth_safe_value(spec.get("label")), "value": _truth_safe_value(spec.get("value"))},
            )
        if not observations.get("specs"):
            unknowns.append(_truth_item(
                field_id="captured_specifications", field_type="captured_spec", value=None, unit=None,
                source_refs=source_refs, observation_refs=[], evidence_refs=source_refs, state="unknown",
            ))
    elif mode == "photo_only":
        if metadata.get("schema_version") != PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION:
            raise IntakeVersionContractError("Photo source artifact has an unsupported observation schema.")
        for observation in metadata.get("observations") or []:
            if not isinstance(observation, Mapping):
                raise IntakeVersionContractError("Photo observation is malformed.")
            value = observation.get("observed_value")
            field_id = str(observation.get("normalized_field") or "")
            if not field_id:
                raise IntakeVersionContractError("Photo observation field identity is missing.")
            add_candidate(field_id, value, field_type=str(observation.get("observation_type") or "photo_observation"), observation=observation)
        for item in metadata.get("unknown_candidates") or []:
            if not isinstance(item, Mapping):
                raise IntakeVersionContractError("Photo unknown candidate is malformed.")
            target = prohibited if item.get("state") == "prohibited_inference" else unknowns
            raw_observations = [dict(ref) for ref in item.get("source_observation_refs") or []]
            inference_kwargs = {}
            if item.get("state") == "prohibited_inference" and item.get("field_id") == "price_advantage":
                inference_kwargs = {
                    "inference_type": "price_advantage",
                    "attempted_claim": None,
                    "prohibition_reason": "Comparative price advantage requires independent price evidence.",
                    "policy_rule_id": _PRICE_ADVANTAGE_POLICY_ID,
                }
            target.append(_truth_item(
                field_id=str(item.get("field_id") or ""), field_type="photo_observation", value=None, unit=None,
                source_refs=source_refs,
                observation_refs=[
                    _truth_observation_reference(
                        source_ref,
                        key=f"{item.get('field_id')}:{index}",
                        content=observation,
                    )
                    for index, observation in enumerate(raw_observations)
                ],
                evidence_refs=source_refs, state=str(item.get("state") or "unknown"), **inference_kwargs,
            ))
        for conflict in metadata.get("conflict_candidates") or []:
            if not isinstance(conflict, Mapping):
                raise IntakeVersionContractError("Photo conflict candidate is malformed.")
            observations = [dict(item) for item in conflict.get("observations") or []]
            conflicts.append(_truth_item(
                field_id=str(conflict.get("field_id") or ""), field_type="photo_observation", value=None, unit=None,
                source_refs=source_refs,
                observation_refs=[_truth_observation_reference(source_ref, key=f"conflict:{conflict.get('field_id')}:{index}", content=item) for index, item in enumerate(observations)],
                evidence_refs=source_refs, state="conflict", observations=observations,
            ))
        for risk in metadata.get("risk_signals") or []:
            if not isinstance(risk, Mapping):
                raise IntakeVersionContractError("Photo risk observation is malformed.")
            risk_identity = {
                "risk_type": str(risk.get("risk_type") or ""),
                "bounded_representation": _truth_safe_value(risk.get("observed_value")),
                "region": dict(risk.get("region") or {}),
                "source_asset_refs": _reference_list(
                    [dict(item) for item in risk.get("source_asset_refs") or []],
                    "truth.photo.risk.source_asset_refs",
                ),
                "extractor_type": str(risk.get("extractor_type") or ""),
                "extractor_version": str(risk.get("extractor_version") or ""),
                "observation_hash": str(risk.get("observation_hash") or ""),
            }
            risks.append({
                **risk_identity,
                "source_refs": source_refs,
                "observation_ref": _truth_observation_reference(
                    source_ref,
                    key=f"risk:{risk_identity['risk_type']}:{risk_identity['observation_hash']}",
                    content=risk_identity,
                ),
                "provenance_hash": canonical_hash(_canonicalize_version_value(risk_identity)),
                "approval_status": "not_approved",
            })
    else:
        raise IntakeVersionContractError("Product Truth source input_mode is unsupported.")

    if product_identity is None:
        product_identity = _truth_item(
            field_id="product_identity", field_type="identity", value=None, unit=None,
            source_refs=source_refs, observation_refs=[], evidence_refs=source_refs, state="unknown",
        )
        unknowns.append(product_identity)
    rights = dict(source.rights_json or {})
    rights_uncertainty = {
        "state": "rights_uncertain" if rights.get("confirmation_state") == "unconfirmed" else "not_uncertain",
        "source_rights": rights,
        "source_refs": source_refs,
    }
    normalization = {
        "schema_version": PRODUCT_TRUTH_NORMALIZATION_SCHEMA_VERSION,
        "normalization_version": PRODUCT_TRUTH_NORMALIZATION_SCHEMA_VERSION,
        "source_snapshot": _row_reference(source),
        "normalized_product_identity": product_identity,
        "fact_candidates": sorted(candidates, key=lambda item: item["fact_id"]),
        "unknown_facts": sorted(unknowns, key=lambda item: item["fact_id"]),
        "conflict_facts": sorted(conflicts, key=lambda item: item["fact_id"]),
        "prohibited_inferences": sorted(prohibited, key=lambda item: item["fact_id"]),
        "rights_uncertainty": rights_uncertainty,
        "observation_risks": sorted(risks, key=lambda item: (item["risk_type"], item["observation_hash"])),
        "source_fidelity": dict(source.source_fidelity_json or {}),
    }
    return normalization, candidates, unknowns, conflicts, prohibited, risks


def normalize_product_truth_from_source_snapshot(
    db: Session, *, run: AgentRun, source_reference: Mapping[str, Any]
) -> dict[str, Any]:
    """Create/reuse one immutable, unapproved Product Truth version."""

    source = _linked_row(
        db, ProductSourceSnapshotVersion, project_id=run.project_id,
        reference=source_reference, label="truth.source",
    )
    if source.workspace_id != run.workspace_id:
        raise IntakeVersionContractError("Product Truth source snapshot workspace does not match its run.")
    normalization, candidates, unknowns, conflicts, prohibited, risks = _truth_normalization_from_source(db, source=source)
    existing = (
        db.query(ProductTruthVersion)
        # A ProductTruthVersion is immutable run/thread provenance, not a
        # shareable cache entry.  The exact same frozen source may be reused
        # by a later intake run, but that later run receives its own Truth
        # version so seller confirmation cannot attach a Truth from another
        # run/thread.
        .filter_by(
            project_id=run.project_id,
            source_snapshot_version_id=source.id,
            creator_run_id=run.id,
        )
        .order_by(ProductTruthVersion.version.asc())
        .all()
    )
    normalized_hash = canonical_hash(_canonicalize_version_value(normalization))
    truth = next((row for row in existing if canonical_hash(_canonicalize_version_value(dict(row.normalization_json or {}))) == normalized_hash), None)
    if truth is None:
        truth = create_product_truth_version(
            db, workspace_id=run.workspace_id, project_id=run.project_id,
            creator_run_id=run.id, created_by=run.created_by,
            source_reference=_row_reference(source),
            fact_refs=[item["reference"] for item in candidates],
            evidence_refs=[source_ref for source_ref in source.source_refs_json],
            unknown_refs=[item["reference"] for item in unknowns],
            conflict_refs=[item["reference"] for item in conflicts],
            prohibited_inference_refs=[item["reference"] for item in prohibited],
            normalization=normalization,
        )
        db.commit()
        db.refresh(truth)
    else:
        validate_immutable_version(db, truth)
    # Truth normalization is deliberately non-promoting: an unresolved unknown,
    # conflict, prohibited inference, or rights uncertainty cannot progress as
    # seller-confirmed product truth before TASK-12I.7.
    requires_review = bool(
        unknowns
        or conflicts
        or prohibited
        or normalization["rights_uncertainty"]["state"] == "rights_uncertain"
    )
    return {
        "schema_version": PRODUCT_TRUTH_NORMALIZATION_SCHEMA_VERSION,
        "truth_version": _row_reference(truth),
        "normalized_product_identity": normalization["normalized_product_identity"],
        "fact_candidates": normalization["fact_candidates"],
        "unknown_facts": normalization["unknown_facts"],
        "conflict_facts": normalization["conflict_facts"],
        "prohibited_inferences": normalization["prohibited_inferences"],
        "evidence_refs": list(truth.evidence_refs_json or []),
        "rights_uncertainty": normalization["rights_uncertainty"],
        "observation_risks": normalization["observation_risks"],
        "requires_review": requires_review,
    }


# TASK-12I.7 keeps seller clarification deterministic and bounded.  These
# constants classify review work; they never decide which product value is
# correct and they do not call a provider.
_CONFIRMATION_MAX_CLARIFICATIONS = 3
_CONFIRMATION_UNSAFE_TEXT = re.compile(
    r"<\s*/?\s*(?:script|html|iframe|object|embed)\b|javascript\s*:|data\s*:\s*text/html",
    re.IGNORECASE,
)


def _confirmation_text(value: Any, label: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise SellerConfirmationContractError(f"{label} must be text.")
    normalized = value.strip()
    if len(normalized) > 500 or _CONFIRMATION_UNSAFE_TEXT.search(normalized):
        raise SellerConfirmationContractError(f"{label} contains unsafe content.")
    if not normalized and not allow_empty:
        raise SellerConfirmationContractError(f"{label} is required.")
    return normalized


def _confirmation_item_reference(item: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    reference = _reference(item.get("reference"), f"{label}.reference")
    provenance_sources = (
        list(item.get("evidence_refs") or [])
        or list(item.get("observation_refs") or [])
        or list(item.get("source_refs") or [])
    )
    if not provenance_sources:
        raise SellerConfirmationContractError(f"{label} is missing source/evidence provenance.")
    return {**reference, "provenance_ref": _reference(provenance_sources[0], f"{label}.provenance_ref")}


def _clarification_from_truth_item(
    item: Mapping[str, Any], *, clarification_type: str, priority: int, required: bool,
) -> dict[str, Any]:
    truth_reference = _reference(item.get("reference"), "clarification.truth_item")
    field_id = str(item.get("field_id") or "")
    if not field_id:
        raise SellerConfirmationContractError("Clarification truth field identity is missing.")
    observation_options: list[dict[str, Any]] = []
    observation_refs = _reference_list(item.get("observation_refs") or [], "clarification.observation_refs")
    for index, observation in enumerate(item.get("conflicting_observations") or item.get("observations") or []):
        if not isinstance(observation, Mapping):
            raise SellerConfirmationContractError("Clarification conflict observation is malformed.")
        identity = {"truth": truth_reference, "index": index, "observation": dict(observation)}
        observation_options.append({
            "observation_id": "observation:" + canonical_hash(_canonicalize_version_value(identity))[:24],
            "value": _truth_safe_value(observation.get("value")),
            "unit": _truth_safe_value(observation.get("unit")),
            "observation_ref": observation_refs[index] if index < len(observation_refs) else None,
        })
    prompt = {
        "identity_conflict": f"상품 식별 정보({field_id})를 확인해 주세요.",
        "rights": "이 소스와 자산을 판매 상품에 사용할 권리가 있는지 확인해 주세요.",
        "fact_conflict": f"서로 다른 정보가 있는 {field_id}의 정확한 값을 확인해 주세요.",
        "fact_unknown": f"{field_id} 정보를 확인해 주세요.",
        "fact_candidate": f"{field_id} 정보가 맞는지 확인해 주세요.",
        "high_risk_claim": f"{field_id} 관련 주장은 근거가 필요합니다. 유지하지 않을지 확인해 주세요.",
    }.get(clarification_type)
    if prompt is None:
        raise SellerConfirmationContractError("Clarification type is unsupported.")
    allowed_answer_type = {
        "identity_conflict": "selected_observation_or_corrected_value",
        "rights": "rights_decision",
        "fact_conflict": "selected_observation_or_corrected_value",
        "fact_unknown": "value_or_unknown",
        "fact_candidate": "confirm_or_reject",
        "high_risk_claim": "acknowledge_or_reject",
    }[clarification_type]
    hash_input = {
        "schema_version": SELLER_CONFIRMATION_SCHEMA_VERSION,
        "type": clarification_type,
        "field_id": field_id,
        "priority": priority,
        "required": required,
        "truth_item": truth_reference,
        "source_refs": _reference_list(item.get("source_refs") or [], "clarification.source_refs"),
        "evidence_refs": _reference_list(item.get("evidence_refs") or [], "clarification.evidence_refs"),
        "allowed_options": observation_options,
}
    digest = canonical_hash(_canonicalize_version_value(hash_input))
    return {
        "clarification_id": "clarification:" + digest[:24],
        "type": clarification_type,
        "field_id": field_id,
        "question_code": f"lg12i.{clarification_type}.v1",
        "human_question": prompt,
        "reason": clarification_type,
        "priority": priority,
        "truth_item_ref": truth_reference,
        "source_refs": hash_input["source_refs"],
        "evidence_refs": hash_input["evidence_refs"],
        "allowed_answer_type": allowed_answer_type,
        "allowed_options": observation_options,
        "required": required,
        "clarification_hash": digest,
    }


def _truth_item_for_confirmation(
    truth: ProductTruthVersion, reference: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve a clarification item from frozen Truth, never a caller plan."""

    expected = _reference(reference, "confirmation.truth_item")
    normalization = dict(truth.normalization_json or {})
    for collection_name in ("fact_candidates", "unknown_facts", "conflict_facts", "prohibited_inferences"):
        for candidate in normalization.get(collection_name) or []:
            if not isinstance(candidate, Mapping):
                continue
            candidate_ref = candidate.get("reference")
            if isinstance(candidate_ref, Mapping) and _reference(candidate_ref, "confirmation.persisted_truth_item") == expected:
                return deepcopy(dict(candidate))
    raise SellerConfirmationContractError("Clarification does not reference a frozen Product Truth item.")


def _answer_identity_reference(answer: Mapping[str, Any]) -> dict[str, Any]:
    identity = {
        "clarification_id": answer["clarification_id"],
        "clarification_hash": answer["clarification_hash"],
        "decision": answer["decision"],
        "answer_value": answer.get("answer_value"),
        "unit": answer.get("unit"),
        "selected_observation_id": answer.get("selected_observation_id"),
    }
    digest = canonical_hash(_canonicalize_version_value(identity))
    return {
        "id": "seller-answer:" + digest[:24],
        "version": 1,
        "hash": digest,
        "schema_version": "lg12i-seller-answer-v1",
    }


def _clarification_identity_reference(question: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _require_id(question.get("clarification_id"), "clarification.id"),
        "version": 1,
        "hash": _require_hash(question.get("clarification_hash"), "clarification.hash"),
        "schema_version": "lg12i-seller-clarification-v1",
    }


def _seller_confirmed_fact_ref(
    *, truth_item: Mapping[str, Any], question: Mapping[str, Any], answer: Mapping[str, Any],
    actor_id: str, confirmation_cycle: int,
) -> dict[str, Any]:
    """Materialize the exact seller decision as an immutable confirmed fact."""

    original = _reference(truth_item.get("reference"), "confirmed.original_truth_item")
    source_refs = _reference_list(truth_item.get("source_refs") or [], "confirmed.source_refs")
    evidence_refs = _reference_list(truth_item.get("evidence_refs") or [], "confirmed.evidence_refs")
    observation_refs = _reference_list(truth_item.get("observation_refs") or [], "confirmed.observation_refs")
    field_id = _require_id(truth_item.get("field_id"), "confirmed.field_id")
    fact_id = _require_id(truth_item.get("fact_id"), "confirmed.fact_id")
    question_type = str(question.get("type") or "")
    selected_ref = None
    conflict_refs: list[dict[str, Any]] = []
    if question_type in {"fact_conflict", "identity_conflict"}:
        conflict_refs = observation_refs
        if answer.get("selected_observation_id"):
            option = next(
                (item for item in question.get("allowed_options") or [] if item.get("observation_id") == answer["selected_observation_id"]),
                None,
            )
            if not isinstance(option, Mapping) or option.get("observation_ref") is None:
                raise SellerConfirmationContractError("Selected observation is missing its frozen provenance identity.")
            selected_ref = _reference(option["observation_ref"], "confirmed.selected_observation")
            normalized_value = _confirmation_text(option.get("value"), "selected observation value", allow_empty=False)
            unit = option.get("unit")
            if unit is not None:
                unit = _confirmation_text(unit, "selected observation unit", allow_empty=False)
            source_kind = "selected_observation"
        else:
            normalized_value = _confirmation_text(answer.get("answer_value"), "seller corrected value", allow_empty=False)
            unit = answer.get("unit")
            source_kind = "seller_confirmation"
    elif question_type == "fact_unknown":
        normalized_value = _confirmation_text(answer.get("answer_value"), "seller confirmed value", allow_empty=False)
        unit = answer.get("unit")
        source_kind = "seller_confirmation"
    else:
        normalized_value = _confirmation_text(truth_item.get("value"), "Product Truth candidate value", allow_empty=False)
        structure = dict(truth_item.get("value_structure") or {})
        unit = structure.get("unit")
        source_kind = "product_truth_candidate"
    if unit is not None:
        unit = _confirmation_text(unit, "seller confirmed unit", allow_empty=False)
    clarification_ref = _clarification_identity_reference(question)
    answer_ref = _answer_identity_reference(answer)
    provenance_ref = (evidence_refs or source_refs)[0]
    provenance_identity = {
        "original_truth_item_ref": original,
        "fact_id": fact_id,
        "field_id": field_id,
        "normalized_value": normalized_value,
        "unit": unit,
        "source_kind": source_kind,
        "clarification_ref": clarification_ref,
        "answer_ref": answer_ref,
        "seller_actor_id": actor_id,
        "confirmation_cycle": confirmation_cycle,
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "selected_observation_ref": selected_ref,
        "conflicting_observation_refs": conflict_refs,
        "decision_status": "confirmed",
    }
    provenance_hash = canonical_hash(_canonicalize_version_value(provenance_identity))
    return {
        **{key: original[key] for key in ("id", "version", "hash")},
        "provenance_ref": provenance_ref,
        "confirmed_fact_id": "seller-confirmed-fact:" + provenance_hash[:24],
        "fact_id": fact_id,
        "field_id": field_id,
        "normalized_value": normalized_value,
        "unit": unit,
        "value_structure": {"value": normalized_value, "unit": unit},
        "source_kind": source_kind,
        "original_truth_item_ref": original,
        "clarification_ref": clarification_ref,
        "answer_ref": answer_ref,
        "seller_actor_id": actor_id,
        "confirmation_cycle": confirmation_cycle,
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "selected_observation_ref": selected_ref,
        "conflicting_observation_refs": conflict_refs,
        "provenance_hash": provenance_hash,
        "decision_status": "confirmed",
    }


def seller_confirmation_resume_request_hash(
    *, run: AgentRun, plan: Mapping[str, Any], actor_id: str,
) -> str:
    """Hash the immutable prompt identity a browser must echo on resume.

    This deliberately binds a response to the persisted run/thread and frozen
    Truth question set.  It is not derived from a mutable checkpoint or the
    transport timestamp, so it remains stable across a restart.
    """

    if not actor_id or actor_id != run.created_by:
        raise SellerConfirmationContractError("Seller confirmation resume identity belongs to the intake run actor.")
    identity = _require_mapping(plan.get("run_identity"), "confirmation.plan.run_identity")
    expected_thread = str(run.graph_thread_id or run.id)
    if str(identity.get("run_id") or "") != str(run.id) or str(identity.get("thread_id") or "") != expected_thread:
        raise SellerConfirmationContractError("Seller confirmation resume identity does not belong to this run/thread.")
    truth = _reference(plan.get("truth_version"), "confirmation.plan.truth_version")
    cycle = plan.get("confirmation_cycle")
    if not isinstance(cycle, int) or cycle < 1:
        raise SellerConfirmationContractError("Seller confirmation resume identity has an invalid cycle.")
    clarifications: list[dict[str, str]] = []
    for index, value in enumerate(_require_list(plan.get("clarifications"), "confirmation.plan.clarifications")):
        question = _require_mapping(value, f"confirmation.plan.clarifications[{index}]")
        clarification_id = str(question.get("clarification_id") or "")
        clarification_hash = _require_hash(question.get("clarification_hash"), f"confirmation.plan.clarifications[{index}].hash")
        if not clarification_id:
            raise SellerConfirmationContractError("Seller confirmation resume identity is missing a clarification ID.")
        clarifications.append({"id": clarification_id, "hash": clarification_hash})
    return canonical_hash(_canonicalize_version_value({
        "kind": "lg12i-seller-confirmation-resume-v1",
        "workspace_id": str(run.workspace_id),
        "project_id": str(run.project_id),
        "run_id": str(run.id),
        "thread_id": expected_thread,
        "actor_id": str(actor_id),
        "truth_version": truth,
        "confirmation_cycle": cycle,
        "clarifications": clarifications,
    }))


def seller_confirmation_answer_bundle_hash(*, decision: str, answers: Sequence[Mapping[str, Any]]) -> str:
    """Hash only the normalized seller answer bundle, independent of order.

    The browser is allowed to omit optional answer fields, while LangGraph's
    interrupt serialization may materialize the same absent fields as empty
    strings.  Both forms mean "no supplied value" and must retain the same
    public replay identity.
    """

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(answers):
        answer = _require_mapping(raw, f"confirmation.resume.answers[{index}]")
        allowed = {"clarification_id", "decision", "answer_value", "unit", "selected_observation_id"}
        if set(answer) - allowed:
            raise SellerConfirmationContractError("Seller confirmation answer contains unsupported fields.")
        clarification_id = str(answer.get("clarification_id") or "")
        if not clarification_id:
            raise SellerConfirmationContractError("Seller confirmation answer is missing its clarification ID.")
        normalized.append({
            "clarification_id": clarification_id,
            "decision": str(answer.get("decision") or ""),
            "answer_value": "" if answer.get("answer_value") is None else answer.get("answer_value"),
            "unit": "" if answer.get("unit") is None else answer.get("unit"),
            "selected_observation_id": (
                "" if answer.get("selected_observation_id") is None
                else answer.get("selected_observation_id")
            ),
        })
    normalized.sort(key=lambda item: item["clarification_id"])
    return canonical_hash(_canonicalize_version_value({
        "kind": "lg12i-seller-confirmation-answer-bundle-v1",
        "decision": str(decision),
        "answers": normalized,
    }))


def find_seller_confirmation_resume_replay(
    db: Session, *, run: AgentRun, actor_id: str, resume_request_hash: str, answer_bundle_hash: str,
) -> SellerConfirmationVersion | None:
    """Find an already-persisted successful public resume without replaying it.

    Request and answer hashes are both required: a stale request token paired
    with changed answers is rejected instead of silently returning the old
    decision.
    """

    request_hash = _require_hash(resume_request_hash, "confirmation.resume_request_hash")
    bundle_hash = _require_hash(answer_bundle_hash, "confirmation.resume_answer_bundle_hash")
    row = (
        db.query(SellerConfirmationVersion)
        .filter(
            SellerConfirmationVersion.workspace_id == run.workspace_id,
            SellerConfirmationVersion.project_id == run.project_id,
            SellerConfirmationVersion.creator_run_id == run.id,
            SellerConfirmationVersion.created_by == actor_id,
            SellerConfirmationVersion.resume_request_hash == request_hash,
        )
        .one_or_none()
    )
    if row is None:
        return None
    if row.resume_answer_bundle_hash != bundle_hash:
        raise SellerConfirmationContractError(
            "Seller confirmation resume identity was already persisted with a different response."
        )
    validate_immutable_version(db, row)
    return row


def build_seller_confirmation_plan(
    db: Session, *, run: AgentRun, truth_reference: Mapping[str, Any], confirmation_cycle: int = 1,
) -> dict[str, Any]:
    """Derive one deterministic, at-most-three-question review cycle.

    This reads only the frozen Truth version.  It neither promotes facts nor
    creates a confirmation version; that occurs only after a public resume.
    """

    if confirmation_cycle < 1:
        raise SellerConfirmationContractError("confirmation_cycle must be positive.")
    truth = _linked_row(
        db, ProductTruthVersion, project_id=run.project_id,
        reference=truth_reference, label="confirmation.truth",
    )
    if truth.workspace_id != run.workspace_id:
        raise SellerConfirmationContractError("Product Truth does not belong to this workspace.")
    if truth.creator_run_id != run.id:
        raise SellerConfirmationContractError("Product Truth does not belong to this intake run/thread.")
    normalization = dict(truth.normalization_json or {})
    questions: list[dict[str, Any]] = []
    for item in normalization.get("conflict_facts") or []:
        if not isinstance(item, Mapping):
            raise SellerConfirmationContractError("Product Truth conflict item is malformed.")
        questions.append(_clarification_from_truth_item(
            item,
            clarification_type="identity_conflict" if item.get("field_id") == "product_identity" else "fact_conflict",
            priority=1 if item.get("field_id") == "product_identity" else 3,
            required=True,
        ))
    rights = dict(normalization.get("rights_uncertainty") or {})
    if rights.get("state") == "rights_uncertain":
        rights_item = {
            "field_id": "final_use_rights",
            "reference": _truth_internal_reference(
                kind="rights_uncertainty",
                identity={"truth": _row_reference(truth), "rights": rights},
            ),
            "source_refs": list(rights.get("source_refs") or truth.evidence_refs_json or []),
            "evidence_refs": list(rights.get("source_refs") or truth.evidence_refs_json or []),
        }
        questions.append(_clarification_from_truth_item(
            rights_item, clarification_type="rights", priority=2, required=True,
        ))
    for item in normalization.get("unknown_facts") or []:
        if not isinstance(item, Mapping):
            raise SellerConfirmationContractError("Product Truth unknown item is malformed.")
        questions.append(_clarification_from_truth_item(
            item, clarification_type="fact_unknown", priority=4, required=True,
        ))
    for item in normalization.get("prohibited_inferences") or []:
        if not isinstance(item, Mapping):
            raise SellerConfirmationContractError("Product Truth prohibited inference is malformed.")
        questions.append(_clarification_from_truth_item(
            item, clarification_type="high_risk_claim", priority=5, required=True,
        ))
    questions.sort(key=lambda item: (int(item["priority"]), str(item["field_id"]), str(item["clarification_id"])))
    current = questions[:_CONFIRMATION_MAX_CLARIFICATIONS]
    queued = questions[_CONFIRMATION_MAX_CLARIFICATIONS:]
    plan = {
        "schema_version": SELLER_CONFIRMATION_SCHEMA_VERSION,
        "truth_version": _row_reference(truth),
        "run_identity": {"run_id": str(run.id), "thread_id": str(run.graph_thread_id or run.id)},
        "confirmation_cycle": confirmation_cycle,
        "confirmation_required": bool(current),
        "clarifications": current,
        "unresolved_queue": queued,
    }
    plan["resume_request_hash"] = seller_confirmation_resume_request_hash(
        run=run, plan=plan, actor_id=str(run.created_by),
    )
    return plan


def _validate_confirmation_answer(value: Any, question: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SellerConfirmationContractError("Clarification answer must be an object.")
    allowed = {"clarification_id", "decision", "answer_value", "unit", "selected_observation_id"}
    extras = set(value) - allowed
    if extras:
        raise SellerConfirmationContractError("Clarification answer contains unsupported fields.")
    if str(value.get("clarification_id") or "") != question["clarification_id"]:
        raise SellerConfirmationContractError("Clarification answer does not match the pending question.")
    decision = str(value.get("decision") or "skip").strip()
    if decision not in {"confirm", "reject", "unknown", "skip"}:
        raise SellerConfirmationContractError("Clarification decision is unsupported.")
    answer_value = value.get("answer_value")
    if answer_value is not None:
        answer_value = _confirmation_text(answer_value, "clarification answer")
    unit = value.get("unit")
    if unit is not None:
        unit = _confirmation_text(unit, "clarification answer unit")
    question_type = str(question.get("type") or "")
    allowed_answer_type = str(question.get("allowed_answer_type") or "")
    selection_question = question_type in {"fact_conflict", "identity_conflict"}
    if selection_question and allowed_answer_type != "selected_observation_or_corrected_value":
        raise SellerConfirmationContractError("Conflict clarification has an unsupported answer contract.")
    selected_raw = value.get("selected_observation_id")
    # Resume serializers may materialize an omitted optional ID as an empty
    # string. That is equivalent to omission for non-selection questions, but
    # remains fail-closed for a conflict selection below.
    selected = None
    if selected_raw is not None:
        if not isinstance(selected_raw, str):
            raise SellerConfirmationContractError("Selected observation must be text.")
        if selected_raw.strip():
            selected = _confirmation_text(selected_raw, "selected observation", allow_empty=False)
    if selected and (decision != "confirm" or not selection_question):
        raise SellerConfirmationContractError("This clarification does not allow an observation selection.")
    if selection_question and decision == "confirm" and selected and answer_value:
        raise SellerConfirmationContractError("A conflict confirmation must select an observation or provide a corrected value, not both.")
    if selection_question and decision == "confirm" and not (selected or answer_value):
        raise SellerConfirmationContractError("A conflict confirmation requires an observation selection or corrected value.")
    if question_type == "fact_unknown" and decision == "confirm" and not answer_value:
        raise SellerConfirmationContractError("An unknown fact confirmation requires a seller value.")
    if question_type == "rights" and decision not in {"confirm", "reject", "skip"}:
        raise SellerConfirmationContractError("Rights confirmation must be confirmed, rejected, or skipped.")
    if question_type == "high_risk_claim" and decision == "confirm":
        raise SellerConfirmationContractError("A prohibited inference cannot be approved by seller confirmation alone.")
    if selected and selected not in {str(option.get("observation_id") or "") for option in question.get("allowed_options") or []}:
        raise SellerConfirmationContractError("Selected conflict observation is not part of the pending clarification.")
    return {
        "clarification_id": question["clarification_id"], "clarification_hash": question["clarification_hash"],
        "decision": decision, "answer_value": answer_value, "unit": unit,
        "selected_observation_id": selected,
    }


def validate_seller_confirmation_answers(
    *, plan: Mapping[str, Any], answers: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Validate a frozen confirmation answer bundle without writing rows."""

    current = [dict(item) for item in plan.get("clarifications") or []]
    if len(current) > _CONFIRMATION_MAX_CLARIFICATIONS:
        raise SellerConfirmationContractError("A confirmation cycle cannot contain more than three clarifications.")
    supplied = list(answers or [])
    if len(supplied) > len(current):
        raise SellerConfirmationContractError("Clarification answer count exceeds the pending questions.")
    raw_by_id: dict[str, Mapping[str, Any]] = {}
    for answer in supplied:
        if not isinstance(answer, Mapping):
            raise SellerConfirmationContractError("Clarification answer must be an object.")
        identifier = str(answer.get("clarification_id") or "")
        if not identifier or identifier in raw_by_id:
            raise SellerConfirmationContractError("Clarification answers must have unique pending IDs.")
        raw_by_id[identifier] = answer
    if set(raw_by_id) - {str(question.get("clarification_id") or "") for question in current}:
        raise SellerConfirmationContractError("Clarification answer targets a question outside the current cycle.")
    return {
        str(question["clarification_id"]): _validate_confirmation_answer(
            raw_by_id.get(
                str(question["clarification_id"]),
                {"clarification_id": question["clarification_id"], "decision": "skip"},
            ),
            question,
        )
        for question in current
    }


def _confirmation_unresolved_ref(question: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "clarification_id": question["clarification_id"],
        "clarification_hash": question["clarification_hash"],
        "type": question["type"], "field_id": question["field_id"],
        "truth_item_ref": _reference(question["truth_item_ref"], "unresolved.truth_item"),
    }


def _source_has_final_use_forbidden_provenance(source: ProductSourceSnapshotVersion) -> bool:
    """Keep a seller attestation from relabelling a forbidden source as owned."""

    forbidden = {"supplier", "reference", "reference_only", "competitor", "blocked"}

    def _walk(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(_walk(item) for item in value.values())
        if isinstance(value, list):
            return any(_walk(item) for item in value)
        return isinstance(value, str) and value.strip().lower() in forbidden

    return _walk(dict(source.provenance_json or {})) or _walk(dict(source.rights_json or {})) or _walk(
        dict(source.source_fidelity_json or {})
    )


def _locked_confirmation_scope(
    db: Session, *, run: AgentRun, truth_reference: Mapping[str, Any], actor_id: str,
) -> tuple[AgentRun, ProductTruthVersion, SellerConfirmationVersion | None]:
    """Lock the durable scope that serializes one confirmation lineage.

    PostgreSQL holds ``FOR UPDATE`` locks until the surrounding Session
    transaction commits.  Locking the project first prevents the global
    immutable version counter from racing across two intake runs; locking the
    run then serializes confirmation cycles for its thread.  SQLite tests do
    not prove those PostgreSQL locks, so the matching database unique
    constraint remains a mandatory backstop.
    """

    project = (
        db.query(ProductProject)
        .filter(ProductProject.id == run.project_id, ProductProject.workspace_id == run.workspace_id)
        .with_for_update()
        .one_or_none()
    )
    if project is None:
        raise SellerConfirmationContractError("Seller confirmation project is unavailable in this workspace.")
    locked_run = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == run.id,
            AgentRun.workspace_id == run.workspace_id,
            AgentRun.project_id == run.project_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if locked_run is None or locked_run.created_by != actor_id:
        raise SellerConfirmationContractError("Only the actor that started this intake run may submit seller confirmation.")
    truth = _linked_row(
        db,
        ProductTruthVersion,
        project_id=locked_run.project_id,
        reference=truth_reference,
        label="confirmation.truth",
    )
    if truth.workspace_id != locked_run.workspace_id:
        raise SellerConfirmationContractError("Product Truth does not belong to this workspace.")
    if truth.creator_run_id != locked_run.id:
        raise SellerConfirmationContractError("Product Truth does not belong to this intake run/thread.")
    latest = (
        db.query(SellerConfirmationVersion)
        .filter(
            SellerConfirmationVersion.workspace_id == locked_run.workspace_id,
            SellerConfirmationVersion.project_id == locked_run.project_id,
            SellerConfirmationVersion.creator_run_id == locked_run.id,
            SellerConfirmationVersion.created_by == locked_run.created_by,
            SellerConfirmationVersion.truth_version_id == truth.id,
            SellerConfirmationVersion.truth_version == truth.version,
            SellerConfirmationVersion.truth_version_hash == truth.canonical_hash,
        )
        .order_by(SellerConfirmationVersion.confirmation_cycle.desc())
        .with_for_update()
        .first()
    )
    return locked_run, truth, latest


def _require_immediate_confirmation_parent(
    *, latest: SellerConfirmationVersion | None, cycle: int, parent_reference: Mapping[str, Any] | None,
) -> tuple[str | None, int | None, str | None]:
    """Require cycle 1 or the exact persisted immediately preceding parent."""

    if latest is None:
        if cycle != 1 or parent_reference is not None:
            raise SellerConfirmationContractError("Initial seller confirmation must be cycle 1 without a parent.")
        return None, None, None
    expected = _row_reference(latest)
    if cycle != latest.confirmation_cycle + 1:
        raise SellerConfirmationContractError("Seller confirmation cycle is stale or skips the persisted latest cycle.")
    if parent_reference is None or _reference(parent_reference, "confirmation.parent") != expected:
        raise SellerConfirmationContractError("Seller confirmation successor must pin the exact latest parent ID/version/hash.")
    return str(latest.id), int(latest.version), str(latest.canonical_hash)


def _validate_confirmation_plan_scope(run: AgentRun, plan: Mapping[str, Any]) -> None:
    identity = _require_mapping(plan.get("run_identity"), "confirmation.plan.run_identity")
    if set(identity) != {"run_id", "thread_id"}:
        raise SellerConfirmationContractError("Seller confirmation plan run identity is malformed.")
    expected_thread = str(run.graph_thread_id or run.id)
    if str(identity.get("run_id") or "") != str(run.id) or str(identity.get("thread_id") or "") != expected_thread:
        raise SellerConfirmationContractError("Seller confirmation plan does not belong to this run/thread.")


def apply_seller_confirmation_cycle(
    db: Session, *, run: AgentRun, plan: Mapping[str, Any], answers: Sequence[Mapping[str, Any]], actor_id: str,
    resume_request_hash: str | None = None, resume_answer_bundle_hash: str | None = None,
    resume_decision: str = "submit",
) -> dict[str, Any]:
    """Persist one immutable seller response without resolving untouched work."""

    _validate_confirmation_plan_scope(run, plan)
    truth_reference = _reference(plan.get("truth_version"), "confirmation.plan.truth_version")
    locked_run, truth, latest = _locked_confirmation_scope(
        db, run=run, truth_reference=truth_reference, actor_id=actor_id,
    )
    source = _linked_row(
        db,
        ProductSourceSnapshotVersion,
        project_id=locked_run.project_id,
        reference={"id": truth.source_snapshot_version_id, "version": truth.source_snapshot_version, "hash": truth.source_snapshot_hash},
        label="confirmation.source",
    )
    current = [dict(item) for item in plan.get("clarifications") or []]
    queued = [dict(item) for item in plan.get("unresolved_queue") or []]
    validated_answers = validate_seller_confirmation_answers(plan=plan, answers=answers)

    cycle = int(plan.get("confirmation_cycle") or 0)
    if cycle < 1:
        raise SellerConfirmationContractError("Seller confirmation cycle must be positive.")
    parent_reference = plan.get("parent_confirmation_version")
    if parent_reference is not None and not isinstance(parent_reference, Mapping):
        raise SellerConfirmationContractError("Seller confirmation parent reference is malformed.")
    expected_resume_request_hash = seller_confirmation_resume_request_hash(
        run=locked_run, plan=plan, actor_id=actor_id,
    )
    supplied_resume_request_hash = resume_request_hash or expected_resume_request_hash
    if _require_hash(supplied_resume_request_hash, "confirmation.resume_request_hash") != expected_resume_request_hash:
        raise SellerConfirmationContractError("Seller confirmation resume request does not match the frozen clarification cycle.")
    expected_answer_bundle_hash = seller_confirmation_answer_bundle_hash(
        decision=resume_decision, answers=answers,
    )
    supplied_answer_bundle_hash = resume_answer_bundle_hash or expected_answer_bundle_hash
    if _require_hash(supplied_answer_bundle_hash, "confirmation.resume_answer_bundle_hash") != expected_answer_bundle_hash:
        raise SellerConfirmationContractError("Seller confirmation answer bundle does not match the submitted response.")
    decision_base = latest
    if latest is not None and latest.confirmation_cycle == cycle:
        decision_base = (
            _linked_row(
                db,
                SellerConfirmationVersion,
                project_id=locked_run.project_id,
                reference={
                    "id": latest.parent_version_id,
                    "version": latest.parent_version,
                    "hash": latest.parent_version_hash,
                },
                label="confirmation.parent",
            )
            if latest.parent_version_id is not None
            else None
        )
    confirmed = [dict(item) for item in decision_base.confirmed_fact_refs_json or []] if decision_base else []
    rejected = [dict(item) for item in decision_base.rejected_fact_refs_json or []] if decision_base else []
    unknown = [dict(item) for item in decision_base.unknown_fact_refs_json or []] if decision_base else []
    rights_decisions = [dict(item) for item in decision_base.rights_confirmations_json or []] if decision_base else []
    recorded_answers: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for question in current:
        answer = validated_answers[str(question["clarification_id"])]
        answer = {**answer, **_answer_identity_reference(answer)}
        recorded_answers.append(answer)
        question_type = str(question["type"])
        truth_item = None if question_type == "rights" else _truth_item_for_confirmation(truth, question["truth_item_ref"])
        fact_ref = (
            _confirmation_item_reference(truth_item, label="confirmation.truth_item")
            if truth_item is not None else None
        )
        if question_type == "rights":
            provenance_blocked = _source_has_final_use_forbidden_provenance(source)
            status = (
                "provenance_blocked" if answer["decision"] == "confirm" and provenance_blocked
                else "rights_confirmed" if answer["decision"] == "confirm"
                else "rights_rejected" if answer["decision"] == "reject"
                else "unconfirmed"
            )
            rights_decisions.append({
                "clarification_id": question["clarification_id"], "status": status,
                "source_refs": list(question.get("source_refs") or []),
                "final_use_status": "not_approved" if status != "rights_confirmed" else "eligible_pending_later_gate",
            })
            if status in {"unconfirmed", "provenance_blocked"}:
                unresolved.append(_confirmation_unresolved_ref(question))
        elif question_type == "high_risk_claim":
            # A seller acknowledgement cannot turn unsupported evidence into a fact.
            if answer["decision"] == "reject":
                assert fact_ref is not None
                rejected.append(fact_ref)
            else:
                unresolved.append(_confirmation_unresolved_ref(question))
        elif answer["decision"] == "confirm":
            assert truth_item is not None
            confirmed.append(_seller_confirmed_fact_ref(
                truth_item=truth_item,
                question=question,
                answer=answer,
                actor_id=actor_id,
                confirmation_cycle=cycle,
            ))
        elif answer["decision"] == "reject":
            assert fact_ref is not None
            rejected.append(fact_ref)
        elif answer["decision"] == "unknown":
            assert fact_ref is not None
            unknown.append(fact_ref)
        else:
            unresolved.append(_confirmation_unresolved_ref(question))
    unresolved.extend(_confirmation_unresolved_ref(question) for question in queued)

    # A confirmation row pins the answer and all remaining work.  Existing
    # questions are immutable: a later cycle is a successor instead of an
    # in-place overwrite.
    # A repeated public resume can replay the same Command after a response was
    # persisted.  Reuse that exact immutable cycle instead of writing a second
    # confirmation row with equivalent answers.
    confirmation = None
    if latest is not None and latest.confirmation_cycle == cycle:
        # A duplicate public resume carries the same frozen clarification set
        # and answer identities.  Reuse it rather than incrementing a cycle or
        # duplicating decisions.  Any changed payload is a stale/replay error.
        if (
            list(latest.clarification_refs_json or []) == current
            and list(latest.answers_json or []) == recorded_answers
            and list(latest.unresolved_refs_json or []) == unresolved
            and list(latest.confirmed_fact_refs_json or []) == confirmed
            and list(latest.rejected_fact_refs_json or []) == rejected
            and list(latest.unknown_fact_refs_json or []) == unknown
            and list(latest.rights_confirmations_json or []) == rights_decisions
        ):
            confirmation = latest
        else:
            raise SellerConfirmationContractError("Seller confirmation cycle has already been persisted with a different response.")
    elif confirmation is None:
        _require_immediate_confirmation_parent(
            latest=latest,
            cycle=cycle,
            parent_reference=parent_reference,
        )
    if confirmation is None:
        confirmation = create_seller_confirmation_version(
            db,
            workspace_id=locked_run.workspace_id, project_id=locked_run.project_id,
            creator_run_id=locked_run.id, created_by=actor_id,
            truth_reference=_row_reference(truth), answers=recorded_answers,
            confirmed_fact_refs=confirmed, rejected_fact_refs=rejected,
            unknown_fact_refs=unknown, rights_confirmations=rights_decisions,
            clarification_refs=current, unresolved_refs=unresolved,
            confirmation_cycle=cycle,
            parent_confirmation_reference=parent_reference,
            resume_request_hash=expected_resume_request_hash,
            resume_answer_bundle_hash=expected_answer_bundle_hash,
        )
        db.commit()
        db.refresh(confirmation)
    else:
        validate_immutable_version(db, confirmation)
    remaining_questions = [
        *[
            question for question in current
            if question["clarification_id"] in {item["clarification_id"] for item in unresolved}
        ],
        *queued,
    ]
    # Preserve the prior deterministic ordering rather than re-ranking seller
    # questions after an answer.  It keeps resume/rebuild stable.
    next_current = remaining_questions[:_CONFIRMATION_MAX_CLARIFICATIONS]
    next_queue = remaining_questions[_CONFIRMATION_MAX_CLARIFICATIONS:]
    return {
        "confirmation_version": _row_reference(confirmation),
        "confirmation_cycle": confirmation.confirmation_cycle,
        "confirmation_ready": not remaining_questions,
        "clarifications": next_current,
        "unresolved_queue": next_queue,
        "unresolved_refs": unresolved,
        "rights_decisions": rights_decisions,
    }


def create_seller_confirmation_version(
    db: Session, *, workspace_id: str, project_id: str, creator_run_id: str, created_by: str,
    truth_reference: Mapping[str, Any], answers: Sequence[Mapping[str, Any]],
    confirmed_fact_refs: Sequence[Mapping[str, Any]], rejected_fact_refs: Sequence[Mapping[str, Any]],
    unknown_fact_refs: Sequence[Mapping[str, Any]],
    rights_confirmations: Sequence[Mapping[str, Any]], parent_confirmation_reference: Mapping[str, Any] | None = None,
    confirmation_cycle: int = 1, clarification_refs: Sequence[Mapping[str, Any]] = (),
    unresolved_refs: Sequence[Mapping[str, Any]] = (), confirmed_at: datetime.datetime | None = None,
    resume_request_hash: str | None = None, resume_answer_bundle_hash: str | None = None,
    schema_version: str = SELLER_CONFIRMATION_SCHEMA_VERSION,
) -> SellerConfirmationVersion:
    if schema_version != SELLER_CONFIRMATION_SCHEMA_VERSION:
        raise IntakeVersionContractError("Seller confirmation schema version is unsupported.")
    if not isinstance(confirmation_cycle, int) or confirmation_cycle < 1:
        raise IntakeVersionContractError("Seller confirmation cycle must be a positive integer.")
    run = _require_run(db, run_id=creator_run_id, workspace_id=workspace_id, project_id=project_id)
    if run.created_by != created_by:
        raise IntakeVersionContractError("Seller confirmation creator must be the immutable intake run actor.")
    locked_run, truth, latest = _locked_confirmation_scope(
        db, run=run, truth_reference=truth_reference, actor_id=created_by,
    )
    parent_id, parent_version, parent_hash = _require_immediate_confirmation_parent(
        latest=latest,
        cycle=confirmation_cycle,
        parent_reference=parent_confirmation_reference,
    )
    # Internal callers that construct a version directly still receive the
    # same immutable identity.  Public LangGraph resumes always pass the
    # already-validated hashes from ``apply_seller_confirmation_cycle``.
    if resume_request_hash is None:
        resume_request_hash = seller_confirmation_resume_request_hash(
            run=locked_run,
            actor_id=created_by,
            plan={
                "run_identity": {"run_id": str(locked_run.id), "thread_id": str(locked_run.graph_thread_id or locked_run.id)},
                "truth_version": _row_reference(truth),
                "confirmation_cycle": confirmation_cycle,
                "clarifications": list(clarification_refs),
            },
        )
    if resume_answer_bundle_hash is None:
        # This constructor is also used by immutable-contract fixtures that
        # persist an audit answer record rather than the public LangGraph
        # resume payload.  Public resumes always supply the stricter
        # ``seller_confirmation_answer_bundle_hash`` above; direct immutable
        # construction still pins a deterministic, non-replayable answer
        # identity without accepting it as a public resume contract.
        resume_answer_bundle_hash = canonical_hash(_canonicalize_version_value({
            "kind": "lg12i-seller-confirmation-direct-answer-bundle-v1",
            "answers": _require_list(answers, "confirmation.answers"),
        }))
    request_hash = _require_hash(resume_request_hash, "confirmation.resume_request_hash")
    answer_hash = _require_hash(resume_answer_bundle_hash, "confirmation.resume_answer_bundle_hash")
    row = SellerConfirmationVersion(
        workspace_id=locked_run.workspace_id, project_id=locked_run.project_id, creator_run_id=locked_run.id, created_by=created_by,
        version=_next_version(db, SellerConfirmationVersion, project_id), schema_version=schema_version,
        truth_version_id=truth.id, truth_version=truth.version, truth_version_hash=truth.canonical_hash, parent_version_id=parent_id, parent_version=parent_version, parent_version_hash=parent_hash,
        answers_json=_require_list(answers, "confirmation.answers"), confirmation_cycle=confirmation_cycle,
        clarification_refs_json=_require_list(clarification_refs, "confirmation.clarifications"),
        unresolved_refs_json=_require_list(unresolved_refs, "confirmation.unresolved_refs"),
        resume_request_hash=request_hash, resume_answer_bundle_hash=answer_hash,
        confirmed_fact_refs_json=_fact_state_reference_list(
            confirmed_fact_refs,
            "confirmation.confirmed_fact_refs",
            require_confirmed_value=True,
        ),
        rejected_fact_refs_json=_fact_state_reference_list(rejected_fact_refs, "confirmation.rejected_fact_refs"),
        unknown_fact_refs_json=_fact_state_reference_list(unknown_fact_refs, "confirmation.unknown_fact_refs"),
        rights_confirmations_json=_require_list(rights_confirmations, "confirmation.rights_confirmations"),
        confirmed_at=confirmed_at or datetime.datetime.utcnow(), canonical_hash="",
    )
    row.canonical_hash = canonical_version_hash(_confirmation_payload(row))
    _check_registered_hash(db, SellerConfirmationVersion, project_id=project_id, digest=row.canonical_hash)
    db.add(row); db.flush(); validate_immutable_version(db, row)
    return row


def ensure_seller_confirmation_not_required(
    db: Session, *, run: AgentRun, truth_reference: Mapping[str, Any],
) -> SellerConfirmationVersion:
    """Persist/reuse the explicit empty confirmation identity for a clean Truth.

    A Master always references a SellerConfirmationVersion.  When the frozen
    Truth contains no clarification work, this small immutable row records that
    fact without pretending a seller response occurred.
    """

    truth = _linked_row(db, ProductTruthVersion, project_id=run.project_id, reference=truth_reference, label="confirmation_not_required.truth")
    if truth.workspace_id != run.workspace_id or truth.creator_run_id != run.id:
        raise IntakeVersionContractError("No-op seller confirmation must use this run's frozen Truth.")
    existing = db.query(SellerConfirmationVersion).filter_by(
        workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
        truth_version_id=truth.id, confirmation_cycle=1,
    ).one_or_none()
    if existing is not None:
        validate_immutable_version(db, existing)
        return existing
    return create_seller_confirmation_version(
        db, workspace_id=run.workspace_id, project_id=run.project_id,
        creator_run_id=run.id, created_by=run.created_by,
        truth_reference=_row_reference(truth), answers=[], confirmed_fact_refs=[],
        rejected_fact_refs=[], unknown_fact_refs=[], rights_confirmations=[],
        clarification_refs=[], unresolved_refs=[],
    )


def create_commerce_creative_master_version(
    db: Session, *, workspace_id: str, project_id: str, creator_run_id: str, created_by: str,
    source_reference: Mapping[str, Any], truth_reference: Mapping[str, Any], confirmation_reference: Mapping[str, Any],
    creative_brief_reference: Mapping[str, Any], brand_kit_reference: Mapping[str, Any],
    evidence_artifact_refs: Sequence[Mapping[str, Any]], approved_fact_snapshot_ref: Mapping[str, Any],
    approved_asset_manifest_ref: Mapping[str, Any], copy_artifact_ref: Mapping[str, Any],
    page_plan_artifact_ref: Mapping[str, Any], target_channels: Sequence[str],
    downstream_output_refs: Sequence[Mapping[str, Any]] = (), parent_version_id: str | None = None,
    schema_version: str = COMMERCE_CREATIVE_MASTER_SCHEMA_VERSION,
) -> CommerceCreativeMasterVersion:
    if schema_version != COMMERCE_CREATIVE_MASTER_SCHEMA_VERSION:
        raise IntakeVersionContractError("Commerce Creative Master schema version is unsupported.")
    _require_run(db, run_id=creator_run_id, workspace_id=workspace_id, project_id=project_id)
    source = _linked_row(db, ProductSourceSnapshotVersion, project_id=project_id, reference=source_reference, label="master.source")
    truth = _linked_row(db, ProductTruthVersion, project_id=project_id, reference=truth_reference, label="master.truth")
    confirmation = _linked_row(db, SellerConfirmationVersion, project_id=project_id, reference=confirmation_reference, label="master.confirmation")
    if truth.source_snapshot_version_id != source.id or confirmation.truth_version_id != truth.id:
        raise IntakeVersionContractError("Commerce Creative Master requires Source -> Truth -> Confirmation lineage.")
    if any(item.workspace_id != workspace_id or item.creator_run_id != creator_run_id for item in (source, truth, confirmation)):
        raise IntakeVersionContractError("Commerce Creative Master lineage must belong to its exact workspace and run.")
    brief_ref = _reference(creative_brief_reference, "master.creative_brief")
    brand_ref = _reference(brand_kit_reference, "master.brand_kit")
    brief = db.query(ProductCreativeBriefVersion).filter_by(id=brief_ref["id"], project_id=project_id).first()
    brand_kit = db.query(BrandKitVersion).filter_by(id=brand_ref["id"], workspace_id=workspace_id).first()
    if brief is None or (brief.version, brief.output_hash) != (brief_ref["version"], brief_ref["hash"]):
        raise IntakeVersionContractError("Commerce Creative Master Creative Brief reference is invalid.")
    if brand_kit is None or (brand_kit.version, brand_kit.content_hash) != (brand_ref["version"], brand_ref["hash"]):
        raise IntakeVersionContractError("Commerce Creative Master Brand Kit reference is invalid.")
    validate_lg12i_brand_kit_scope(
        brand_kit, workspace_id=workspace_id, project_id=project_id
    )
    normalized_channels = sorted(set(str(channel) for channel in target_channels if isinstance(channel, str) and channel))
    if not normalized_channels or any(channel not in supported_channel_keys() for channel in normalized_channels):
        raise IntakeVersionContractError("Commerce Creative Master must pin supported target channels.")
    _validate_lg12i_creative_brief_links(
        brief=brief, source=source, truth=truth, confirmation=confirmation,
        brand_kit=brand_kit, creator_run_id=creator_run_id, target_channels=normalized_channels,
    )
    if list(confirmation.unresolved_refs_json or []):
        raise IntakeVersionContractError("Commerce Creative Master cannot be created while seller confirmation is unresolved.")
    prohibited_refs = {
        (item["id"], item["version"], item["hash"])
        for item in _reference_list(
            truth.prohibited_inference_refs_json,
            "truth.prohibited_inference_refs",
        )
    }
    rejected_refs: set[tuple[str, int, str]] = set()
    confirmation_cursor: SellerConfirmationVersion | None = confirmation
    seen_confirmation_ids: set[str] = set()
    while confirmation_cursor is not None:
        if str(confirmation_cursor.id) in seen_confirmation_ids:
            raise IntakeVersionContractError("Seller confirmation lineage contains a cycle.")
        seen_confirmation_ids.add(str(confirmation_cursor.id))
        rejected_refs.update(
            (item["id"], item["version"], item["hash"])
            for item in _fact_state_reference_list(
                confirmation_cursor.rejected_fact_refs_json,
                "confirmation.rejected_fact_refs",
            )
        )
        if confirmation_cursor.parent_version_id is None:
            confirmation_cursor = None
            continue
        confirmation_cursor = db.query(SellerConfirmationVersion).filter_by(
            id=confirmation_cursor.parent_version_id,
            project_id=project_id,
            workspace_id=workspace_id,
            creator_run_id=creator_run_id,
        ).one_or_none()
        if confirmation_cursor is None:
            raise IntakeVersionContractError("Seller confirmation parent is missing from the same intake lineage.")
    if prohibited_refs - rejected_refs:
        raise IntakeVersionContractError("Commerce Creative Master cannot promote unresolved prohibited inferences.")
    fact_ref = _reference(approved_fact_snapshot_ref, "master.approved_fact_snapshot")
    fact_snapshot = db.query(FactSnapshot).filter_by(id=fact_ref["id"], project_id=project_id).first()
    if fact_snapshot is None or fact_ref["version"] != 1 or fact_snapshot.snapshot_hash != fact_ref["hash"]:
        raise IntakeVersionContractError("Commerce Creative Master approved fact snapshot reference is invalid.")
    _validate_master_approved_fact_states(fact_snapshot, confirmation)
    evidence_refs = sorted(_reference_list(evidence_artifact_refs, "master.evidence_artifacts"), key=_canonical_collection_sort_key)
    expected_evidence_refs = sorted(_reference_list(truth.evidence_refs_json, "truth.evidence_refs"), key=_canonical_collection_sort_key)
    if not evidence_refs or evidence_refs != expected_evidence_refs:
        raise IntakeVersionContractError("Commerce Creative Master must pin evidence artifact references.")
    live_assets, _asset_exclusions = resolve_lg12i_final_use_assets(
        db, project_id=project_id, source=source, confirmation=confirmation,
    )
    if live_assets != list(brief.usable_asset_refs_json or []):
        raise IntakeVersionContractError("Commerce Creative Master cannot use stale or tampered Brief asset bytes.")
    expected_manifest = lg12i_approved_asset_manifest_reference(
        source_reference=_row_reference(source), usable_asset_refs=live_assets,
    )
    if _reference(approved_asset_manifest_ref, "master.approved_asset_manifest") != expected_manifest:
        raise IntakeVersionContractError("Commerce Creative Master approved asset manifest does not match the frozen Brief assets.")
    for key, reference in (("copywriting", copy_artifact_ref), ("page_planning", page_plan_artifact_ref)):
        expected_pending = lg12i_pending_production_artifact_reference(
            artifact_key=key, creative_brief_reference=_row_reference(brief, hash_field="output_hash"),
        )
        supplied = _reference(reference, f"master.{key}")
        if supplied.get("schema_version") == LG12I_PENDING_PRODUCTION_ARTIFACT_SCHEMA_VERSION and supplied != expected_pending:
            raise IntakeVersionContractError(f"Commerce Creative Master pending {key} reference is stale or tampered.")
    parent_id, parent_version, parent_hash = _validate_parent(db, CommerceCreativeMasterVersion, project_id=project_id, parent_version_id=parent_version_id)
    if parent_id:
        parent = db.query(CommerceCreativeMasterVersion).filter_by(id=parent_id, project_id=project_id).one()
        if (
            parent.workspace_id != workspace_id or parent.creator_run_id != creator_run_id
            or parent.source_snapshot_version_id != source.id or parent.truth_version_id != truth.id
            or parent.confirmation_version_id != confirmation.id
        ):
            raise IntakeVersionContractError("Commerce Creative Master successor cannot change its source/truth/confirmation lineage.")
    row = CommerceCreativeMasterVersion(
        workspace_id=workspace_id, project_id=project_id, creator_run_id=creator_run_id, created_by=created_by,
        version=_next_version(db, CommerceCreativeMasterVersion, project_id), schema_version=schema_version,
        parent_version_id=parent_id, parent_version=parent_version, parent_version_hash=parent_hash,
        source_snapshot_version_id=source.id, source_snapshot_version=source.version, source_snapshot_hash=source.canonical_hash,
        truth_version_id=truth.id, truth_version=truth.version, truth_version_hash=truth.canonical_hash,
        confirmation_version_id=confirmation.id, confirmation_version=confirmation.version, confirmation_version_hash=confirmation.canonical_hash,
        creative_brief_version_id=brief.id, creative_brief_version=brief.version, creative_brief_hash=brief.output_hash,
        brand_kit_version_id=brand_kit.id, brand_kit_version=brand_kit.version, brand_kit_hash=brand_kit.content_hash,
        evidence_artifact_refs_json=evidence_refs,
        approved_fact_snapshot_ref_json=fact_ref,
        approved_asset_manifest_ref_json=_reference(approved_asset_manifest_ref, "master.approved_asset_manifest"),
        copy_artifact_ref_json=_reference(copy_artifact_ref, "master.copy_artifact"),
        page_plan_artifact_ref_json=_reference(page_plan_artifact_ref, "master.page_plan_artifact"),
        target_channels=normalized_channels,
        downstream_output_refs_json=_require_list(downstream_output_refs, "master.downstream_outputs"), canonical_hash="",
    )
    _validate_downstream_refs(row)
    semantic_hash = _master_idempotency_hash(_master_payload(row))
    for existing in db.query(CommerceCreativeMasterVersion).filter_by(project_id=project_id).all():
        if _master_idempotency_hash(_master_payload(existing)) == semantic_hash:
            validate_immutable_version(db, existing)
            return existing
    row.canonical_hash = canonical_version_hash(_master_payload(row))
    _check_registered_hash(db, CommerceCreativeMasterVersion, project_id=project_id, digest=row.canonical_hash)
    db.add(row); db.flush(); validate_immutable_version(db, row)
    return row


def master_reference_index(master: CommerceCreativeMasterVersion) -> dict[str, Any]:
    """Return only the immutable index; no raw source/copy/asset body is exposed."""

    validate_payload = _master_payload(master)
    return deepcopy({key: value for key, value in validate_payload.items() if key not in {"workspace_id", "project_id", "creator_run_id"}})
