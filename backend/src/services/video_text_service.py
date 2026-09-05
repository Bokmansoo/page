"""LG-16-A6 immutable, fact-bound editable video text."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import hashlib
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import AgentRun, CommerceCreativeMasterVersion, FactSnapshot, VideoProjectVersion, VideoTextVersion
from src.services.prompt_intelligence_service import canonical_hash
from src.services.rule_based_copy_service import unsupported_claims
from src.services.video_project_version_service import (
    VideoProjectContractError,
    _reference_for,
    _reference_list,
    create_video_project_version,
    validate_video_project_version,
)
from src.services.video_storyboard_service import validate_video_storyboard


VIDEO_TEXT_SCHEMA_VERSION = "lg16-video-text-v1"
VIDEO_TEXT_ROLES = frozenset({"scene_copy", "overlay_text", "caption_text"})
VIDEO_TEXT_PLACEMENT_ROLES = frozenset({"headline", "body", "cta", "caption"})
VIDEO_TEXT_VISIBILITY = frozenset({"visible", "hidden"})
_MAX_TEXT_LENGTH = 2000


class VideoTextContractError(ValueError):
    """A video text artifact or successor request is invalid."""


def _body_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text_ref(row: VideoTextVersion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "version": int(row.version),
        "hash": str(row.body_hash),
        "schema_version": VIDEO_TEXT_SCHEMA_VERSION,
        "artifact_key": "video_text_layer",
    }


def _canonical_hash(row: VideoTextVersion) -> str:
    return canonical_hash({
        "kind": "VideoTextVersion",
        "schema_version": row.schema_version,
        "workspace_id": row.workspace_id,
        "project_id": row.project_id,
        "video_project_version": {"id": row.video_project_version_id},
        "source_master": {"id": row.source_master_id},
        "scene_id": row.scene_id,
        "text_role": row.text_role,
        "placement_role": row.placement_role,
        "visibility_status": row.visibility_status,
        "version": row.version,
        "parent": (
            {"id": row.parent_text_version_id, "version": row.parent_text_version, "hash": row.parent_text_hash}
            if row.parent_text_version_id else None
        ),
        "body_hash": row.body_hash,
        "source_fact_refs": row.source_fact_refs_json,
        "provenance_refs": row.provenance_refs_json,
        "validation_status": row.validation_status,
        "validation_result": row.validation_result_json,
        "author_id": row.author_id,
        "idempotency_key": row.idempotency_key,
    })


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        raise VideoTextContractError("text body must be a string.")
    value = unicodedata.normalize("NFC", value).strip()
    if not value or len(value) > _MAX_TEXT_LENGTH:
        raise VideoTextContractError("text body must be between one and 2000 characters.")
    return value


def _validate_refs(value: Any, allowed: Sequence[Mapping[str, Any]], label: str) -> list[dict[str, Any]]:
    try:
        refs = _reference_list(value, label)
    except VideoProjectContractError as exc:
        raise VideoTextContractError(str(exc)) from exc
    allowed_ids = {(str(item["id"]), int(item["version"]), str(item["hash"])) for item in allowed}
    if not refs or any((item["id"], item["version"], item["hash"]) not in allowed_ids for item in refs):
        raise VideoTextContractError(f"{label} must use approved scene references.")
    return refs


def _validation(
    db: Session,
    *,
    parent: VideoProjectVersion,
    scene: Mapping[str, Any],
    body: str,
    fact_refs: list[dict[str, Any]],
    provenance_refs: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if not fact_refs or not provenance_refs:
        return "FAIL", {"status": "FAIL", "reason_codes": ["MISSING_APPROVED_EVIDENCE"]}
    master = db.query(CommerceCreativeMasterVersion).filter_by(
        id=parent.source_master_id, workspace_id=parent.workspace_id, project_id=parent.project_id,
    ).one_or_none()
    snapshot = None
    if master is not None:
        fact_ref = dict(parent.approved_fact_snapshot_ref_json or {})
        snapshot = db.query(FactSnapshot).filter_by(id=fact_ref.get("id"), project_id=parent.project_id).one_or_none()
    facts = [
        str(item.get("fact_text") or item.get("value") or "")
        for item in (snapshot.facts_json if snapshot else []) if isinstance(item, Mapping)
    ]
    from src.services.grounding_validator import detect_claim_risks
    risks = detect_claim_risks(body, [value for value in facts if value])
    reason_codes = sorted({str(item.risk_type) for item in risks})[:8]
    reason_codes.extend(f"unsupported:{item}" for item in unsupported_claims(body)[:8])
    if reason_codes:
        return "REVIEW_REQUIRED", {
            "status": "REVIEW_REQUIRED", "reason_codes": sorted(set(reason_codes))[:8],
            "fact_count": len(facts), "scene_id": str(scene["scene_id"]),
        }
    return "PASS", {
        "status": "PASS", "reason_codes": [], "fact_count": len(facts),
        "scene_id": str(scene["scene_id"]), "provenance_count": len(provenance_refs),
    }


def _successor_for(db: Session, parent_id: str, text_ref: Mapping[str, Any]) -> VideoProjectVersion | None:
    for candidate in db.query(VideoProjectVersion).filter_by(parent_video_project_version_id=parent_id).all():
        refs = list((candidate.video_manifest_json or {}).get("text_layer_refs") or [])
        if any(ref.get("id") == text_ref.get("id") and ref.get("hash") == text_ref.get("hash") for ref in refs if isinstance(ref, Mapping)):
            return candidate
    return None


def _journal_text_event(db: Session, *, parent: VideoProjectVersion, video: VideoProjectVersion, row: VideoTextVersion) -> None:
    """Project bounded text identity; never pass the body to the journal."""
    run = db.query(AgentRun).filter_by(
        id=parent.creator_run_id, workspace_id=parent.workspace_id, project_id=parent.project_id,
    ).one_or_none()
    if run is None:
        raise VideoTextContractError("VideoTextVersion creator run is missing.")
    storyboard = dict((video.video_manifest_json or {}).get("storyboard") or {})
    storyboard_ref = None
    if storyboard:
        storyboard_ref = {
            "id": str(storyboard.get("storyboard_id") or ""),
            "version": 1,
            "hash": str(storyboard.get("canonical_hash") or ""),
        }
    from src.services.langgraph_run_service import AgentRunEventJournal
    AgentRunEventJournal.append_video_text(
        run, db,
        video={
            "video_project_ref": _reference_for(video),
            "storyboard_ref": storyboard_ref,
            "scene_count": int(storyboard.get("scene_count") or 0),
        },
        text_layer={
            "text_ref": _text_ref(row), "scene_id": row.scene_id,
            "text_role": row.text_role, "validation_status": row.validation_status,
            "body_hash": row.body_hash,
        },
    )


def validate_video_text_version(db: Session, row: VideoTextVersion) -> None:
    """Fail closed when an immutable text artifact or its lineage is stale."""
    if row.schema_version != VIDEO_TEXT_SCHEMA_VERSION:
        raise VideoTextContractError("VideoTextVersion schema is unsupported.")
    if _body_hash(str(row.body_text)) != str(row.body_hash) or _canonical_hash(row) != str(row.canonical_hash):
        raise VideoTextContractError("VideoTextVersion content hash is invalid.")
    parent = db.query(VideoProjectVersion).filter_by(
        id=row.video_project_version_id, workspace_id=row.workspace_id, project_id=row.project_id,
    ).one_or_none()
    if parent is None or parent.source_master_id != row.source_master_id:
        raise VideoTextContractError("VideoTextVersion project lineage is invalid.")
    validate_video_project_version(db, parent, require_current_master=False)
    storyboard = validate_video_storyboard(db, parent)
    scene = next((item for item in storyboard["scenes"] if str(item["scene_id"]) == str(row.scene_id)), None)
    if scene is None:
        raise VideoTextContractError("VideoTextVersion scene binding is stale.")
    _validate_refs(row.source_fact_refs_json, scene["fact_refs"], "source_fact_refs")
    _validate_refs(row.provenance_refs_json, scene["provenance_refs"], "provenance_refs")


def create_video_text_version(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    parent_video_project_version_id: str,
    scene_id: str,
    text_role: str,
    body_text: str,
    author_id: str,
    fact_refs: Sequence[Mapping[str, Any]],
    provenance_refs: Sequence[Mapping[str, Any]],
    placement_role: str = "body",
    visibility_status: str = "visible",
) -> dict[str, Any]:
    """Persist an exact text artifact and, only for PASS, a VideoProject successor."""
    if text_role not in VIDEO_TEXT_ROLES or placement_role not in VIDEO_TEXT_PLACEMENT_ROLES:
        raise VideoTextContractError("text role or placement role is unsupported.")
    if visibility_status not in VIDEO_TEXT_VISIBILITY:
        raise VideoTextContractError("text visibility is unsupported.")
    body = _normalize_text(body_text)
    body_digest = _body_hash(body)
    parent = db.query(VideoProjectVersion).filter_by(
        id=parent_video_project_version_id, workspace_id=workspace_id, project_id=project_id,
    ).with_for_update().one_or_none()
    if parent is None:
        raise VideoTextContractError("VideoProject parent is outside the requested scope.")
    validate_video_project_version(db, parent)
    latest = db.query(VideoProjectVersion).filter_by(workspace_id=workspace_id, project_id=project_id).order_by(VideoProjectVersion.version.desc()).first()
    storyboard = validate_video_storyboard(db, parent)
    scene = next((item for item in storyboard["scenes"] if str(item["scene_id"]) == str(scene_id)), None)
    if scene is None:
        raise VideoTextContractError("Text scene is missing or stale.")
    normalized_facts = _validate_refs(fact_refs, scene["fact_refs"], "fact_refs")
    normalized_provenance = _validate_refs(provenance_refs, scene["provenance_refs"], "provenance_refs")
    identity = {
        "schema_version": VIDEO_TEXT_SCHEMA_VERSION,
        "workspace_id": workspace_id, "project_id": project_id,
        "parent_video_project": _reference_for(parent), "scene_id": str(scene_id),
        "text_role": text_role, "placement_role": placement_role,
        "visibility_status": visibility_status, "body_hash": body_digest,
        "source_fact_refs": normalized_facts, "provenance_refs": normalized_provenance,
    }
    idempotency = canonical_hash(identity)
    existing = db.query(VideoTextVersion).filter_by(project_id=project_id, idempotency_key=idempotency).one_or_none()
    if existing is not None:
        text_ref = _text_ref(existing)
        existing_successor = _successor_for(db, parent.id, text_ref)
        _journal_text_event(db, parent=parent, video=existing_successor or parent, row=existing)
        return {
            "artifact": existing, "successor": existing_successor,
            "replayed": True, "text_ref": text_ref,
        }
    if latest is None or latest.id != parent.id:
        raise VideoTextContractError("VideoProject parent is stale; reload before editing.")
    prior = None
    for ref in list((parent.video_manifest_json or {}).get("text_layer_refs") or []):
        candidate = db.query(VideoTextVersion).filter_by(id=ref.get("id"), project_id=project_id).one_or_none() if isinstance(ref, Mapping) else None
        if candidate is not None and candidate.scene_id == str(scene_id) and candidate.text_role == text_role:
            prior = candidate
            break
    validation_status, validation_result = _validation(
        db, parent=parent, scene=scene, body=body,
        fact_refs=normalized_facts, provenance_refs=normalized_provenance,
    )
    version = int(prior.version if prior else 0) + 1
    row = VideoTextVersion(
        id=f"video-text:{idempotency[:24]}", workspace_id=workspace_id, project_id=project_id,
        video_project_version_id=parent.id, source_master_id=parent.source_master_id,
        schema_version=VIDEO_TEXT_SCHEMA_VERSION,
        scene_id=str(scene_id), text_role=text_role, placement_role=placement_role,
        visibility_status=visibility_status, version=version,
        parent_text_version_id=prior.id if prior else None,
        parent_text_version=prior.version if prior else None,
        parent_text_hash=prior.canonical_hash if prior else None,
        body_text=body, body_hash=body_digest,
        source_fact_refs_json=copy.deepcopy(normalized_facts),
        provenance_refs_json=copy.deepcopy(normalized_provenance),
        validation_status=validation_status, validation_result_json=validation_result,
        author_id=author_id, idempotency_key=idempotency, canonical_hash="",
    )
    row.canonical_hash = _canonical_hash(row)
    db.add(row)
    db.flush()
    text_ref = _text_ref(row)
    if validation_status != "PASS":
        _journal_text_event(db, parent=parent, video=parent, row=row)
        return {"artifact": row, "successor": None, "replayed": False, "text_ref": text_ref}
    manifest = copy.deepcopy(parent.video_manifest_json or {})
    refs = []
    for ref in list(manifest.get("text_layer_refs") or []):
        candidate = db.query(VideoTextVersion).filter_by(id=ref.get("id"), project_id=project_id).one_or_none() if isinstance(ref, Mapping) else None
        if candidate is not None and candidate.scene_id == str(scene_id) and candidate.text_role == text_role:
            continue
        refs.append(dict(ref))
    refs.append(text_ref)
    manifest["text_layer_refs"] = sorted(refs, key=lambda ref: (str(ref.get("id")), int(ref.get("version", 0))))
    successor = create_video_project_version(
        db, workspace_id=workspace_id, project_id=project_id,
        creator_run_id=parent.creator_run_id, created_by=author_id,
        source_master_reference={
            "id": parent.source_master_id,
            "version": parent.source_master_version,
            "hash": parent.source_master_hash,
        },
        planning_contract_reference=copy.deepcopy(parent.planning_contract_ref_json or {}),
        publishing_targets=list(parent.publishing_targets_json or []), video_manifest=manifest,
        parent_version_id=parent.id, output_hash=parent.output_hash,
    )
    _journal_text_event(db, parent=parent, video=successor, row=row)
    return {"artifact": row, "successor": successor, "replayed": False, "text_ref": text_ref}


def public_video_text_projection(row: VideoTextVersion) -> dict[str, Any]:
    return {
        "id": str(row.id), "version": int(row.version), "scene_id": row.scene_id,
        "text_role": row.text_role, "placement_role": row.placement_role,
        "visibility_status": row.visibility_status, "text": row.body_text,
        "body_hash": row.body_hash, "source_fact_refs": list(row.source_fact_refs_json or []),
        "provenance_refs": list(row.provenance_refs_json or []),
        "validation_status": row.validation_status,
        "validation_result": dict(row.validation_result_json or {}),
        "canonical_hash": row.canonical_hash,
    }
