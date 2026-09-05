"""LG-16-A7 deterministic publishing metadata artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import hashlib
import re
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    Asset,
    CommerceCreativeMasterVersion,
    VideoPlatformMetadataVersion,
    VideoProjectVersion,
    VideoTextVersion,
)
from src.services.grounding_validator import detect_claim_risks
from src.services.prompt_intelligence_service import canonical_hash
from src.services.rule_based_copy_service import unsupported_claims
from src.services.video_project_version_service import (
    VideoProjectContractError,
    _reference,
    _reference_for,
    _reference_list,
    validate_video_project_version,
)
from src.services.video_storyboard_service import validate_video_storyboard


VIDEO_PLATFORM_METADATA_SCHEMA_VERSION = "lg16-video-platform-metadata-v1"
VIDEO_PLATFORM_TARGETS = ("reels", "tiktok", "youtube_shorts")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT = {"title": 500, "caption": 5000, "description": 10000, "cta": 500}
_UNSAFE_CTA_PATTERNS = (
    r"지금.*손해",
    r"마감",
    r"한정",
    r"마지막",
    r"오늘만",
    r"품절\s*임박",
    r"무조건",
    r"보장",
)
_PLATFORM_FIELDS = {
    "reels": frozenset({"caption", "hashtags", "cta"}),
    "tiktok": frozenset({"caption", "hashtags", "cta"}),
    "youtube_shorts": frozenset({"title", "description", "hashtags"}),
}


class VideoPlatformMetadataContractError(ValueError):
    """A platform metadata request or immutable artifact is invalid."""


def _text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise VideoPlatformMetadataContractError(f"{field} must be text.")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        return None
    if len(normalized) > _MAX_TEXT[field]:
        raise VideoPlatformMetadataContractError(f"{field} exceeds the bounded metadata contract.")
    return normalized


def _hashtags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > 32:
        raise VideoPlatformMetadataContractError("hashtags must be a bounded list.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise VideoPlatformMetadataContractError("hashtags must contain text.")
        tag = unicodedata.normalize("NFC", item).strip()
        if not re.fullmatch(r"#[\w-]{1,99}", tag, re.UNICODE):
            raise VideoPlatformMetadataContractError("hashtags must be seller-safe #tags.")
        if tag in result:
            raise VideoPlatformMetadataContractError("hashtags must not contain duplicates.")
        result.append(tag)
    return result


def _refs(value: Any, allowed: Sequence[Mapping[str, Any]], label: str) -> list[dict[str, Any]]:
    try:
        refs = _reference_list(value, label)
    except VideoProjectContractError as exc:
        raise VideoPlatformMetadataContractError(str(exc)) from exc
    allowed_ids = {(str(item["id"]), int(item["version"]), str(item["hash"])) for item in allowed}
    if not refs or any((item["id"], item["version"], item["hash"]) not in allowed_ids for item in refs):
        raise VideoPlatformMetadataContractError(f"{label} must use approved references.")
    return refs


def _text_refs(db: Session, parent: VideoProjectVersion, value: Any) -> list[dict[str, Any]]:
    refs = _reference_list(value or [], "text_refs")
    current = {str(item.get("id")): item for item in list((parent.video_manifest_json or {}).get("text_layer_refs") or []) if isinstance(item, Mapping)}
    for ref in refs:
        bound = current.get(ref["id"])
        if bound is None or dict(bound) != dict(ref):
            raise VideoPlatformMetadataContractError("text_refs must belong to the current VideoProjectVersion.")
        row = db.query(VideoTextVersion).filter_by(id=ref["id"], project_id=parent.project_id).one_or_none()
        if row is None or row.body_hash != ref["hash"]:
            raise VideoPlatformMetadataContractError("text_refs are stale or out of scope.")
    return refs


def _final_asset(db: Session, *, project_id: str, reference: Mapping[str, Any]) -> Asset:
    try:
        ref = _reference(reference, "final_asset_reference")
    except VideoProjectContractError as exc:
        raise VideoPlatformMetadataContractError(str(exc)) from exc
    asset = db.query(Asset).filter_by(id=ref["id"], project_id=project_id).one_or_none()
    if asset is None or asset.asset_role != "video_final" or asset.mime_type != "video/mp4" or asset.content_hash != ref["hash"]:
        raise VideoPlatformMetadataContractError("final_asset_reference is stale or not a common MP4.")
    return asset


def _current_video(db: Session, *, parent_id: str, workspace_id: str, project_id: str) -> VideoProjectVersion:
    parent = db.query(VideoProjectVersion).filter_by(id=parent_id, workspace_id=workspace_id, project_id=project_id).with_for_update().one_or_none()
    if parent is None:
        raise VideoPlatformMetadataContractError("VideoProjectVersion is outside the requested scope.")
    validate_video_project_version(db, parent)
    latest = db.query(VideoProjectVersion).filter_by(workspace_id=workspace_id, project_id=project_id).order_by(VideoProjectVersion.version.desc()).first()
    if latest is None or latest.id != parent.id:
        raise VideoPlatformMetadataContractError("VideoProjectVersion is stale; reload before adapting metadata.")
    return parent


def _approved_refs(db: Session, parent: VideoProjectVersion) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    storyboard = validate_video_storyboard(db, parent)
    facts: dict[tuple[str, int, str], dict[str, Any]] = {}
    provenance: dict[tuple[str, int, str], dict[str, Any]] = {}
    for scene in storyboard["scenes"]:
        for item in scene["fact_refs"]:
            facts[(item["id"], item["version"], item["hash"])] = dict(item)
        for item in scene["provenance_refs"]:
            provenance[(item["id"], item["version"], item["hash"])] = dict(item)
    return list(facts.values()), list(provenance.values())


def _quality(db: Session, parent: VideoProjectVersion, *, values: Mapping[str, Any], fact_refs: list[dict[str, Any]], provenance_refs: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    if not fact_refs or not provenance_refs:
        return "FAIL", {"status": "FAIL", "reason_codes": ["MISSING_APPROVED_EVIDENCE"]}
    snapshot = db.query(CommerceCreativeMasterVersion).filter_by(id=parent.source_master_id, project_id=parent.project_id).one_or_none()
    fact_snapshot = None
    if snapshot is not None:
        from src.db.models import FactSnapshot
        fact_ref = dict(parent.approved_fact_snapshot_ref_json or {})
        fact_snapshot = db.query(FactSnapshot).filter_by(id=fact_ref.get("id"), project_id=parent.project_id).one_or_none()
    facts = [str(item.get("fact_text") or item.get("value") or "") for item in list(fact_snapshot.facts_json or []) if isinstance(item, Mapping)] if fact_snapshot else []
    reasons: set[str] = set()
    hard_failures: set[str] = set()
    for field in ("title", "caption", "description"):
        body = str(values.get(field) or "")
        if body:
            reasons.update(str(item.risk_type) for item in detect_claim_risks(body, [fact for fact in facts if fact]))
            reasons.update(f"unsupported:{item}" for item in unsupported_claims(body)[:8])
    cta_body = str(values.get("cta") or "")
    if cta_body:
        hard_failures.update(str(item.risk_type) for item in detect_claim_risks(cta_body, [fact for fact in facts if fact]))
        hard_failures.update(f"unsafe_cta:{item}" for item in unsupported_claims(cta_body)[:8])
        hard_failures.update(
            f"unsafe_cta:policy_{index}"
            for index, pattern in enumerate(_UNSAFE_CTA_PATTERNS)
            if re.search(pattern, cta_body, re.IGNORECASE)
        )
    for tag in list(values.get("hashtags") or []):
        hard_failures.update(f"unsupported_hashtag:{item}" for item in unsupported_claims(tag)[:4])
    if hard_failures:
        return "FAIL", {"status": "FAIL", "reason_codes": sorted(hard_failures)[:12], "fact_count": len(facts)}
    if reasons:
        return "REVIEW_REQUIRED", {"status": "REVIEW_REQUIRED", "reason_codes": sorted(reasons)[:12], "fact_count": len(facts)}
    return "PASS", {"status": "PASS", "reason_codes": [], "fact_count": len(facts), "provenance_count": len(provenance_refs)}


def _canonical_hash(row: VideoPlatformMetadataVersion) -> str:
    return canonical_hash({
        "kind": "VideoPlatformMetadataVersion", "schema_version": row.schema_version,
        "workspace_id": row.workspace_id, "project_id": row.project_id,
        "video_project_ref": {"id": row.video_project_version_id},
        "source_master_id": row.source_master_id, "final_asset_id": row.final_asset_id,
        "final_asset_hash": row.final_asset_hash, "platform": row.platform,
        "version": row.version,
        "parent": {"id": row.parent_metadata_version_id, "version": row.parent_metadata_version, "hash": row.parent_metadata_hash} if row.parent_metadata_version_id else None,
        "title": row.title_text, "caption": row.caption_text, "description": row.description_text,
        "cta": row.cta_text, "hashtags": row.hashtags_json, "text_refs": row.text_refs_json,
        "source_fact_refs": row.source_fact_refs_json, "provenance_refs": row.provenance_refs_json,
        "validation_status": row.validation_status, "validation_result": row.validation_result_json,
        "author_id": row.author_id, "idempotency_key": row.idempotency_key,
    })


def validate_video_platform_metadata_version(db: Session, row: VideoPlatformMetadataVersion) -> None:
    if row.schema_version != VIDEO_PLATFORM_METADATA_SCHEMA_VERSION or row.platform not in VIDEO_PLATFORM_TARGETS:
        raise VideoPlatformMetadataContractError("Platform metadata schema or target is invalid.")
    if not _HASH.fullmatch(str(row.final_asset_hash or "")) or _canonical_hash(row) != row.canonical_hash:
        raise VideoPlatformMetadataContractError("Platform metadata hash is invalid.")
    parent = _current_video(db, parent_id=row.video_project_version_id, workspace_id=row.workspace_id, project_id=row.project_id)
    if parent.source_master_id != row.source_master_id:
        raise VideoPlatformMetadataContractError("Platform metadata Master lineage is invalid.")
    _final_asset(db, project_id=row.project_id, reference={"id": row.final_asset_id, "version": 1, "hash": row.final_asset_hash})
    _text_refs(db, parent, row.text_refs_json)
    facts, provenance = _approved_refs(db, parent)
    _refs(row.source_fact_refs_json, facts, "source_fact_refs")
    _refs(row.provenance_refs_json, provenance, "provenance_refs")


def create_video_platform_metadata_version(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_project_version_id: str,
    final_asset_reference: Mapping[str, Any],
    platform: str,
    author_id: str,
    fact_refs: Sequence[Mapping[str, Any]],
    provenance_refs: Sequence[Mapping[str, Any]],
    text_refs: Sequence[Mapping[str, Any]] | None = None,
    title: str | None = None,
    caption: str | None = None,
    description: str | None = None,
    hashtags: Sequence[str] | None = None,
    cta: str | None = None,
    parent_metadata_version_id: str | None = None,
) -> dict[str, Any]:
    if platform not in VIDEO_PLATFORM_TARGETS:
        raise VideoPlatformMetadataContractError("Unsupported platform target.")
    parent = _current_video(db, parent_id=video_project_version_id, workspace_id=workspace_id, project_id=project_id)
    asset = _final_asset(db, project_id=project_id, reference=final_asset_reference)
    authoritative = dict((parent.video_manifest_json or {}).get("final_output_ref") or {})
    if not authoritative or str(authoritative.get("id")) != str(asset.id) or str(authoritative.get("hash")) != str(asset.content_hash):
        raise VideoPlatformMetadataContractError("Metadata must bind to the finalized VideoProjectVersion output.")
    final_ref = {"id": str(asset.id), "version": 1, "hash": str(asset.content_hash)}
    values = {
        "title": _text(title, "title"), "caption": _text(caption, "caption"),
        "description": _text(description, "description"), "cta": _text(cta, "cta"),
        "hashtags": _hashtags(hashtags),
    }
    allowed_fields = _PLATFORM_FIELDS[platform]
    if values["title"] and "title" not in allowed_fields or values["description"] and "description" not in allowed_fields or values["caption"] and "caption" not in allowed_fields or values["cta"] and "cta" not in allowed_fields:
        raise VideoPlatformMetadataContractError("Metadata field is not supported by this platform contract.")
    if platform in {"reels", "tiktok"} and not values["caption"]:
        raise VideoPlatformMetadataContractError("caption is required for this platform contract.")
    if platform == "youtube_shorts" and not values["title"]:
        raise VideoPlatformMetadataContractError("title is required for YouTube Shorts metadata.")
    approved_facts, approved_provenance = _approved_refs(db, parent)
    normalized_facts = _refs(fact_refs, approved_facts, "fact_refs")
    normalized_provenance = _refs(provenance_refs, approved_provenance, "provenance_refs")
    normalized_text = _text_refs(db, parent, text_refs or [])
    identity = {
        "schema_version": VIDEO_PLATFORM_METADATA_SCHEMA_VERSION, "workspace_id": workspace_id, "project_id": project_id,
        "video_project_ref": _reference_for(parent), "final_asset_ref": final_ref, "platform": platform,
        **values, "text_refs": normalized_text, "source_fact_refs": normalized_facts, "provenance_refs": normalized_provenance,
    }
    idempotency = canonical_hash(identity)
    existing = db.query(VideoPlatformMetadataVersion).filter_by(project_id=project_id, platform=platform, idempotency_key=idempotency).one_or_none()
    if existing is not None:
        _journal(db, parent, existing)
        return {"artifact": existing, "replayed": True, "metadata_ref": _metadata_ref(existing)}
    latest = db.query(VideoPlatformMetadataVersion).filter_by(project_id=project_id, platform=platform).order_by(VideoPlatformMetadataVersion.version.desc()).first()
    if latest is not None:
        if not parent_metadata_version_id or parent_metadata_version_id != latest.id:
            raise VideoPlatformMetadataContractError("Platform metadata parent is stale; reload before editing.")
        if latest.video_project_version_id != parent.id or latest.final_asset_hash != asset.content_hash:
            raise VideoPlatformMetadataContractError("Platform metadata parent is bound to a stale video or MP4.")
    elif parent_metadata_version_id is not None:
        raise VideoPlatformMetadataContractError("Platform metadata parent does not exist.")
    status, result = _quality(db, parent, values=values, fact_refs=normalized_facts, provenance_refs=normalized_provenance)
    row = VideoPlatformMetadataVersion(
        id=f"video-meta:{idempotency[:24]}", workspace_id=workspace_id, project_id=project_id,
        video_project_version_id=parent.id, source_master_id=parent.source_master_id,
        final_asset_id=asset.id, final_asset_hash=asset.content_hash,
        schema_version=VIDEO_PLATFORM_METADATA_SCHEMA_VERSION, platform=platform,
        version=(latest.version + 1 if latest else 1),
        parent_metadata_version_id=latest.id if latest else None,
        parent_metadata_version=latest.version if latest else None,
        parent_metadata_hash=latest.canonical_hash if latest else None,
        title_text=values["title"], caption_text=values["caption"], description_text=values["description"], cta_text=values["cta"],
        hashtags_json=copy.deepcopy(values["hashtags"]), text_refs_json=copy.deepcopy(normalized_text),
        source_fact_refs_json=copy.deepcopy(normalized_facts), provenance_refs_json=copy.deepcopy(normalized_provenance),
        validation_status=status, validation_result_json=result, author_id=author_id,
        idempotency_key=idempotency, canonical_hash="",
    )
    row.canonical_hash = _canonical_hash(row)
    db.add(row)
    db.flush()
    _journal(db, parent, row)
    return {"artifact": row, "replayed": False, "metadata_ref": _metadata_ref(row)}


def _metadata_ref(row: VideoPlatformMetadataVersion) -> dict[str, Any]:
    return {"id": str(row.id), "version": int(row.version), "hash": str(row.canonical_hash), "schema_version": VIDEO_PLATFORM_METADATA_SCHEMA_VERSION, "artifact_key": "video_platform_metadata"}


def _journal(db: Session, parent: VideoProjectVersion, row: VideoPlatformMetadataVersion) -> None:
    run = db.query(AgentRun).filter_by(id=parent.creator_run_id, workspace_id=parent.workspace_id, project_id=parent.project_id).one_or_none()
    if run is None:
        raise VideoPlatformMetadataContractError("Video platform metadata creator run is missing.")
    storyboard = dict((parent.video_manifest_json or {}).get("storyboard") or {})
    from src.services.langgraph_run_service import AgentRunEventJournal
    AgentRunEventJournal.append_video_platform_metadata(
        run, db,
        video={
            "video_project_ref": _reference_for(parent), "source_master_ref": {"id": parent.source_master_id, "version": parent.source_master_version, "hash": parent.source_master_hash},
            "scene_count": int(storyboard.get("scene_count") or 0),
        },
        metadata={
            "metadata_ref": _metadata_ref(row), "platform": row.platform, "version": row.version,
            "validation_status": row.validation_status, "canonical_hash": row.canonical_hash, "final_asset_hash": row.final_asset_hash,
        },
    )


def public_video_platform_metadata_projection(row: VideoPlatformMetadataVersion) -> dict[str, Any]:
    """Return the exact seller-editable body only from the canonical artifact."""
    return {
        "id": str(row.id), "version": int(row.version), "platform": row.platform,
        "video_project_ref": {"id": str(row.video_project_version_id), "version": int(row.version)},
        "final_asset_ref": {"id": str(row.final_asset_id), "version": 1, "hash": row.final_asset_hash},
        "title": row.title_text, "caption": row.caption_text, "description": row.description_text,
        "hashtags": list(row.hashtags_json or []), "cta": row.cta_text,
        "text_refs": list(row.text_refs_json or []), "source_fact_refs": list(row.source_fact_refs_json or []),
        "provenance_refs": list(row.provenance_refs_json or []), "validation_status": row.validation_status,
        "validation_result": dict(row.validation_result_json or {}), "canonical_hash": row.canonical_hash,
    }
