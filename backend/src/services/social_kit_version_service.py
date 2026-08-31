"""Immutable LG-15 Social Creative Kit persistence foundation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import os
import re
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    AgentRunEvent,
    Asset,
    BrandKitVersion,
    CommerceCreativeMasterVersion,
    FactSnapshot,
    ProductCreativeBriefVersion,
    SocialCardCopyVersion,
    SocialKitVersion,
    generate_uuid,
)
from src.services.product_intake_version_service import validate_immutable_version
from src.services.prompt_intelligence_service import canonical_hash


SOCIAL_KIT_SCHEMA_VERSION = "lg15-social-kit-v1"
SOCIAL_CHANNEL_CONTRACT_SCHEMA_VERSION = "lg15-social-channel-contract-v1"
SOCIAL_CARD_MANIFEST_SCHEMA_VERSION = "lg15-card-semantic-manifest-v2"
SOCIAL_RENDER_PROFILE_SCHEMA_VERSION = "lg15-social-render-profile-v2"
SOCIAL_RENDER_SCHEMA_VERSION = "lg15-social-render-v1"
DETERMINISTIC_FAKE_EXECUTION_MODE = "deterministic_fake"
_REFERENCE_KEYS = frozenset({"id", "version", "hash", "schema_version", "artifact_key"})
_LEGACY_CARD_KEYS = frozenset({"logical_target", "channel", "format", "copy_ref", "asset_ref", "output_hash"})
_MANIFEST_KEYS = frozenset({"manifest_schema_version", "brand_kit_ref", "cards", "publishing_profile_ref"})
_LEGACY_MANIFEST_KEYS = frozenset({"manifest_schema_version", "brand_kit_ref", "cards"})
_CARD_KEYS = frozenset({
    "card_id", "logical_target", "role", "order", "channel", "format",
    "copy_ref", "asset_ref", "fact_refs", "provenance_refs",
    "selected_variant_ref", "status", "output_hash",
})
_CARD_KEYS_WITH_VARIANTS = _CARD_KEYS | {"variant_refs"}
_REQUIRED_CARD_ROLES = ("hero", "benefit", "cta")
_DEFAULT_CARD_ROLES = ("hero", "benefit", "feature", "usage", "cta")
_CARD_ROLE_ORDER = ("hero", "benefit", "feature", "evidence", "usage", "cta")
_CARD_ROLES = frozenset(_CARD_ROLE_ORDER)
_QUALITY_DETERMINISTIC_DIMENSIONS = (
    "source_master_current",
    "manifest_integrity",
    "required_role_coverage",
    "role_relevance",
    "card_order_integrity",
    "fact_fidelity",
    "provenance_complete",
    "rights_valid",
    "brand_reference_valid",
    "copy_reference_complete",
    "duplicate_card_identity",
    "duplicate_logical_target",
    "output_completeness",
    "message_hierarchy",
)
_QUALITY_DEFERRED_DIMENSIONS = (
    "copy_coherence",
    "semantic_duplication",
    "visual_brand_alignment",
)
_KEY = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,99}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOCIAL_REQUEST_KEYS = frozenset({
    "source_master_reference",
    "target_channel",
    "target_format",
    "channel_contract_reference",
    "logical_targets",
    "template_version",
    "evaluator_version",
    "parent_version_id",
    "execution_mode",
})
SOCIAL_CARD_ACTIONS = frozenset({
    "reorder", "delete", "regenerate", "request_alternative", "select_alternative", "edit_copy",
})


class SocialKitContractError(ValueError):
    """A SocialKitVersion request or immutable lineage is invalid."""


def deterministic_social_render_profile(
    kit: SocialKitVersion | None = None,
    *,
    profile_id: str = "instagram_feed_portrait",
    layout_template: str | None = None,
    brand_kit_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the immutable LG-15 Beta profile for the frozen kit."""

    is_instagram_beta = (
        kit is None
        or (str(kit.target_channel) == "instagram" and str(kit.target_format) == "feed_portrait")
    )
    if not is_instagram_beta:
        legacy = {
            "schema_version": "lg15-social-render-profile-v1",
            "profile_id": _key(profile_id, "profile_id"),
            "version": 1,
            "target_platform": "deterministic_test",
            "target_format": str(kit.target_format),
            "canvas": {"width": 640, "height": 360},
            "layout_template": str(kit.template_version),
            "brand_kit_ref": _reference(kit.brand_kit_ref_json, "brand_kit_ref"),
            "output_type": "image/png",
            "production_compliance": "unresolved",
        }
        legacy["canonical_hash"] = canonical_hash(legacy)
        return legacy
    if profile_id != "instagram_feed_portrait":
        raise SocialKitContractError("Unknown SocialKit publishing profile.")

    profile = {
        "schema_version": SOCIAL_RENDER_PROFILE_SCHEMA_VERSION,
        "profile_id": profile_id,
        "profile_version": 1,
        "target_platform": "instagram",
        "target_format": "feed_portrait",
        "canvas": {"width": 1080, "height": 1350},
        "aspect_ratio": "4:5",
        "safe_area_policy": "none_v1",
        "copy_policy": "existing_content_quality",
        "exports": ["png", "jpg", "zip"],
        "classification": "SELLFORM_PRODUCT_DECISION",
        "layout_template": str(layout_template if layout_template is not None else kit.template_version),
        "brand_kit_ref": _reference(brand_kit_ref if brand_kit_ref is not None else kit.brand_kit_ref_json, "brand_kit_ref"),
        "output_type": "image/png",
        "production_compliance": "production",
    }
    profile["canonical_hash"] = canonical_hash(profile)
    return profile


def social_publishing_profile_ref(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return the bounded immutable profile identity stored with a kit/output."""

    if not isinstance(profile, Mapping):
        raise SocialKitContractError("SocialKit publishing profile is invalid.")
    required = {"profile_id", "profile_version", "canonical_hash"}
    if not required.issubset(profile) or profile.get("profile_id") != "instagram_feed_portrait" or profile.get("profile_version") != 1:
        raise SocialKitContractError("SocialKit publishing profile identity is invalid.")
    profile_hash = str(profile.get("canonical_hash") or "")
    if len(profile_hash) != 64 or profile_hash != canonical_hash({key: value for key, value in profile.items() if key != "canonical_hash"}):
        raise SocialKitContractError("SocialKit publishing profile hash is invalid.")
    return {"id": "instagram_feed_portrait", "version": 1, "hash": profile_hash}


def _social_channel_authorized(master: CommerceCreativeMasterVersion, channel: str, format: str) -> bool:
    """Keep social targets bounded while allowing the canonical Instagram derivative."""

    return channel in set(master.target_channels or []) or (channel == "instagram" and format == "feed_portrait")


def render_social_kit_deterministic(
    db: Session,
    kit: SocialKitVersion,
    *,
    output_dir: str | None = None,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Render frozen semantic cards to deterministic local Assets.

    The image contains only bounded role/hash labels.  Copy bodies, provider
    payloads and source URLs never cross this persistence boundary.
    """

    locked_kit = db.query(SocialKitVersion).filter_by(
        id=kit.id, workspace_id=kit.workspace_id, project_id=kit.project_id,
    ).with_for_update().one_or_none()
    if locked_kit is None:
        raise SocialKitContractError("SocialKit render source is missing or out of scope.")
    kit = locked_kit
    validate_social_kit_version(db, kit)
    quality = evaluate_social_card_quality(db, kit)
    if quality.get("verdict") != "PASS":
        raise SocialKitContractError("SocialKit content quality must pass before rendering.")
    render_profile = dict(profile or deterministic_social_render_profile(kit))
    expected_profile = deterministic_social_render_profile(kit)
    if render_profile.get("schema_version") != expected_profile["schema_version"]:
        raise SocialKitContractError("Unsupported SocialKit render profile.")
    if render_profile.get("production_compliance") != expected_profile["production_compliance"]:
        if expected_profile.get("production_compliance") == "unresolved" and render_profile.get("production_compliance") == "production":
            raise SocialKitContractError("A deterministic test profile cannot claim production compliance.")
        raise SocialKitContractError("SocialKit render profile compliance is invalid.")
    if render_profile.get("target_format") != expected_profile["target_format"] or render_profile.get("layout_template") != kit.template_version:
        raise SocialKitContractError("SocialKit render profile does not match the frozen kit.")
    if expected_profile["schema_version"] == SOCIAL_RENDER_PROFILE_SCHEMA_VERSION:
        for key in ("profile_id", "profile_version", "target_platform", "aspect_ratio", "safe_area_policy", "copy_policy", "exports", "classification", "canvas"):
            if render_profile.get(key) != expected_profile.get(key):
                raise SocialKitContractError("SocialKit render profile does not match the canonical Instagram profile.")
    if _reference(render_profile.get("brand_kit_ref"), "render_profile.brand_kit_ref") != _reference(kit.brand_kit_ref_json, "brand_kit_ref"):
        raise SocialKitContractError("SocialKit render profile Brand Kit is stale or out of scope.")
    profile_hash = str(render_profile.get("canonical_hash") or "")
    if profile_hash != canonical_hash({key: value for key, value in render_profile.items() if key != "canonical_hash"}):
        raise SocialKitContractError("SocialKit render profile hash is invalid.")
    manifest = dict(kit.card_manifest_json or {})
    cards = list(manifest.get("cards") or [])
    brand = db.query(BrandKitVersion).filter_by(
        id=kit.brand_kit_ref_json["id"], workspace_id=kit.workspace_id,
    ).one_or_none()
    colors = dict((brand.color_tokens if brand is not None else {}) or {})
    background = str(colors.get("background") or "#F3F4F6")
    accent = str(colors.get("accent") or "#2563EB")
    root = output_dir or "./uploads"
    render_dir = os.path.join(root, "social-renders")
    os.makedirs(render_dir, exist_ok=True)
    canvas = dict(render_profile.get("canvas") or {})
    width, height = int(canvas.get("width") or 0), int(canvas.get("height") or 0)
    if width <= 0 or height <= 0:
        raise SocialKitContractError("SocialKit render profile canvas is invalid.")
    rendered_cards: list[dict[str, Any]] = []
    for card in cards:
        source_ref = _reference(card.get("asset_ref"), "card.asset_ref")
        source_asset = db.query(Asset).filter_by(
            id=source_ref["id"], project_id=kit.project_id,
        ).one_or_none()
        if source_asset is None or str(source_asset.content_hash or "") != source_ref["hash"]:
            raise SocialKitContractError("SocialKit card source asset is stale or out of scope.")
        identity = {
            "social_kit": _reference_for(kit),
            "card_id": str(card["card_id"]),
            "selected_variant_ref": dict(card["selected_variant_ref"]),
            "copy_ref": dict(card["copy_ref"]),
            "render_profile_hash": profile_hash,
            "layout_template": str(kit.template_version),
        }
        semantic_hash = canonical_hash(identity)
        filename = f"social-{semantic_hash}.png"
        file_path = os.path.join(render_dir, filename)
        asset = db.query(Asset).filter_by(project_id=kit.project_id, file_path=file_path).one_or_none()
        if asset is None:
            from src.services.renderer import render_deterministic_social_card

            render_deterministic_social_card(
                file_path,
                role=str(card["role"]),
                card_id=str(card["card_id"]),
                semantic_hash=semantic_hash,
                background=background,
                accent=accent,
                width=width,
                height=height,
            )
            with open(file_path, "rb") as rendered_file:
                content_hash = hashlib.sha256(rendered_file.read()).hexdigest()
            asset = Asset(
                project_id=kit.project_id,
                source_type="html-graphic",
                usage_status="derived_graphic",
                filename=filename,
                file_path=file_path,
                mime_type="image/png",
                file_size=os.path.getsize(file_path),
                source_asset_id=source_asset.id,
                asset_role=f"social_{card['role']}",
                quality_status="usable",
                identity_status="confirmed",
                width=width,
                height=height,
                image_format="PNG",
                quality_warnings=[],
                content_hash=content_hash,
            )
            db.add(asset)
            db.flush()
        rendered_cards.append({
            "card_id": str(card["card_id"]),
            "role": str(card["role"]),
            "asset_ref": {"id": str(asset.id), "version": 1, "hash": str(asset.content_hash)},
            "semantic_hash": semantic_hash,
            "status": "rendered",
        })
    body = {
        "schema_version": SOCIAL_RENDER_SCHEMA_VERSION,
        "execution_mode": DETERMINISTIC_FAKE_EXECUTION_MODE,
        "social_kit_ref": _reference_for(kit),
        "source_master_ref": {"id": kit.source_master_id, "version": kit.source_master_version, "hash": kit.source_master_hash},
        "render_profile": render_profile,
        "cards": rendered_cards,
        "status": "completed",
    }
    body["canonical_hash"] = canonical_hash(body)
    return body


def evaluate_social_platform_quality(db: Session, kit: SocialKitVersion, render: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate the frozen Instagram profile against every rendered card asset."""

    profile = dict((render or {}).get("render_profile") or {})
    expected = deterministic_social_render_profile(kit)
    if expected.get("schema_version") != SOCIAL_RENDER_PROFILE_SCHEMA_VERSION:
        return {
            "schema_version": "lg15-social-platform-quality-v1",
            "profile_id": str(profile.get("profile_id") or ""),
            "profile_version": int(profile.get("version") or 0),
            "verdict": "PASS",
            "reasons": [],
            "card_count": len(list((render or {}).get("cards") or [])),
            "canonical_hash": canonical_hash({
                "schema_version": "lg15-social-platform-quality-v1",
                "profile_id": str(profile.get("profile_id") or ""),
                "profile_version": int(profile.get("version") or 0),
                "verdict": "PASS",
                "reasons": [],
                "card_count": len(list((render or {}).get("cards") or [])),
            }),
        }
    reasons: list[str] = []
    if profile != expected:
        reasons.append("profile_mismatch")
    cards = list((render or {}).get("cards") or [])
    manifest_cards = {str(card.get("card_id")): card for card in list((kit.card_manifest_json or {}).get("cards") or [])}
    seen_profiles = {str(profile.get("canonical_hash") or "")} if profile else set()
    for card in cards:
        ref = dict(card.get("asset_ref") or {})
        asset = db.query(Asset).filter_by(id=ref.get("id"), project_id=kit.project_id).one_or_none()
        if asset is None or str(asset.content_hash or "") != str(ref.get("hash") or ""):
            reasons.append("asset_mismatch")
            continue
        if (int(asset.width or 0), int(asset.height or 0)) != (1080, 1350):
            reasons.append("wrong_dimensions")
        if str(asset.mime_type or "") not in {"image/png", "image/jpeg"}:
            reasons.append("unsupported_mime")
        if str(card.get("card_id") or "") not in manifest_cards:
            reasons.append("card_mismatch")
    if len(seen_profiles) != 1 or len(cards) != len(manifest_cards):
        reasons.append("mixed_or_incomplete_profile")
    return {
        "schema_version": "lg15-social-platform-quality-v1",
        "profile_id": str(profile.get("profile_id") or ""),
        "profile_version": int(profile.get("profile_version") or 0),
        "verdict": "PASS" if not reasons else "FAIL",
        "reasons": sorted(set(reasons)),
        "card_count": len(cards),
        "canonical_hash": canonical_hash({
            "schema_version": "lg15-social-platform-quality-v1",
            "profile_id": str(profile.get("profile_id") or ""),
            "profile_version": int(profile.get("profile_version") or 0),
            "verdict": "PASS" if not reasons else "FAIL",
            "reasons": sorted(set(reasons)),
            "card_count": len(cards),
        }),
    }


def _quality_ref(row: SocialKitVersion) -> dict[str, Any]:
    return {"id": str(row.id), "version": int(row.version), "hash": str(row.canonical_hash)}


def _quality_target(card: Mapping[str, Any] | None, reason_code: str) -> dict[str, Any]:
    card = dict(card or {})
    return {
        "card_id": str(card.get("card_id") or ""),
        "logical_target": str(card.get("logical_target") or ""),
        "role": str(card.get("role") or ""),
        "reason_code": reason_code,
        "action_type": "card_rework",
    }


def _quality_failure_code(message: str) -> tuple[str, str]:
    lowered = message.lower()
    mappings = (
        ("requires hero", "required_role_missing", "required_role_coverage"),
        ("requires approved facts", "required_fact_missing", "fact_fidelity"),
        ("approved master fact", "fact_reference_invalid", "fact_fidelity"),
        ("approved master provenance", "provenance_invalid", "provenance_complete"),
        ("brand kit", "brand_reference_invalid", "brand_reference_valid"),
        ("rights-confirmed", "rights_invalid", "rights_valid"),
        ("source_master", "source_master_stale", "source_master_current"),
        ("card order", "card_order_invalid", "card_order_integrity"),
        ("identities and semantic roles", "duplicate_card_identity", "duplicate_card_identity"),
        ("logical targets", "duplicate_logical_target", "duplicate_logical_target"),
        ("copy_ref", "copy_reference_invalid", "copy_reference_complete"),
        ("output hash", "output_hash_invalid", "output_completeness"),
        ("manifest", "manifest_invalid", "manifest_integrity"),
    )
    for needle, code, dimension in mappings:
        if needle in lowered:
            return code, dimension
    return "quality_input_invalid", "manifest_integrity"


def evaluate_social_card_quality(db: Session, kit: SocialKitVersion) -> dict[str, Any]:
    """Return a bounded deterministic content-quality result for one frozen kit.

    The immutable SocialKitVersion remains the authority.  This is a pure
    projection stored in the existing AgentRun/checkpoint/journal boundaries;
    it never evaluates raw copy, image bytes, or provider output.
    """

    dimensions = [
        {"dimension_id": name, "status": "PASS", "reason_codes": []}
        for name in _QUALITY_DETERMINISTIC_DIMENSIONS
    ]
    dimensions.extend(
        {"dimension_id": name, "status": "DEFERRED", "reason_codes": ["evaluator_required_later"]}
        for name in _QUALITY_DEFERRED_DIMENSIONS
    )
    cards = list((kit.card_manifest_json or {}).get("cards") or []) if isinstance(kit.card_manifest_json, Mapping) else []
    failure_code = None
    failure_dimension = None
    try:
        validate_social_kit_version(db, kit)
    except (SocialKitContractError, ValueError) as exc:
        failure_code, failure_dimension = _quality_failure_code(str(exc))
        for item in dimensions:
            if item["dimension_id"] == failure_dimension:
                item["status"] = "FAIL"
                item["reason_codes"] = [failure_code]
                break
    card_ids: set[str] = set()
    targets: set[str] = set()
    for card in cards:
        role = str(card.get("role") or "")
        card_id = str(card.get("card_id") or "")
        target = str(card.get("logical_target") or "")
        card_ids.add(card_id)
        targets.add(target)
    if len(card_ids) != len(cards) and failure_code is None:
        failure_code, failure_dimension = "duplicate_card_identity", "duplicate_card_identity"
    if len(targets) != len(cards) and failure_code is None:
        failure_code, failure_dimension = "duplicate_logical_target", "duplicate_logical_target"
    if failure_code is not None:
        for item in dimensions:
            if item["dimension_id"] == failure_dimension and item["status"] != "FAIL":
                item["status"] = "FAIL"
                item["reason_codes"] = [failure_code]
    failed = [item for item in dimensions if item["status"] == "FAIL"]
    reason_codes = sorted({code for item in failed for code in item["reason_codes"]})
    rework_targets = []
    if failed:
        rework_targets = [_quality_target(cards[0] if cards else None, reason_codes[0] if reason_codes else "quality_input_invalid")]
    body = {
        "schema_version": "lg15-social-quality-v1",
        "quality_stage": "content",
        "social_kit_ref": _quality_ref(kit),
        "verdict": "FAIL" if failed else "PASS",
        "dimension_results": dimensions,
        "reason_codes": reason_codes,
        "rework_targets": rework_targets,
        "evaluator_version": str(kit.evaluator_version),
    }
    return {**body, "canonical_hash": canonical_hash(body)}


def validate_social_kit_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the reference-only A2 graph input contract."""

    if not isinstance(request, Mapping) or set(request) != _SOCIAL_REQUEST_KEYS:
        raise SocialKitContractError("SocialKit request contains unsupported fields.")
    source_master = _reference(request["source_master_reference"], "source_master_reference")
    channel = _key(request["target_channel"], "target_channel")
    target_format = _key(request["target_format"], "target_format")
    contract = _reference(request["channel_contract_reference"], "channel_contract_reference")
    if contract != deterministic_social_channel_contract_reference(channel=channel, format=target_format):
        raise SocialKitContractError("channel_contract does not match the canonical channel/format identity.")
    raw_targets = request["logical_targets"]
    if not isinstance(raw_targets, (list, tuple)):
        raise SocialKitContractError("logical_targets must be a list.")
    requested_roles = [_key(value, "logical_target") for value in raw_targets]
    if len(set(requested_roles)) != len(requested_roles):
        raise SocialKitContractError("logical_targets contains duplicate semantic roles.")
    unknown_roles = set(requested_roles) - _CARD_ROLES
    if unknown_roles:
        raise SocialKitContractError("logical_targets contains an unsupported semantic role.")
    if not set(_REQUIRED_CARD_ROLES).issubset(requested_roles):
        raise SocialKitContractError("logical_targets must include hero, benefit, and cta.")
    logical_targets = [role for role in _CARD_ROLE_ORDER if role in requested_roles]
    parent = request["parent_version_id"]
    if parent is not None:
        parent = _key(parent, "parent_version_id")
    execution_mode = request["execution_mode"]
    if execution_mode != DETERMINISTIC_FAKE_EXECUTION_MODE:
        raise SocialKitContractError("A2 supports deterministic fake execution only.")
    return {
        "source_master_reference": source_master,
        "target_channel": channel,
        "target_format": target_format,
        "channel_contract_reference": contract,
        "logical_targets": logical_targets,
        "template_version": _key(request["template_version"], "template_version"),
        "evaluator_version": _key(request["evaluator_version"], "evaluator_version"),
        "parent_version_id": parent,
        "execution_mode": execution_mode,
    }


def resolve_current_social_master(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    source_master_reference: Mapping[str, Any],
) -> CommerceCreativeMasterVersion:
    """Resolve and validate the server-authoritative current Master."""

    reference = _reference(source_master_reference, "source_master_reference")
    master = _current_master(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        master_id=reference["id"],
    )
    if reference != _reference_for(master):
        raise SocialKitContractError("source_master ID/version/hash does not match the current Master.")
    return master


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise SocialKitContractError(f"{label} must be a lowercase SHA-256 hash.")
    return value


def _key(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise SocialKitContractError(f"{label} must be a bounded canonical key.")
    return value


def _reference(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - _REFERENCE_KEYS:
        raise SocialKitContractError(f"{label} must be a bounded immutable reference.")
    result = deepcopy(dict(value))
    if not isinstance(result.get("id"), str) or not result["id"]:
        raise SocialKitContractError(f"{label}.id is required.")
    if not isinstance(result.get("version"), int) or result["version"] < 1:
        raise SocialKitContractError(f"{label}.version must be positive.")
    _hash(result.get("hash"), f"{label}.hash")
    for name in ("schema_version", "artifact_key"):
        if name in result:
            _key(result[name], f"{label}.{name}")
    return result


def _reference_for(row: Any, *, hash_field: str = "canonical_hash") -> dict[str, Any]:
    return {"id": str(row.id), "version": int(row.version), "hash": str(getattr(row, hash_field))}


def _reference_list(values: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(values, (list, tuple)):
        raise SocialKitContractError(f"{label} must be a list.")
    refs = [_reference(value, f"{label}[{index}]") for index, value in enumerate(values)]
    if len({(item["id"], item["version"], item["hash"]) for item in refs}) != len(refs):
        raise SocialKitContractError(f"{label} contains duplicate references.")
    return sorted(refs, key=lambda item: (item["id"], item["version"], item["hash"]))


def deterministic_social_channel_contract_reference(*, channel: str, format: str) -> dict[str, Any]:
    """Pin channel/format identity without inventing unspecified platform dimensions."""

    normalized_channel = _key(channel, "channel")
    normalized_format = _key(format, "format")
    payload = {
        "schema_version": SOCIAL_CHANNEL_CONTRACT_SCHEMA_VERSION,
        "channel": normalized_channel,
        "format": normalized_format,
    }
    digest = canonical_hash(payload)
    return {
        "id": f"social-channel-contract:{digest[:24]}",
        "version": 1,
        "hash": digest,
        "schema_version": SOCIAL_CHANNEL_CONTRACT_SCHEMA_VERSION,
        "artifact_key": "social_channel_contract",
    }


def deterministic_fake_social_cards(
    db: Session,
    *,
    master: CommerceCreativeMasterVersion,
    channel: str,
    format: str,
    logical_targets: Sequence[str],
    template_version: str,
    evaluator_version: str,
) -> dict[str, Any]:
    """Create one ordered reference-only semantic manifest without provider work."""

    normalized_channel = _key(channel, "channel")
    normalized_format = _key(format, "format")
    normalized_template = _key(template_version, "template_version")
    normalized_evaluator = _key(evaluator_version, "evaluator_version")
    _fact_snapshot_ref, _brief_ref, brand_ref, assets, facts, provenance = _master_inputs(db, master)
    if not isinstance(logical_targets, (list, tuple)):
        raise SocialKitContractError("logical_targets must be a list.")
    requested_roles = [_key(value, "logical_target") for value in logical_targets]
    if len(set(requested_roles)) != len(requested_roles) or set(requested_roles) - _CARD_ROLES:
        raise SocialKitContractError("Deterministic card planning requires unique supported semantic roles.")
    if not set(_REQUIRED_CARD_ROLES).issubset(requested_roles):
        raise SocialKitContractError("Deterministic card planning requires hero, benefit, and cta.")
    roles = [role for role in _CARD_ROLE_ORDER if role in requested_roles]
    if not assets or not facts or not provenance:
        raise SocialKitContractError("Deterministic card planning requires approved facts, provenance, and assets.")
    master_ref = _reference_for(master)
    cards: list[dict[str, Any]] = []
    for index, role in enumerate(roles):
        asset_ref = assets[index % len(assets)]
        fact_ref = facts[index % len(facts)]
        card_identity = {
            "schema_version": SOCIAL_CARD_MANIFEST_SCHEMA_VERSION,
            "source_master": master_ref,
            "channel": normalized_channel,
            "format": normalized_format,
            "role": role,
            "logical_target": role,
        }
        card_id = f"social-card:{canonical_hash(card_identity)[:24]}"
        selected_variant_ref = _variant_reference(
            card_id=card_id,
            intent="initial",
            variant_key="primary",
        )
        copy_text = _default_copy_text(role)
        copy_hash = _copy_hash(master_ref, card_id, copy_text)
        copy_identity = _copy_identity_hash(master_ref, card_id, copy_text)
        card = {
            "card_id": card_id,
            "logical_target": role,
            "role": role,
            "order": index + 1,
            "channel": normalized_channel,
            "format": normalized_format,
            "copy_ref": _copy_reference(copy_hash, identity_hash=copy_identity),
            "asset_ref": deepcopy(asset_ref),
            "fact_refs": [deepcopy(fact_ref)],
            "provenance_refs": deepcopy(provenance),
            "selected_variant_ref": selected_variant_ref,
            "status": "planned",
        }
        cards.append(_rehash_card(card))
    manifest = {
        "manifest_schema_version": SOCIAL_CARD_MANIFEST_SCHEMA_VERSION,
        "brand_kit_ref": brand_ref,
        "cards": cards,
    }
    if normalized_channel == "instagram" and normalized_format == "feed_portrait":
        manifest["publishing_profile_ref"] = social_publishing_profile_ref(
            deterministic_social_render_profile(layout_template=template_version, brand_kit_ref=brand_ref)
        )
    return manifest


def _default_copy_text(role: str) -> str:
    return {
        "hero": "상품의 핵심 가치를 한눈에 확인하세요.",
        "benefit": "일상에서 바로 체감하는 주요 장점.",
        "feature": "필요한 기능을 간편하게 사용할 수 있습니다.",
        "usage": "원하는 순간 간단하게 사용하세요.",
        "cta": "지금 상품의 장점을 확인해 보세요.",
    }.get(role, "상품의 주요 특징을 확인해 보세요.")


def _copy_hash(source_master_ref: Mapping[str, Any], card_id: str, body_text: str, parent_ref: Mapping[str, Any] | None = None) -> str:
    return hashlib.sha256(body_text.encode("utf-8")).hexdigest()


def _copy_identity_hash(source_master_ref: Mapping[str, Any], card_id: str, body_text: str, parent_ref: Mapping[str, Any] | None = None) -> str:
    return canonical_hash({
        "schema_version": "lg15-social-card-copy-v1",
        "source_master": dict(source_master_ref),
        "card_id": card_id,
        "parent": dict(parent_ref) if parent_ref else None,
        "body_text": body_text,
    })


def _copy_reference(copy_hash: str, *, version: int = 1, identity_hash: str | None = None) -> dict[str, Any]:
    return {
        "id": f"social-copy:{(identity_hash or copy_hash)[:24]}",
        "version": version,
        "hash": copy_hash,
        "schema_version": "lg15-social-card-copy-v1",
        "artifact_key": "social_card_copy",
    }


def _copy_canonical_hash(row: SocialCardCopyVersion) -> str:
    return canonical_hash({
        "kind": "SocialCardCopyVersion",
        "workspace_id": row.workspace_id,
        "project_id": row.project_id,
        "source_social_kit": {
            "id": row.source_social_kit_id,
            "version": row.source_social_kit_version,
        },
        "source_master": {"id": row.source_master_id, "version": row.source_master_version},
        "card_id": row.card_id,
        "version": row.version,
        "parent": (
            {"id": row.parent_version_id, "version": row.parent_version, "hash": row.parent_version_hash}
            if row.parent_version_id else None
        ),
        "body_hash": row.body_hash,
        "validation_status": row.validation_status,
        "validation_result": row.validation_result_json,
        "idempotency_key": row.idempotency_key,
    })


def _validate_copy_artifact(db: Session, kit: SocialKitVersion, card: Mapping[str, Any]) -> SocialCardCopyVersion:
    ref = _reference(card.get("copy_ref"), "card.copy_ref")
    copy = db.query(SocialCardCopyVersion).filter_by(
        id=ref["id"], workspace_id=kit.workspace_id, project_id=kit.project_id,
    ).one_or_none()
    if copy is None or int(copy.version) != int(ref["version"]) or str(copy.body_hash) != str(ref["hash"]):
        raise SocialKitContractError("SocialKit card copy reference is missing or stale.")
    source_kit = db.query(SocialKitVersion).filter_by(
        id=copy.source_social_kit_id, workspace_id=kit.workspace_id, project_id=kit.project_id,
    ).one_or_none()
    if (
        source_kit is None
        or
        copy.card_id != str(card.get("card_id"))
        or copy.source_master_id != kit.source_master_id
        or int(copy.source_master_version) != int(kit.source_master_version)
        or copy.validation_status != "PASS"
        or hashlib.sha256(str(copy.body_text).encode("utf-8")).hexdigest() != copy.body_hash
        or _copy_canonical_hash(copy) != copy.canonical_hash
    ):
        raise SocialKitContractError("SocialKit card copy artifact is invalid or out of scope.")
    return copy


def _materialize_initial_copy_artifacts(
    db: Session, *, kit: SocialKitVersion, master: CommerceCreativeMasterVersion, cards: Sequence[Mapping[str, Any]], author_id: str,
) -> None:
    master_ref = _reference_for(master)
    for card in cards:
        ref = _reference(card.get("copy_ref"), "card.copy_ref")
        if db.query(SocialCardCopyVersion).filter_by(id=ref["id"], project_id=kit.project_id).one_or_none() is not None:
            continue
        body = _default_copy_text(str(card.get("role") or "social_card"))
        expected_hash = _copy_hash(master_ref, str(card["card_id"]), body)
        expected_id = _copy_reference(expected_hash, identity_hash=_copy_identity_hash(master_ref, str(card["card_id"]), body))["id"]
        if expected_hash != ref["hash"] or expected_id != ref["id"]:
            raise SocialKitContractError("Initial SocialKit copy reference is not canonical.")
        idempotency = canonical_hash({"source_master": master_ref, "card_id": str(card["card_id"]), "body_hash": expected_hash})
        copy = SocialCardCopyVersion(
            id=ref["id"], workspace_id=kit.workspace_id, project_id=kit.project_id,
            source_social_kit_id=kit.id, source_social_kit_version=kit.version,
            card_id=str(card["card_id"]), source_master_id=master.id, source_master_version=master.version,
            version=1, body_text=body, body_hash=expected_hash, validation_status="PASS",
            validation_result_json={"status": "PASS", "reason_code": "deterministic_initial_copy"},
            author_id=author_id, idempotency_key=idempotency, canonical_hash="",
        )
        copy.canonical_hash = _copy_canonical_hash(copy)
        db.add(copy)


def _validate_copy_edit(db: Session, master: CommerceCreativeMasterVersion, text: str) -> tuple[str, dict[str, Any]]:
    snapshot_ref = _reference(master.approved_fact_snapshot_ref_json, "master.approved_fact_snapshot")
    snapshot = db.query(FactSnapshot).filter_by(id=snapshot_ref["id"], project_id=master.project_id).one_or_none()
    facts = [str(item.get("fact_text") or item.get("value") or "") for item in (snapshot.facts_json if snapshot else []) if isinstance(item, Mapping)]
    from src.services.grounding_validator import detect_claim_risks
    risks = detect_claim_risks(text, [value for value in facts if value])
    if risks:
        return "REVIEW_REQUIRED", {
            "status": "REVIEW_REQUIRED",
            "reason_codes": sorted({str(item.risk_type) for item in risks})[:8],
            "fact_count": len(facts),
        }
    return "PASS", {"status": "PASS", "reason_codes": [], "fact_count": len(facts)}


def _variant_reference(
    *,
    card_id: str,
    intent: str,
    variant_key: str,
) -> dict[str, Any]:
    identity = {
        "schema_version": "lg15-social-card-variant-ref-v1",
        "card_id": _key(card_id, "card_id"),
        "intent": _key(intent, "intent"),
        "variant_key": _key(variant_key, "variant_key"),
    }
    digest = canonical_hash(identity)
    return {
        "id": f"social-card-variant:{digest[:24]}",
        "version": 1,
        "hash": digest,
        "schema_version": "lg15-social-card-variant-ref-v1",
        "artifact_key": "social_card_variant",
    }


def _rehash_card(card: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(card))
    result.pop("output_hash", None)
    result["output_hash"] = canonical_hash(result)
    return result


def evolve_social_card_manifest(
    manifest: Mapping[str, Any],
    *,
    intent: str,
    card_id: str | None = None,
    ordered_card_ids: Sequence[str] = (),
    variant_key: str = "successor",
) -> dict[str, Any]:
    """Derive a successor manifest while preserving stable card identities."""

    if not isinstance(manifest, Mapping) or set(manifest) not in {_MANIFEST_KEYS, _LEGACY_MANIFEST_KEYS}:
        raise SocialKitContractError("A4 successor requires a semantic card manifest.")
    result = deepcopy(dict(manifest))
    cards = list(result.get("cards") or [])
    normalized_intent = _key(intent, "intent")
    if normalized_intent == "reorder":
        identities = [_key(value, "ordered_card_id") for value in ordered_card_ids]
        if len(identities) != len(cards) or set(identities) != {item.get("card_id") for item in cards}:
            raise SocialKitContractError("Reorder must contain every card identity exactly once.")
        by_id = {item["card_id"]: item for item in cards}
        cards = [_rehash_card({**by_id[identity], "order": index + 1}) for index, identity in enumerate(identities)]
    elif normalized_intent == "delete":
        target = _key(card_id, "card_id")
        selected = next((item for item in cards if item.get("card_id") == target), None)
        if selected is None:
            raise SocialKitContractError("Delete target card is missing.")
        if selected.get("role") in _REQUIRED_CARD_ROLES:
            raise SocialKitContractError("Required hero, benefit, and cta cards cannot be deleted.")
        cards = [item for item in cards if item.get("card_id") != target]
        cards = [_rehash_card({**item, "order": index + 1}) for index, item in enumerate(cards)]
    elif normalized_intent in {"regenerate", "alternative", "edit"}:
        target = _key(card_id, "card_id")
        found = False
        updated: list[dict[str, Any]] = []
        for item in cards:
            if item.get("card_id") != target:
                updated.append(item)
                continue
            found = True
            updated.append(_rehash_card({
                **item,
                "selected_variant_ref": _variant_reference(
                    card_id=target,
                    intent=normalized_intent,
                    variant_key=variant_key,
                ),
            }))
        if not found:
            raise SocialKitContractError("Successor target card is missing.")
        cards = updated
    elif normalized_intent == "request_alternative":
        target = _key(card_id, "card_id")
        candidate = _variant_reference(card_id=target, intent="alternative", variant_key=variant_key)
        found = False
        updated: list[dict[str, Any]] = []
        for item in cards:
            if item.get("card_id") != target:
                updated.append(item)
                continue
            found = True
            candidates = [dict(value) for value in list(item.get("variant_refs") or [])]
            if candidate not in candidates:
                candidates.append(candidate)
            updated.append(_rehash_card({**item, "variant_refs": candidates}))
        if not found:
            raise SocialKitContractError("Successor target card is missing.")
        cards = updated
    elif normalized_intent == "select_alternative":
        target = _key(card_id, "card_id")
        selected = _variant_reference(card_id=target, intent="alternative", variant_key=variant_key)
        found = False
        updated: list[dict[str, Any]] = []
        for item in cards:
            if item.get("card_id") != target:
                updated.append(item)
                continue
            found = True
            candidates = [dict(value) for value in list(item.get("variant_refs") or [])]
            if selected not in candidates:
                raise SocialKitContractError("Selected alternative is not an existing candidate.")
            updated.append(_rehash_card({**item, "selected_variant_ref": selected}))
        if not found:
            raise SocialKitContractError("Successor target card is missing.")
        cards = updated
    else:
        raise SocialKitContractError("Unsupported SocialKit successor intent.")
    result["cards"] = cards
    return result


def _card_manifest(
    values: Any,
    *,
    channel: str,
    format: str,
    rights_asset_refs: Sequence[Mapping[str, Any]],
    approved_fact_refs: Sequence[Mapping[str, Any]] = (),
    provenance_refs: Sequence[Mapping[str, Any]] = (),
    brand_kit_ref: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    allowed_assets = {
        (item["id"], item["version"], item["hash"])
        for item in _reference_list(rights_asset_refs, "rights_asset_refs")
    }
    if isinstance(values, (list, tuple)):
        if not values:
            raise SocialKitContractError("card_manifest must contain at least one frozen card.")
        cards: list[dict[str, Any]] = []
        targets: set[str] = set()
        for index, value in enumerate(values):
            if not isinstance(value, Mapping) or set(value) != _LEGACY_CARD_KEYS:
                raise SocialKitContractError(f"card_manifest[{index}] must contain only frozen reference fields.")
            card = deepcopy(dict(value))
            logical_target = _key(card.get("logical_target"), f"card_manifest[{index}].logical_target")
            if logical_target in targets:
                raise SocialKitContractError("card_manifest logical targets must be unique.")
            targets.add(logical_target)
            if card.get("channel") != channel or card.get("format") != format:
                raise SocialKitContractError("Every card must match the SocialKit channel and format.")
            card["copy_ref"] = _reference(card.get("copy_ref"), f"card_manifest[{index}].copy_ref")
            card["asset_ref"] = _reference(card.get("asset_ref"), f"card_manifest[{index}].asset_ref")
            if (card["asset_ref"]["id"], card["asset_ref"]["version"], card["asset_ref"]["hash"]) not in allowed_assets:
                raise SocialKitContractError("Social cards may use only rights-confirmed Master assets.")
            card["output_hash"] = _hash(card.get("output_hash"), f"card_manifest[{index}].output_hash")
            cards.append(card)
        return sorted(cards, key=lambda item: item["logical_target"])

    if not isinstance(values, Mapping) or set(values) not in {_MANIFEST_KEYS, _LEGACY_MANIFEST_KEYS}:
        raise SocialKitContractError("card_manifest must be a bounded semantic manifest.")
    if values.get("manifest_schema_version") != SOCIAL_CARD_MANIFEST_SCHEMA_VERSION:
        raise SocialKitContractError("card_manifest schema version is unsupported.")
    expected_brand = _reference(brand_kit_ref, "brand_kit_ref")
    if _reference(values.get("brand_kit_ref"), "card_manifest.brand_kit_ref") != expected_brand:
        raise SocialKitContractError("card_manifest Brand Kit reference does not match its Master.")
    publishing_profile_ref = values.get("publishing_profile_ref")
    if publishing_profile_ref is not None:
        if not isinstance(publishing_profile_ref, Mapping) or set(publishing_profile_ref) != {"id", "version", "hash"}:
            raise SocialKitContractError("card_manifest publishing profile reference is invalid.")
        if publishing_profile_ref.get("id") != "instagram_feed_portrait" or publishing_profile_ref.get("version") != 1 or not _SHA256.fullmatch(str(publishing_profile_ref.get("hash") or "")):
            raise SocialKitContractError("card_manifest publishing profile reference is invalid.")
    raw_cards = values.get("cards")
    if not isinstance(raw_cards, list) or not raw_cards:
        raise SocialKitContractError("card_manifest.cards must contain frozen semantic cards.")
    allowed_facts = {
        (item["id"], item["version"], item["hash"])
        for item in _reference_list(approved_fact_refs, "approved_fact_refs")
    }
    allowed_provenance = {
        (item["id"], item["version"], item["hash"])
        for item in _reference_list(provenance_refs, "provenance_refs")
    }
    cards: list[dict[str, Any]] = []
    identities: set[str] = set()
    roles: set[str] = set()
    orders: set[int] = set()
    for index, value in enumerate(raw_cards):
        if not isinstance(value, Mapping) or set(value) not in {_CARD_KEYS, _CARD_KEYS_WITH_VARIANTS}:
            raise SocialKitContractError(f"card_manifest.cards[{index}] must contain only bounded reference fields.")
        card = deepcopy(dict(value))
        card_id = _key(card.get("card_id"), f"card_manifest.cards[{index}].card_id")
        role = _key(card.get("role"), f"card_manifest.cards[{index}].role")
        logical_target = _key(card.get("logical_target"), f"card_manifest.cards[{index}].logical_target")
        order = card.get("order")
        if role not in _CARD_ROLES or logical_target != role:
            raise SocialKitContractError("Every card must use a supported semantic role.")
        if card_id in identities or role in roles:
            raise SocialKitContractError("Card identities and semantic roles must be unique.")
        if not isinstance(order, int) or order < 1 or order in orders:
            raise SocialKitContractError("Card order must be a unique positive integer.")
        identities.add(card_id); roles.add(role); orders.add(order)
        if card.get("channel") != channel or card.get("format") != format:
            raise SocialKitContractError("Every card must match the SocialKit channel and format.")
        card["copy_ref"] = _reference(card.get("copy_ref"), f"card_manifest.cards[{index}].copy_ref")
        card["asset_ref"] = _reference(card.get("asset_ref"), f"card_manifest.cards[{index}].asset_ref")
        asset_identity = (card["asset_ref"]["id"], card["asset_ref"]["version"], card["asset_ref"]["hash"])
        if asset_identity not in allowed_assets:
            raise SocialKitContractError("Social cards may use only rights-confirmed Master assets.")
        card["fact_refs"] = _reference_list(card.get("fact_refs"), f"card_manifest.cards[{index}].fact_refs")
        if not card["fact_refs"] or any((ref["id"], ref["version"], ref["hash"]) not in allowed_facts for ref in card["fact_refs"]):
            raise SocialKitContractError("Every card must use only approved Master fact references.")
        card["provenance_refs"] = _reference_list(card.get("provenance_refs"), f"card_manifest.cards[{index}].provenance_refs")
        if not card["provenance_refs"] or any((ref["id"], ref["version"], ref["hash"]) not in allowed_provenance for ref in card["provenance_refs"]):
            raise SocialKitContractError("Every card must pin approved Master provenance references.")
        card["selected_variant_ref"] = _reference(card.get("selected_variant_ref"), f"card_manifest.cards[{index}].selected_variant_ref")
        if "variant_refs" in card:
            card["variant_refs"] = _reference_list(card.get("variant_refs"), f"card_manifest.cards[{index}].variant_refs")
        if card.get("status") != "planned":
            raise SocialKitContractError("Card status must be the bounded planned state.")
        card["output_hash"] = _hash(card.get("output_hash"), f"card_manifest.cards[{index}].output_hash")
        if _rehash_card(card)["output_hash"] != card["output_hash"]:
            raise SocialKitContractError("Card output hash does not match its semantic content.")
        cards.append(card)
    if not set(_REQUIRED_CARD_ROLES).issubset(roles):
        raise SocialKitContractError("card_manifest requires hero, benefit, and cta cards.")
    if orders != set(range(1, len(cards) + 1)):
        raise SocialKitContractError("Card order must be contiguous from one.")
    return {
        "manifest_schema_version": SOCIAL_CARD_MANIFEST_SCHEMA_VERSION,
        "brand_kit_ref": expected_brand,
        **({"publishing_profile_ref": dict(publishing_profile_ref)} if publishing_profile_ref is not None else {}),
        "cards": sorted(cards, key=lambda item: item["order"]),
    }


def _payload(row: SocialKitVersion) -> dict[str, Any]:
    return {
        "kind": "SocialKitVersion",
        "schema_version": row.schema_version,
        "workspace_id": row.workspace_id,
        "project_id": row.project_id,
        "creator_run_id": row.creator_run_id,
        "version": row.version,
        "parent": (
            {"id": row.parent_version_id, "version": row.parent_version, "hash": row.parent_version_hash}
            if row.parent_version_id else None
        ),
        "source_master": {
            "id": row.source_master_id,
            "version": row.source_master_version,
            "hash": row.source_master_hash,
        },
        "approved_fact_snapshot": row.approved_fact_snapshot_ref_json,
        "creative_brief": row.creative_brief_ref_json,
        "brand_kit": row.brand_kit_ref_json,
        "rights_asset_refs": row.rights_asset_refs_json,
        "target_channel": row.target_channel,
        "target_format": row.target_format,
        "channel_contract": row.channel_contract_ref_json,
        "execution_mode": row.execution_mode,
        "template_version": row.template_version,
        "evaluator_version": row.evaluator_version,
        "card_manifest": row.card_manifest_json,
        "output_hash": row.output_hash,
        "idempotency_key": row.idempotency_key,
    }


def _idempotency_key(payload: Mapping[str, Any]) -> str:
    value = dict(payload)
    identity = {
        "kind": value["kind"],
        "schema_version": value["schema_version"],
        "workspace_id": value["workspace_id"],
        "project_id": value["project_id"],
        "parent": value["parent"],
        "source_master": value["source_master"],
        "target_channel": value["target_channel"],
        "target_format": value["target_format"],
        "channel_contract": value["channel_contract"],
        "execution_mode": value["execution_mode"],
        "template_version": value["template_version"],
        "evaluator_version": value["evaluator_version"],
        "card_manifest": value["card_manifest"],
    }
    return canonical_hash(identity)


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return canonical_hash({key: value for key, value in payload.items() if key != "canonical_hash"})


def _current_master(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    master_id: str,
    lock: bool = False,
) -> CommerceCreativeMasterVersion:
    query = db.query(CommerceCreativeMasterVersion).filter_by(
        id=master_id,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    master = (query.with_for_update() if lock else query).one_or_none()
    if master is None:
        raise SocialKitContractError("source_master must belong to the same workspace and project.")
    validate_immutable_version(db, master)
    latest = (
        db.query(CommerceCreativeMasterVersion)
        .filter_by(workspace_id=workspace_id, project_id=project_id)
        .order_by(CommerceCreativeMasterVersion.version.desc())
        .first()
    )
    if latest is None or latest.id != master.id:
        raise SocialKitContractError("source_master is stale; SocialKit creation requires the current Master.")
    return master


def _master_inputs(
    db: Session,
    master: CommerceCreativeMasterVersion,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    brief = db.query(ProductCreativeBriefVersion).filter_by(
        id=master.creative_brief_version_id,
        project_id=master.project_id,
    ).one_or_none()
    if brief is None or (brief.version, brief.output_hash) != (master.creative_brief_version, master.creative_brief_hash):
        raise SocialKitContractError("source_master Creative Brief reference is stale or tampered.")
    rights_assets = _reference_list(brief.usable_asset_refs_json, "master.rights_asset_refs")
    if not rights_assets:
        raise SocialKitContractError("SocialKit requires at least one rights-confirmed Master asset.")
    fact_snapshot_ref = _reference(master.approved_fact_snapshot_ref_json, "master.approved_fact_snapshot")
    snapshot = db.query(FactSnapshot).filter_by(
        id=fact_snapshot_ref["id"],
        project_id=master.project_id,
    ).one_or_none()
    if snapshot is None or snapshot.snapshot_hash != fact_snapshot_ref["hash"]:
        raise SocialKitContractError("source_master approved fact snapshot is stale or tampered.")
    approved_fact_refs = []
    for item in snapshot.facts_json or []:
        if not isinstance(item, Mapping) or not (item.get("fact_id") or item.get("id")):
            raise SocialKitContractError("source_master approved fact snapshot contains an invalid fact identity.")
        fact_id = str(item.get("fact_id") or item["id"])
        approved_fact_refs.append({
            "id": fact_id,
            "version": 1,
            "hash": canonical_hash({
                "schema_version": "lg15-approved-fact-ref-v1",
                "snapshot": fact_snapshot_ref,
                "fact_id": fact_id,
            }),
            "schema_version": "lg15-approved-fact-ref-v1",
            "artifact_key": "approved_fact",
        })
    approved_fact_refs = _reference_list(approved_fact_refs, "master.approved_fact_refs")
    provenance_refs = _reference_list(master.evidence_artifact_refs_json, "master.provenance_refs")
    if not approved_fact_refs or not provenance_refs:
        raise SocialKitContractError("SocialKit requires approved facts and provenance references.")
    return (
        fact_snapshot_ref,
        _reference_for(brief, hash_field="output_hash"),
        {"id": str(master.brand_kit_version_id), "version": int(master.brand_kit_version), "hash": str(master.brand_kit_hash)},
        rights_assets,
        approved_fact_refs,
        provenance_refs,
    )


def validate_social_kit_version(db: Session, row: SocialKitVersion, *, require_current_master: bool = True) -> None:
    if row.schema_version != SOCIAL_KIT_SCHEMA_VERSION or not isinstance(row.version, int) or row.version < 1:
        raise SocialKitContractError("SocialKitVersion schema or version is invalid.")
    master = _current_master(
        db,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        master_id=row.source_master_id,
    ) if require_current_master else db.query(CommerceCreativeMasterVersion).filter_by(
        id=row.source_master_id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
    ).one_or_none()
    if master is None:
        raise SocialKitContractError("SocialKit source Master is missing.")
    validate_immutable_version(db, master)
    if _reference_for(master) != {
        "id": row.source_master_id,
        "version": row.source_master_version,
        "hash": row.source_master_hash,
    }:
        raise SocialKitContractError("SocialKit source Master identity is stale or tampered.")
    fact_ref, brief_ref, brand_ref, rights_assets, approved_facts, provenance_refs = _master_inputs(db, master)
    if _reference(row.approved_fact_snapshot_ref_json, "social_kit.approved_fact_snapshot") != fact_ref:
        raise SocialKitContractError("SocialKit approved fact snapshot does not match its Master.")
    if _reference(row.creative_brief_ref_json, "social_kit.creative_brief") != brief_ref:
        raise SocialKitContractError("SocialKit Creative Brief does not match its Master.")
    if _reference(row.brand_kit_ref_json, "social_kit.brand_kit") != brand_ref:
        raise SocialKitContractError("SocialKit Brand Kit does not match its Master.")
    if _reference_list(row.rights_asset_refs_json, "social_kit.rights_asset_refs") != rights_assets:
        raise SocialKitContractError("SocialKit rights assets do not match its Master.")
    channel = _key(row.target_channel, "target_channel")
    format = _key(row.target_format, "target_format")
    if not _social_channel_authorized(master, channel, format):
        raise SocialKitContractError("SocialKit target channel is not authorized by its Master.")
    _reference(row.channel_contract_ref_json, "social_kit.channel_contract")
    _key(row.template_version, "template_version")
    _key(row.evaluator_version, "evaluator_version")
    if row.execution_mode != DETERMINISTIC_FAKE_EXECUTION_MODE:
        raise SocialKitContractError("A1 supports deterministic fake execution only.")
    cards = _card_manifest(
        row.card_manifest_json,
        channel=channel,
        format=format,
        rights_asset_refs=rights_assets,
        approved_fact_refs=approved_facts,
        provenance_refs=provenance_refs,
        brand_kit_ref=brand_ref,
    )
    if channel == "instagram" and format == "feed_portrait":
        expected_profile_ref = social_publishing_profile_ref(deterministic_social_render_profile(row))
        if cards.get("publishing_profile_ref") != expected_profile_ref:
            raise SocialKitContractError("Instagram SocialKit publishing profile is missing or stale.")
    if canonical_hash(cards) != row.output_hash:
        raise SocialKitContractError("SocialKit output hash does not match its frozen cards.")
    for card in list(cards.get("cards") or []):
        _validate_copy_artifact(db, row, card)
    if row.parent_version_id:
        parent = db.query(SocialKitVersion).filter_by(
            id=row.parent_version_id,
            workspace_id=row.workspace_id,
            project_id=row.project_id,
        ).one_or_none()
        if parent is None or _reference_for(parent) != {
            "id": row.parent_version_id,
            "version": row.parent_version,
            "hash": row.parent_version_hash,
        }:
            raise SocialKitContractError("SocialKit parent identity is stale or tampered.")
        if (
            parent.source_master_id != row.source_master_id
            or parent.target_channel != row.target_channel
            or parent.target_format != row.target_format
            or parent.version >= row.version
        ):
            raise SocialKitContractError("SocialKit successor cannot change its lineage identity.")
    elif row.parent_version is not None or row.parent_version_hash is not None:
        raise SocialKitContractError("Initial SocialKitVersion cannot contain partial parent identity.")
    payload = _payload(row)
    if _idempotency_key(payload) != row.idempotency_key:
        raise SocialKitContractError("SocialKit idempotency key does not match its semantic request.")
    if _canonical_hash(payload) != row.canonical_hash:
        raise SocialKitContractError("SocialKit canonical hash does not match its persisted content.")


def create_social_kit_version(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    creator_run_id: str,
    created_by: str,
    source_master_reference: Mapping[str, Any],
    target_channel: str,
    target_format: str,
    channel_contract_reference: Mapping[str, Any],
    card_manifest: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    template_version: str,
    evaluator_version: str,
    parent_version_id: str | None = None,
    execution_mode: str = DETERMINISTIC_FAKE_EXECUTION_MODE,
) -> SocialKitVersion:
    run = db.query(AgentRun).filter_by(
        id=creator_run_id,
        workspace_id=workspace_id,
        project_id=project_id,
    ).one_or_none()
    if run is None or str(run.created_by) != str(created_by):
        raise SocialKitContractError("creator_run_id must belong to the same actor, workspace, and project.")
    supplied_master = _reference(source_master_reference, "source_master")
    master = _current_master(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        master_id=supplied_master["id"],
        lock=True,
    )
    if supplied_master != _reference_for(master):
        raise SocialKitContractError("source_master ID/version/hash does not match the current Master.")
    channel = _key(target_channel, "target_channel")
    format = _key(target_format, "target_format")
    if not _social_channel_authorized(master, channel, format):
        raise SocialKitContractError("target_channel must be authorized by the current Master.")
    if execution_mode != DETERMINISTIC_FAKE_EXECUTION_MODE:
        raise SocialKitContractError("A1 supports deterministic fake execution only.")
    template = _key(template_version, "template_version")
    evaluator = _key(evaluator_version, "evaluator_version")
    channel_contract = _reference(channel_contract_reference, "channel_contract")
    expected_channel_contract = deterministic_social_channel_contract_reference(channel=channel, format=format)
    if channel_contract != expected_channel_contract:
        raise SocialKitContractError("channel_contract does not match the canonical channel/format identity.")
    fact_ref, brief_ref, brand_ref, rights_assets, approved_facts, provenance_refs = _master_inputs(db, master)
    cards = _card_manifest(
        card_manifest,
        channel=channel,
        format=format,
        rights_asset_refs=rights_assets,
        approved_fact_refs=approved_facts,
        provenance_refs=provenance_refs,
        brand_kit_ref=brand_ref,
    )

    parent = None
    parent_ref = None
    if parent_version_id:
        parent = db.query(SocialKitVersion).filter_by(
            id=parent_version_id,
            workspace_id=workspace_id,
            project_id=project_id,
            source_master_id=master.id,
            target_channel=channel,
            target_format=format,
        ).with_for_update().one_or_none()
        if parent is None:
            raise SocialKitContractError("SocialKit parent must belong to the same Master, channel, and format.")
        validate_social_kit_version(db, parent)
        parent_ref = _reference_for(parent)

    next_version = int(
        db.query(SocialKitVersion.version)
        .filter_by(project_id=project_id)
        .order_by(SocialKitVersion.version.desc())
        .limit(1)
        .scalar() or 0
    ) + 1
    row = SocialKitVersion(
        id=generate_uuid(),
        workspace_id=workspace_id,
        project_id=project_id,
        creator_run_id=creator_run_id,
        created_by=created_by,
        version=next_version,
        schema_version=SOCIAL_KIT_SCHEMA_VERSION,
        parent_version_id=parent_ref["id"] if parent_ref else None,
        parent_version=parent_ref["version"] if parent_ref else None,
        parent_version_hash=parent_ref["hash"] if parent_ref else None,
        source_master_id=master.id,
        source_master_version=master.version,
        source_master_hash=master.canonical_hash,
        approved_fact_snapshot_ref_json=fact_ref,
        creative_brief_ref_json=brief_ref,
        brand_kit_ref_json=brand_ref,
        rights_asset_refs_json=rights_assets,
        target_channel=channel,
        target_format=format,
        channel_contract_ref_json=channel_contract,
        execution_mode=execution_mode,
        template_version=template,
        evaluator_version=evaluator,
        card_manifest_json=cards,
        output_hash=canonical_hash(cards),
        idempotency_key="",
        canonical_hash="",
    )
    payload = _payload(row)
    row.idempotency_key = _idempotency_key(payload)
    existing = db.query(SocialKitVersion).filter_by(
        project_id=project_id,
        idempotency_key=row.idempotency_key,
    ).one_or_none()
    if existing is not None:
        validate_social_kit_version(db, existing)
        return existing

    latest = (
        db.query(SocialKitVersion)
        .filter_by(
            project_id=project_id,
            source_master_id=master.id,
            target_channel=channel,
            target_format=format,
        )
        .order_by(SocialKitVersion.version.desc())
        .first()
    )
    if latest is not None and (parent is None or latest.id != parent.id):
        raise SocialKitContractError("A SocialKit successor must pin the current kit version.")
    row.canonical_hash = _canonical_hash(_payload(row))
    db.add(row)
    db.flush()
    _materialize_initial_copy_artifacts(
        db, kit=row, master=master, cards=list(cards.get("cards") or []), author_id=created_by,
    )
    db.flush()
    validate_social_kit_version(db, row)
    return row


def plan_social_kit_version(
    db: Session,
    *,
    run: AgentRun,
    request: Mapping[str, Any],
) -> SocialKitVersion:
    """Run the deterministic A2 planner and persist one immutable kit."""

    normalized = validate_social_kit_request(request)
    master = resolve_current_social_master(
        db,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        source_master_reference=normalized["source_master_reference"],
    )
    cards = deterministic_fake_social_cards(
        db,
        master=master,
        channel=normalized["target_channel"],
        format=normalized["target_format"],
        logical_targets=normalized["logical_targets"],
        template_version=normalized["template_version"],
        evaluator_version=normalized["evaluator_version"],
    )
    return create_social_kit_version(
        db,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        source_master_reference=normalized["source_master_reference"],
        target_channel=normalized["target_channel"],
        target_format=normalized["target_format"],
        channel_contract_reference=normalized["channel_contract_reference"],
        card_manifest=cards,
        template_version=normalized["template_version"],
        evaluator_version=normalized["evaluator_version"],
        parent_version_id=normalized["parent_version_id"],
        execution_mode=normalized["execution_mode"],
    )


_SOCIAL_CARD_ACTION_KEYS = frozenset({
    "action", "parent_social_kit_ref", "card_id", "ordered_card_ids", "variant_key", "variant_ref", "copy_reference", "proposed_text",
})


def validate_social_card_action(request: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a bounded seller card action without accepting freeform content."""

    if not isinstance(request, Mapping) or set(request) - _SOCIAL_CARD_ACTION_KEYS:
        raise SocialKitContractError("Social card action contains unsupported fields.")
    action = _key(request.get("action"), "action")
    if action not in SOCIAL_CARD_ACTIONS:
        raise SocialKitContractError("Unsupported Social card action.")
    parent_ref = _reference(request.get("parent_social_kit_ref"), "parent_social_kit_ref")
    card_id = request.get("card_id")
    if card_id is not None:
        card_id = _key(card_id, "card_id")
    ordered = request.get("ordered_card_ids", ())
    if not isinstance(ordered, (list, tuple)) or any(not isinstance(value, str) for value in ordered):
        raise SocialKitContractError("ordered_card_ids must be a bounded list.")
    ordered = [_key(value, "ordered_card_id") for value in ordered]
    variant_key = request.get("variant_key")
    if variant_key is not None:
        variant_key = _key(variant_key, "variant_key")
    variant_ref = request.get("variant_ref")
    if variant_ref is not None:
        variant_ref = _reference(variant_ref, "variant_ref")
    copy_reference = request.get("copy_reference")
    if copy_reference is not None:
        copy_reference = _reference(copy_reference, "copy_reference")
    proposed_text = request.get("proposed_text")
    if proposed_text is not None:
        if not isinstance(proposed_text, str):
            raise SocialKitContractError("proposed_text must be text.")
        proposed_text = " ".join(proposed_text.split())
        if not proposed_text or len(proposed_text) > 2000:
            raise SocialKitContractError("proposed_text must contain 1-2000 characters.")
    return {
        "action": action,
        "parent_social_kit_ref": parent_ref,
        "card_id": card_id,
        "ordered_card_ids": ordered,
        "variant_key": variant_key or "alternative-1",
        "variant_ref": variant_ref,
        "copy_reference": copy_reference,
        "proposed_text": proposed_text,
    }


def social_card_action_idempotency_key(action: Mapping[str, Any]) -> str:
    normalized = validate_social_card_action(action)
    return canonical_hash({
        "parent_social_kit_ref": normalized["parent_social_kit_ref"],
        "action": normalized["action"],
        "card_id": normalized["card_id"],
        "ordered_card_ids": normalized["ordered_card_ids"],
        "variant_key": normalized["variant_key"],
        "variant_ref": normalized["variant_ref"],
        "copy_reference": normalized["copy_reference"],
        "proposed_text": normalized["proposed_text"],
    })


def apply_social_card_action(
    db: Session,
    *,
    run: AgentRun,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Create one immutable SocialKit successor and enqueue only targeted work."""

    normalized = validate_social_card_action(request)
    if not run or not run.id or run.workspace_id is None or run.project_id is None:
        raise SocialKitContractError("A Social card action requires a scoped AgentRun.")
    action_key = social_card_action_idempotency_key(normalized)
    from src.services.langgraph_run_service import AgentRunEventJournal

    replay = db.query(AgentRunEvent).filter_by(
        run_id=run.id, event_type="social_card_action_submitted",
    ).all()
    for event in replay:
        event_action = dict((event.payload_json or {}).get("action") or {})
        if event_action.get("action_idempotency_key") == action_key:
            successor_ref = event_action.get("successor_social_kit_ref")
            successor = db.query(SocialKitVersion).filter_by(
                id=successor_ref.get("id") if isinstance(successor_ref, Mapping) else None,
                workspace_id=run.workspace_id, project_id=run.project_id,
            ).one_or_none()
            if successor is not None:
                return {
                    "action": normalized["action"],
                    "action_idempotency_key": action_key,
                    "parent_social_kit_ref": normalized["parent_social_kit_ref"],
                    "successor": successor,
                    "generation": None,
                    "replayed": True,
                }

    parent_ref = normalized["parent_social_kit_ref"]
    parent = db.query(SocialKitVersion).filter_by(
        id=parent_ref["id"], workspace_id=run.workspace_id, project_id=run.project_id,
    ).with_for_update().one_or_none()
    if parent is None or _reference_for(parent) != parent_ref:
        raise SocialKitContractError("SocialKit parent identity is stale or out of scope.")
    validate_social_kit_version(db, parent)
    cards = list((parent.card_manifest_json or {}).get("cards") or [])
    by_id = {str(card.get("card_id")): card for card in cards}
    action = normalized["action"]
    target_id = normalized["card_id"]
    if action == "reorder":
        successor_manifest = evolve_social_card_manifest(
            parent.card_manifest_json, intent="reorder", ordered_card_ids=normalized["ordered_card_ids"],
        )
    elif action == "delete":
        successor_manifest = evolve_social_card_manifest(parent.card_manifest_json, intent="delete", card_id=target_id)
    elif action == "regenerate":
        successor_manifest = evolve_social_card_manifest(
            parent.card_manifest_json, intent="regenerate", card_id=target_id, variant_key=normalized["variant_key"],
        )
    elif action == "request_alternative":
        successor_manifest = evolve_social_card_manifest(
            parent.card_manifest_json, intent="request_alternative", card_id=target_id, variant_key=normalized["variant_key"],
        )
    elif action == "select_alternative":
        if target_id not in by_id:
            raise SocialKitContractError("Selected alternative target card is missing.")
        candidates = [dict(value) for value in list(by_id[target_id].get("variant_refs") or [])]
        selected = normalized["variant_ref"]
        if selected is None:
            selected = _variant_reference(card_id=target_id, intent="alternative", variant_key=normalized["variant_key"])
        else:
            selected = next((candidate for candidate in candidates if all(
                selected.get(key) == candidate.get(key) for key in ("id", "version", "hash")
            )), None)
        if selected is None or selected not in candidates:
            raise SocialKitContractError("Selected alternative is not an existing candidate.")
        successor_manifest = deepcopy(parent.card_manifest_json)
        successor_manifest["cards"] = [
            _rehash_card({**card, "selected_variant_ref": selected}) if card.get("card_id") == target_id else dict(card)
            for card in cards
        ]
    else:  # edit_copy
        copy_ref = normalized["copy_reference"]
        proposed_text = normalized["proposed_text"]
        master = db.query(CommerceCreativeMasterVersion).filter_by(
            id=parent.source_master_id, workspace_id=run.workspace_id, project_id=run.project_id,
        ).one_or_none()
        if master is None or copy_ref is None or proposed_text is None or target_id not in by_id:
            raise SocialKitContractError("edit_copy requires the current copy reference, card, and proposed text.")
        current_copy = _validate_copy_artifact(db, parent, by_id[target_id])
        if copy_ref != _reference(by_id[target_id].get("copy_ref"), "card.copy_ref"):
            raise SocialKitContractError("Copy edit is stale; reload the current card before editing.")
        validation_status, validation_result = _validate_copy_edit(db, master, proposed_text)
        if validation_status != "PASS":
            raise SocialKitContractError("COPY_EDIT_REVIEW_REQUIRED")
        next_copy_version = int(db.query(SocialCardCopyVersion.version).filter_by(
            project_id=run.project_id, card_id=target_id,
        ).order_by(SocialCardCopyVersion.version.desc()).limit(1).scalar() or current_copy.version) + 1
        new_copy_hash = _copy_hash(_reference_for(master), target_id, proposed_text, copy_ref)
        new_copy_identity = _copy_identity_hash(_reference_for(master), target_id, proposed_text, copy_ref)
        copy_idempotency = canonical_hash({
            "parent_copy_ref": copy_ref,
            "proposed_text": proposed_text,
            "card_id": target_id,
            "social_kit": _reference_for(parent),
        })
        edited_copy = db.query(SocialCardCopyVersion).filter_by(
            project_id=run.project_id, idempotency_key=copy_idempotency,
        ).one_or_none()
        if edited_copy is None:
            edited_copy = SocialCardCopyVersion(
                id=_copy_reference(new_copy_hash, version=next_copy_version, identity_hash=new_copy_identity)["id"],
                workspace_id=run.workspace_id, project_id=run.project_id,
                source_social_kit_id=parent.id, source_social_kit_version=parent.version,
                card_id=target_id, source_master_id=master.id, source_master_version=master.version,
                version=next_copy_version, parent_version_id=current_copy.id,
                parent_version=current_copy.version, parent_version_hash=current_copy.canonical_hash,
                body_text=proposed_text, body_hash=new_copy_hash,
                validation_status=validation_status, validation_result_json=validation_result,
                author_id=str(run.created_by), idempotency_key=copy_idempotency, canonical_hash="",
            )
            edited_copy.canonical_hash = _copy_canonical_hash(edited_copy)
            db.add(edited_copy)
            db.flush()
        copy_ref = _copy_reference(edited_copy.body_hash, version=edited_copy.version, identity_hash=new_copy_identity if edited_copy.idempotency_key == copy_idempotency else None)
        if target_id not in by_id:
            raise SocialKitContractError("Copy edit target card is missing.")
        successor_manifest = deepcopy(parent.card_manifest_json)
        successor_manifest["cards"] = [
            _rehash_card({**card, "copy_ref": copy_ref}) if card.get("card_id") == target_id else dict(card)
            for card in cards
        ]

    # A prior crash may have committed the exact successor before its journal
    # event. Reuse it instead of creating another immutable version.
    existing_successor = next((row for row in db.query(SocialKitVersion).filter_by(
        parent_version_id=parent.id, workspace_id=run.workspace_id, project_id=run.project_id,
    ).all() if row.card_manifest_json == successor_manifest), None)
    if existing_successor is not None:
        return {
            "action": action, "action_idempotency_key": action_key,
            "parent_social_kit_ref": parent_ref, "successor": existing_successor,
            "generation": None, "replayed": True,
        }
    latest = db.query(SocialKitVersion).filter_by(
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        source_master_id=parent.source_master_id,
        target_channel=parent.target_channel,
        target_format=parent.target_format,
    ).order_by(SocialKitVersion.version.desc()).first()
    if latest is None or latest.id != parent.id:
        raise SocialKitContractError("SocialKit parent version is stale; reload before editing.")

    successor = create_social_kit_version(
        db,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        source_master_reference=_reference_for(db.get(CommerceCreativeMasterVersion, parent.source_master_id)),
        target_channel=parent.target_channel,
        target_format=parent.target_format,
        channel_contract_reference=parent.channel_contract_ref_json,
        card_manifest=successor_manifest,
        template_version=parent.template_version,
        evaluator_version=parent.evaluator_version,
        parent_version_id=parent.id,
        execution_mode=parent.execution_mode,
    )
    quality = evaluate_social_card_quality(db, successor)
    if quality.get("verdict") != "PASS":
        raise SocialKitContractError("SocialKit successor content quality must pass before action completion.")
    generation = None
    variant_override = None
    if action in {"regenerate", "request_alternative", "edit_copy"}:
        target_card = next(card for card in successor_manifest["cards"] if card.get("card_id") == target_id)
        variant_override = {target_id: dict(target_card.get("selected_variant_ref") or {})}
        if action == "request_alternative":
            variant_override[target_id] = _variant_reference(
                card_id=target_id, intent="alternative", variant_key=normalized["variant_key"],
            )
        from src.services.langgraph_image_generation_service import prepare_social_card_generation_jobs
        generation = prepare_social_card_generation_jobs(
            run_id=run.id,
            project_id=run.project_id,
            kit_id=successor.id,
            render_profile=deterministic_social_render_profile(successor),
            card_ids=[target_id],
            variant_ref_overrides=variant_override,
            db=db,
            commit=False,
        )
    card_ref = None
    if target_id:
        card_ref = {"id": target_id, "version": 1, "hash": canonical_hash({"card_id": target_id})}
    variant_ref_value = variant_override.get(target_id) if variant_override else normalized.get("variant_ref")
    variant_ref = (
        {key: variant_ref_value[key] for key in ("id", "version", "hash")}
        if variant_ref_value is not None else None
    )
    action_record = {
        "action": action,
        "action_idempotency_key": action_key,
        "card_ref": card_ref,
        "variant_ref": variant_ref,
        "copy_ref": (
            {key: value for key, value in dict(next((card for card in successor_manifest["cards"] if card.get("card_id") == target_id), {}).get("copy_ref") or {}).items() if key in {"id", "version", "hash"}}
            if target_id and next((card for card in successor_manifest["cards"] if card.get("card_id") == target_id), {}).get("copy_ref") else None
        ),
        "preserved_card_count": len(successor_manifest["cards"]),
    }
    master_ref = _reference_for(db.get(CommerceCreativeMasterVersion, parent.source_master_id))
    AgentRunEventJournal.append_social_action_lifecycle(
        run, db, event_type="social_card_action_submitted", action=action_record,
        master_ref=master_ref, parent_social_kit_ref=parent_ref,
        successor_social_kit_ref=_reference_for(successor),
    )
    AgentRunEventJournal.append_social_action_lifecycle(
        run, db, event_type="social_kit_version_forked", action=action_record,
        master_ref=master_ref, parent_social_kit_ref=parent_ref,
        successor_social_kit_ref=_reference_for(successor),
    )
    db.commit()
    db.refresh(successor)
    return {
        "action": action,
        "action_idempotency_key": action_key,
        "parent_social_kit_ref": parent_ref,
        "successor": successor,
        "quality": quality,
        "generation": generation,
        "replayed": False,
    }


def public_social_kit_projection(db: Session, kit: SocialKitVersion, run: AgentRun | None = None) -> dict[str, Any]:
    """Return the bounded seller projection for one frozen SocialKitVersion."""

    validate_social_kit_version(db, kit)
    social = dict((run.outputs_json or {}).get("langgraph_social") or {}) if run is not None else {}
    render = dict(social.get("render") or {})
    rendered = {
        str(card.get("card_id")): dict(card)
        for card in list(render.get("cards") or [])
        if isinstance(card, Mapping) and card.get("card_id")
    }
    render_profile = dict(render.get("render_profile") or {})
    render_profile_hash = str(render_profile.get("canonical_hash") or "")
    render_kit_id = str((render.get("social_kit_ref") or {}).get("id") or "")
    render_kit = db.query(SocialKitVersion).filter_by(
        id=render_kit_id, workspace_id=kit.workspace_id, project_id=kit.project_id,
    ).one_or_none() if render_kit_id else None
    render_cards = {
        str(card.get("card_id")): dict(card)
        for card in list((render_kit.card_manifest_json or {}).get("cards") or [])
        if isinstance(card, Mapping) and card.get("card_id")
    } if render_kit is not None else {}

    def rendered_asset(card: Mapping[str, Any]) -> dict[str, Any] | None:
        output = rendered.get(str(card.get("card_id") or ""))
        if not output or not isinstance(output.get("asset_ref"), Mapping):
            return None
        source_card = render_cards.get(str(card.get("card_id") or ""))
        if source_card is None or not render_profile_hash:
            return None
        render_identity = {
            "social_kit": _reference_for(render_kit),
            "card_id": str(source_card["card_id"]),
            "selected_variant_ref": dict(source_card.get("selected_variant_ref") or {}),
            "copy_ref": dict(source_card.get("copy_ref") or {}),
            "render_profile_hash": render_profile_hash,
            "layout_template": str(render_kit.template_version),
        }
        expected_hashes = {canonical_hash(render_identity)}
        # Graph-generated assets include the existing image-generation contract
        # in their semantic identity; deterministic direct renders do not.
        from src.services.langgraph_image_generation_service import SOCIAL_GENERATION_CONTRACT_VERSION
        expected_hashes.add(canonical_hash({
            **{key: render_identity[key] for key in (
                "social_kit", "card_id", "selected_variant_ref", "copy_ref", "render_profile_hash",
            )},
            "generation_contract_version": SOCIAL_GENERATION_CONTRACT_VERSION,
        }))
        if str(output.get("semantic_hash") or "") not in expected_hashes:
            return None
        if render_kit.id != kit.id and dict(card.get("selected_variant_ref") or {}) != dict(source_card.get("selected_variant_ref") or {}):
            return None
        return _reference(output["asset_ref"], "render.asset_ref")

    manifest = dict(kit.card_manifest_json or {})
    cards: list[dict[str, Any]] = []
    for raw in sorted(list(manifest.get("cards") or []), key=lambda item: int(item.get("order") or 0)):
        card = dict(raw or {})
        card_id = str(card.get("card_id") or "")
        if not card_id:
            continue
        safe: dict[str, Any] = {
            "card_id": card_id,
            "role": str(card.get("role") or "social_card"),
            "order": int(card.get("order") or 0),
            "status": str(card.get("status") or "planned"),
            "selected_variant_ref": dict(card.get("selected_variant_ref") or {}),
            "copy_ref": dict(card.get("copy_ref") or {}),
            "actions": ["edit_copy", "regenerate", "request_alternative", "select_alternative"],
        }
        if card.get("role") in {"feature", "usage"}:
            safe["actions"].append("delete")
        if card.get("variant_refs"):
            safe["variant_refs"] = [
                {key: value for key, value in dict(ref).items() if key in {"id", "version", "hash", "schema_version", "artifact_key", "variant_key"}}
                for ref in list(card.get("variant_refs") or [])[:10]
                if isinstance(ref, Mapping)
            ]
        copy = _validate_copy_artifact(db, kit, card)
        safe["copy_text"] = str(copy.body_text)
        safe["copy_validation"] = str(copy.validation_status)
        asset_ref = rendered_asset(card)
        if asset_ref is not None:
            safe["preview_asset_ref"] = asset_ref
            safe["preview_url"] = f"/api/v1/files/assets/{asset_ref['id']}?expected_content_hash={asset_ref['hash']}"
            safe["status"] = "rendered"
        cards.append(safe)
    status = "rendered" if cards and all(item.get("status") == "rendered" for item in cards) else "planned"
    quality_snapshot = evaluate_social_card_quality(db, kit)
    quality = {
        "verdict": str(quality_snapshot.get("verdict") or "NEEDS_REVIEW"),
        "review_required": str(quality_snapshot.get("verdict") or "") != "PASS",
    }
    result = {
        "id": str(kit.id),
        "version": int(kit.version),
        "status": status,
        "target_channel": str(kit.target_channel),
        "target_format": str(kit.target_format),
        "execution_mode": str(kit.execution_mode),
        "cards": cards,
        "card_count": len(cards),
        "quality": quality,
        "actions": ["edit_copy", "reorder", "regenerate", "request_alternative", "select_alternative", "export"],
    }
    if kit.target_channel == "instagram" and kit.target_format == "feed_portrait":
        platform_quality = evaluate_social_platform_quality(db, kit, render)
        result["publishing_profile"] = {
            "platform": "instagram",
            "format": "feed_portrait",
            "width": 1080,
            "height": 1350,
            "aspect_ratio": "4:5",
            "safe_area_policy": "none_v1",
            "copy_policy": "existing_content_quality",
            "exports": ["png", "jpg", "zip"],
            "readiness": "ready" if platform_quality["verdict"] == "PASS" else "review_required",
        }
        result["platform_quality"] = {
            "verdict": platform_quality["verdict"],
            "card_count": platform_quality["card_count"],
            "reasons": platform_quality["reasons"],
        }
    return result
