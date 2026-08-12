import datetime
import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    Asset,
    BrandKitVersion,
    DetailPageVersion,
    ImageGenerationJobRecord,
    ProductCreativeBriefVersion,
    ProductFact,
    ProductPage,
    ProductProject,
)
from src.services.channel_export_service import image_sha256
from src.services.commerce_policy import REFERENCE_SOURCE_TYPES, is_asset_final_output_eligible
from src.services.commerce_renderer_service import build_commerce_artifact
from src.services.page_asset_policy import ORIGINAL_IMAGE_SOURCE_TYPES, get_page_eligible_assets
from src.services.page_visual_contract import (
    normalize_lg10_design_direction,
    select_lg10_page_assembly_component,
)
from src.services.renderer import render_lg10_canonical_page_html


class PageDraftNotFoundError(ValueError):
    pass


class FinalPageNotFoundError(ValueError):
    pass


class PageAssemblyInputError(ValueError):
    """The immutable LG-10 assembly input cannot be established safely."""


LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION = "lg10-canonical-page-assembly-input-v1"
LG10_PAGE_ASSEMBLY_SCHEMA_VERSION = "lg10-page-assembly-v1"
LG10_CANONICAL_RENDER_SCHEMA_VERSION = "lg10-canonical-render-v1"
LG10_DETAIL_PAGE_VERSION_SCHEMA_VERSION = "lg10-detail-page-version-v1"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_COMMERCE_ARTIFACT_KEY = "langgraph_commerce_planning_artifacts"
_COPY_FIELDS_BY_SECTION = {
    "hero": ("hero_title", "hero_subtitle"),
    "pain_point": ("painpoint_title", "painpoint_body"),
    "feature_1": ("feature_1_title", "feature_1_body"),
    "feature_2": ("feature_2_title", "feature_2_body"),
    "feature_3": ("feature_3_title", "feature_3_body"),
    "usage_guide": ("usage_title", "usage_body"),
    "details_components": ("details_title", "details_body"),
    "product_information": ("guarantee_title", "guarantee_body"),
}
_SAFE_BRAND_TOKENS = {
    "color_tokens": {
        "accent": "#0f766e",
        "text": "#172033",
        "surface": "#ffffff",
        "muted_surface": "#eef2f7",
    },
    "typography": {"body_font": "system-ui, sans-serif"},
    "asset_layer": {"logo": None, "watermark": None, "font_assets": []},
    "fallback": True,
}
_CSS_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_SAFE_FONT = re.compile(r"[A-Za-z0-9 ,.'\-]+")


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _artifact_reference(run: AgentRun, stage: str) -> tuple[dict[str, Any], dict[str, Any]]:
    artifacts = dict((run.outputs_json or {}).get(_COMMERCE_ARTIFACT_KEY) or {})
    artifact = dict(artifacts.get(stage) or {})
    output = dict(artifact.get("output") or {})
    metadata = dict(artifact.get("metadata") or {})
    artifact_hash = str(metadata.get("artifact_hash") or "")
    if not output or not _SHA256_HEX.fullmatch(artifact_hash):
        raise PageAssemblyInputError(f"LG-10 requires the immutable {stage} planning artifact.")
    return {
        "artifact_key": stage,
        "schema_version": str(artifact.get("schema_version") or ""),
        "artifact_hash": artifact_hash,
    }, output


def _manifest_entries(
    *,
    run: AgentRun,
    approved_asset_manifest: dict[str, Any],
    db: Session,
) -> list[dict[str, Any]]:
    manifest = deepcopy(approved_asset_manifest)
    manifest_hash = str(manifest.pop("manifest_hash", "") or "")
    if (
        manifest.get("run_id") != run.id
        or manifest.get("project_id") != run.project_id
        or not _SHA256_HEX.fullmatch(manifest_hash)
        or _canonical_hash(manifest) != manifest_hash
    ):
        raise PageAssemblyInputError("LG-10 requires an untampered approved asset manifest for this run.")

    required_jobs = _required_generation_jobs(run, db)
    if (
        not required_jobs
        or any(job.status != "approved" or not job.output_asset_id for job in required_jobs)
    ):
        raise PageAssemblyInputError("LG-10 cannot promote a partial or unapproved image review.")

    rows = list(manifest.get("assets") or [])
    asset_ids = [str(item.get("asset_id") or "") for item in rows]
    required_asset_ids = {str(job.output_asset_id) for job in required_jobs}
    if (
        not rows
        or not all(asset_ids)
        or len(set(asset_ids)) != len(asset_ids)
        or set(asset_ids) != required_asset_ids
    ):
        raise PageAssemblyInputError("LG-10 requires at least one uniquely identified approved asset.")

    assets = {
        asset.id: asset
        for asset in db.query(Asset).filter(Asset.project_id == run.project_id, Asset.id.in_(asset_ids)).all()
    }
    entries: list[dict[str, Any]] = []
    for item in rows:
        asset_id = str(item.get("asset_id") or "")
        asset_hash = str(item.get("asset_content_hash") or "")
        asset = assets.get(asset_id)
        if (
            asset is None
            or not is_asset_final_output_eligible(asset)
            or not _SHA256_HEX.fullmatch(asset_hash)
            or asset.content_hash != asset_hash
        ):
            raise PageAssemblyInputError("LG-10 approved asset identity is missing or no longer eligible.")
        entries.append({
            "scene_id": str(item.get("scene_id") or ""),
            "section_id": str(item.get("section_id") or ""),
            "asset_id": asset_id,
            "asset_content_hash": asset_hash,
            "job_id": str(item.get("job_id") or ""),
            "generation_attempt": int(item.get("generation_attempt") or 1),
        })
    return entries


def _required_generation_jobs(run: AgentRun, db: Session) -> list[ImageGenerationJobRecord]:
    jobs = [
        job
        for job in db.query(ImageGenerationJobRecord).filter(
            ImageGenerationJobRecord.project_id == run.project_id,
        ).all()
        if str((job.usage_metadata or {}).get("langgraph_run_id") or "") == run.id
    ]
    latest_by_scene: dict[str, ImageGenerationJobRecord] = {}
    for job in jobs:
        scene_key = str(job.scene_id or job.section_id)
        current = latest_by_scene.get(scene_key)
        if current is None or int(job.generation_attempt or 1) > int(current.generation_attempt or 1):
            latest_by_scene[scene_key] = job
    return [job for job in latest_by_scene.values() if job.required_for_completion]


def _lg10_design_direction_for_run(run: AgentRun, db: Session) -> str:
    snapshot = dict(run.input_snapshot or {})
    # The current planning screen already persists its selected storyboard
    # choice.  An explicit run input is supported only when it uses a fixed
    # LG-10 direction; no free-form design value enters the canonical input.
    requested = snapshot.get("design_direction")
    if requested is None:
        project = db.query(ProductProject).filter(ProductProject.id == run.project_id).one()
        requested = dict(project.planning_draft or {}).get("selected_candidate_key")
    return normalize_lg10_design_direction(requested)


def _safe_brand_tokens(*, fallback_reason: str) -> dict[str, Any]:
    return {**deepcopy(_SAFE_BRAND_TOKENS), "fallback_reason": fallback_reason}


def _safe_css_color(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate.lower() if _CSS_COLOR.fullmatch(candidate) else fallback


def _safe_font(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate and _SAFE_FONT.fullmatch(candidate) else "system-ui, sans-serif"


def _brand_asset_identity(asset: Asset) -> dict[str, str] | None:
    content_hash = str(asset.content_hash or "")
    if (
        (asset.usage_status or "").lower() not in {"seller_owned", "rights_confirmed"}
        or (asset.source_type or "").lower() in {*REFERENCE_SOURCE_TYPES, "supplier"}
        or not asset.mime_type.startswith("image/")
        or not _SHA256_HEX.fullmatch(content_hash)
    ):
        return None
    return {"asset_id": asset.id, "asset_content_hash": content_hash}


def resolve_lg10_brand_renderer_tokens(
    *,
    run: AgentRun,
    brand_kit_ref: dict[str, Any],
    db: Session,
) -> dict[str, Any]:
    """Resolve only rights-confirmed Brand Kit tokens for the frozen LG-10 run."""

    version_id = str(brand_kit_ref.get("brand_kit_version_id") or "")
    version_hash = str(brand_kit_ref.get("brand_kit_hash") or "")
    if not version_id or not _SHA256_HEX.fullmatch(version_hash):
        return _safe_brand_tokens(fallback_reason="brand_kit_unavailable")
    version = db.query(BrandKitVersion).filter(
        BrandKitVersion.id == version_id,
        BrandKitVersion.workspace_id == run.workspace_id,
    ).first()
    if version is None or version.content_hash != version_hash:
        return _safe_brand_tokens(fallback_reason="brand_kit_version_mismatch")

    requested_ids = list(dict.fromkeys([
        *(str(asset_id) for asset_id in (version.logo_asset_ids or []) if asset_id),
        *(str(asset_id) for asset_id in (version.font_asset_ids or []) if asset_id),
    ]))
    assets = {
        asset.id: asset
        for asset in db.query(Asset).join(ProductProject).filter(
            ProductProject.workspace_id == run.workspace_id,
            Asset.id.in_(requested_ids),
        ).all()
    } if requested_ids else {}
    logos = [
        identity for asset_id in (version.logo_asset_ids or [])
        if (asset := assets.get(str(asset_id))) and (identity := _brand_asset_identity(asset))
    ]
    # Font files are kept as immutable identities for later package resolution,
    # but are not URL-resolved or loaded by this task's HTML renderer.
    fonts = [
        {"asset_id": asset.id, "asset_content_hash": str(asset.content_hash)}
        for asset_id in (version.font_asset_ids or [])
        if (asset := assets.get(str(asset_id)))
        and (asset.usage_status or "").lower() in {"seller_owned", "rights_confirmed"}
        and _SHA256_HEX.fullmatch(str(asset.content_hash or ""))
    ]
    watermark_policy = dict(version.watermark_policy or {})
    watermark_enabled = bool(watermark_policy.get("enabled")) or watermark_policy.get("mode") == "logo_subtle"
    watermark = logos[0] if watermark_enabled and logos else None
    colors = dict(version.color_tokens or {})
    typography = dict(version.typography or {})
    return {
        "brand_kit_version_id": version.id,
        "brand_kit_hash": version.content_hash,
        "color_tokens": {
            "accent": _safe_css_color(colors.get("primary") or colors.get("accent"), "#0f766e"),
            "text": _safe_css_color(colors.get("text"), "#172033"),
            "surface": _safe_css_color(colors.get("surface") or colors.get("background"), "#ffffff"),
            "muted_surface": _safe_css_color(colors.get("secondary"), "#eef2f7"),
        },
        "typography": {"body_font": _safe_font(typography.get("body") or typography.get("font_family"))},
        "asset_layer": {"logo": logos[0] if logos else None, "watermark": watermark, "font_assets": fonts},
        "fallback": not bool(logos),
        "fallback_reason": "brand_asset_unavailable" if not logos else None,
    }


def _seller_owned_fallback_assets(run: AgentRun, db: Session) -> list[dict[str, str]]:
    """Return only stable, seller-owned originals; information-only is always safer than a weak fallback."""

    entries: list[dict[str, str]] = []
    for asset in get_page_eligible_assets(db, run.project_id):
        if (
            asset.source_type not in ORIGINAL_IMAGE_SOURCE_TYPES
            or asset.source_type == "sourced"
            or (asset.usage_status or "").lower() != "seller_owned"
            or not os.path.isfile(asset.file_path)
        ):
            continue
        content_hash = image_sha256(asset.file_path)
        if asset.content_hash != content_hash:
            asset.content_hash = content_hash
        if not _SHA256_HEX.fullmatch(content_hash):
            continue
        entries.append({"asset_id": asset.id, "asset_content_hash": content_hash})
    return sorted(entries, key=lambda item: (item["asset_content_hash"], item["asset_id"]))


def build_canonical_page_assembly_input(
    *,
    run: AgentRun,
    approved_asset_manifest: dict[str, Any] | None,
    db: Session,
) -> dict[str, Any]:
    """Build the narrow, immutable LG-10 input without starting Page Assembly.

    The next task chooses renderer components. This boundary only pins the
    previously approved planning/copy/asset identities and deliberately keeps
    image-free sections valid when no generated asset is necessary.
    """

    page_ref, page_plan = _artifact_reference(run, "page_planning")
    copy_ref, copy_set = _artifact_reference(run, "copywriting")
    _, visual_plan = _artifact_reference(run, "visual_planning")
    creative_snapshot = dict((run.input_snapshot or {}).get("creative_brief_snapshot") or {})
    brief = db.query(ProductCreativeBriefVersion).filter(
        ProductCreativeBriefVersion.id == creative_snapshot.get("id"),
        ProductCreativeBriefVersion.run_id == run.id,
        ProductCreativeBriefVersion.project_id == run.project_id,
    ).first()
    if brief is None or brief.output_hash != creative_snapshot.get("output_hash"):
        raise PageAssemblyInputError("LG-10 requires the pinned Creative Brief for this production run.")

    required_jobs = _required_generation_jobs(run, db)
    if approved_asset_manifest is None and required_jobs:
        if any(job.status != "approved" or not job.output_asset_id for job in required_jobs):
            raise PageAssemblyInputError("LG-10 cannot use fallback while a required image scene is incomplete.")
        raise PageAssemblyInputError("LG-10 requires the approved asset manifest for completed required image scenes.")

    approved_assets = (
        _manifest_entries(run=run, approved_asset_manifest=approved_asset_manifest, db=db)
        if approved_asset_manifest is not None
        else []
    )
    fallback_assets = _seller_owned_fallback_assets(run, db) if not approved_assets else []
    assets_by_section: dict[str, list[dict[str, Any]]] = {}
    for asset in approved_assets:
        assets_by_section.setdefault(asset["section_id"], []).append(asset)
    visual_scenes = {
        str(scene.get("id") or ""): dict(scene or {})
        for scene in (visual_plan.get("scene_plan") or [])
        if isinstance(scene, dict) and scene.get("id")
    }

    sections: list[dict[str, Any]] = []
    for index, raw_section in enumerate(page_plan.get("sections") or []):
        section = dict(raw_section or {})
        section_id = str(section.get("id") or "")
        if not section_id:
            raise PageAssemblyInputError("LG-10 page planning contains a section without a stable ID.")
        section_assets = sorted(
            assets_by_section.get(section_id, []),
            key=lambda item: (item["scene_id"], item["generation_attempt"], item["asset_id"]),
        )
        scene = visual_scenes.get(section_id, {})
        image_required = str(scene.get("generation_mode") or "") in {"ai_redesign", "safe_existing_photo"}
        # A section consumes one deterministic original so preview, image
        # export, and standalone HTML expose the same asset layer.
        fallback = fallback_assets[:1] if not approved_assets and image_required else []
        sections.append({
            "section_id": section_id,
            "sort_order": index,
            "copy_ref": {
                **copy_ref,
                "fields": list(_COPY_FIELDS_BY_SECTION.get(section_id, ())),
                "fact_ids": list((copy_set.get("section_fact_ids") or {}).get(section_id) or []),
            },
            # Actual renderer tokens are selected in TASK-10.2. This reference
            # pins the only current layout contract without inventing a new one.
            "layout_token_ref": {
                **page_ref,
                "field": "layout_concept",
                "layout_concept": str(page_plan.get("layout_concept") or ""),
            },
            "approved_assets": section_assets,
            "seller_owned_fallback_assets": fallback,
            "image_required": image_required,
            "rendering_mode": (
                "approved_asset" if section_assets else "seller_owned_fallback" if fallback
                else "image_required_missing" if image_required else "information_only"
            ),
        })

    if approved_assets and {
        asset["asset_id"]
        for section in sections
        for asset in section["approved_assets"]
    } != {asset["asset_id"] for asset in approved_assets}:
        raise PageAssemblyInputError("LG-10 approved assets must map to a stable planned section.")

    if approved_asset_manifest is not None:
        page_asset_manifest = deepcopy(approved_asset_manifest)
        completion_basis = "approved_required_scenes"
    else:
        fallback_by_id: dict[str, dict[str, str]] = {}
        for section in sections:
            for asset in section["seller_owned_fallback_assets"]:
                fallback_by_id[asset["asset_id"]] = {
                    **asset,
                    "source": "seller_owned_fallback",
                }
        fallback_entries = sorted(
            fallback_by_id.values(),
            key=lambda item: (item["asset_content_hash"], item["asset_id"]),
        )
        page_manifest_payload = {
            "run_id": run.id,
            "project_id": run.project_id,
            "source": "seller_owned_fallback" if fallback_entries else "information_only",
            "assets": fallback_entries,
        }
        page_asset_manifest = {
            **page_manifest_payload,
            "manifest_hash": _canonical_hash(page_manifest_payload),
        }
        completion_basis = "no_required_image_scenes"

    payload = {
        "schema_version": LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION,
        "run_id": run.id,
        "project_id": run.project_id,
        "design_direction": _lg10_design_direction_for_run(run, db),
        "planning_refs": {"page_plan": page_ref, "copy": copy_ref},
        "brand_kit_ref": {
            "brand_kit_version_id": brief.brand_kit_version_id,
            "brand_kit_hash": brief.brand_kit_hash,
        },
        "channel_override_ref": {
            "kind": "channel_prompt_pack_version",
            "channel_pack_version_id": brief.channel_pack_version_id,
            "compiled_prompt_artifact_id": brief.compiled_prompt_artifact_id,
        },
        "image_generation_contract": {
            "required_scene_count": len(required_jobs),
            "completion_basis": completion_basis,
        },
        "approved_asset_manifest": deepcopy(approved_asset_manifest) if approved_asset_manifest is not None else None,
        "page_asset_manifest": page_asset_manifest,
        "sections": sections,
    }
    return {**payload, "input_hash": _canonical_hash(payload)}


def build_page_assembly_structure(
    *,
    canonical_page_assembly_input: dict[str, Any],
) -> dict[str, Any]:
    """Choose only allowed LG-10 component and layout tokens from a frozen input.

    The function deliberately produces no HTML, CSS, copy, or image payload.
    Those remain referenced by the immutable canonical input until the
    deterministic renderer is introduced in a later task.
    """

    canonical_input = deepcopy(canonical_page_assembly_input)
    input_hash = str(canonical_input.pop("input_hash", "") or "")
    manifest = canonical_input.get("approved_asset_manifest")
    image_contract = canonical_input.get("image_generation_contract")
    if isinstance(image_contract, dict):
        required_scene_count = int(image_contract.get("required_scene_count") or 0)
        completion_basis = str(image_contract.get("completion_basis") or "")
    elif isinstance(manifest, dict):
        # Preserve the existing required-image canonical contract while the
        # explicit zero-image contract remains mandatory for fallback pages.
        required_scene_count = len(manifest.get("assets") or [])
        completion_basis = "approved_required_scenes"
    else:
        required_scene_count = -1
        completion_basis = ""
    page_manifest = canonical_input.get("page_asset_manifest") or manifest
    if (
        canonical_input.get("schema_version") != LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION
        or not _SHA256_HEX.fullmatch(input_hash)
        or _canonical_hash(canonical_input) != input_hash
    ):
        raise PageAssemblyInputError("LG-10 Page Assembly requires an immutable approved canonical input.")

    if not isinstance(page_manifest, dict):
        raise PageAssemblyInputError("LG-10 Page Assembly requires an immutable page asset manifest.")
    page_manifest_payload = deepcopy(page_manifest)
    page_manifest_hash = str(page_manifest_payload.pop("manifest_hash", "") or "")
    page_manifest_assets = list(page_manifest.get("assets") or [])
    if (
        not _SHA256_HEX.fullmatch(page_manifest_hash)
        or _canonical_hash(page_manifest_payload) != page_manifest_hash
        or not all(
        isinstance(asset, dict)
        and _SHA256_HEX.fullmatch(str(asset.get("asset_content_hash") or ""))
        and bool(asset.get("asset_id"))
        for asset in page_manifest_assets
        )
    ):
        raise PageAssemblyInputError("LG-10 Page Assembly requires stable page asset identities.")
    if required_scene_count > 0:
        if (
            completion_basis != "approved_required_scenes"
            or not isinstance(manifest, dict)
            or not list(manifest.get("assets") or [])
            or page_manifest != manifest
        ):
            raise PageAssemblyInputError("LG-10 Page Assembly requires approved assets for every required image scene.")
    elif (
        required_scene_count != 0
        or completion_basis != "no_required_image_scenes"
        or manifest is not None
    ):
        raise PageAssemblyInputError("LG-10 Page Assembly cannot treat incomplete required images as an image-free page.")

    sections: list[dict[str, Any]] = []
    selected_asset_identities: set[tuple[str, str]] = set()
    for expected_order, raw_section in enumerate(canonical_input.get("sections") or []):
        section = dict(raw_section or {})
        section_id = str(section.get("section_id") or "")
        rendering_mode = str(section.get("rendering_mode") or "")
        if not section_id or section.get("sort_order") != expected_order:
            raise PageAssemblyInputError("LG-10 Page Assembly requires stable canonical section ordering.")
        if bool(section.get("image_required")) and rendering_mode != "approved_asset":
            if rendering_mode != "seller_owned_fallback":
                raise PageAssemblyInputError("LG-10 Page Assembly cannot continue with an incomplete required image scene.")
        selected_assets = (
            list(section.get("approved_assets") or [])
            if rendering_mode == "approved_asset"
            else list(section.get("seller_owned_fallback_assets") or [])
            if rendering_mode == "seller_owned_fallback"
            else []
        )
        if not all(
            isinstance(asset, dict)
            and bool(asset.get("asset_id"))
            and _SHA256_HEX.fullmatch(str(asset.get("asset_content_hash") or ""))
            for asset in selected_assets
        ):
            raise PageAssemblyInputError("LG-10 Page Assembly received an invalid section asset identity.")
        selected_asset_identities.update(
            (str(asset["asset_id"]), str(asset["asset_content_hash"]))
            for asset in selected_assets
        )
        try:
            selected = select_lg10_page_assembly_component(
                rendering_mode=rendering_mode,
                design_direction=canonical_input.get("design_direction"),
            )
        except ValueError as error:
            raise PageAssemblyInputError(str(error)) from error
        sections.append({
            "section_id": section_id,
            "sort_order": expected_order,
            **selected,
            "selection_basis": rendering_mode,
        })

    page_asset_identities = {
        (str(asset["asset_id"]), str(asset["asset_content_hash"]))
        for asset in page_manifest_assets
    }
    if selected_asset_identities != page_asset_identities:
        raise PageAssemblyInputError("LG-10 Page Assembly section assets do not match the frozen page manifest.")

    payload = {
        "schema_version": LG10_PAGE_ASSEMBLY_SCHEMA_VERSION,
        "design_direction": normalize_lg10_design_direction(canonical_input.get("design_direction")),
        "canonical_input_ref": {
            "schema_version": LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION,
            "input_hash": input_hash,
        },
        "brand_kit_ref": deepcopy(dict(canonical_input.get("brand_kit_ref") or {})),
        "approved_asset_manifest_ref": (
            {"manifest_hash": str(manifest["manifest_hash"])} if isinstance(manifest, dict) else None
        ),
        "page_asset_manifest_ref": {"manifest_hash": page_manifest_hash},
        "sections": sections,
    }
    return {**payload, "assembly_hash": _canonical_hash(payload)}


def build_canonical_page_rendering_artifact(
    *,
    run: AgentRun,
    canonical_page_assembly_input: dict[str, Any],
    page_assembly: dict[str, Any],
    db: Session,
) -> dict[str, Any]:
    """Render the frozen LG-10 page contract without reading mutable page state."""

    expected_assembly = build_page_assembly_structure(
        canonical_page_assembly_input=canonical_page_assembly_input,
    )
    if page_assembly != expected_assembly:
        raise PageAssemblyInputError("LG-10 canonical renderer requires the matching immutable assembly state.")
    copy_ref, copy_set = _artifact_reference(run, "copywriting")
    canonical_refs = dict(canonical_page_assembly_input.get("planning_refs") or {})
    if canonical_refs.get("copy") != copy_ref:
        raise PageAssemblyInputError("LG-10 canonical renderer copy reference does not match the frozen input.")
    if dict(page_assembly.get("brand_kit_ref") or {}) != dict(canonical_page_assembly_input.get("brand_kit_ref") or {}):
        raise PageAssemblyInputError("LG-10 canonical renderer Brand Kit reference does not match the frozen input.")
    brand_tokens = resolve_lg10_brand_renderer_tokens(
        run=run,
        brand_kit_ref=dict(canonical_page_assembly_input.get("brand_kit_ref") or {}),
        db=db,
    )
    try:
        rendered = render_lg10_canonical_page_html(
            canonical_page_assembly_input=canonical_page_assembly_input,
            page_assembly=page_assembly,
            copy_set=copy_set,
            brand_tokens=brand_tokens,
        )
    except ValueError as error:
        raise PageAssemblyInputError(str(error)) from error
    payload = {
        **rendered,
        "canonical_input_ref": {
            "schema_version": LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION,
            "input_hash": str(canonical_page_assembly_input.get("input_hash") or ""),
        },
        "page_assembly_ref": {
            "schema_version": LG10_PAGE_ASSEMBLY_SCHEMA_VERSION,
            "assembly_hash": str(page_assembly.get("assembly_hash") or ""),
        },
    }
    if payload.get("schema_version") != LG10_CANONICAL_RENDER_SCHEMA_VERSION:
        raise PageAssemblyInputError("LG-10 canonical renderer returned an invalid artifact.")
    return {**payload, "render_hash": _canonical_hash(payload)}


def _lg10_preview_sections(rendering: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapt frozen renderer layers to the existing version preview contract."""

    sections: list[dict[str, Any]] = []
    for index, raw_section in enumerate(rendering.get("sections") or []):
        section = dict(raw_section or {})
        text_layer = list(section.get("text_layer") or [])
        asset_layer = list(section.get("asset_layer") or [])
        primary_asset = dict(asset_layer[0] or {}) if asset_layer else {}
        sections.append({
            "id": str(section.get("section_id") or ""),
            "key": str(section.get("section_id") or ""),
            "section_type": str(section.get("section_id") or ""),
            "title": str((text_layer[0] or {}).get("text") or "") if text_layer else "",
            "body": "\n".join(str(item.get("text") or "") for item in text_layer[1:]),
            "body_copy": "\n".join(str(item.get("text") or "") for item in text_layer[1:]),
            "image_asset_id": str(primary_asset.get("asset_id") or "") or None,
            "image_asset_content_hash": str(primary_asset.get("asset_content_hash") or "") or None,
            "visual_kind": "image" if asset_layer else None,
            "visual_payload": {"layout_token": str(section.get("layout_token") or "")},
            "sort_order": index,
            "is_visible": True,
        })
    return sections


def _lg10_preview_brand_assets(rendering: dict[str, Any]) -> dict[str, dict[str, str] | None]:
    """Keep only the renderer's frozen, hash-addressed Brand Kit identities."""

    asset_layer = dict((rendering.get("brand_tokens") or {}).get("asset_layer") or {})
    renderer_html = str(rendering.get("html") or "")
    assets: dict[str, dict[str, str] | None] = {"logo": None, "watermark": None}
    for role in assets:
        placement = "header" if role == "logo" else "watermark"
        identity = asset_layer.get(role)
        if identity is None:
            continue
        if (
            not isinstance(identity, dict)
            or not str(identity.get("asset_id") or "")
            or not _SHA256_HEX.fullmatch(str(identity.get("asset_content_hash") or ""))
        ):
            raise PageAssemblyInputError("LG-10 Brand Kit asset identity must be a stable SHA-256 reference.")
        if not re.search(
            rf'<(?:header|aside)\b(?=[^>]*data-brand-placement="{placement}")'
            rf'(?=[^>]*data-asset-id="{re.escape(str(identity["asset_id"]))}")'
            rf'(?=[^>]*data-asset-content-hash="{identity["asset_content_hash"]}")[^>]*>',
            renderer_html,
        ):
            raise PageAssemblyInputError("LG-10 Brand Kit asset must be placed by the canonical renderer.")
        assets[role] = {
            "asset_id": str(identity["asset_id"]),
            "asset_content_hash": str(identity["asset_content_hash"]),
        }
    return assets


def persist_lg10_detail_page_version(
    *,
    run: AgentRun,
    canonical_page_assembly_input: dict[str, Any],
    page_assembly: dict[str, Any],
    rendering: dict[str, Any],
    db: Session,
) -> DetailPageVersion:
    """Persist the LG-10 frozen output once, using a deterministic version id.

    The id is derived from the immutable renderer artifact so a history rebuild
    can repair a missed SQL write without creating another final version.
    """

    # ``detail_page_version`` is the durable pointer added after persistence;
    # it is intentionally not part of the renderer artifact hashed by LG-10.3.
    frozen_rendering = deepcopy(rendering)
    frozen_rendering.pop("detail_page_version", None)
    render_hash = str(frozen_rendering.get("render_hash") or "")
    if (
        frozen_rendering.get("schema_version") != LG10_CANONICAL_RENDER_SCHEMA_VERSION
        or not _SHA256_HEX.fullmatch(render_hash)
        or str((rendering.get("canonical_input_ref") or {}).get("input_hash") or "")
        != str(canonical_page_assembly_input.get("input_hash") or "")
        or str((rendering.get("page_assembly_ref") or {}).get("assembly_hash") or "")
        != str(page_assembly.get("assembly_hash") or "")
    ):
        raise PageAssemblyInputError("LG-10 DetailPageVersion requires matching immutable renderer references.")

    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sellform:lg10:{run.id}:{render_hash}"))
    brand_tokens = dict(rendering.get("brand_tokens") or {})
    preview_sections = _lg10_preview_sections(rendering)
    preview_brand_assets = _lg10_preview_brand_assets(rendering)
    snapshot_payload = {
        "schema_version": LG10_DETAIL_PAGE_VERSION_SCHEMA_VERSION,
        "lg10": {
            "run_id": run.id,
            "canonical_page_assembly_input": deepcopy(canonical_page_assembly_input),
            "page_assembly": deepcopy(page_assembly),
            "canonical_rendering": frozen_rendering,
        },
        # Existing preview/export consumers already read this immutable
        # renderer snapshot. It contains only the canonical renderer's copy
        # and approved asset identities, never mutable page-draft state.
        "commerce_renderer": {
            "theme_color": str((brand_tokens.get("color_tokens") or {}).get("surface") or "#ffffff"),
            "font_family": str((brand_tokens.get("typography") or {}).get("body_font") or "system-ui, sans-serif"),
            "brand_assets": preview_brand_assets,
            "sections": preview_sections,
        },
        "sections": preview_sections,
    }
    snapshot = {**snapshot_payload, "snapshot_hash": _canonical_hash(snapshot_payload)}
    existing = db.query(DetailPageVersion).filter(
        DetailPageVersion.id == version_id,
        DetailPageVersion.project_id == run.project_id,
    ).first()
    if existing is not None:
        if existing.sections_json != snapshot:
            raise PageAssemblyInputError("LG-10 DetailPageVersion identity does not match its immutable snapshot.")
        return existing

    db.query(DetailPageVersion).filter(
        DetailPageVersion.project_id == run.project_id,
        DetailPageVersion.is_final == True,  # noqa: E712
    ).update({"is_final": False})
    version = DetailPageVersion(
        id=version_id,
        project_id=run.project_id,
        name="LG-10 generated detail page",
        style_key=str(canonical_page_assembly_input.get("design_direction") or "balanced_sale"),
        sections_json=snapshot,
        is_final=True,
    )
    db.add(version)
    db.flush()
    return version


def build_final_page_snapshot(db: Session, page: ProductPage) -> dict[str, Any]:
    sorted_sections = sorted(page.sections, key=lambda section: section.sort_order)
    facts = db.query(ProductFact).filter(ProductFact.project_id == page.project_id).all()
    assets = get_page_eligible_assets(db, page.project_id)
    eligible_asset_ids = {asset.id for asset in assets}

    # Keep the renderer input in the final version as well as the legacy
    # section snapshot.  The preview/export route reads this immutable
    # contract first, so a later database edit cannot silently alter a paid
    # export that was already finalized.
    commerce_renderer = build_commerce_artifact(page, assets)

    snapshot = {
        "theme_color": page.theme_color,
        "font_family": page.font_family,
        "style_key": page.project.selected_style if page.project else None,
        "category": page.project.category if page.project else None,
        "sections": [
            {
                "key": section.section_type,
                "section_type": section.section_type,
                "title": section.title,
                "body": section.body_copy,
                "body_copy": section.body_copy,
                "associated_fact_ids": section.associated_fact_ids or [],
                "image_asset_id": (
                    section.image_asset_id
                    if section.image_asset_id in eligible_asset_ids
                    else None
                ),
                # Preserve the same visual contract consumed by the draft
                # renderer.  This makes the export route render Sprint 3's
                # composed HERO instead of falling back to the legacy image.
                "visual_kind": section.visual_kind,
                "visual_payload": section.visual_payload or {},
                "sort_order": section.sort_order,
                "is_visible": section.is_visible,
            }
            for section in sorted_sections
        ],
        "facts_snapshot": [
            {
                "id": fact.id,
                "fact_text": fact.fact_text,
                "source_text": fact.source_text,
                "source_asset_id": fact.source_asset_id,
                "verification_status": fact.verification_status,
                "extraction_source": fact.extraction_source,
                "provider": fact.provider,
                "model_name": fact.model_name,
                "confidence": fact.confidence,
                "needs_review": fact.needs_review,
                "risk_flags": fact.risk_flags,
            }
            for fact in facts
        ],
        "assets_snapshot": [
            {
                "id": asset.id,
                "source_type": asset.source_type,
                "filename": asset.filename,
                "file_path": asset.file_path,
                "mime_type": asset.mime_type,
                "file_size": asset.file_size,
            }
            for asset in assets
        ],
        "commerce_renderer": commerce_renderer,
    }
    # UX-2D freezes the same content-quality decision with the immutable
    # export snapshot.  A later draft edit therefore cannot silently change
    # what was approved for sale or downloaded.
    from src.services.commerce_content_quality_service import inspect_content_quality
    from src.services.api_ready_generation_service import generation_rendering_contract, get_generation_plan
    snapshot["ux2d_content_quality"] = inspect_content_quality(page, db)
    generation_plan = get_generation_plan(page.project)
    if generation_plan:
        snapshot["ux2e0_generation_plan"] = generation_plan
        # Export consumes ``commerce_renderer`` from this immutable snapshot.
        # Store the pending-scene fallback policy beside it so JPG/ZIP exports
        # can never be mistaken for completed AI-generated assets.
        snapshot["commerce_renderer"]["api_generation"] = generation_rendering_contract(generation_plan)
    return snapshot


def get_final_page_version(db: Session, project_id: str) -> DetailPageVersion:
    version = (
        db.query(DetailPageVersion)
        .filter(
            DetailPageVersion.project_id == project_id,
            DetailPageVersion.is_final == True,  # noqa: E712
        )
        .order_by(DetailPageVersion.created_at.desc())
        .first()
    )
    if not version:
        raise FinalPageNotFoundError("Final detail page version not found. Please finalize the page before export.")
    return version


def get_page_version_for_export(
    db: Session,
    project_id: str,
    version_id: str,
) -> DetailPageVersion:
    version = (
        db.query(DetailPageVersion)
        .filter(
            DetailPageVersion.id == version_id,
            DetailPageVersion.project_id == project_id,
        )
        .first()
    )
    if not version:
        raise FinalPageNotFoundError("Requested detail page version was not found.")
    return version


def finalize_page(
    db: Session,
    project_id: str,
    name: str | None = None,
) -> DetailPageVersion:
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise PageDraftNotFoundError("Page draft not found for this project.")

    snapshot = build_final_page_snapshot(db, page)
    style_key = snapshot.get("style_key") or "problem_solution"

    (
        db.query(DetailPageVersion)
        .filter(
            DetailPageVersion.project_id == project_id,
            DetailPageVersion.is_final == True,  # noqa: E712
        )
        .update({"is_final": False})
    )

    version = DetailPageVersion(
        project_id=project_id,
        name=name or f"Final export {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
        style_key=style_key,
        sections_json=snapshot,
        is_final=True,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
