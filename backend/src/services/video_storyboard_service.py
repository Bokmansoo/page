"""LG-16-A2 bounded, deterministic storyboard planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import re
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Asset, CommerceCreativeMasterVersion, FactSnapshot, VideoProjectVersion
from src.services.prompt_intelligence_service import canonical_hash
from src.services.video_project_version_service import (
    VIDEO_PROJECT_SCHEMA_VERSION,
    VideoProjectContractError,
    _current_master,
    _master_refs,
    _reference,
    _reference_for,
    _reference_list,
    create_video_project_version,
    validate_video_project_version,
)


VIDEO_STORYBOARD_SCHEMA_VERSION = "lg16-video-storyboard-v1"
VIDEO_SCENE_STATUS = "planned"
VIDEO_SCENE_ROLES = ("hook", "product", "benefit", "feature", "evidence", "usage", "demo", "cta")
VIDEO_SCENE_ROLE_SET = frozenset(VIDEO_SCENE_ROLES)
VIDEO_CREATIVE_INTENTS = frozenset({"product_demo", "benefit_story", "conversion"})
VIDEO_DURATION_INTENTS = frozenset({"short", "medium", "long"})
VIDEO_VISUAL_INTENTS = frozenset({
    "opening_product", "product_detail", "benefit_highlight", "feature_detail",
    "evidence_detail", "usage_in_context", "usage_steps", "closing_cta",
})
VIDEO_USAGE_INTENTS = frozenset({"show_product", "show_benefit", "demonstrate_usage", "close_conversion", "none"})
_KEY = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
_RAW_FIELDS = frozenset({
    "prompt", "raw_prompt", "provider", "provider_payload", "reasoning", "model_output",
    "text", "body", "private_source", "image_bytes", "video_bytes", "url",
})
_GRAPH_SCENE_KEYS = frozenset({
    "scene_id", "logical_target", "role", "order", "duration_intent", "visual_intent",
    "product_asset_refs", "fact_refs", "provenance_refs", "copy_ref", "caption_ref",
    "usage_intent", "selected_variant_ref", "output_ref", "output_hash", "status",
})
_GRAPH_REF_KEYS = frozenset({"id", "version", "hash", "schema_version", "artifact_key"})


class VideoStoryboardContractError(ValueError):
    """A storyboard or scene violates the bounded A2 contract."""


VIDEO_QUALITY_EVALUATOR_VERSION = "lg16-video-quality-v1"
VIDEO_QUALITY_STAGE = "storyboard_content"
VIDEO_QUALITY_DIMENSIONS = (
    "source_master_current", "video_project_current", "storyboard_manifest_integrity",
    "scene_identity_unique", "scene_order_valid", "fact_fidelity", "provenance_complete",
    "rights_valid", "product_identity_valid", "usage_evidence_valid", "role_semantics_valid",
    "scene_completeness", "duplicate_logical_target", "unsupported_claim", "common_video_target_valid",
)
VIDEO_DEFERRED_QUALITY_DIMENSIONS = (
    "visual_continuity", "motion_quality", "actual_usage_realism", "caption_language_quality",
    "audio_sync", "visual_brand_alignment",
)


def _key(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _KEY.fullmatch(value) or "://" in value:
        raise VideoStoryboardContractError(f"{label} must be a bounded semantic key.")
    return value


def _scene_ref(value: Any, label: str) -> dict[str, Any]:
    try:
        return _reference(value, label)
    except VideoProjectContractError as exc:
        raise VideoStoryboardContractError(str(exc)) from exc


def _refs(value: Any, label: str) -> list[dict[str, Any]]:
    try:
        return _reference_list(value, label)
    except VideoProjectContractError as exc:
        raise VideoStoryboardContractError(str(exc)) from exc


def _approved_fact_refs(db: Session, master: CommerceCreativeMasterVersion) -> tuple[dict[str, Any], ...]:
    fact_ref, _brief_ref, _brand_ref, _rights = _master_refs(db, master)
    snapshot = db.query(FactSnapshot).filter_by(id=fact_ref["id"], project_id=master.project_id).one_or_none()
    if snapshot is None or snapshot.snapshot_hash != fact_ref["hash"]:
        raise VideoStoryboardContractError("The Master approved fact snapshot is stale or tampered.")
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(snapshot.facts_json or []):
        if isinstance(item, Mapping):
            fact_id = item.get("fact_id") or item.get("id")
        else:
            fact_id = item
        fact_id = _key(fact_id, f"approved_facts[{index}].id")
        digest = canonical_hash({
            "schema_version": "lg16-approved-fact-ref-v1",
            "snapshot": fact_ref,
            "fact_id": fact_id,
        })
        refs.append({
            "id": fact_id, "version": 1, "hash": digest,
            "schema_version": "lg16-approved-fact-ref-v1", "artifact_key": "approved_fact",
        })
    if not refs:
        raise VideoStoryboardContractError("A storyboard requires approved Master facts.")
    return tuple(refs)


def _normalize_ref_list(value: Any, *, allowed: Mapping[tuple[str, int, str], Mapping[str, Any]], label: str) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise VideoStoryboardContractError(f"{label} must contain approved references.")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            candidates = [ref for identity, ref in allowed.items() if identity[0] == item]
            if len(candidates) != 1:
                raise VideoStoryboardContractError(f"{label}[{index}] is not an approved reference.")
            ref = dict(candidates[0])
        else:
            ref = _scene_ref(item, f"{label}[{index}]")
            identity = (ref["id"], ref["version"], ref["hash"])
            if identity not in allowed:
                raise VideoStoryboardContractError(f"{label}[{index}] is not an approved reference.")
            ref = dict(allowed[identity])
        normalized.append(ref)
    identities = {(ref["id"], ref["version"], ref["hash"]) for ref in normalized}
    if len(identities) != len(normalized):
        raise VideoStoryboardContractError(f"{label} contains duplicate references.")
    return sorted(normalized, key=lambda ref: (ref["id"], ref["version"], ref["hash"]))


def _semantic_scene_identity(source_ref: Mapping[str, Any], scene: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": VIDEO_STORYBOARD_SCHEMA_VERSION,
        "source_video_project": dict(source_ref),
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
    }


def _scene_id(source_ref: Mapping[str, Any], scene: Mapping[str, Any]) -> str:
    return f"video-scene:{canonical_hash(_semantic_scene_identity(source_ref, scene))[:24]}"


def _normalize_scene(
    raw: Mapping[str, Any], *, source_ref: Mapping[str, Any], allowed_assets: Mapping[tuple[str, int, str], Mapping[str, Any]],
    allowed_facts: Mapping[tuple[str, int, str], Mapping[str, Any]], allowed_provenance: Mapping[tuple[str, int, str], Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) & _RAW_FIELDS:
        raise VideoStoryboardContractError("A scene may contain bounded semantics only, not raw provider or source data.")
    required = {"logical_target", "role", "order", "duration_intent", "visual_intent", "product_asset_refs", "fact_refs", "provenance_refs", "usage_intent"}
    missing = required - set(raw)
    if missing:
        raise VideoStoryboardContractError(f"Scene is missing required fields: {sorted(missing)}.")
    role = _key(raw["role"], "scene.role")
    if role not in VIDEO_SCENE_ROLE_SET:
        raise VideoStoryboardContractError("Scene role is unsupported.")
    scene = {
        "logical_target": _key(raw["logical_target"], "scene.logical_target"),
        "role": role,
        "order": raw["order"],
        "duration_intent": _key(raw["duration_intent"], "scene.duration_intent"),
        "visual_intent": _key(raw["visual_intent"], "scene.visual_intent"),
        "product_asset_refs": _normalize_ref_list(raw["product_asset_refs"], allowed=allowed_assets, label="scene.product_asset_refs"),
        "fact_refs": _normalize_ref_list(raw["fact_refs"], allowed=allowed_facts, label="scene.fact_refs"),
        "provenance_refs": _normalize_ref_list(raw["provenance_refs"], allowed=allowed_provenance, label="scene.provenance_refs"),
        "usage_intent": _key(raw["usage_intent"], "scene.usage_intent"),
        "status": VIDEO_SCENE_STATUS,
    }
    if scene["duration_intent"] not in VIDEO_DURATION_INTENTS:
        raise VideoStoryboardContractError("Scene duration_intent is unsupported.")
    if scene["visual_intent"] not in VIDEO_VISUAL_INTENTS:
        raise VideoStoryboardContractError("Scene visual_intent is unsupported.")
    if scene["usage_intent"] not in VIDEO_USAGE_INTENTS:
        raise VideoStoryboardContractError("Scene usage_intent is unsupported.")
    if not isinstance(scene["order"], int) or scene["order"] < 1:
        raise VideoStoryboardContractError("Scene order must be a positive integer.")
    if role in {"benefit", "feature", "evidence", "usage", "demo", "cta"} and not scene["fact_refs"]:
        raise VideoStoryboardContractError("Claim-bearing scenes require approved facts.")
    if role in {"usage", "demo"}:
        if scene["usage_intent"] != "demonstrate_usage" or not scene["provenance_refs"]:
            raise VideoStoryboardContractError("Usage scenes require approved usage evidence and provenance.")
    for field in ("copy_ref", "caption_ref", "selected_variant_ref"):
        if field in raw and raw[field] is not None:
            scene[field] = _scene_ref(raw[field], f"scene.{field}")
    if "output_ref" in raw and raw["output_ref"] is not None:
        scene["output_ref"] = _scene_ref(raw["output_ref"], "scene.output_ref")
    if "output_hash" in raw and raw["output_hash"] is not None:
        output_hash = raw["output_hash"]
        if not isinstance(output_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", output_hash):
            raise VideoStoryboardContractError("scene.output_hash must be a lowercase SHA-256 hash.")
        scene["output_hash"] = output_hash
    identity = _scene_id(source_ref, scene)
    supplied_id = raw.get("scene_id")
    if supplied_id is not None and supplied_id != identity:
        raise VideoStoryboardContractError("scene_id does not match its stable semantic identity.")
    scene["scene_id"] = identity
    return scene


def plan_video_storyboard(
    db: Session,
    video_project: VideoProjectVersion,
    scenes: Sequence[Mapping[str, Any]],
    *,
    creative_intent: str = "product_demo",
) -> dict[str, Any]:
    """Build a deterministic, provider-free storyboard from frozen Master refs."""
    try:
        validate_video_project_version(db, video_project)
    except VideoProjectContractError as exc:
        raise VideoStoryboardContractError(str(exc)) from exc
    if video_project.schema_version != VIDEO_PROJECT_SCHEMA_VERSION:
        raise VideoStoryboardContractError("VideoProjectVersion schema is unsupported.")
    creative_intent = _key(creative_intent, "creative_intent")
    if creative_intent not in VIDEO_CREATIVE_INTENTS:
        raise VideoStoryboardContractError("creative_intent is unsupported.")
    if not isinstance(scenes, (list, tuple)) or not scenes or len(scenes) > 32:
        raise VideoStoryboardContractError("A storyboard requires one to thirty-two scenes.")
    master = db.query(CommerceCreativeMasterVersion).filter_by(
        id=video_project.source_master_id,
        workspace_id=video_project.workspace_id,
        project_id=video_project.project_id,
    ).one_or_none()
    if master is None:
        raise VideoStoryboardContractError("VideoProject source Master is missing.")
    try:
        master = _current_master(
            db,
            workspace_id=video_project.workspace_id,
            project_id=video_project.project_id,
            reference={"id": master.id, "version": master.version, "hash": master.canonical_hash},
            lock=False,
        )
        _fact_ref, _brief_ref, _brand_ref, rights = _master_refs(db, master)
    except VideoProjectContractError as exc:
        raise VideoStoryboardContractError(str(exc)) from exc
    fact_refs = _approved_fact_refs(db, master)
    provenance_refs = tuple(_refs(master.evidence_artifact_refs_json, "master.provenance_refs"))
    if not provenance_refs:
        raise VideoStoryboardContractError("A storyboard requires Master provenance references.")
    allowed_assets = {(ref["id"], ref["version"], ref["hash"]): dict(ref) for ref in rights}
    for identity in allowed_assets:
        asset = db.query(Asset).filter_by(id=identity[0], project_id=master.project_id).one_or_none()
        if asset is None or str(asset.identity_status or "").lower() != "confirmed":
            raise VideoStoryboardContractError("Video scenes require confirmed product-identity assets.")
    allowed_facts = {(ref["id"], ref["version"], ref["hash"]): dict(ref) for ref in fact_refs}
    allowed_provenance = {(ref["id"], ref["version"], ref["hash"]): dict(ref) for ref in provenance_refs}
    source_ref = _reference_for(video_project, hash_field="canonical_hash")
    normalized = [
        _normalize_scene(
            raw, source_ref=source_ref, allowed_assets=allowed_assets,
            allowed_facts=allowed_facts, allowed_provenance=allowed_provenance,
        )
        for raw in scenes
    ]
    orders = [scene["order"] for scene in normalized]
    ids = [scene["scene_id"] for scene in normalized]
    if len(set(orders)) != len(orders) or set(orders) != set(range(1, len(normalized) + 1)):
        raise VideoStoryboardContractError("Scene order must be unique and contiguous from one.")
    if len(set(ids)) != len(ids):
        raise VideoStoryboardContractError("Scene identity must be unique.")
    ordered = sorted(normalized, key=lambda scene: scene["order"])
    payload = {
        "storyboard_schema_version": VIDEO_STORYBOARD_SCHEMA_VERSION,
        "source_video_project_ref": source_ref,
        "creative_intent": creative_intent,
        "publishing_target_intent": {"strategy": "common_video", "targets": sorted(video_project.publishing_targets_json or [])},
        "scene_count": len(ordered),
        "scenes": ordered,
    }
    digest = canonical_hash(payload)
    return {
        **payload,
        "storyboard_id": f"video-storyboard:{digest[:24]}",
        "canonical_hash": digest,
    }


def create_video_storyboard_version(
    db: Session,
    *,
    video_project: VideoProjectVersion,
    scenes: Sequence[Mapping[str, Any]],
    creative_intent: str = "product_demo",
    creator_run_id: str | None = None,
    created_by: str | None = None,
) -> VideoProjectVersion:
    """Persist a storyboard through an immutable VideoProject successor."""
    source_project = video_project
    existing_storyboard = dict((video_project.video_manifest_json or {}).get("storyboard") or {})
    source_ref = existing_storyboard.get("source_video_project_ref")
    if isinstance(source_ref, Mapping) and source_ref.get("id"):
        source_project = db.query(VideoProjectVersion).filter_by(
            id=source_ref["id"], workspace_id=video_project.workspace_id, project_id=video_project.project_id,
        ).one_or_none() or video_project
    storyboard = plan_video_storyboard(db, source_project, scenes, creative_intent=creative_intent)
    manifest = deepcopy(video_project.video_manifest_json or {})
    manifest.update({"storyboard": storyboard, "audio_ref": None, "thumbnail_ref": None, "final_output_ref": None})
    return create_video_project_version(
        db,
        workspace_id=video_project.workspace_id,
        project_id=video_project.project_id,
        creator_run_id=creator_run_id or video_project.creator_run_id,
        created_by=created_by or video_project.created_by,
        source_master_reference={
            "id": video_project.source_master_id,
            "version": video_project.source_master_version,
            "hash": video_project.source_master_hash,
        },
        planning_contract_reference=deepcopy(video_project.planning_contract_ref_json or {}),
        publishing_targets=list(video_project.publishing_targets_json or []),
        video_manifest=manifest,
        parent_version_id=video_project.id,
        output_hash=None,
    )


def validate_video_storyboard(db: Session, video_project: VideoProjectVersion) -> dict[str, Any]:
    """Validate the persisted storyboard against its frozen project successor."""
    manifest = dict(video_project.video_manifest_json or {})
    storyboard = manifest.get("storyboard")
    if not isinstance(storyboard, Mapping):
        raise VideoStoryboardContractError("VideoProjectVersion has no storyboard manifest.")
    scenes = list(storyboard.get("scenes") or [])
    source_row = db.query(VideoProjectVersion).filter_by(
        id=storyboard["source_video_project_ref"]["id"],
        workspace_id=video_project.workspace_id,
        project_id=video_project.project_id,
    ).one_or_none()
    if source_row is None:
        raise VideoStoryboardContractError("Storyboard source VideoProjectVersion is invalid.")
    # A text-only successor may retain the same immutable storyboard source
    # while advancing the VideoProject lineage. The source must remain an
    # ancestor, never an unrelated or future project.
    ancestor_id = video_project.parent_video_project_version_id
    ancestor_ids: set[str] = set()
    while ancestor_id:
        if ancestor_id in ancestor_ids:
            raise VideoStoryboardContractError("VideoProject lineage is cyclic.")
        ancestor_ids.add(str(ancestor_id))
        ancestor = db.query(VideoProjectVersion).filter_by(
            id=ancestor_id, workspace_id=video_project.workspace_id, project_id=video_project.project_id,
        ).one_or_none()
        if ancestor is None:
            break
        ancestor_id = ancestor.parent_video_project_version_id
    if source_row.id != video_project.parent_video_project_version_id and source_row.id not in ancestor_ids:
        raise VideoStoryboardContractError("Storyboard source VideoProjectVersion is not an ancestor.")
    normalized = plan_video_storyboard(
        db,
        source_row,
        scenes,
        creative_intent=storyboard["creative_intent"],
    )
    if normalized != dict(storyboard):
        raise VideoStoryboardContractError("Persisted storyboard hash or semantics are invalid.")
    if storyboard["source_video_project_ref"] != _reference_for(source_row):
        raise VideoStoryboardContractError("Storyboard source VideoProjectVersion is invalid.")
    return dict(storyboard)


def validate_video_graph_request(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the bounded graph command; scene bodies never enter checkpoints."""
    if not isinstance(value, Mapping) or set(value) - {
        "source_video_project_ref", "scenes", "creative_intent",
    }:
        raise VideoStoryboardContractError("Video graph request contains unsupported fields.")
    source = _scene_ref(value.get("source_video_project_ref"), "source_video_project_ref")
    scenes = value.get("scenes")
    if not isinstance(scenes, (list, tuple)) or not scenes or len(scenes) > 32:
        raise VideoStoryboardContractError("Video graph request requires one to thirty-two scenes.")
    for index, scene in enumerate(scenes):
        if (
            not isinstance(scene, Mapping)
            or set(scene) - _GRAPH_SCENE_KEYS
            or any(key in _RAW_FIELDS for key in scene)
        ):
            raise VideoStoryboardContractError(f"Video graph scene {index} contains unsupported or raw fields.")
        nested = [scene.get(key) for key in ("product_asset_refs", "fact_refs", "provenance_refs")]
        if any(
            isinstance(item, (list, tuple))
            and any(isinstance(ref, Mapping) and (set(ref) - _GRAPH_REF_KEYS or set(ref) & _RAW_FIELDS) for ref in item)
            for item in nested
        ):
            raise VideoStoryboardContractError(f"Video graph scene {index} contains raw reference fields.")
    intent = _key(value.get("creative_intent", "product_demo"), "creative_intent")
    if intent not in VIDEO_CREATIVE_INTENTS:
        raise VideoStoryboardContractError("creative_intent is unsupported.")
    # Run the same deterministic normalizer used by the planner only after the
    # source row is loaded; this boundary rejects raw prompt/provider fields.
    return {"source_video_project_ref": source, "scenes": deepcopy(list(scenes)), "creative_intent": intent}


def evaluate_video_storyboard_quality(db: Session, video_project: VideoProjectVersion) -> dict[str, Any]:
    """Return a bounded stage-aware result without requiring a video renderer."""
    project_ref = _reference_for(video_project)
    checks = {name: "DEFERRED" for name in VIDEO_DEFERRED_QUALITY_DIMENSIONS}
    checks.update({name: "PASS" for name in VIDEO_QUALITY_DIMENSIONS})
    reasons: list[str] = []
    targets: list[dict[str, Any]] = []
    storyboard_ref: dict[str, Any] | None = None
    try:
        storyboard = validate_video_storyboard(db, video_project)
        storyboard_ref = {
            "id": storyboard["storyboard_id"],
            "version": 1,
            "hash": storyboard["canonical_hash"],
        }
    except VideoStoryboardContractError as exc:
        message = str(exc).lower()
        checks["storyboard_manifest_integrity"] = "FAIL"
        if "scene" in message and "order" in message:
            checks["scene_order_valid"] = "FAIL"
            reasons.append("SCENE_ORDER_INVALID")
        elif "duplic" in message and "scene" in message:
            checks["scene_identity_unique"] = "FAIL"
            reasons.append("SCENE_ID_DUPLICATE")
        elif "usage" in message or "provenance" in message:
            checks["usage_evidence_valid"] = "FAIL"
            checks["provenance_complete"] = "FAIL"
            reasons.append("USAGE_EVIDENCE_INVALID")
        elif "fact" in message or "claim" in message:
            checks["fact_fidelity"] = "FAIL"
            checks["unsupported_claim"] = "FAIL"
            reasons.append("UNSUPPORTED_CLAIM")
        elif "right" in message:
            checks["rights_valid"] = "FAIL"
            reasons.append("RIGHTS_INVALID")
        elif "identity" in message or "asset" in message:
            checks["product_identity_valid"] = "FAIL"
            reasons.append("PRODUCT_IDENTITY_INVALID")
        elif "master" in message or "stale" in message:
            checks["source_master_current"] = "FAIL"
            reasons.append("SOURCE_MASTER_STALE")
        else:
            reasons.append("STORYBOARD_INVALID")
        # A failed deterministic validation is intentionally fail-closed. The
        # optional target remains bounded and can be filled by later rework UI.
    verdict = "FAIL" if reasons else "PASS"
    result = {
        "schema_version": "lg16-video-quality-v1",
        "quality_stage": VIDEO_QUALITY_STAGE,
        "video_project_ref": project_ref,
        "storyboard_ref": storyboard_ref,
        "verdict": verdict,
        "dimension_results": checks,
        "reason_codes": reasons[:10],
        "rework_targets": targets[:32],
        "evaluator_version": VIDEO_QUALITY_EVALUATOR_VERSION,
    }
    result["canonical_hash"] = canonical_hash({key: value for key, value in result.items() if key != "canonical_hash"})
    return result


def public_video_storyboard_projection(db: Session, video_project: VideoProjectVersion) -> dict[str, Any]:
    storyboard = validate_video_storyboard(db, video_project)
    return {
        "storyboard_schema_version": storyboard["storyboard_schema_version"],
        "storyboard_id": storyboard["storyboard_id"],
        "source_video_project_ref": dict(storyboard["source_video_project_ref"]),
        "creative_intent": storyboard["creative_intent"],
        "publishing_target_intent": deepcopy(storyboard["publishing_target_intent"]),
        "scene_count": storyboard["scene_count"],
        "scenes": deepcopy(storyboard["scenes"]),
        "canonical_hash": storyboard["canonical_hash"],
    }


# Explicit aliases make the deterministic planning boundary discoverable to
# future graph work without creating another service or provider adapter.
deterministic_video_storyboard = plan_video_storyboard
persist_video_storyboard = create_video_storyboard_version
