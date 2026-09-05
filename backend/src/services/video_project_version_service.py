"""LG-16-A1 immutable VideoProjectVersion foundation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import re
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    Asset,
    CommerceCreativeMasterVersion,
    FactSnapshot,
    ProductCreativeBriefVersion,
    VideoProjectVersion,
)
from src.services.commerce_policy import resolved_asset_usage_status
from src.services.product_intake_version_service import validate_immutable_version
from src.services.prompt_intelligence_service import canonical_hash


VIDEO_PROJECT_SCHEMA_VERSION = "lg16-video-project-version-v1"
VIDEO_MANIFEST_SCHEMA_VERSION = "lg16-video-manifest-v1"
VIDEO_EXECUTION_MODE = "deterministic_fake"
VIDEO_PUBLISHING_TARGETS = ("reels", "tiktok", "youtube_shorts")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}$")
_REF_KEYS = frozenset({
    "id", "version", "hash", "schema_version", "artifact_key", "media_type",
    "output_role", "profile_id", "profile_version", "assembly_hash", "source_video_project_ref",
})
_MANIFEST_KEYS = frozenset({
    "schema_version", "storyboard_ref", "scene_manifest_ref", "caption_ref",
    "audio_ref", "thumbnail_ref", "final_output_ref", "text_layer_refs", "storyboard",
})
_STORYBOARD_KEYS = frozenset({
    "storyboard_schema_version", "storyboard_id", "source_video_project_ref",
    "creative_intent", "publishing_target_intent", "scene_count", "scenes",
    "canonical_hash",
})
_STORYBOARD_SCENE_KEYS = frozenset({
    "scene_id", "logical_target", "role", "order", "duration_intent", "visual_intent",
    "product_asset_refs", "fact_refs", "provenance_refs", "copy_ref", "caption_ref",
    "usage_intent", "selected_variant_ref", "status", "output_ref", "output_hash",
})
_STORYBOARD_ROLES = frozenset({"hook", "product", "benefit", "feature", "evidence", "usage", "demo", "cta"})
_STORYBOARD_CREATIVE_INTENTS = frozenset({"product_demo", "benefit_story", "conversion"})
_STORYBOARD_DURATIONS = frozenset({"short", "medium", "long"})
_STORYBOARD_VISUALS = frozenset({
    "opening_product", "product_detail", "benefit_highlight", "feature_detail",
    "evidence_detail", "usage_in_context", "usage_steps", "closing_cta",
})
_STORYBOARD_USAGE = frozenset({"show_product", "show_benefit", "demonstrate_usage", "close_conversion", "none"})


class VideoProjectContractError(ValueError):
    """A VideoProjectVersion request or immutable row is invalid."""


def _reference(value: Any, label: str, *, allow_empty: bool = False) -> dict[str, Any]:
    if allow_empty and value == {}:
        return {}
    if not isinstance(value, Mapping) or set(value) - _REF_KEYS:
        raise VideoProjectContractError(f"{label} must be a bounded immutable reference.")
    result = dict(value)
    if (
        not isinstance(result.get("id"), str)
        or not _IDENTIFIER.fullmatch(result["id"])
        or "://" in result["id"]
    ):
        raise VideoProjectContractError(f"{label}.id is required.")
    if not isinstance(result.get("version"), int) or result["version"] < 1:
        raise VideoProjectContractError(f"{label}.version must be positive.")
    digest = result.get("hash")
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise VideoProjectContractError(f"{label}.hash must be a lowercase SHA-256 hash.")
    for key in ("schema_version", "artifact_key", "media_type", "output_role", "profile_id"):
        if key in result and (
            not isinstance(result[key], str)
            or not _IDENTIFIER.fullmatch(result[key])
            or len(result[key]) > 100
            or "://" in result[key]
        ):
            raise VideoProjectContractError(f"{label}.{key} is invalid.")
    if "profile_version" in result and (not isinstance(result["profile_version"], int) or result["profile_version"] < 1):
        raise VideoProjectContractError(f"{label}.profile_version is invalid.")
    if "assembly_hash" in result and (not isinstance(result["assembly_hash"], str) or not _HASH.fullmatch(result["assembly_hash"])):
        raise VideoProjectContractError(f"{label}.assembly_hash is invalid.")
    if "source_video_project_ref" in result and _reference(result["source_video_project_ref"], f"{label}.source_video_project_ref") != result["source_video_project_ref"]:
        raise VideoProjectContractError(f"{label}.source_video_project_ref is invalid.")
    return result


def _reference_for(row: Any, *, hash_field: str = "canonical_hash") -> dict[str, Any]:
    return {"id": str(row.id), "version": int(row.version), "hash": str(getattr(row, hash_field))}


def _reference_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or len(value) > 128:
        raise VideoProjectContractError(f"{label} must be a bounded list.")
    refs = [_reference(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if len({(item["id"], item["version"], item["hash"]) for item in refs}) != len(refs):
        raise VideoProjectContractError(f"{label} contains duplicate references.")
    return sorted(refs, key=lambda item: (item["id"], item["version"], item["hash"]))


def _manifest(value: Mapping[str, Any] | None) -> dict[str, Any]:
    manifest = dict(value or {})
    if set(manifest) - _MANIFEST_KEYS:
        raise VideoProjectContractError("video_manifest contains an unsupported field.")
    if manifest and manifest.get("schema_version") not in {None, VIDEO_MANIFEST_SCHEMA_VERSION}:
        raise VideoProjectContractError("video_manifest schema is unsupported.")
    result = {"schema_version": VIDEO_MANIFEST_SCHEMA_VERSION}
    for key in sorted(_MANIFEST_KEYS - {"schema_version"}):
        item = manifest.get(key)
        if key == "storyboard":
            result[key] = None if item is None else _bounded_storyboard(item, "video_manifest.storyboard")
        elif key == "text_layer_refs":
            result[key] = [] if item is None else _reference_list(item, "video_manifest.text_layer_refs")
        else:
            result[key] = None if item is None else _reference(item, f"video_manifest.{key}")
    return result


def _bounded_storyboard(value: Any, label: str) -> dict[str, Any]:
    """Validate the at-rest storyboard envelope without copying source bodies."""
    if not isinstance(value, Mapping) or set(value) - _STORYBOARD_KEYS:
        raise VideoProjectContractError(f"{label} must be a bounded semantic manifest.")
    if value.get("storyboard_schema_version") != "lg16-video-storyboard-v1":
        raise VideoProjectContractError(f"{label}.storyboard_schema_version is unsupported.")
    storyboard_id = value.get("storyboard_id")
    if not isinstance(storyboard_id, str) or not _IDENTIFIER.fullmatch(storyboard_id) or "://" in storyboard_id:
        raise VideoProjectContractError(f"{label}.storyboard_id is invalid.")
    source = _reference(value.get("source_video_project_ref"), f"{label}.source_video_project_ref")
    creative_intent = value.get("creative_intent")
    if (
        not isinstance(creative_intent, str)
        or not _IDENTIFIER.fullmatch(creative_intent)
        or "://" in creative_intent
        or creative_intent not in _STORYBOARD_CREATIVE_INTENTS
    ):
        raise VideoProjectContractError(f"{label}.creative_intent is invalid.")
    target_intent = value.get("publishing_target_intent")
    if not isinstance(target_intent, Mapping) or set(target_intent) != {"strategy", "targets"}:
        raise VideoProjectContractError(f"{label}.publishing_target_intent is invalid.")
    if target_intent.get("strategy") != "common_video" or not isinstance(target_intent.get("targets"), list):
        raise VideoProjectContractError(f"{label}.publishing_target_intent is invalid.")
    targets = target_intent["targets"]
    if not targets or len(targets) > 3 or any(target not in VIDEO_PUBLISHING_TARGETS for target in targets):
        raise VideoProjectContractError(f"{label}.publishing_target_intent.targets is invalid.")
    scene_count = value.get("scene_count")
    scenes = value.get("scenes")
    if not isinstance(scene_count, int) or scene_count < 1 or scene_count > 32 or not isinstance(scenes, list) or len(scenes) != scene_count:
        raise VideoProjectContractError(f"{label}.scene_count must match bounded scenes.")
    orders: set[int] = set()
    identities: set[str] = set()
    normalized_scenes: list[dict[str, Any]] = []
    for index, raw_scene in enumerate(scenes):
        if not isinstance(raw_scene, Mapping) or set(raw_scene) - _STORYBOARD_SCENE_KEYS:
            raise VideoProjectContractError(f"{label}.scenes[{index}] contains an unsupported field.")
        scene = dict(raw_scene)
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, str) or not _IDENTIFIER.fullmatch(scene_id) or scene_id in identities:
            raise VideoProjectContractError(f"{label}.scenes[{index}].scene_id is invalid or duplicated.")
        order = scene.get("order")
        if not isinstance(order, int) or order < 1 or order in orders:
            raise VideoProjectContractError(f"{label}.scenes[{index}].order is invalid or duplicated.")
        for field in ("logical_target", "role", "duration_intent", "visual_intent", "usage_intent", "status"):
            if not isinstance(scene.get(field), str) or not _IDENTIFIER.fullmatch(scene[field]) or "://" in scene[field]:
                raise VideoProjectContractError(f"{label}.scenes[{index}].{field} is invalid.")
        if scene["role"] not in _STORYBOARD_ROLES or scene["duration_intent"] not in _STORYBOARD_DURATIONS or scene["visual_intent"] not in _STORYBOARD_VISUALS or scene["usage_intent"] not in _STORYBOARD_USAGE or scene["status"] != "planned":
            raise VideoProjectContractError(f"{label}.scenes[{index}] uses unsupported semantics.")
        for field in ("product_asset_refs", "fact_refs", "provenance_refs"):
            scene[field] = _reference_list(scene.get(field), f"{label}.scenes[{index}].{field}")
            if not scene[field]:
                raise VideoProjectContractError(f"{label}.scenes[{index}].{field} cannot be empty.")
        for field in ("copy_ref", "caption_ref", "selected_variant_ref", "output_ref"):
            if field in scene:
                scene[field] = None if scene[field] is None else _reference(scene[field], f"{label}.scenes[{index}].{field}")
        if "output_hash" in scene and scene["output_hash"] is not None and not _HASH.fullmatch(str(scene["output_hash"])):
            raise VideoProjectContractError(f"{label}.scenes[{index}].output_hash is invalid.")
        expected_scene_id = "video-scene:" + canonical_hash({
            "schema_version": "lg16-video-storyboard-v1",
            "source_video_project": source,
            "logical_target": scene["logical_target"],
            "role": scene["role"],
            "duration_intent": scene["duration_intent"],
            "visual_intent": scene["visual_intent"],
            "product_asset_refs": scene["product_asset_refs"],
            "fact_refs": scene["fact_refs"],
            "provenance_refs": scene["provenance_refs"],
            "usage_intent": scene["usage_intent"],
            "copy_ref": scene.get("copy_ref"),
            "caption_ref": scene.get("caption_ref"),
            "selected_variant_ref": scene.get("selected_variant_ref"),
        })[:24]
        if scene_id != expected_scene_id:
            raise VideoProjectContractError(f"{label}.scenes[{index}].scene_id is not semantically stable.")
        identities.add(scene_id)
        orders.add(order)
        normalized_scenes.append(scene)
    if orders != set(range(1, scene_count + 1)):
        raise VideoProjectContractError(f"{label}.scene order must be contiguous from one.")
    canonical_hash_value = value.get("canonical_hash")
    if not isinstance(canonical_hash_value, str) or not _HASH.fullmatch(canonical_hash_value):
        raise VideoProjectContractError(f"{label}.canonical_hash is invalid.")
    expected_hash = canonical_hash({
        "storyboard_schema_version": value["storyboard_schema_version"],
        "source_video_project_ref": source,
        "creative_intent": creative_intent,
        "publishing_target_intent": {"strategy": "common_video", "targets": list(targets)},
        "scene_count": scene_count,
        "scenes": sorted(normalized_scenes, key=lambda item: item["order"]),
    })
    if canonical_hash_value != expected_hash or storyboard_id != "video-storyboard:" + expected_hash[:24]:
        raise VideoProjectContractError(f"{label} canonical hash is invalid.")
    return {
        "storyboard_schema_version": value["storyboard_schema_version"],
        "storyboard_id": storyboard_id,
        "source_video_project_ref": source,
        "creative_intent": creative_intent,
        "publishing_target_intent": {"strategy": "common_video", "targets": list(targets)},
        "scene_count": scene_count,
        "scenes": sorted(normalized_scenes, key=lambda item: item["order"]),
        "canonical_hash": canonical_hash_value,
    }


def _current_master(db: Session, *, workspace_id: str, project_id: str, reference: Mapping[str, Any], lock: bool) -> CommerceCreativeMasterVersion:
    supplied = _reference(reference, "source_master")
    query = db.query(CommerceCreativeMasterVersion).filter_by(
        id=supplied["id"], workspace_id=workspace_id, project_id=project_id,
    )
    master = (query.with_for_update() if lock else query).one_or_none()
    if master is None:
        raise VideoProjectContractError("source_master must belong to the same workspace and project.")
    validate_immutable_version(db, master)
    latest = db.query(CommerceCreativeMasterVersion).filter_by(
        workspace_id=workspace_id, project_id=project_id,
    ).order_by(CommerceCreativeMasterVersion.version.desc()).first()
    if latest is None or latest.id != master.id:
        raise VideoProjectContractError("source_master is stale; VideoProject creation requires the current Master.")
    if supplied != _reference_for(master):
        raise VideoProjectContractError("source_master ID/version/hash does not match its frozen version.")
    return master


def _master_refs(db: Session, master: CommerceCreativeMasterVersion) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    brief = db.query(ProductCreativeBriefVersion).filter_by(
        id=master.creative_brief_version_id, project_id=master.project_id,
    ).one_or_none()
    if brief is None or (brief.version, brief.output_hash) != (master.creative_brief_version, master.creative_brief_hash):
        raise VideoProjectContractError("source_master Creative Brief reference is stale or tampered.")
    fact_ref = _reference(master.approved_fact_snapshot_ref_json, "master.approved_fact_snapshot")
    snapshot = db.query(FactSnapshot).filter_by(id=fact_ref["id"], project_id=master.project_id).one_or_none()
    if snapshot is None or snapshot.snapshot_hash != fact_ref["hash"]:
        raise VideoProjectContractError("source_master approved fact snapshot is stale or tampered.")
    rights = _reference_list(brief.usable_asset_refs_json, "master.rights_asset_refs")
    for ref in rights:
        asset = db.query(Asset).filter_by(id=ref["id"], project_id=master.project_id).one_or_none()
        if asset is None or resolved_asset_usage_status(asset) not in {"seller_owned", "rights_confirmed"}:
            raise VideoProjectContractError("VideoProject requires rights-confirmed Master assets.")
    return (
        fact_ref,
        _reference_for(brief, hash_field="output_hash"),
        {"id": str(master.brand_kit_version_id), "version": int(master.brand_kit_version), "hash": str(master.brand_kit_hash)},
        rights,
    )


def _parent_ref(db: Session, *, parent_id: str | None, workspace_id: str, project_id: str, master: CommerceCreativeMasterVersion) -> tuple[VideoProjectVersion | None, dict[str, Any] | None]:
    if not parent_id:
        return None, None
    parent = db.query(VideoProjectVersion).filter_by(
        id=parent_id, workspace_id=workspace_id, project_id=project_id,
    ).with_for_update().one_or_none()
    if parent is None or parent.source_master_id != master.id:
        raise VideoProjectContractError("VideoProject parent must belong to the same current Master.")
    validate_video_project_version(db, parent, require_current_master=False)
    return parent, {"id": parent.id, "version": parent.version, "hash": parent.canonical_hash}


def _identity(*, workspace_id: str, project_id: str, schema_version: str, parent: Mapping[str, Any] | None, source_master: Mapping[str, Any], fact_ref: Mapping[str, Any], brief_ref: Mapping[str, Any], brand_ref: Mapping[str, Any], rights: Sequence[Mapping[str, Any]], planning: Mapping[str, Any], manifest: Mapping[str, Any], targets: Sequence[str], execution_mode: str) -> dict[str, Any]:
    return {
        "kind": "VideoProjectVersion", "schema_version": schema_version,
        "workspace_id": workspace_id, "project_id": project_id, "parent": parent,
        "source_master": dict(source_master), "approved_fact_snapshot": dict(fact_ref),
        "creative_brief": dict(brief_ref), "brand_kit": dict(brand_ref),
        "rights_asset_refs": list(rights), "planning_contract": dict(planning),
        "video_manifest": dict(manifest), "publishing_targets": list(targets),
        "execution_mode": execution_mode,
    }


def _canonical_payload(row: VideoProjectVersion) -> dict[str, Any]:
    return {
        **_identity(
            workspace_id=row.workspace_id, project_id=row.project_id, schema_version=row.schema_version,
            parent=(
                {"id": row.parent_video_project_version_id, "version": row.parent_version, "hash": row.parent_version_hash}
                if row.parent_video_project_version_id else None
            ),
            source_master={"id": row.source_master_id, "version": row.source_master_version, "hash": row.source_master_hash},
            fact_ref=row.approved_fact_snapshot_ref_json, brief_ref=row.creative_brief_ref_json,
            brand_ref=row.brand_kit_ref_json, rights=row.rights_asset_refs_json,
            planning=row.planning_contract_ref_json, manifest=row.video_manifest_json,
            targets=row.publishing_targets_json, execution_mode=row.execution_mode,
        ),
        "version": row.version, "output_hash": row.output_hash, "idempotency_key": row.idempotency_key,
    }


def validate_video_project_version(db: Session, row: VideoProjectVersion, *, require_current_master: bool = True) -> None:
    if row.schema_version != VIDEO_PROJECT_SCHEMA_VERSION or not isinstance(row.version, int) or row.version < 1:
        raise VideoProjectContractError("VideoProjectVersion schema or version is invalid.")
    if row.execution_mode != VIDEO_EXECUTION_MODE:
        raise VideoProjectContractError("A1 supports deterministic fake execution only.")
    creator_run = db.query(AgentRun).filter_by(
        id=row.creator_run_id, workspace_id=row.workspace_id, project_id=row.project_id,
    ).one_or_none()
    if creator_run is None or str(creator_run.created_by) != str(row.created_by):
        raise VideoProjectContractError("VideoProject creator run scope is invalid.")
    master = _current_master(
        db, workspace_id=row.workspace_id, project_id=row.project_id,
        reference={"id": row.source_master_id, "version": row.source_master_version, "hash": row.source_master_hash},
        lock=False,
    ) if require_current_master else db.query(CommerceCreativeMasterVersion).filter_by(
        id=row.source_master_id, workspace_id=row.workspace_id, project_id=row.project_id,
    ).one_or_none()
    if master is None:
        raise VideoProjectContractError("VideoProject source Master is missing.")
    if (master.version, master.canonical_hash) != (row.source_master_version, row.source_master_hash):
        raise VideoProjectContractError("VideoProject source Master identity is stale or tampered.")
    fact_ref, brief_ref, brand_ref, rights = _master_refs(db, master)
    if row.approved_fact_snapshot_ref_json != fact_ref or row.creative_brief_ref_json != brief_ref or row.brand_kit_ref_json != brand_ref or row.rights_asset_refs_json != rights:
        raise VideoProjectContractError("VideoProject frozen Master references do not match the current Master.")
    _reference(row.planning_contract_ref_json, "planning_contract", allow_empty=True)
    _manifest(row.video_manifest_json)
    targets = list(row.publishing_targets_json or [])
    if sorted(targets) != sorted(set(targets)) or any(target not in VIDEO_PUBLISHING_TARGETS for target in targets):
        raise VideoProjectContractError("VideoProject publishing targets are invalid.")
    manifest = _manifest(row.video_manifest_json)
    if row.output_hash is not None and not _HASH.fullmatch(str(row.output_hash)):
        raise VideoProjectContractError("VideoProject output hash is invalid.")
    final_ref = manifest.get("final_output_ref")
    if final_ref is not None:
        if row.output_hash != final_ref.get("hash") or final_ref.get("media_type") != "video/mp4" or final_ref.get("output_role") != "video_final":
            raise VideoProjectContractError("Final video output reference does not match output_hash.")
        if not final_ref.get("assembly_hash") or final_ref.get("profile_id") != "common_shortform_mp4":
            raise VideoProjectContractError("Final video output profile is missing.")
        audio_ref = manifest.get("audio_ref")
        if not isinstance(audio_ref, Mapping) or audio_ref.get("id") != "audio:silent" or audio_ref.get("artifact_key") != "silent_audio":
            raise VideoProjectContractError("Final video audio identity must be explicitly silent.")
        thumbnail_ref = manifest.get("thumbnail_ref")
        if not isinstance(thumbnail_ref, Mapping) or thumbnail_ref.get("media_type") != "image/png" or thumbnail_ref.get("output_role") != "video_thumbnail":
            raise VideoProjectContractError("Final video thumbnail reference is missing.")
    if row.parent_video_project_version_id:
        parent = db.query(VideoProjectVersion).filter_by(
            id=row.parent_video_project_version_id, workspace_id=row.workspace_id, project_id=row.project_id,
        ).one_or_none()
        if parent is None or parent.source_master_id != row.source_master_id:
            raise VideoProjectContractError("VideoProject successor parent is invalid.")
        if row.parent_version != parent.version or row.parent_version_hash != parent.canonical_hash or parent.version >= row.version:
            raise VideoProjectContractError("VideoProject successor parent lineage is invalid.")
    elif row.parent_version is not None or row.parent_version_hash is not None:
        raise VideoProjectContractError("Initial VideoProjectVersion must not pin a parent.")
    payload = _canonical_payload(row)
    expected_idempotency = canonical_hash({key: value for key, value in payload.items() if key not in {"version", "output_hash", "idempotency_key"}})
    if row.idempotency_key != expected_idempotency:
        raise VideoProjectContractError("VideoProject semantic idempotency key is invalid.")
    if row.canonical_hash != canonical_hash({key: value for key, value in payload.items() if key != "canonical_hash"}):
        raise VideoProjectContractError("VideoProject canonical hash does not match its persisted content.")


def create_video_project_version(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    creator_run_id: str,
    created_by: str,
    source_master_reference: Mapping[str, Any],
    planning_contract_reference: Mapping[str, Any] | None = None,
    publishing_targets: Sequence[str] | None = None,
    video_manifest: Mapping[str, Any] | None = None,
    parent_version_id: str | None = None,
    output_hash: str | None = None,
    execution_mode: str = VIDEO_EXECUTION_MODE,
) -> VideoProjectVersion:
    run = db.query(AgentRun).filter_by(id=creator_run_id, workspace_id=workspace_id, project_id=project_id).one_or_none()
    if run is None or str(run.created_by) != str(created_by):
        raise VideoProjectContractError("creator_run_id must belong to the same actor, workspace, and project.")
    if execution_mode != VIDEO_EXECUTION_MODE:
        raise VideoProjectContractError("A1 supports deterministic fake execution only.")
    master = _current_master(db, workspace_id=workspace_id, project_id=project_id, reference=source_master_reference, lock=True)
    fact_ref, brief_ref, brand_ref, rights = _master_refs(db, master)
    planning = _reference(planning_contract_reference or {}, "planning_contract", allow_empty=True)
    manifest = _manifest(video_manifest)
    if manifest.get("storyboard") is not None and not parent_version_id:
        raise VideoProjectContractError("A storyboard must be persisted as a VideoProject successor.")
    targets = sorted(set(publishing_targets or VIDEO_PUBLISHING_TARGETS))
    if not targets or any(target not in VIDEO_PUBLISHING_TARGETS for target in targets):
        raise VideoProjectContractError("publishing_targets must use the canonical LG-16 targets.")
    parent, parent_ref = _parent_ref(db, parent_id=parent_version_id, workspace_id=workspace_id, project_id=project_id, master=master)
    if manifest.get("storyboard") is not None and manifest["storyboard"]["source_video_project_ref"] != parent_ref:
        # A text-only successor may carry forward the exact immutable
        # storyboard while advancing the project lineage. Re-planning would
        # change stable scene identities, so accept only an unchanged
        # storyboard whose source is an ancestor of the immediate parent.
        parent_storyboard = dict((parent.video_manifest_json or {}).get("storyboard") or {})
        candidate_storyboard = dict(manifest.get("storyboard") or {})
        same_storyboard = candidate_storyboard == parent_storyboard
        parent_scenes = {str(item.get("scene_id")): {key: value for key, value in item.items() if key != "order"} for item in parent_storyboard.get("scenes") or [] if isinstance(item, Mapping)}
        candidate_scenes = {str(item.get("scene_id")): {key: value for key, value in item.items() if key != "order"} for item in candidate_storyboard.get("scenes") or [] if isinstance(item, Mapping)}
        reordered_storyboard = bool(parent_scenes) and parent_scenes == candidate_scenes and candidate_storyboard.get("source_video_project_ref") == parent_storyboard.get("source_video_project_ref")
        ancestor_id = parent.parent_video_project_version_id if parent else None
        ancestors: set[str] = set()
        while ancestor_id:
            if ancestor_id in ancestors:
                break
            ancestors.add(str(ancestor_id))
            ancestor = db.query(VideoProjectVersion).filter_by(
                id=ancestor_id, workspace_id=workspace_id, project_id=project_id,
            ).one_or_none()
            if ancestor is None:
                break
            ancestor_id = ancestor.parent_video_project_version_id
        source_id = str(manifest["storyboard"]["source_video_project_ref"]["id"])
        if not (same_storyboard or reordered_storyboard) or source_id not in ancestors:
            raise VideoProjectContractError("Storyboard must pin its immediate parent VideoProjectVersion.")
    identity = _identity(
        workspace_id=workspace_id, project_id=project_id, schema_version=VIDEO_PROJECT_SCHEMA_VERSION,
        parent=parent_ref, source_master=_reference_for(master), fact_ref=fact_ref, brief_ref=brief_ref,
        brand_ref=brand_ref, rights=rights, planning=planning, manifest=manifest, targets=targets,
        execution_mode=execution_mode,
    )
    idempotency_key = canonical_hash(identity)
    existing = db.query(VideoProjectVersion).filter_by(project_id=project_id, idempotency_key=idempotency_key).one_or_none()
    if existing is not None:
        validate_video_project_version(db, existing, require_current_master=False)
        return existing
    latest = db.query(VideoProjectVersion).filter_by(project_id=project_id).order_by(VideoProjectVersion.version.desc()).first()
    if latest is not None and (parent is None or latest.id != parent.id):
        raise VideoProjectContractError("A VideoProject successor must pin the current VideoProjectVersion.")
    row = VideoProjectVersion(
        workspace_id=workspace_id, project_id=project_id, creator_run_id=creator_run_id,
        created_by=created_by, version=int(latest.version if latest else 0) + 1,
        schema_version=VIDEO_PROJECT_SCHEMA_VERSION,
        parent_video_project_version_id=parent_ref["id"] if parent_ref else None,
        parent_version=parent_ref["version"] if parent_ref else None,
        parent_version_hash=parent_ref["hash"] if parent_ref else None,
        source_master_id=master.id, source_master_version=master.version, source_master_hash=master.canonical_hash,
        approved_fact_snapshot_ref_json=copy.deepcopy(fact_ref), creative_brief_ref_json=copy.deepcopy(brief_ref),
        brand_kit_ref_json=copy.deepcopy(brand_ref), rights_asset_refs_json=copy.deepcopy(rights),
        planning_contract_ref_json=copy.deepcopy(planning), video_manifest_json=copy.deepcopy(manifest),
        publishing_targets_json=targets, execution_mode=execution_mode, output_hash=output_hash,
        idempotency_key=idempotency_key, canonical_hash="",
    )
    row.canonical_hash = canonical_hash({key: value for key, value in _canonical_payload(row).items() if key != "canonical_hash"})
    db.add(row)
    db.flush()
    validate_video_project_version(db, row, require_current_master=False)
    return row


SILENT_AUDIO_REFERENCE = {
    "id": "audio:silent",
    "version": 1,
    "hash": canonical_hash({"schema_version": "lg16-silent-audio-v1"}),
    "schema_version": "lg16-silent-audio-v1",
    "artifact_key": "silent_audio",
    "media_type": "audio/none",
}


def _asset_reference(asset: Asset, *, output_role: str, media_type: str, **extra: Any) -> dict[str, Any]:
    reference = {
        "id": str(asset.id), "version": 1, "hash": str(asset.content_hash),
        "artifact_key": output_role, "output_role": output_role, "media_type": media_type,
        **extra,
    }
    return _reference(reference, f"{output_role}_ref")


def finalize_video_project_version(
    db: Session,
    *,
    parent: VideoProjectVersion,
    final_asset: Asset,
    thumbnail_asset: Asset,
    assembly_hash: str,
    profile_id: str = "common_shortform_mp4",
    profile_version: int = 1,
) -> VideoProjectVersion:
    """Create the immutable output-bound successor for one assembled MP4."""
    if final_asset.project_id != parent.project_id or final_asset.asset_role != "video_final" or final_asset.mime_type != "video/mp4":
        raise VideoProjectContractError("Final video asset is outside the project output boundary.")
    if thumbnail_asset.project_id != parent.project_id or thumbnail_asset.asset_role != "video_thumbnail" or thumbnail_asset.mime_type != "image/png":
        raise VideoProjectContractError("Video thumbnail asset is outside the project output boundary.")
    if not isinstance(final_asset.content_hash, str) or not _HASH.fullmatch(final_asset.content_hash):
        raise VideoProjectContractError("Final video asset hash is invalid.")
    if not isinstance(thumbnail_asset.content_hash, str) or not _HASH.fullmatch(thumbnail_asset.content_hash):
        raise VideoProjectContractError("Video thumbnail asset hash is invalid.")
    if not _HASH.fullmatch(str(assembly_hash)):
        raise VideoProjectContractError("Video assembly identity is invalid.")
    manifest = copy.deepcopy(_manifest(parent.video_manifest_json))
    manifest["final_output_ref"] = _asset_reference(
        final_asset,
        output_role="video_final",
        media_type="video/mp4",
        profile_id=profile_id,
        profile_version=profile_version,
        assembly_hash=str(assembly_hash),
        source_video_project_ref={"id": str(parent.id), "version": int(parent.version), "hash": str(parent.canonical_hash)},
    )
    manifest["audio_ref"] = copy.deepcopy(SILENT_AUDIO_REFERENCE)
    manifest["thumbnail_ref"] = _asset_reference(
        thumbnail_asset,
        output_role="video_thumbnail",
        media_type="image/png",
    )
    return create_video_project_version(
        db,
        workspace_id=parent.workspace_id,
        project_id=parent.project_id,
        creator_run_id=parent.creator_run_id,
        created_by=parent.created_by,
        source_master_reference={"id": parent.source_master_id, "version": parent.source_master_version, "hash": parent.source_master_hash},
        planning_contract_reference=parent.planning_contract_ref_json,
        publishing_targets=parent.publishing_targets_json,
        video_manifest=manifest,
        parent_version_id=parent.id,
        output_hash=str(final_asset.content_hash),
    )


def public_video_project_projection(db: Session, row: VideoProjectVersion) -> dict[str, Any]:
    """Return only bounded identity references; no prompts, provider data, or media bytes."""
    validate_video_project_version(db, row, require_current_master=False)
    return {
        "id": str(row.id), "version": int(row.version), "schema_version": row.schema_version,
        "source_master": {"id": row.source_master_id, "version": row.source_master_version, "hash": row.source_master_hash},
        "publishing_targets": list(row.publishing_targets_json or []),
        "video_manifest": {
            key: (dict(value) if isinstance(value, Mapping) else None)
            for key, value in dict(row.video_manifest_json or {}).items()
        },
        "output_hash": row.output_hash,
        "canonical_hash": row.canonical_hash,
    }
