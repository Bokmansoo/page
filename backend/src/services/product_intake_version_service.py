"""Immutable LG-12I Product Intake version and lineage contracts.

This module deliberately contains no routing, provider, adapter, or UI code.
It establishes the small durable contract that later LG-12I graph nodes share.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    BrandKitVersion,
    CommerceCreativeMasterVersion,
    FactSnapshot,
    ProductCreativeBriefVersion,
    ProductSourceSnapshotVersion,
    ProductTruthVersion,
    SellerConfirmationVersion,
)
from src.services.prompt_intelligence_service import canonical_hash


PRODUCT_SOURCE_SNAPSHOT_SCHEMA_VERSION = "lg12i-product-source-snapshot-v1"
PRODUCT_TRUTH_SCHEMA_VERSION = "lg12i-product-truth-v1"
SELLER_CONFIRMATION_SCHEMA_VERSION = "lg12i-seller-confirmation-v1"
COMMERCE_CREATIVE_MASTER_SCHEMA_VERSION = "lg12i-commerce-creative-master-v1"
_SHA256_CHARS = set("0123456789abcdef")
_MASTER_REFERENCE_KEYS = {"id", "version", "hash", "schema_version", "artifact_key"}
_DOWNSTREAM_KINDS = {"DetailPageVersion", "SocialKitVersion", "VideoProjectVersion"}
_UNORDERED_REFERENCE_COLLECTION_FIELDS = frozenset({
    "source_refs", "fact_refs", "evidence_refs", "unknown_refs", "conflict_refs",
    "prohibited_inference_refs", "confirmed_fact_refs", "rejected_fact_refs",
    "unknown_fact_refs", "evidence_artifacts", "asset_refs", "artifact_refs",
    "rights_confirmations", "target_channels", "downstream_outputs",
})


class IntakeVersionContractError(ValueError):
    """An immutable LG-12I version or its lineage is invalid."""


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


def _fact_state_reference(value: Any, label: str) -> dict[str, Any]:
    """Pin a seller decision to both a fact identity and provenance identity."""

    # Validation may run against a persisted JSON field.  Never mutate that
    # field while checking it: persisted versions must remain read-only even
    # during canonical/lineage validation.
    item = dict(_require_mapping(value, label))
    provenance = item.pop("provenance_ref", None)
    fact = _reference(item, label)
    if provenance is None:
        raise IntakeVersionContractError(f"{label}.provenance_ref is required.")
    fact["provenance_ref"] = _reference(provenance, f"{label}.provenance_ref")
    return fact


def _fact_state_reference_list(value: Any, label: str) -> list[dict[str, Any]]:
    return [_fact_state_reference(item, f"{label}[{index}]") for index, item in enumerate(_require_list(value, label))]


def _validate_confirmation_fact_states(row: SellerConfirmationVersion, truth: ProductTruthVersion) -> None:
    states = {
        "confirmed": _fact_state_reference_list(row.confirmed_fact_refs_json, "confirmation.confirmed_fact_refs"),
        "rejected": _fact_state_reference_list(row.rejected_fact_refs_json, "confirmation.rejected_fact_refs"),
        "unknown": _fact_state_reference_list(row.unknown_fact_refs_json, "confirmation.unknown_fact_refs"),
    }
    known_truth_facts = {
        (item["id"], item["version"], item["hash"])
        for item in _reference_list(truth.fact_refs_json, "truth.fact_refs")
    }
    assigned: dict[tuple[str, int, str], str] = {}
    for state, references in states.items():
        for reference in references:
            identity = (reference["id"], reference["version"], reference["hash"])
            if identity not in known_truth_facts:
                raise IntakeVersionContractError("Seller confirmation fact state must reference a fact pinned by Product Truth.")
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
    }


def _confirmation_payload(row: SellerConfirmationVersion) -> dict[str, Any]:
    return {
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
        if row.schema_version != expected_schema:
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
    if (row.creative_brief_version, row.creative_brief_hash) != (brief.version, brief.output_hash):
        raise IntakeVersionContractError("Commerce Creative Master Creative Brief reference is stale or tampered.")
    if (row.brand_kit_version, row.brand_kit_hash) != (brand_kit.version, brand_kit.content_hash):
        raise IntakeVersionContractError("Commerce Creative Master Brand Kit reference is stale or tampered.")

    fact_ref = _reference(row.approved_fact_snapshot_ref_json, "master.approved_fact_snapshot")
    fact_snapshot = db.query(FactSnapshot).filter_by(id=fact_ref["id"], project_id=row.project_id).first()
    if fact_snapshot is None or fact_ref["version"] != 1 or fact_snapshot.snapshot_hash != fact_ref["hash"]:
        raise IntakeVersionContractError("Commerce Creative Master approved fact snapshot reference is invalid.")
    _validate_master_approved_fact_states(fact_snapshot, confirmation)

    for label, reference in (
        ("master.approved_asset_manifest", row.approved_asset_manifest_ref_json),
        ("master.copy_artifact", row.copy_artifact_ref_json),
        ("master.page_plan_artifact", row.page_plan_artifact_ref_json),
    ):
        _reference(reference, label)
    evidence_refs = _reference_list(row.evidence_artifact_refs_json, "master.evidence_artifacts")
    if not evidence_refs:
        raise IntakeVersionContractError("Commerce Creative Master must pin evidence artifact references.")
    if not isinstance(row.target_channels, list) or not row.target_channels or not all(isinstance(item, str) and item for item in row.target_channels):
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
        prohibited_inference_refs_json=_reference_list(prohibited_inference_refs, "truth.prohibited_inference_refs"), canonical_hash="",
    )
    row.canonical_hash = canonical_version_hash(_truth_payload(row))
    _check_registered_hash(db, ProductTruthVersion, project_id=project_id, digest=row.canonical_hash)
    db.add(row); db.flush(); validate_immutable_version(db, row)
    return row


def create_seller_confirmation_version(
    db: Session, *, workspace_id: str, project_id: str, creator_run_id: str, created_by: str,
    truth_reference: Mapping[str, Any], answers: Sequence[Mapping[str, Any]],
    confirmed_fact_refs: Sequence[Mapping[str, Any]], rejected_fact_refs: Sequence[Mapping[str, Any]],
    unknown_fact_refs: Sequence[Mapping[str, Any]],
    rights_confirmations: Sequence[Mapping[str, Any]], parent_version_id: str | None = None,
    schema_version: str = SELLER_CONFIRMATION_SCHEMA_VERSION,
) -> SellerConfirmationVersion:
    if schema_version != SELLER_CONFIRMATION_SCHEMA_VERSION:
        raise IntakeVersionContractError("Seller confirmation schema version is unsupported.")
    _require_run(db, run_id=creator_run_id, workspace_id=workspace_id, project_id=project_id)
    truth = _linked_row(db, ProductTruthVersion, project_id=project_id, reference=truth_reference, label="confirmation.truth")
    parent_id, parent_version, parent_hash = _validate_parent(db, SellerConfirmationVersion, project_id=project_id, parent_version_id=parent_version_id)
    row = SellerConfirmationVersion(
        workspace_id=workspace_id, project_id=project_id, creator_run_id=creator_run_id, created_by=created_by,
        version=_next_version(db, SellerConfirmationVersion, project_id), schema_version=schema_version,
        truth_version_id=truth.id, truth_version=truth.version, truth_version_hash=truth.canonical_hash, parent_version_id=parent_id, parent_version=parent_version, parent_version_hash=parent_hash,
        answers_json=_require_list(answers, "confirmation.answers"),
        confirmed_fact_refs_json=_fact_state_reference_list(confirmed_fact_refs, "confirmation.confirmed_fact_refs"),
        rejected_fact_refs_json=_fact_state_reference_list(rejected_fact_refs, "confirmation.rejected_fact_refs"),
        unknown_fact_refs_json=_fact_state_reference_list(unknown_fact_refs, "confirmation.unknown_fact_refs"),
        rights_confirmations_json=_require_list(rights_confirmations, "confirmation.rights_confirmations"), canonical_hash="",
    )
    row.canonical_hash = canonical_version_hash(_confirmation_payload(row))
    _check_registered_hash(db, SellerConfirmationVersion, project_id=project_id, digest=row.canonical_hash)
    db.add(row); db.flush(); validate_immutable_version(db, row)
    return row


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
    brief_ref = _reference(creative_brief_reference, "master.creative_brief")
    brand_ref = _reference(brand_kit_reference, "master.brand_kit")
    brief = db.query(ProductCreativeBriefVersion).filter_by(id=brief_ref["id"], project_id=project_id).first()
    brand_kit = db.query(BrandKitVersion).filter_by(id=brand_ref["id"], workspace_id=workspace_id).first()
    if brief is None or (brief.version, brief.output_hash) != (brief_ref["version"], brief_ref["hash"]):
        raise IntakeVersionContractError("Commerce Creative Master Creative Brief reference is invalid.")
    if brand_kit is None or (brand_kit.version, brand_kit.content_hash) != (brand_ref["version"], brand_ref["hash"]):
        raise IntakeVersionContractError("Commerce Creative Master Brand Kit reference is invalid.")
    fact_ref = _reference(approved_fact_snapshot_ref, "master.approved_fact_snapshot")
    fact_snapshot = db.query(FactSnapshot).filter_by(id=fact_ref["id"], project_id=project_id).first()
    if fact_snapshot is None or fact_ref["version"] != 1 or fact_snapshot.snapshot_hash != fact_ref["hash"]:
        raise IntakeVersionContractError("Commerce Creative Master approved fact snapshot reference is invalid.")
    _validate_master_approved_fact_states(fact_snapshot, confirmation)
    evidence_refs = _reference_list(evidence_artifact_refs, "master.evidence_artifacts")
    if not evidence_refs:
        raise IntakeVersionContractError("Commerce Creative Master must pin evidence artifact references.")
    normalized_channels = sorted(set(str(channel) for channel in target_channels if isinstance(channel, str) and channel))
    if not normalized_channels:
        raise IntakeVersionContractError("Commerce Creative Master must pin one or more target channels.")
    parent_id, parent_version, parent_hash = _validate_parent(db, CommerceCreativeMasterVersion, project_id=project_id, parent_version_id=parent_version_id)
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
    row.canonical_hash = canonical_version_hash(_master_payload(row))
    _check_registered_hash(db, CommerceCreativeMasterVersion, project_id=project_id, digest=row.canonical_hash)
    db.add(row); db.flush(); validate_immutable_version(db, row)
    return row


def master_reference_index(master: CommerceCreativeMasterVersion) -> dict[str, Any]:
    """Return only the immutable index; no raw source/copy/asset body is exposed."""

    validate_payload = _master_payload(master)
    return deepcopy({key: value for key, value in validate_payload.items() if key not in {"workspace_id", "project_id", "creator_run_id"}})
