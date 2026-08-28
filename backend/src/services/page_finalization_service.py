import datetime
import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    Asset,
    BrandKitVersion,
    CommerceCreativeMasterVersion,
    DetailPageVersion,
    ImageGenerationJobRecord,
    ProductCreativeBriefVersion,
    ProductFact,
    ProductPage,
    ProductProject,
)
from src.services.channel_export_service import image_sha256
from src.services.commerce_policy import REFERENCE_SOURCE_TYPES, is_asset_final_output_eligible
from src.services.product_identity_validator import (
    ProductIdentityValidationError,
    build_frozen_image_quality_evidence,
)
from src.services.commerce_renderer_service import FINAL_SPEC_TYPES, build_commerce_artifact
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


class EditIntentValidationError(ValueError):
    """An LG-11 edit request does not target the supplied frozen version."""


LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION = "lg10-canonical-page-assembly-input-v1"
LG10_PAGE_ASSEMBLY_SCHEMA_VERSION = "lg10-page-assembly-v1"
LG10_CANONICAL_RENDER_SCHEMA_VERSION = "lg10-canonical-render-v1"
LG10_DETAIL_PAGE_VERSION_SCHEMA_VERSION = "lg10-detail-page-version-v1"
LG11_EDIT_INTENT_SCHEMA_VERSION = "lg11-edit-intent-v1"
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
    # ``cta_text`` is already part of the frozen CopySet contract.  Keeping it
    # in the canonical renderer gives LG-12 a real CTA role to evaluate rather
    # than asking a quality reader to infer one from an arbitrary body field.
    "product_information": ("guarantee_title", "guarantee_body", "cta_text"),
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
    reference = {
        "artifact_key": stage,
        "schema_version": str(artifact.get("schema_version") or ""),
        "artifact_hash": artifact_hash,
    }
    # Current planning artifacts can optionally carry their immutable logical
    # identity in metadata.  Preserve it in the frozen renderer input when it
    # is present; older artifacts remain readable with their hash-only shape.
    artifact_id = str(metadata.get("artifact_id") or "")
    artifact_version = metadata.get("artifact_version")
    if artifact_id and isinstance(artifact_version, int) and artifact_version >= 1:
        reference["artifact_id"] = artifact_id
        reference["artifact_version"] = artifact_version
    return reference, output


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
    required_by_job_id = {str(job.job_id): job for job in required_jobs}
    manifest_job_ids = [str(item.get("job_id") or "") for item in rows]
    if (
        not rows
        or not all(asset_ids)
        or not all(manifest_job_ids)
        or len(set(manifest_job_ids)) != len(manifest_job_ids)
        or set(manifest_job_ids) != set(required_by_job_id)
    ):
        raise PageAssemblyInputError("LG-10 requires one approved manifest entry for every required scene job.")

    assets = {
        asset.id: asset
        for asset in db.query(Asset).filter(Asset.project_id == run.project_id, Asset.id.in_(asset_ids)).all()
    }
    entries: list[dict[str, Any]] = []
    for item in rows:
        asset_id = str(item.get("asset_id") or "")
        asset_hash = str(item.get("asset_content_hash") or "")
        job_id = str(item.get("job_id") or "")
        job = required_by_job_id.get(job_id)
        asset = assets.get(asset_id)
        if (
            job is None
            or asset_id != str(job.output_asset_id)
            or str(item.get("scene_id") or "") != str(job.scene_id or job.section_id)
            or str(item.get("section_id") or "") != str(job.section_id or "")
            or int(item.get("generation_attempt") or 1) != int(job.generation_attempt or 1)
            or asset is None
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
        "brand_kit_version": int(version.version),
        "brand_kit_hash": version.content_hash,
        "color_tokens": {
            "accent": _safe_css_color(colors.get("primary") or colors.get("accent"), "#0f766e"),
            "text": _safe_css_color(colors.get("text"), "#172033"),
            "surface": _safe_css_color(colors.get("surface") or colors.get("background"), "#ffffff"),
            "muted_surface": _safe_css_color(colors.get("secondary"), "#eef2f7"),
        },
        "typography": {"body_font": _safe_font(typography.get("body") or typography.get("font_family"))},
        "contrast_minimum": (
            float(dict(version.constraints or {}).get("minimum_contrast_ratio"))
            if isinstance(dict(version.constraints or {}).get("minimum_contrast_ratio"), (int, float))
            else None
        ),
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
    visual_plan_ref, visual_plan = _artifact_reference(run, "visual_planning")
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
            # A scene remains a reference inside the canonical PagePlan input;
            # the renderer never copies visual-plan content into a page.
            "scene_ref": {
                "scene_id": str(scene.get("id") or ""),
                "scene_type": str(scene.get("scene_type") or scene.get("generation_mode") or ""),
                "scene_order": index,
                "page_plan_id": str(page_ref.get("id") or page_ref.get("artifact_id") or ""),
                "page_plan_version": page_ref.get("version") or page_ref.get("artifact_version"),
                "page_plan_hash": str(page_ref.get("hash") or page_ref.get("artifact_hash") or ""),
                "visual_plan_id": str(visual_plan_ref.get("id") or visual_plan_ref.get("artifact_id") or ""),
                "visual_plan_version": visual_plan_ref.get("version") or visual_plan_ref.get("artifact_version"),
                "visual_plan_hash": str(visual_plan_ref.get("hash") or visual_plan_ref.get("artifact_hash") or ""),
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

    for section in sections:
        _lg11_canvas_normalize_section_elements(section)

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
        canvas = dict(section.get("canvas") or {})
        is_visible = canvas.get("is_visible", True)
        height_px = canvas.get("height_px")
        if not isinstance(is_visible, bool) or height_px is not None and (
            not isinstance(height_px, int) or height_px < 160 or height_px > 2400
        ):
            raise PageAssemblyInputError("LG-10 frozen renderer has invalid Canvas section bounds.")
        visual_payload = {"layout_token": str(section.get("layout_token") or "")}
        if canvas:
            visual_payload["canvas_height_px"] = height_px
            visual_payload["canvas_is_visible"] = is_visible
        if section.get("canvas_elements"):
            # This is frozen renderer state for editor/preview consumers, never a live Canvas draft.
            visual_payload["canvas_elements"] = deepcopy(list(section.get("canvas_elements") or []))
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
            "visual_payload": visual_payload,
            "sort_order": index,
            "is_visible": is_visible,
            "height_px": height_px,
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


def _lg12_quality_lineage_for_run(*, db: Session, run: AgentRun) -> dict[str, Any] | None:
    """Pin the latest immutable LG-12I Master when this run has one.

    LG-10/11 pages remain valid production artifacts for runs that predate
    intake Master creation.  A page that does have an LG-12I Master is frozen
    with its exact source/truth/confirmation/manifest identities so quality
    evaluation cannot substitute another same-project lineage.
    """

    master = (
        db.query(CommerceCreativeMasterVersion)
        .filter_by(workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id)
        .order_by(CommerceCreativeMasterVersion.version.desc())
        .first()
    )
    if master is None:
        return None
    return {
        "schema_version": "lg12-detail-page-quality-lineage-v1",
        "creator_run_id": str(run.id),
        "source_snapshot_ref": {
            "id": str(master.source_snapshot_version_id), "version": int(master.source_snapshot_version),
            "hash": str(master.source_snapshot_hash),
        },
        "truth_ref": {
            "id": str(master.truth_version_id), "version": int(master.truth_version),
            "hash": str(master.truth_version_hash),
        },
        "confirmation_ref": {
            "id": str(master.confirmation_version_id), "version": int(master.confirmation_version),
            "hash": str(master.confirmation_version_hash),
        },
        "master_ref": {
            "id": str(master.id), "version": int(master.version), "hash": str(master.canonical_hash),
        },
        "approved_asset_manifest_ref": deepcopy(dict(master.approved_asset_manifest_ref_json or {})),
    }


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
    lg12_quality_lineage = _lg12_quality_lineage_for_run(db=db, run=run)
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
    if lg12_quality_lineage is not None:
        # This is a bounded immutable reference index, not a copy of any
        # Intake/Master payload.  It lets TASK-12.3 reject a same-project page
        # paired with an unrelated Master during quality evaluation.
        snapshot_payload["lg12_quality_lineage"] = lg12_quality_lineage
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


_EDIT_OPERATIONS_BY_SCOPE = {
    "page": {"reorder", "restyle", "canvas_draft", "restore"},
    "section": {"rewrite", "reorder", "replace", "add", "remove", "restyle"},
    "scene": {"regenerate", "replace", "remove"},
    "copy": {"rewrite", "replace", "add", "remove"},
    "style": {"restyle", "replace"},
    "fact": {"rewrite", "replace", "add", "remove"},
}
_AMBIGUOUS_EDIT_MARKERS = (
    "알아서",
    "적당히",
    "예쁘게",
    "좋게",
    "전체적으로",
    "이거",
    "저거",
    "something",
    "whatever",
)
_FACT_EDIT_MARKERS = (
    "사양",
    "스펙",
    "규격",
    "용량",
    "성능",
    "효과",
    "fact",
    "spec",
)
_FACT_VALUE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mah|wh|hz|db|kg|g|mg|cm|mm|m|v|w|a|%|°c)|"
    r"\d+(?:\.\d+)?\s*(?:시간|분|초|개|장|인치|도)",
    re.IGNORECASE,
)
_VALUE_CHANGE_VERBS = (
    "바꿔",
    "변경",
    "고쳐",
    "정정",
    "수정",
    "늘려",
    "줄여",
    "replace",
    "change",
    "correct",
    "update",
)
_LG11_FACTUAL_CLAIM_CUES = re.compile(
    r"(?:\b(?:waterproof|wireless|battery|charging|capacity|motor|certified|"
    r"compatible|warranty|included|feature|specification|weight|material|"
    r"performance|power|port|connector|sensor|filter|antibacterial|led)\b|"
    r"방수|방진|무선|유선|배터리|충전|용량|모터|저소음|정숙|전력|무게|"
    r"크기|규격|치수|재질|성능|기능|효과|인증|호환|보증|구성품|포함|"
    r"포트|커넥터|센서|필터|항균|살균|탈취|풍량|회전|온도|습도|"
    r"접이식|휴대|내구|절전|고속|강력|타이머|디스플레이)",
    re.IGNORECASE,
)
_LG11_NARRATIVE_REWRITE_TOKENS = {
    "더", "간결", "간결한", "간결하게", "한눈", "소개", "강조", "강조한",
    "보기", "쉽게", "편안", "편안한", "가볍", "가벼운", "프리미엄", "추천",
    "확인", "일상", "감성", "좋은", "새로운", "제품을", "제품의", "문구",
}


def _lg11_text_tokens(text: str) -> set[str]:
    """Return a small deterministic token set for conservative copy provenance."""

    tokens: set[str] = set()
    for raw_token in re.findall(r"[A-Za-z]{2,}|[가-힣]{2,}", str(text or "")):
        token = raw_token.lower()
        if re.fullmatch(r"[가-힣]+", token):
            for particle in ("으로", "에게", "에서", "까지", "부터", "처럼", "보다", "를", "을", "은", "는", "이", "가", "의", "와", "과", "에", "도", "만", "로", "한"):
                if token.endswith(particle) and len(token) > len(particle) + 1:
                    token = token[:-len(particle)]
                    break
        tokens.add(token)
    return tokens


def _lg11_factual_cues(text: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _LG11_FACTUAL_CLAIM_CUES.finditer(str(text or ""))
    }


def _lg11_frozen_edit_targets(version: DetailPageVersion) -> dict[str, Any]:
    """Read the edit surface only from the immutable LG-10 version snapshot."""

    snapshot = deepcopy(dict(version.sections_json or {}))
    snapshot_hash = str(snapshot.pop("snapshot_hash", "") or "")
    lg10 = dict(snapshot.get("lg10") or {})
    canonical_input = dict(lg10.get("canonical_page_assembly_input") or {})
    page_assembly = dict(lg10.get("page_assembly") or {})
    rendering = dict(lg10.get("canonical_rendering") or {})
    if (
        snapshot.get("schema_version") != LG10_DETAIL_PAGE_VERSION_SCHEMA_VERSION
        or canonical_input.get("schema_version") != LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION
        or rendering.get("schema_version") != LG10_CANONICAL_RENDER_SCHEMA_VERSION
        or not _SHA256_HEX.fullmatch(snapshot_hash)
        or _canonical_hash(snapshot) != snapshot_hash
    ):
        raise EditIntentValidationError("LG-11 edits require a frozen LG-10 DetailPageVersion.")

    sections = {
        str(section.get("section_id")): dict(section)
        for section in canonical_input.get("sections") or []
        if isinstance(section, dict) and str(section.get("section_id") or "")
    }
    if not sections:
        raise EditIntentValidationError("The frozen version has no stable section targets.")

    facts: dict[str, dict[str, Any]] = {}
    for section in sections.values():
        copy_ref = dict(section.get("copy_ref") or {})
        evidence_by_fact = dict(copy_ref.get("evidence_ids_by_fact") or {})
        for fact_id in copy_ref.get("fact_ids") or []:
            normalized_fact_id = str(fact_id or "")
            if not normalized_fact_id:
                continue
            evidence_ids = [
                str(evidence_id)
                for evidence_id in evidence_by_fact.get(normalized_fact_id, copy_ref.get("evidence_ids") or [])
                if str(evidence_id or "")
            ]
            facts.setdefault(normalized_fact_id, {"evidence_ids": sorted(set(evidence_ids))})
    manifest = dict(canonical_input.get("approved_asset_manifest") or {})
    scenes = {
        str(asset.get("scene_id")): dict(asset)
        for asset in manifest.get("assets") or []
        if isinstance(asset, dict) and str(asset.get("scene_id") or "")
    }
    return {
        "canonical_input": canonical_input,
        "page_assembly": page_assembly,
        "rendering": rendering,
        "sections": sections,
        "facts": facts,
        "scenes": scenes,
        "snapshot_hash": snapshot_hash,
    }


def _lg11_target_descriptions(
    *,
    version: DetailPageVersion,
    scope: str,
    target_ids: list[str],
    targets: dict[str, Any],
) -> list[dict[str, str]]:
    descriptions: list[dict[str, str]] = []
    for target_id in target_ids:
        target_id = str(target_id)
        if scope in {"page", "style"}:
            if target_id != version.id:
                raise EditIntentValidationError("Page/style targets must be the supplied frozen DetailPageVersion.")
            descriptions.append({"target_id": target_id, "target_type": "detail_page_version"})
        elif scope in {"section", "copy"}:
            if target_id not in targets["sections"]:
                raise EditIntentValidationError(f"Unknown frozen section target: {target_id}")
            descriptions.append({"target_id": target_id, "target_type": "section", "section_id": target_id})
        elif scope == "scene":
            scene = targets["scenes"].get(target_id)
            if scene is None:
                raise EditIntentValidationError(f"Unknown approved scene target: {target_id}")
            descriptions.append({
                "target_id": target_id,
                "target_type": "scene",
                "section_id": str(scene.get("section_id") or ""),
            })
        elif scope == "fact":
            if target_id not in targets["facts"]:
                raise EditIntentValidationError(f"Unknown frozen fact target: {target_id}")
            descriptions.append({"target_id": target_id, "target_type": "fact"})
        else:  # Guarded above; keep this branch safe if schemas evolve.
            raise EditIntentValidationError(f"Unsupported edit scope: {scope}")
    return descriptions


def _lg11_frozen_scene_costs(*, scene_ids: list[str]) -> dict[str, Any]:
    """State explicitly when an LG-10 snapshot did not freeze a cost estimate.

    LG-10 versions intentionally pin final assets, not a future regeneration
    quote.  Reading a current image job here would make this preview mutable,
    so TASK-11.1 must leave that amount unavailable for the later cost-plan
    task to establish under its own approval contract.
    """

    return {
        "status": "not_available",
        "source": "frozen_detail_page_version",
        "currency": "credits",
        "total": None,
        "scenes": [
            {"scene_id": scene_id, "status": "not_available"}
            for scene_id in sorted(scene_ids)
        ],
    }


def _lg11_is_whitespace_only_copy_change(*, source_text: str, new_text: str) -> bool:
    """Return true only for a semantic no-op whitespace normalisation."""

    return (
        new_text != source_text
        and re.sub(r"\s+", "", new_text) == re.sub(r"\s+", "", source_text)
    )


def _lg11_fact_change_risk(
    *,
    scope: str,
    instruction: str,
    target_descriptions: list[dict[str, str]],
    targets: dict[str, Any],
    copy_changes: dict[str, dict[str, str]] | None = None,
    copy_change_provenance: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[bool, list[str]]:
    """Conservatively identify a possible fact-value change without an LLM call."""

    if scope == "fact":
        return True, sorted({item["target_id"] for item in target_descriptions})
    if copy_changes:
        frozen_copy_set = _lg11_copy_set_from_frozen_rendering(
            canonical_input=targets["canonical_input"],
            rendering=targets["rendering"],
        )
        if all(
            _lg11_is_whitespace_only_copy_change(
                source_text=frozen_copy_set[field], new_text=str(new_text),
            )
            for fields in copy_changes.values()
            for field, new_text in fields.items()
        ):
            # Fact-related wording in an instruction must not turn a verified
            # semantic no-op (for example, repeated-space repair) into a fact
            # edit. The exact frozen field/value remains unchanged.
            return False, []
    lower_instruction = instruction.lower()
    changed_text = "\n".join(
        str(value)
        for fields in (copy_changes or {}).values()
        for value in fields.values()
    ).lower()
    has_value_change = bool(_FACT_VALUE_PATTERN.search(lower_instruction)) and any(
        verb in lower_instruction for verb in _VALUE_CHANGE_VERBS
    ) or bool(changed_text and _FACT_VALUE_PATTERN.search(changed_text))
    has_fact_marker = any(marker in lower_instruction for marker in _FACT_EDIT_MARKERS)
    referenced_fact_ids = sorted({
        fact_id
        for target in target_descriptions
        for fact_id in dict(targets["sections"].get(str(target.get("section_id") or ""), {}).get("copy_ref") or {}).get("fact_ids") or []
        if str(fact_id or "")
    })
    evidence_review_fields = [
        field
        for fields in (copy_change_provenance or {}).values()
        for field in fields.values()
        if str(field.get("classification") or "") == "needs_evidence_review"
    ]
    if not (has_value_change or has_fact_marker or evidence_review_fields):
        return False, []
    # A fact-like value command is still confirmation-required even when this
    # frozen section had no recorded fact link; it must not silently become a
    # copy rewrite merely because provenance is incomplete.
    return True, referenced_fact_ids


def _normalize_lg11_style_change(
    *,
    scope: str,
    frozen_targets: dict[str, Any],
    design_direction: str | None,
    brand_kit_ref: dict[str, Any] | None,
) -> dict[str, Any]:
    """Pin only deterministic LG-10 style inputs for an LG-11 style edit."""

    requested_direction = str(design_direction or "").strip() or None
    requested_brand_ref = deepcopy(dict(brand_kit_ref or {}))
    if scope != "style":
        if requested_direction is not None or requested_brand_ref:
            raise EditIntentValidationError("Design direction and Brand Kit selection are only valid for style edits.")
        return {}

    source_canonical = dict(frozen_targets["canonical_input"])
    source_direction = normalize_lg10_design_direction(source_canonical.get("design_direction"))
    source_brand_ref = deepcopy(dict(source_canonical.get("brand_kit_ref") or {}))
    next_direction = (
        normalize_lg10_design_direction(requested_direction)
        if requested_direction is not None
        else source_direction
    )
    if requested_brand_ref:
        version_id = str(requested_brand_ref.get("brand_kit_version_id") or "")
        version_hash = str(requested_brand_ref.get("brand_kit_hash") or "")
        if not version_id or not _SHA256_HEX.fullmatch(version_hash):
            raise EditIntentValidationError("LG-11 style edits require a hash-pinned Brand Kit version.")
        next_brand_ref = {
            "brand_kit_version_id": version_id,
            "brand_kit_hash": version_hash,
        }
    else:
        next_brand_ref = source_brand_ref

    return {
        "source_design_direction": source_direction,
        "design_direction": next_direction,
        "source_brand_kit_ref": source_brand_ref,
        "brand_kit_ref": next_brand_ref,
    }


def _normalize_lg11_copy_changes(
    *,
    scope: str,
    target_ids: list[str],
    copy_changes: dict[str, dict[str, str]] | None,
    targets: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Validate direct text edits against fields pinned by the frozen snapshot."""

    raw_changes = copy_changes or {}
    if not raw_changes:
        return {}
    if scope != "copy":
        raise EditIntentValidationError("copy_changes are only valid for copy edit intents.")
    normalized: dict[str, dict[str, str]] = {}
    selected = set(target_ids)
    for raw_section_id, raw_fields in raw_changes.items():
        section_id = str(raw_section_id or "").strip()
        if section_id not in selected or section_id not in targets["sections"]:
            raise EditIntentValidationError("Copy changes must target a selected frozen section.")
        if not isinstance(raw_fields, dict) or not raw_fields:
            raise EditIntentValidationError("Each copy change must contain a non-empty field map.")
        allowed_fields = {
            str(field)
            for field in dict(targets["sections"][section_id].get("copy_ref") or {}).get("fields") or []
        }
        changed_fields: dict[str, str] = {}
        for raw_field, raw_text in raw_fields.items():
            field = str(raw_field or "").strip()
            if field not in allowed_fields:
                raise EditIntentValidationError(f"Unknown frozen copy field for {section_id}: {field}")
            if not isinstance(raw_text, str):
                raise EditIntentValidationError("Copy changes must contain text values.")
            changed_fields[field] = raw_text
        normalized[section_id] = {
            field: changed_fields[field]
            for field in sorted(changed_fields)
        }
    return {section_id: normalized[section_id] for section_id in sorted(normalized)}


def _lg11_copy_change_provenance(
    *,
    targets: dict[str, Any],
    copy_changes: dict[str, dict[str, str]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Classify each changed field using only frozen text and frozen fact refs.

    A copy-only fork must never turn a new claim into fact-backed copy merely
    because its section happened to have fact IDs before the edit.  This is a
    deliberately conservative lexical guard: known factual cues that were not
    present in the frozen field, numeric values, or a substantive unrecognised
    delta on fact-backed text are sent to evidence review.  Claim-free wording
    changes retain no fact IDs; a fact-backed rewrite has to retain the frozen
    field's factual cues.
    """

    copy_set = _lg11_copy_set_from_frozen_rendering(
        canonical_input=targets["canonical_input"],
        rendering=targets["rendering"],
    )
    provenance: dict[str, dict[str, dict[str, Any]]] = {}
    for section_id, fields in copy_changes.items():
        copy_ref = dict(targets["sections"][section_id].get("copy_ref") or {})
        source_fact_ids = sorted({str(value) for value in copy_ref.get("fact_ids") or [] if str(value or "")})
        source_evidence = {
            fact_id: sorted({str(value) for value in list(dict(copy_ref.get("evidence_ids_by_fact") or {}).get(fact_id) or []) if str(value or "")})
            for fact_id in source_fact_ids
        }
        section_provenance: dict[str, dict[str, Any]] = {}
        for field, new_text in fields.items():
            source_text = copy_set[field]
            source_cues = _lg11_factual_cues(source_text)
            new_cues = _lg11_factual_cues(new_text)
            new_tokens = _lg11_text_tokens(new_text)
            source_tokens = _lg11_text_tokens(source_text)
            novel_tokens = {
                token
                for token in new_tokens - source_tokens
                if token not in _LG11_NARRATIVE_REWRITE_TOKENS
            }
            numeric_value = bool(_FACT_VALUE_PATTERN.search(new_text))
            new_claim_cues = sorted(new_cues - source_cues)
            # Whitespace-only normalisation preserves every visible token and
            # numeric/factual cue from the frozen source. It is a bounded
            # cosmetic change, not a new value claim, even where the source
            # text legitimately contains a number or fact-backed cue.
            whitespace_only_change = _lg11_is_whitespace_only_copy_change(
                source_text=source_text, new_text=new_text,
            )
            if whitespace_only_change:
                classification = "fact_backed" if source_fact_ids else "narrative_only"
                reason = "cosmetic_whitespace_normalization"
            elif numeric_value:
                classification = "needs_evidence_review"
                reason = "numeric_or_unit_value_change"
            elif new_claim_cues:
                classification = "needs_evidence_review"
                reason = "new_factual_claim_cue"
            elif source_fact_ids and novel_tokens:
                classification = "needs_evidence_review"
                reason = "unverified_fact_backed_text_delta"
            elif source_fact_ids and (new_cues & source_cues or new_text == source_text):
                classification = "fact_backed"
                reason = "frozen_fact_cues_preserved"
            else:
                classification = "narrative_only"
                reason = "no_factual_claim_retained"
            field_provenance = {
                "classification": classification,
                "reason": reason,
                "source_text_hash": _canonical_hash(source_text),
                "source_factual_cues": sorted(source_cues),
                "new_factual_cues": sorted(new_cues),
                "fact_ids": source_fact_ids if classification == "fact_backed" else [],
                "evidence_ids_by_fact": source_evidence if classification == "fact_backed" else {},
            }
            section_provenance[field] = field_provenance
        provenance[section_id] = section_provenance
    return provenance


def _lg11_structured_affected_artifacts(
    *,
    scope: str,
    target_descriptions: list[dict[str, str]],
    fact_sensitive: bool,
    fact_ids: list[str],
    targets: dict[str, Any],
) -> dict[str, Any]:
    """Return only identity references that already exist in the frozen snapshot."""

    canonical_input = targets["canonical_input"]
    sections_by_id = targets["sections"]
    if scope in {"page", "style"}:
        affected_section_ids = sorted(sections_by_id)
    elif scope == "scene":
        affected_section_ids = sorted({str(target.get("section_id") or "") for target in target_descriptions if target.get("section_id")})
    elif fact_sensitive:
        affected_section_ids = sorted(
            section_id
            for section_id, section in sections_by_id.items()
            if set(str(fact_id) for fact_id in dict(section.get("copy_ref") or {}).get("fact_ids") or []) & set(fact_ids)
        )
    else:
        affected_section_ids = sorted({str(target.get("section_id") or "") for target in target_descriptions if target.get("section_id")})

    affected_scene_ids = sorted({
        scene_id
        for scene_id, scene in targets["scenes"].items()
        if scope == "scene" and scene_id in {item["target_id"] for item in target_descriptions}
        or (fact_sensitive and str(scene.get("section_id") or "") in affected_section_ids)
    })
    section_assets = [
        asset
        for section_id in affected_section_ids
        for asset in [
            *list(sections_by_id[section_id].get("approved_assets") or []),
            *list(sections_by_id[section_id].get("seller_owned_fallback_assets") or []),
        ]
        if isinstance(asset, dict)
    ]
    manifest_assets = [
        asset
        for scene_id, asset in targets["scenes"].items()
        if scene_id in affected_scene_ids
    ]
    asset_identities = {
        (str(asset.get("asset_id") or ""), str(asset.get("asset_content_hash") or "")): {
            "asset_id": str(asset.get("asset_id") or ""),
            "asset_content_hash": str(asset.get("asset_content_hash") or ""),
            "scene_id": str(asset.get("scene_id") or "") or None,
            "section_id": str(asset.get("section_id") or "") or None,
        }
        for asset in [*section_assets, *manifest_assets]
        if str(asset.get("asset_id") or "") and _SHA256_HEX.fullmatch(str(asset.get("asset_content_hash") or ""))
    }
    copy_references = [
        {
            "section_id": section_id,
            "artifact_key": str(dict(sections_by_id[section_id].get("copy_ref") or {}).get("artifact_key") or ""),
            "schema_version": str(dict(sections_by_id[section_id].get("copy_ref") or {}).get("schema_version") or ""),
            "artifact_hash": str(dict(sections_by_id[section_id].get("copy_ref") or {}).get("artifact_hash") or ""),
            "fields": list(dict(sections_by_id[section_id].get("copy_ref") or {}).get("fields") or []),
            "fact_ids": list(dict(sections_by_id[section_id].get("copy_ref") or {}).get("fact_ids") or []),
        }
        for section_id in affected_section_ids
    ]
    facts = [
        {
            "fact_id": fact_id,
            "evidence_ids": list(targets["facts"].get(fact_id, {}).get("evidence_ids") or []),
            "evidence_reference_status": "frozen" if targets["facts"].get(fact_id, {}).get("evidence_ids") else "not_recorded_in_frozen_version",
        }
        for fact_id in fact_ids
    ]
    assembly_sections = {
        str(section.get("section_id") or ""): dict(section)
        for section in targets["page_assembly"].get("sections") or []
        if isinstance(section, dict)
    }
    brand_asset_layer = dict((targets["rendering"].get("brand_tokens") or {}).get("asset_layer") or {})
    return {
        "artifact_kinds": [],
        "section_ids": affected_section_ids,
        "scene_ids": affected_scene_ids,
        "assets": [asset_identities[key] for key in sorted(asset_identities)],
        "copy_artifacts": copy_references,
        "brand_kit": {
            **dict(canonical_input.get("brand_kit_ref") or {}),
            "assets": {
                role: {
                    "asset_id": str(identity.get("asset_id") or ""),
                    "asset_content_hash": str(identity.get("asset_content_hash") or ""),
                }
                for role, identity in brand_asset_layer.items()
                if role in {"logo", "watermark"} and isinstance(identity, dict)
                and str(identity.get("asset_id") or "")
                and _SHA256_HEX.fullmatch(str(identity.get("asset_content_hash") or ""))
            },
        },
        "facts": facts,
        "style_layout_tokens": [
            {
                "section_id": section_id,
                "layout_token_ref": deepcopy(dict(sections_by_id[section_id].get("layout_token_ref") or {})),
                "component_id": str(assembly_sections.get(section_id, {}).get("component_id") or "") or None,
                "layout_token": str(assembly_sections.get(section_id, {}).get("layout_token") or "") or None,
            }
            for section_id in affected_section_ids
        ],
    }


def preview_lg11_edit_intent(
    *,
    version: DetailPageVersion,
    scope: str,
    target_ids: list[str],
    operation: str,
    instruction: str,
    preserve_constraints: dict[str, Any] | None = None,
    copy_changes: dict[str, dict[str, str]] | None = None,
    replacement_asset_id: str | None = None,
    seller_attested: bool = False,
    design_direction: str | None = None,
    brand_kit_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize and inspect an LG-11 edit request without mutating production state.

    TASK-11.1 deliberately stops at this boundary.  It neither starts a
    LangGraph run nor creates a page/version/job; a later task owns execution.
    """

    normalized_scope = str(scope or "").strip().lower()
    normalized_operation = str(operation or "").strip().lower()
    normalized_targets = [str(target_id).strip() for target_id in target_ids if str(target_id).strip()]
    normalized_instruction = str(instruction or "").strip()
    if normalized_scope not in _EDIT_OPERATIONS_BY_SCOPE:
        raise EditIntentValidationError(f"Unsupported edit scope: {normalized_scope}")
    if normalized_operation not in _EDIT_OPERATIONS_BY_SCOPE[normalized_scope]:
        raise EditIntentValidationError(
            f"Operation {normalized_operation!r} is not allowed for {normalized_scope} edits."
        )
    if not normalized_targets or len(set(normalized_targets)) != len(normalized_targets):
        raise EditIntentValidationError("EditIntent target_ids must be a non-empty unique frozen target list.")
    if not normalized_instruction:
        raise EditIntentValidationError("EditIntent requires a non-empty instruction.")
    # Conversational edits are normalized into the existing structured edit
    # contract.  They never carry executable markup, external image URLs, or
    # raw styling through a text instruction/copy field.
    unsafe_text = "\n".join([
        normalized_instruction,
        *(
            str(value)
            for fields in (copy_changes or {}).values()
            if isinstance(fields, dict)
            for value in fields.values()
        ),
    ]).lower()
    if any(marker in unsafe_text for marker in ("<script", "</script", "<style", "javascript:", "data:text/html", "http://", "https://")):
        raise EditIntentValidationError("LG-11 conversational edits cannot contain raw HTML, script, styling, or external URLs.")
    if normalized_scope == "scene" and normalized_operation == "replace" and not str(replacement_asset_id or ""):
        raise EditIntentValidationError("Scene asset replacement requires a seller-owned asset ID.")

    frozen_targets = _lg11_frozen_edit_targets(version)
    selected_context = dict(dict(preserve_constraints or {}).get("selected_context") or {})
    selected_section_id = str(selected_context.get("section_id") or "")
    selected_element_id = str(selected_context.get("element_id") or "")
    if selected_section_id:
        selected_section = dict(frozen_targets["sections"].get(selected_section_id) or {})
        if not selected_section:
            raise EditIntentValidationError("LG-11 selected section is not part of the frozen version.")
        if selected_element_id:
            element_ids = {
                str(item.get("element_id") or "")
                for item in list(selected_section.get("canvas_elements") or [])
                if isinstance(item, dict)
            }
            if selected_element_id not in element_ids:
                raise EditIntentValidationError("LG-11 selected element is not part of the frozen selected section.")
    style_change = _normalize_lg11_style_change(
        scope=normalized_scope,
        frozen_targets=frozen_targets,
        design_direction=design_direction,
        brand_kit_ref=brand_kit_ref,
    )
    target_descriptions = _lg11_target_descriptions(
        version=version,
        scope=normalized_scope,
        target_ids=normalized_targets,
        targets=frozen_targets,
    )
    normalized_copy_changes = _normalize_lg11_copy_changes(
        scope=normalized_scope,
        target_ids=normalized_targets,
        copy_changes=copy_changes,
        targets=frozen_targets,
    )
    copy_change_provenance = _lg11_copy_change_provenance(
        targets=frozen_targets,
        copy_changes=normalized_copy_changes,
    )
    lower_instruction = normalized_instruction.lower()
    ambiguous = any(marker in lower_instruction for marker in _AMBIGUOUS_EDIT_MARKERS)
    fact_sensitive, impacted_fact_ids = _lg11_fact_change_risk(
        scope=normalized_scope,
        instruction=normalized_instruction,
        target_descriptions=target_descriptions,
        targets=frozen_targets,
        copy_changes=normalized_copy_changes,
        copy_change_provenance=copy_change_provenance,
    )
    requires_cost_approval = normalized_scope == "scene" and normalized_operation == "regenerate"
    expected_provider_cost = (
        {
            "status": "not_required",
            "source": "lg11_style_selective_reassembly" if normalized_scope == "style" else "lg11_frozen_version_restore",
            "currency": "credits",
            "total": 0,
            "scenes": [],
        }
        if normalized_scope == "style" or (normalized_scope == "page" and normalized_operation == "restore")
        else _lg11_frozen_scene_costs(
            scene_ids=normalized_targets if normalized_scope == "scene" and requires_cost_approval else [],
        )
    )

    retained_scene_ids = sorted(set(frozen_targets["scenes"]) - (set(normalized_targets) if normalized_scope == "scene" else set()))
    invalidated_approvals: list[dict[str, str]] = []
    if normalized_scope == "scene":
        invalidated_approvals = [
            {"approval_type": "scene", "target_id": target_id}
            for target_id in normalized_targets
        ]
    elif fact_sensitive:
        invalidated_approvals = [
            {"approval_type": "fact_evidence", "target_id": fact_id}
            for fact_id in impacted_fact_ids
        ]
        if not invalidated_approvals:
            invalidated_approvals = [{"approval_type": "fact_evidence", "target_id": "unresolved_frozen_fact"}]

    affected_by_scope = {
        "copy": ["copy_artifact", "canonical_renderer", "detail_page_version", "preview", "export"],
        "scene": ["image_generation", "approved_asset_manifest", "canonical_page_assembly_input", "page_assembly", "canonical_renderer", "detail_page_version", "preview", "export"],
        "style": ["brand_kit_tokens", "page_assembly", "canonical_renderer", "detail_page_version", "preview", "export"],
        "fact": ["fact_evidence_review", "copy_artifact", "visual_planning", "canonical_page_assembly_input", "page_assembly", "canonical_renderer", "detail_page_version", "preview", "export"],
        "page": ["page_assembly", "canonical_renderer", "detail_page_version", "preview", "export"],
        "section": ["page_assembly", "canonical_renderer", "detail_page_version", "preview", "export"],
    }
    if normalized_scope == "page" and normalized_operation == "restore":
        affected_by_scope = {**affected_by_scope, "page": ["detail_page_version", "preview", "export"]}
    affected_kinds = list(affected_by_scope[normalized_scope])
    if fact_sensitive and "fact_evidence_review" not in affected_kinds:
        affected_kinds = ["fact_evidence_review", *affected_kinds]
    affected_artifacts = _lg11_structured_affected_artifacts(
        scope=normalized_scope,
        target_descriptions=target_descriptions,
        fact_sensitive=fact_sensitive,
        fact_ids=impacted_fact_ids,
        targets=frozen_targets,
    )
    if normalized_scope == "style":
        # Style changes reassemble deterministic layout/render tokens only.
        # Existing product assets, copy, and evidence remain pinned in the
        # source snapshot and are therefore explicitly not invalidated.
        affected_artifacts["assets"] = []
        affected_artifacts["copy_artifacts"] = []
        affected_artifacts["facts"] = []
        affected_artifacts["brand_kit"] = deepcopy(style_change["brand_kit_ref"])
    affected_artifacts["artifact_kinds"] = affected_kinds
    snapshot_hash = frozen_targets["snapshot_hash"]
    intent_payload = {
        "schema_version": LG11_EDIT_INTENT_SCHEMA_VERSION,
        "base_detail_page_version_id": version.id,
        "base_snapshot_hash": snapshot_hash,
        "scope": normalized_scope,
        "target_ids": normalized_targets,
        "operation": normalized_operation,
        "instruction": normalized_instruction,
        "preserve_constraints": deepcopy(preserve_constraints or {}),
        "copy_changes": normalized_copy_changes,
        "replacement_asset_id": str(replacement_asset_id or "") or None,
        "seller_attested": bool(seller_attested),
        "style_change": style_change,
        "copy_change_provenance": copy_change_provenance,
        "requires_cost_approval": requires_cost_approval,
        "affected_artifacts": affected_artifacts,
    }
    intent = {**intent_payload, "intent_hash": _canonical_hash(intent_payload)}
    explicit_confirmation = ambiguous or fact_sensitive
    return {
        "edit_intent": intent,
        "impact_preview": {
            "base_detail_page_version_id": version.id,
            "targets": target_descriptions,
            "stale_artifacts": affected_kinds,
            "affected_artifacts": affected_artifacts,
            "copy_change_provenance": copy_change_provenance,
            "retained_approvals": {
                "approved_scene_ids": retained_scene_ids,
                "approved_asset_manifest_hash": str(
                    (frozen_targets["canonical_input"].get("approved_asset_manifest") or {}).get("manifest_hash") or ""
                ) or None,
            },
            "invalidated_approvals": invalidated_approvals,
            "expected_provider_cost": expected_provider_cost,
            "requires_cost_approval": requires_cost_approval,
            "requires_evidence_review": fact_sensitive,
            "requires_explicit_confirmation": explicit_confirmation,
            "execution_blocked": explicit_confirmation,
            "confirmation_reasons": [
                reason
                for reason, required in (
                    ("ambiguous_instruction", ambiguous),
                    ("fact_change_requires_evidence_review", fact_sensitive),
                )
                if required
            ],
        },
    }


def build_lg11_fact_selective_stale_state(
    *,
    source_version: DetailPageVersion,
    edit_run_id: str,
    intent: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the approved fact-change invalidation surface without mutating it.

    LG-11.5 deliberately records only the downstream artifacts that are stale
    relative to a frozen version.  It neither edits the fact board nor creates
    a renderer/version/provider job; later tasks own those explicit rebuilds.
    """

    frozen = _lg11_frozen_edit_targets(source_version)
    intent_payload = deepcopy(dict(intent or {}))
    intent_hash = str(intent_payload.pop("intent_hash", "") or "")
    if (
        intent_payload.get("schema_version") != LG11_EDIT_INTENT_SCHEMA_VERSION
        or not _SHA256_HEX.fullmatch(intent_hash)
        or _canonical_hash(intent_payload) != intent_hash
        or str(intent_payload.get("base_detail_page_version_id") or "") != source_version.id
        or str(intent_payload.get("base_snapshot_hash") or "") != frozen["snapshot_hash"]
        or str(intent_payload.get("scope") or "") not in {"fact", "copy"}
    ):
        raise EditIntentValidationError("LG-11 fact stale state requires one immutable frozen fact-sensitive intent.")

    preview = preview_lg11_edit_intent(
        version=source_version,
        scope=str(intent_payload["scope"]),
        target_ids=list(intent_payload.get("target_ids") or []),
        operation=str(intent_payload.get("operation") or ""),
        instruction=str(intent_payload.get("instruction") or ""),
        preserve_constraints=deepcopy(dict(intent_payload.get("preserve_constraints") or {})),
        copy_changes=deepcopy(dict(intent_payload.get("copy_changes") or {})),
        replacement_asset_id=intent_payload.get("replacement_asset_id"),
        seller_attested=bool(intent_payload.get("seller_attested")),
    )
    if preview["edit_intent"] != {**intent_payload, "intent_hash": intent_hash}:
        raise EditIntentValidationError("LG-11 fact stale state no longer matches its immutable impact preview.")
    impact = deepcopy(dict(preview["impact_preview"] or {}))
    affected = deepcopy(dict(impact.get("affected_artifacts") or {}))
    fact_evidence = [
        {
            "fact_id": str(item.get("fact_id") or ""),
            "evidence_ids": sorted({str(value) for value in item.get("evidence_ids") or [] if str(value or "")}),
            "evidence_reference_status": str(item.get("evidence_reference_status") or ""),
        }
        for item in affected.get("facts") or []
        if str(item.get("fact_id") or "")
    ]
    if not impact.get("requires_evidence_review") or not fact_evidence:
        raise EditIntentValidationError("LG-11 fact stale state requires frozen fact/evidence review identities.")

    affected_section_ids = sorted({str(value) for value in affected.get("section_ids") or [] if str(value or "")})
    affected_scene_ids = sorted({str(value) for value in affected.get("scene_ids") or [] if str(value or "")})
    return {
        "schema_version": "lg11-fact-selective-stale-v1",
        "status": "stale",
        "reason": "approved_fact_change_requires_selective_rebuild",
        "edit_run_id": edit_run_id,
        "source_detail_page_version_id": source_version.id,
        "parent_detail_page_version_id": source_version.id,
        "base_snapshot_hash": frozen["snapshot_hash"],
        "intent_id": intent_hash,
        "fact_evidence": fact_evidence,
        "affected": {
            "section_ids": affected_section_ids,
            "scene_ids": affected_scene_ids,
            "copy_artifacts": deepcopy(list(affected.get("copy_artifacts") or [])),
            "assets": deepcopy(list(affected.get("assets") or [])),
            "style_layout_tokens": deepcopy(list(affected.get("style_layout_tokens") or [])),
            "page_assembly": {
                "status": "stale" if affected_section_ids else "unaffected",
                "section_ids": affected_section_ids,
            },
        },
        "retained": {
            "section_ids": sorted(set(frozen["sections"]) - set(affected_section_ids)),
            "scene_ids": sorted(set(frozen["scenes"]) - set(affected_scene_ids)),
        },
        "execution": {
            "provider_calls": 0,
            "outbox_records": 0,
            "cost_approvals": 0,
            "next_action": "none",
        },
    }


def _lg11_copy_set_from_frozen_rendering(
    *,
    canonical_input: dict[str, Any],
    rendering: dict[str, Any],
) -> dict[str, str]:
    """Recover only the frozen renderer's text values for a copy-only fork."""

    rendered_sections = {
        str(section.get("section_id") or ""): dict(section)
        for section in rendering.get("sections") or []
        if isinstance(section, dict) and str(section.get("section_id") or "")
    }
    copy_set: dict[str, str] = {}
    for canonical_section in canonical_input.get("sections") or []:
        section = dict(canonical_section or {})
        section_id = str(section.get("section_id") or "")
        rendered = rendered_sections.get(section_id)
        expected_fields = [
            str(field)
            for field in dict(section.get("copy_ref") or {}).get("fields") or []
        ]
        if rendered is None:
            canvas_origin = str(dict(section.get("canvas") or {}).get("origin") or "")
            if canvas_origin == "canvas_added" and not expected_fields:
                # A Canvas-added information-only section intentionally has no
                # frozen text provenance.  It renders as an empty safe section.
                continue
            if canvas_origin != "canvas_duplicate":
                raise EditIntentValidationError("LG-11 Canvas requires frozen renderer provenance for every source section.")
            candidates = [
                candidate for candidate in rendered_sections.values()
                if [
                    str(item.get("field") or "")
                    for item in candidate.get("text_layer") or []
                    if isinstance(item, dict) and str(item.get("field") or "")
                ] == expected_fields
            ]
            if not candidates:
                raise EditIntentValidationError("LG-11 Canvas duplicate has no matching frozen copy provenance.")
            rendered = candidates[0]
            candidate_values = [
                {
                    str(item.get("field") or ""): str(item.get("text") or "")
                    for item in candidate.get("text_layer") or []
                    if isinstance(item, dict) and str(item.get("field") or "")
                }
                for candidate in candidates
            ]
            if any(values != candidate_values[0] for values in candidate_values[1:]):
                raise EditIntentValidationError("LG-11 Canvas duplicate has ambiguous frozen copy provenance.")
        rendered_fields = {
            str(item.get("field") or ""): str(item.get("text") or "")
            for item in rendered.get("text_layer") or []
            if isinstance(item, dict) and str(item.get("field") or "")
        }
        if set(rendered_fields) != set(expected_fields):
            raise EditIntentValidationError("LG-11 copy fork found mismatched frozen text-layer provenance.")
        for field in expected_fields:
            existing = copy_set.get(field)
            if existing is not None and existing != rendered_fields[field]:
                raise EditIntentValidationError("LG-11 copy fork found ambiguous shared copy provenance.")
            copy_set[field] = rendered_fields[field]
    return copy_set


def _lg11_apply_copy_change_provenance(
    *,
    canonical_input: dict[str, Any],
    copy_changes: dict[str, dict[str, str]],
    copy_change_provenance: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Freeze field-level copy provenance into the child canonical input."""

    updated = deepcopy(canonical_input)
    for raw_section in updated.get("sections") or []:
        if not isinstance(raw_section, dict):
            continue
        section_id = str(raw_section.get("section_id") or "")
        if section_id not in copy_changes:
            continue
        source_copy_ref = deepcopy(dict(raw_section.get("copy_ref") or {}))
        source_fact_ids = sorted({str(value) for value in source_copy_ref.get("fact_ids") or [] if str(value or "")})
        source_evidence = {
            fact_id: sorted({str(value) for value in list(dict(source_copy_ref.get("evidence_ids_by_fact") or {}).get(fact_id) or []) if str(value or "")})
            for fact_id in source_fact_ids
        }
        changed_fields = set(copy_changes[section_id])
        field_provenance: dict[str, dict[str, Any]] = {}
        retained_fact_ids: set[str] = set()
        for field in source_copy_ref.get("fields") or []:
            field_name = str(field or "")
            if field_name in changed_fields:
                field_entry = deepcopy(copy_change_provenance[section_id][field_name])
            else:
                field_entry = {
                    "classification": "fact_backed" if source_fact_ids else "narrative_only",
                    "reason": "unchanged_frozen_field",
                    "fact_ids": source_fact_ids,
                    "evidence_ids_by_fact": source_evidence,
                }
            field_provenance[field_name] = field_entry
            retained_fact_ids.update(str(value) for value in field_entry.get("fact_ids") or [] if str(value or ""))
        retained_fact_ids = set(sorted(retained_fact_ids))
        copy_ref = {
            **source_copy_ref,
            "fact_ids": sorted(retained_fact_ids),
            "evidence_ids_by_fact": {
                fact_id: source_evidence.get(fact_id, [])
                for fact_id in sorted(retained_fact_ids)
            },
            "lg11_copy_overlay": {
                "schema_version": "lg11-copy-provenance-v1",
                "source_copy_ref": source_copy_ref,
                "copy_changes": deepcopy(copy_changes[section_id]),
                "field_provenance": field_provenance,
            },
        }
        overlay = dict(copy_ref["lg11_copy_overlay"])
        copy_ref["lg11_copy_overlay"] = {**overlay, "overlay_hash": _canonical_hash(overlay)}
        raw_section["copy_ref"] = copy_ref
    payload = deepcopy(updated)
    payload.pop("input_hash", None)
    return {**payload, "input_hash": _canonical_hash(payload)}


def build_lg11_copy_version_fork(
    *,
    source_version: DetailPageVersion,
    edit_run_id: str,
    intent: dict[str, Any],
) -> dict[str, Any]:
    """Build an immutable, provider-free LG-11 copy fork from one frozen version.

    The returned plan is checkpoint-safe.  The graph projector persists it
    idempotently so a checkpoint/projection crash can reconstruct the exact
    DetailPageVersion without rerunning an image provider or reading mutable
    page state.
    """

    frozen_targets = _lg11_frozen_edit_targets(source_version)
    intent_payload = dict(intent or {})
    intent_hash = str(intent_payload.pop("intent_hash", "") or "")
    if (
        intent_payload.get("schema_version") != LG11_EDIT_INTENT_SCHEMA_VERSION
        or not _SHA256_HEX.fullmatch(intent_hash)
        or _canonical_hash(intent_payload) != intent_hash
        or str(intent_payload.get("base_detail_page_version_id") or "") != source_version.id
        or str(intent_payload.get("base_snapshot_hash") or "") != frozen_targets["snapshot_hash"]
        or str(intent_payload.get("scope") or "") != "copy"
    ):
        raise EditIntentValidationError("LG-11 copy fork requires the matching immutable EditIntent.")

    target_ids = [str(value) for value in intent_payload.get("target_ids") or []]
    if not target_ids or len(set(target_ids)) != len(target_ids):
        raise EditIntentValidationError("LG-11 copy fork requires stable selected section targets.")
    _lg11_target_descriptions(
        version=source_version,
        scope="copy",
        target_ids=target_ids,
        targets=frozen_targets,
    )
    copy_changes = _normalize_lg11_copy_changes(
        scope="copy",
        target_ids=target_ids,
        copy_changes=intent_payload.get("copy_changes"),
        targets=frozen_targets,
    )
    if not copy_changes:
        raise EditIntentValidationError("LG-11 copy fork requires explicit direct-editor copy changes.")
    preview = preview_lg11_edit_intent(
        version=source_version,
        scope="copy",
        target_ids=target_ids,
        operation=str(intent_payload.get("operation") or ""),
        instruction=str(intent_payload.get("instruction") or ""),
        preserve_constraints=dict(intent_payload.get("preserve_constraints") or {}),
        copy_changes=copy_changes,
    )
    if preview["edit_intent"] != intent:
        raise EditIntentValidationError("LG-11 copy fork intent does not match its frozen impact preview.")
    if bool(preview["impact_preview"].get("requires_evidence_review")):
        raise EditIntentValidationError("Fact-sensitive copy changes require evidence review before version fork.")

    copy_change_provenance = deepcopy(dict(intent_payload.get("copy_change_provenance") or {}))
    if copy_change_provenance != preview["edit_intent"].get("copy_change_provenance"):
        raise EditIntentValidationError("LG-11 copy fork requires matching frozen copy provenance.")
    canonical_input = _lg11_apply_copy_change_provenance(
        canonical_input=frozen_targets["canonical_input"],
        copy_changes=copy_changes,
        copy_change_provenance=copy_change_provenance,
    )
    try:
        page_assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical_input)
    except PageAssemblyInputError as error:
        raise EditIntentValidationError(str(error)) from error
    source_rendering = deepcopy(frozen_targets["rendering"])
    copy_set = _lg11_copy_set_from_frozen_rendering(
        canonical_input=canonical_input,
        rendering=source_rendering,
    )
    for section_changes in copy_changes.values():
        copy_set.update(section_changes)
    try:
        rendered = render_lg10_canonical_page_html(
            canonical_page_assembly_input=canonical_input,
            page_assembly=page_assembly,
            copy_set=copy_set,
            brand_tokens=deepcopy(dict(source_rendering.get("brand_tokens") or {})),
        )
    except ValueError as error:
        raise EditIntentValidationError(str(error)) from error
    rendering_payload = {
        **rendered,
        "canonical_input_ref": {
            "schema_version": LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION,
            "input_hash": str(canonical_input.get("input_hash") or ""),
        },
        "page_assembly_ref": {
            "schema_version": LG10_PAGE_ASSEMBLY_SCHEMA_VERSION,
            "assembly_hash": str(page_assembly.get("assembly_hash") or ""),
        },
    }
    if (
        rendering_payload["canonical_input_ref"] != {
            "schema_version": LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION,
            "input_hash": str(canonical_input.get("input_hash") or ""),
        }
        or rendering_payload["page_assembly_ref"] != {
            "schema_version": LG10_PAGE_ASSEMBLY_SCHEMA_VERSION,
            "assembly_hash": str(page_assembly.get("assembly_hash") or ""),
        }
    ):
        raise EditIntentValidationError("LG-11 copy fork requires matching immutable renderer references.")
    rendering = {**rendering_payload, "render_hash": _canonical_hash(rendering_payload)}

    source_snapshot = deepcopy(dict(source_version.sections_json or {}))
    source_snapshot.pop("snapshot_hash", None)
    source_snapshot["lg10"] = {
        **dict(source_snapshot.get("lg10") or {}),
        "canonical_page_assembly_input": canonical_input,
        "page_assembly": page_assembly,
        "canonical_rendering": rendering,
    }
    preview_sections = _lg10_preview_sections(rendering)
    brand_tokens = dict(rendering.get("brand_tokens") or {})
    source_snapshot["commerce_renderer"] = {
        "theme_color": str((brand_tokens.get("color_tokens") or {}).get("surface") or "#ffffff"),
        "font_family": str((brand_tokens.get("typography") or {}).get("body_font") or "system-ui, sans-serif"),
        "brand_assets": _lg10_preview_brand_assets(rendering),
        "sections": preview_sections,
    }
    source_snapshot["sections"] = preview_sections
    source_snapshot["lg11"] = {
        "schema_version": "lg11-copy-version-fork-v1",
        "edit_run_id": edit_run_id,
        "source_detail_page_version_id": source_version.id,
        "parent_detail_page_version_id": source_version.id,
        "intent_id": intent_hash,
        "copy_changes": deepcopy(copy_changes),
        "copy_provenance": copy_change_provenance,
    }
    snapshot = {**source_snapshot, "snapshot_hash": _canonical_hash(source_snapshot)}
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sellform:lg11:{edit_run_id}:{rendering['render_hash']}"))
    return {
        "schema_version": "lg11-copy-version-fork-v1",
        "detail_page_version_id": version_id,
        "snapshot_hash": snapshot["snapshot_hash"],
        "source_detail_page_version_id": source_version.id,
        "parent_detail_page_version_id": source_version.id,
        "edit_run_id": edit_run_id,
        "intent_id": intent_hash,
        "snapshot": snapshot,
    }


def persist_lg11_copy_version_fork(
    *,
    run: AgentRun,
    copy_version_fork: dict[str, Any],
    db: Session,
) -> DetailPageVersion:
    """Persist one checkpointed copy-fork plan without mutating its source."""

    fork = deepcopy(dict(copy_version_fork or {}))
    snapshot = dict(fork.get("snapshot") or {})
    snapshot_hash = str(snapshot.pop("snapshot_hash", "") or "")
    version_id = str(fork.get("detail_page_version_id") or "")
    if (
        fork.get("schema_version") != "lg11-copy-version-fork-v1"
        or not version_id
        or str(fork.get("edit_run_id") or "") != run.id
        or str(fork.get("source_detail_page_version_id") or "") != str(fork.get("parent_detail_page_version_id") or "")
        or not _SHA256_HEX.fullmatch(snapshot_hash)
        or snapshot_hash != str(fork.get("snapshot_hash") or "")
        or _canonical_hash(snapshot) != snapshot_hash
    ):
        raise EditIntentValidationError("LG-11 copy fork checkpoint is not an immutable version plan.")
    lineage = dict(snapshot.get("lg11") or {})
    if (
        lineage.get("schema_version") != "lg11-copy-version-fork-v1"
        or str(lineage.get("edit_run_id") or "") != run.id
        or str(lineage.get("source_detail_page_version_id") or "") != str(fork.get("source_detail_page_version_id") or "")
        or str(lineage.get("parent_detail_page_version_id") or "") != str(fork.get("parent_detail_page_version_id") or "")
        or str(lineage.get("intent_id") or "") != str(fork.get("intent_id") or "")
    ):
        raise EditIntentValidationError("LG-11 copy fork lineage does not match its frozen snapshot.")
    source = db.query(DetailPageVersion).filter(
        DetailPageVersion.id == str(fork["source_detail_page_version_id"]),
        DetailPageVersion.project_id == run.project_id,
    ).first()
    if source is None:
        raise EditIntentValidationError("LG-11 copy fork source version is not in this project.")
    _lg11_frozen_edit_targets(source)

    stored_snapshot = {**snapshot, "snapshot_hash": snapshot_hash}
    existing = db.query(DetailPageVersion).filter(
        DetailPageVersion.id == version_id,
        DetailPageVersion.project_id == run.project_id,
    ).first()
    if existing is not None:
        if existing.sections_json != stored_snapshot:
            raise EditIntentValidationError("LG-11 copy fork identity does not match its immutable snapshot.")
        return existing

    db.query(DetailPageVersion).filter(
        DetailPageVersion.project_id == run.project_id,
        DetailPageVersion.is_final == True,  # noqa: E712
    ).update({"is_final": False})
    version = DetailPageVersion(
        id=version_id,
        project_id=run.project_id,
        name="LG-11 copy edited detail page",
        style_key=source.style_key,
        sections_json=stored_snapshot,
        is_final=True,
    )
    db.add(version)
    db.flush()
    return version


def build_lg11_style_version_fork(
    *,
    run: AgentRun,
    source_version: DetailPageVersion,
    edit_run_id: str,
    intent: dict[str, Any],
    db: Session,
) -> dict[str, Any]:
    """Reassemble a frozen page with only a pinned style/Brand Kit change."""

    frozen = _lg11_frozen_edit_targets(source_version)
    intent_payload = deepcopy(dict(intent or {}))
    intent_hash = str(intent_payload.pop("intent_hash", "") or "")
    if (
        intent_payload.get("schema_version") != LG11_EDIT_INTENT_SCHEMA_VERSION
        or not _SHA256_HEX.fullmatch(intent_hash)
        or _canonical_hash(intent_payload) != intent_hash
        or str(intent_payload.get("base_detail_page_version_id") or "") != source_version.id
        or str(intent_payload.get("base_snapshot_hash") or "") != frozen["snapshot_hash"]
        or str(intent_payload.get("scope") or "") != "style"
    ):
        raise EditIntentValidationError("LG-11 style fork requires one immutable frozen style intent.")

    style_change = dict(intent_payload.get("style_change") or {})
    source_canonical = deepcopy(frozen["canonical_input"])
    source_direction = normalize_lg10_design_direction(source_canonical.get("design_direction"))
    source_brand_ref = deepcopy(dict(source_canonical.get("brand_kit_ref") or {}))
    design_direction = normalize_lg10_design_direction(style_change.get("design_direction"))
    brand_kit_ref = deepcopy(dict(style_change.get("brand_kit_ref") or {}))
    if (
        style_change.get("source_design_direction") != source_direction
        or dict(style_change.get("source_brand_kit_ref") or {}) != source_brand_ref
        or bool(brand_kit_ref) and (
            not str(brand_kit_ref.get("brand_kit_version_id") or "")
            or not _SHA256_HEX.fullmatch(str(brand_kit_ref.get("brand_kit_hash") or ""))
        )
        or (design_direction == source_direction and brand_kit_ref == source_brand_ref)
    ):
        raise EditIntentValidationError("LG-11 style fork does not match its frozen style-change contract.")

    canonical = deepcopy(source_canonical)
    canonical["design_direction"] = design_direction
    canonical["brand_kit_ref"] = brand_kit_ref
    canonical_payload = deepcopy(canonical)
    canonical_payload.pop("input_hash", None)
    canonical = {**canonical_payload, "input_hash": _canonical_hash(canonical_payload)}
    try:
        page_assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical)
        brand_tokens = resolve_lg10_brand_renderer_tokens(
            run=run,
            brand_kit_ref=brand_kit_ref,
            db=db,
        )
        rendered = render_lg10_canonical_page_html(
            canonical_page_assembly_input=canonical,
            page_assembly=page_assembly,
            copy_set=_lg11_copy_set_from_frozen_rendering(
                canonical_input=canonical,
                rendering=deepcopy(frozen["rendering"]),
            ),
            brand_tokens=brand_tokens,
        )
    except (PageAssemblyInputError, ValueError) as error:
        raise EditIntentValidationError(str(error)) from error
    rendering_payload = {
        **rendered,
        "canonical_input_ref": {
            "schema_version": LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION,
            "input_hash": canonical["input_hash"],
        },
        "page_assembly_ref": {
            "schema_version": LG10_PAGE_ASSEMBLY_SCHEMA_VERSION,
            "assembly_hash": page_assembly["assembly_hash"],
        },
    }
    rendering = {**rendering_payload, "render_hash": _canonical_hash(rendering_payload)}

    snapshot = deepcopy(dict(source_version.sections_json or {}))
    snapshot.pop("snapshot_hash", None)
    snapshot["lg10"] = {
        **dict(snapshot.get("lg10") or {}),
        "canonical_page_assembly_input": canonical,
        "page_assembly": page_assembly,
        "canonical_rendering": rendering,
    }
    brand_tokens = dict(rendering.get("brand_tokens") or {})
    preview_sections = _lg10_preview_sections(rendering)
    snapshot["commerce_renderer"] = {
        "theme_color": str((brand_tokens.get("color_tokens") or {}).get("surface") or "#ffffff"),
        "font_family": str((brand_tokens.get("typography") or {}).get("body_font") or "system-ui, sans-serif"),
        "brand_assets": _lg10_preview_brand_assets(rendering),
        "sections": preview_sections,
    }
    snapshot["sections"] = preview_sections
    snapshot["lg11"] = {
        "schema_version": "lg11-style-version-fork-v1",
        "edit_run_id": edit_run_id,
        "source_detail_page_version_id": source_version.id,
        "parent_detail_page_version_id": source_version.id,
        "intent_id": intent_hash,
        "style_change": deepcopy(style_change),
        "retained": {
            "approved_asset_manifest_hash": str(
                (source_canonical.get("approved_asset_manifest") or {}).get("manifest_hash") or ""
            ) or None,
            "page_asset_manifest_hash": str(
                (source_canonical.get("page_asset_manifest") or {}).get("manifest_hash") or ""
            ),
            "section_ids": sorted(frozen["sections"]),
            "scene_ids": sorted(frozen["scenes"]),
            "fact_ids": sorted(frozen["facts"]),
        },
    }
    snapshot = {**snapshot, "snapshot_hash": _canonical_hash(snapshot)}
    version_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"sellform:lg11-style:{edit_run_id}:{rendering['render_hash']}",
    ))
    return {
        "schema_version": "lg11-style-version-fork-v1",
        "detail_page_version_id": version_id,
        "snapshot_hash": snapshot["snapshot_hash"],
        "source_detail_page_version_id": source_version.id,
        "parent_detail_page_version_id": source_version.id,
        "edit_run_id": edit_run_id,
        "intent_id": intent_hash,
        "snapshot": snapshot,
    }


def persist_lg11_style_version_fork(
    *,
    run: AgentRun,
    style_version_fork: dict[str, Any],
    db: Session,
) -> DetailPageVersion:
    """Persist one idempotent, immutable LG-11 style reassembly result."""

    fork = deepcopy(dict(style_version_fork or {}))
    snapshot = dict(fork.get("snapshot") or {})
    snapshot_hash = str(snapshot.pop("snapshot_hash", "") or "")
    version_id = str(fork.get("detail_page_version_id") or "")
    if (
        fork.get("schema_version") != "lg11-style-version-fork-v1"
        or not version_id
        or str(fork.get("edit_run_id") or "") != run.id
        or str(fork.get("source_detail_page_version_id") or "") != str(fork.get("parent_detail_page_version_id") or "")
        or not _SHA256_HEX.fullmatch(snapshot_hash)
        or snapshot_hash != str(fork.get("snapshot_hash") or "")
        or _canonical_hash(snapshot) != snapshot_hash
    ):
        raise EditIntentValidationError("LG-11 style fork checkpoint is not an immutable version plan.")
    lineage = dict(snapshot.get("lg11") or {})
    if (
        lineage.get("schema_version") != "lg11-style-version-fork-v1"
        or str(lineage.get("edit_run_id") or "") != run.id
        or str(lineage.get("source_detail_page_version_id") or "") != str(fork.get("source_detail_page_version_id") or "")
        or str(lineage.get("parent_detail_page_version_id") or "") != str(fork.get("parent_detail_page_version_id") or "")
        or str(lineage.get("intent_id") or "") != str(fork.get("intent_id") or "")
    ):
        raise EditIntentValidationError("LG-11 style fork lineage does not match its frozen snapshot.")
    source = db.query(DetailPageVersion).filter(
        DetailPageVersion.id == str(fork["source_detail_page_version_id"]),
        DetailPageVersion.project_id == run.project_id,
    ).first()
    if source is None:
        raise EditIntentValidationError("LG-11 style fork source version is not in this project.")
    _lg11_frozen_edit_targets(source)

    stored_snapshot = {**snapshot, "snapshot_hash": snapshot_hash}
    existing = db.query(DetailPageVersion).filter(
        DetailPageVersion.id == version_id,
        DetailPageVersion.project_id == run.project_id,
    ).first()
    if existing is not None:
        if existing.sections_json != stored_snapshot:
            raise EditIntentValidationError("LG-11 style fork identity does not match its immutable snapshot.")
        return existing

    db.query(DetailPageVersion).filter(
        DetailPageVersion.project_id == run.project_id,
        DetailPageVersion.is_final == True,  # noqa: E712
    ).update({"is_final": False})
    version = DetailPageVersion(
        id=version_id,
        project_id=run.project_id,
        name="LG-11 style edited detail page",
        style_key=str(
            dict(dict(stored_snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {}).get("design_direction")
            or source.style_key
        ),
        sections_json=stored_snapshot,
        is_final=True,
    )
    db.add(version)
    db.flush()
    return version


_LG11_CANVAS_DRAFT_SCHEMA = "lg11-canvas-draft-v1"
_LG11_CANVAS_FORK_SCHEMA = "lg11-canvas-version-fork-v1"
_LG11_CANVAS_ELEMENT_KINDS = {"background", "text", "asset", "mask", "icon", "decorative"}
_LG11_CANVAS_DECORATIVE_TOKENS = {
    "mask": {"rounded", "circle", "fade"},
    "icon": {"check", "info", "sparkle"},
    "decorative": {"divider", "badge", "shape"},
}


def _lg11_canvas_section_assets(section: dict[str, Any]) -> list[dict[str, str]]:
    mode = str(section.get("rendering_mode") or "")
    raw_assets = (
        section.get("approved_assets") if mode == "approved_asset"
        else section.get("seller_owned_fallback_assets") if mode == "seller_owned_fallback"
        else []
    )
    return [
        {"asset_id": str(item.get("asset_id") or ""), "asset_content_hash": str(item.get("asset_content_hash") or "")}
        for item in list(raw_assets or []) if isinstance(item, dict) and item.get("asset_id")
    ]


def _lg11_canvas_default_elements(section: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive the small, stable element set from an immutable section contract."""
    section_id = str(section.get("section_id") or "")
    if not section_id:
        raise EditIntentValidationError("LG-11 Canvas element requires a stable section identity.")
    elements = [{"element_id": f"{section_id}:background", "kind": "background", "x": 0, "y": 0,
                 "width": 760, "height": 160, "z_index": 0, "locked": False, "group_id": None}]
    if list(dict(section.get("copy_ref") or {}).get("fields") or []):
        elements.append({"element_id": f"{section_id}:text", "kind": "text", "x": 0, "y": 0,
                         "width": 712, "height": 120, "z_index": 2, "locked": False, "group_id": None})
    assets = _lg11_canvas_section_assets(section)
    for index, asset in enumerate(assets):
        # Existing one-asset versions retain their original stable ID.  More
        # than one figure gets an asset-qualified ID and can therefore move,
        # lock, and group independently.
        element_id = f"{section_id}:asset" if len(assets) == 1 else f"{section_id}:asset:{asset['asset_id']}"
        elements.append({"element_id": element_id, "kind": "asset", "x": 0, "y": index * 12,
                         "width": 712, "height": 320, "z_index": 1 + index, "locked": False, "group_id": None,
                         **asset})
    return elements


def _lg11_canvas_normalize_section_elements(section: dict[str, Any]) -> None:
    """Validate the frozen, allow-listed Canvas element contract."""
    section_id = str(section.get("section_id") or "")
    expected = {item["element_id"]: item for item in _lg11_canvas_default_elements(section)}
    raw_elements = section.get("canvas_elements")
    elements = _lg11_canvas_default_elements(section) if raw_elements is None else list(raw_elements or [])
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in elements:
        item = dict(raw or {})
        element_id, kind = str(item.get("element_id") or ""), str(item.get("kind") or "")
        if element_id in seen or kind not in _LG11_CANVAS_ELEMENT_KINDS or not element_id.startswith(f"{section_id}:"):
            raise EditIntentValidationError("LG-11 Canvas element identity is invalid.")
        base = expected.get(element_id)
        if base is not None and base["kind"] != kind:
            raise EditIntentValidationError("LG-11 Canvas element identity is invalid.")
        if base is None and not (
            isinstance(item.get("origin_element_id"), str) and item.get("origin_element_id")
            or kind in _LG11_CANVAS_DECORATIVE_TOKENS and item.get("token") in _LG11_CANVAS_DECORATIVE_TOKENS[kind]
        ):
            raise EditIntentValidationError("LG-11 Canvas element is not derived from an allowed element token.")
        seen.add(element_id)
        numbers = {key: item.get(key) for key in ("x", "y", "width", "height", "z_index")}
        if (not all(isinstance(value, int) for value in numbers.values())
                or not -2400 <= numbers["x"] <= 2400 or not -2400 <= numbers["y"] <= 2400
                or not 1 <= numbers["width"] <= 760 or not 1 <= numbers["height"] <= 2400
                or not 0 <= numbers["z_index"] <= 100 or not isinstance(item.get("locked"), bool)
                or item.get("group_id") is not None and not isinstance(item.get("group_id"), str)
                or not isinstance(item.get("deleted", False), bool)):
            raise EditIntentValidationError("LG-11 Canvas element bounds are invalid.")
        normalized_item = {"element_id": element_id, "kind": kind, **numbers, "locked": item["locked"],
                           "group_id": item.get("group_id"), "deleted": bool(item.get("deleted", False))}
        allowed_overlap_with = item.get("allowed_overlap_with")
        if allowed_overlap_with is not None:
            if (
                kind not in _LG11_CANVAS_DECORATIVE_TOKENS
                or not isinstance(allowed_overlap_with, list)
                or not all(isinstance(value, str) and value.startswith(f"{section_id}:") for value in allowed_overlap_with)
            ):
                raise EditIntentValidationError("LG-11 Canvas overlap relationship is invalid.")
            normalized_item["allowed_overlap_with"] = sorted(set(allowed_overlap_with))
        if kind == "asset":
            asset_id = str(item.get("asset_id") or (base or {}).get("asset_id") or "")
            asset_hash = str(item.get("asset_content_hash") or (base or {}).get("asset_content_hash") or "")
            if not asset_id or not _SHA256_HEX.fullmatch(asset_hash):
                raise EditIntentValidationError("LG-11 Canvas asset element requires a SHA-256 identity.")
            normalized_item.update({"asset_id": asset_id, "asset_content_hash": asset_hash})
        if kind in _LG11_CANVAS_DECORATIVE_TOKENS:
            token = item.get("token")
            if token not in _LG11_CANVAS_DECORATIVE_TOKENS[kind]:
                raise EditIntentValidationError("LG-11 Canvas decorative token is not allowed.")
            normalized_item["token"] = token
        if base is None:
            normalized_item["origin_element_id"] = str(item.get("origin_element_id") or "")
        seen.add(element_id)
        normalized.append(normalized_item)
    if not set(expected).issubset(seen):
        raise EditIntentValidationError("LG-11 Canvas must retain every immutable section element.")
    section["canvas_elements"] = sorted(normalized, key=lambda item: (int(item["z_index"]), item["element_id"]))


def _lg11_canvas_validate_groups(canonical: dict[str, Any], groups: list[Any]) -> list[dict[str, Any]]:
    element_by_id = {
        str(element.get("element_id")): (element, str(dict(section or {}).get("section_id") or ""))
        for section in canonical.get("sections") or []
        for element in list(dict(section or {}).get("canvas_elements") or [])
    }
    normalized: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for raw in groups:
        group = dict(raw or {})
        group_id = str(group.get("group_id") or "")
        child_ids = [str(value) for value in group.get("child_element_ids") or []]
        if not group_id or len(child_ids) < 2 or len(child_ids) != len(set(child_ids)) or not isinstance(group.get("locked"), bool):
            raise EditIntentValidationError("LG-11 Canvas group is invalid.")
        sections = {element_by_id[element_id][1] for element_id in child_ids if element_id in element_by_id}
        if len(sections) != 1 or any(element_id not in element_by_id for element_id in child_ids) or assigned.intersection(child_ids):
            raise EditIntentValidationError("LG-11 Canvas group members are invalid.")
        if any(str(element_by_id[element_id][0].get("group_id") or "") != group_id for element_id in child_ids):
            raise EditIntentValidationError("LG-11 Canvas group membership is inconsistent.")
        assigned.update(child_ids)
        normalized.append({"group_id": group_id, "section_id": sections.pop(), "child_element_ids": sorted(child_ids), "locked": group["locked"]})
    if any(element.get("group_id") and str(element.get("element_id")) not in assigned for element, _ in element_by_id.values()):
        raise EditIntentValidationError("LG-11 Canvas element references an unknown group.")
    return sorted(normalized, key=lambda item: item["group_id"])


def _lg11_canvas_history_snapshot(canonical: dict[str, Any], groups: list[Any]) -> dict[str, Any]:
    return {"canonical_page_assembly_input": deepcopy(canonical), "element_groups": deepcopy(groups)}


def _lg11_canvas_restore_history(value: Any) -> tuple[dict[str, Any], list[Any]]:
    item = dict(value or {})
    if "canonical_page_assembly_input" in item:
        return deepcopy(dict(item["canonical_page_assembly_input"])), deepcopy(list(item.get("element_groups") or []))
    # TASK-11.7 checkpoints held a canonical input directly; retain resume compatibility.
    return deepcopy(item), []


def _lg11_canvas_hash(value: dict[str, Any]) -> str:
    payload = deepcopy(value)
    payload.pop("draft_hash", None)
    return _canonical_hash(payload)


def _lg11_canvas_finalize_draft(value: dict[str, Any]) -> dict[str, Any]:
    draft = deepcopy(value)
    canonical = dict(draft.get("canonical_page_assembly_input") or {})
    if canonical:
        # Persist the same deterministic channel result with the checkpoint so
        # a resumed Canvas review never needs to inspect mutable page state.
        from src.services.page_visual_contract import validate_lg11_canvas_safety
        source = {"lg11": {"canvas_revision": int(draft.get("revision") or 0)}, "lg10": {"canonical_page_assembly_input": canonical}}
        draft["safety_validation"] = {
            channel: validate_lg11_canvas_safety(version_snapshot=source, channel=channel)
            for channel in ("smartstore", "coupang")
        }
    draft["draft_hash"] = _lg11_canvas_hash(draft)
    return draft


def _lg11_canvas_validate_draft(draft: dict[str, Any]) -> None:
    if (
        draft.get("schema_version") != _LG11_CANVAS_DRAFT_SCHEMA
        or not str(draft.get("edit_run_id") or "")
        or not _SHA256_HEX.fullmatch(str(draft.get("draft_hash") or ""))
        or _lg11_canvas_hash(draft) != str(draft.get("draft_hash") or "")
        or not isinstance(draft.get("canonical_page_assembly_input"), dict)
        or not isinstance(draft.get("undo_stack"), list)
        or not isinstance(draft.get("redo_stack"), list)
    ):
        raise EditIntentValidationError("LG-11 canvas draft is not a valid immutable-source checkpoint.")
    _lg11_canvas_validate_groups(dict(draft["canonical_page_assembly_input"]), list(draft.get("element_groups") or []))


def _lg11_canvas_rehash(
    canonical: dict[str, Any], *, enforce_safety: bool = True,
) -> dict[str, Any]:
    payload = deepcopy(canonical)
    payload.pop("input_hash", None)
    sections = list(payload.get("sections") or [])
    for index, raw in enumerate(sections):
        section = dict(raw or {})
        canvas = dict(section.get("canvas") or {})
        visible = canvas.get("is_visible", True)
        height = canvas.get("height_px")
        if not isinstance(visible, bool) or height is not None and (not isinstance(height, int) or height < 160 or height > 2400):
            raise EditIntentValidationError("LG-11 canvas section bounds are invalid.")
        section["sort_order"] = index
        section["canvas"] = {"is_visible": visible, "height_px": height, **({"origin": canvas["origin"]} if canvas.get("origin") else {})}
        _lg11_canvas_normalize_section_elements(section)
        sections[index] = section
    payload["sections"] = sections
    if enforce_safety:
        _lg11_validate_canvas_safety(payload)
    return {**payload, "input_hash": _canonical_hash(payload)}


def _lg11_canvas_is_final_spec(section: dict[str, Any]) -> bool:
    section_id = str(section.get("section_id") or "").strip().lower()
    return section_id in {"specs", *FINAL_SPEC_TYPES} or section_id.endswith("_specs")


def _lg11_validate_canvas_safety(canonical: dict[str, Any]) -> None:
    """Keep an existing final-spec section visible and last before commit/export."""
    sections = [dict(item or {}) for item in canonical.get("sections") or []]
    final_positions = [index for index, section in enumerate(sections) if _lg11_canvas_is_final_spec(section)]
    if final_positions and (
        len(final_positions) != 1
        or final_positions[0] != len(sections) - 1
        or not bool(dict(sections[final_positions[-1]].get("canvas") or {}).get("is_visible", True))
    ):
        raise EditIntentValidationError("LG-11 Canvas requires the final specification section to remain visible and last.")


def build_lg11_canvas_draft(
    *,
    source_version: DetailPageVersion,
    edit_run_id: str,
    intent: dict[str, Any],
    allow_unsafe_source_repair: bool = False,
) -> dict[str, Any]:
    """Derive a reversible, section-only draft without touching the source version."""
    frozen = _lg11_frozen_edit_targets(source_version)
    payload = deepcopy(dict(intent or {}))
    intent_hash = str(payload.pop("intent_hash", "") or "")
    if (
        payload.get("schema_version") != LG11_EDIT_INTENT_SCHEMA_VERSION
        or not _SHA256_HEX.fullmatch(intent_hash)
        or _canonical_hash(payload) != intent_hash
        or payload.get("scope") != "page" or payload.get("operation") != "canvas_draft"
        or str(payload.get("base_detail_page_version_id") or "") != source_version.id
        or str(payload.get("base_snapshot_hash") or "") != frozen["snapshot_hash"]
    ):
        raise EditIntentValidationError("LG-11 canvas requires a matching frozen page EditIntent.")
    # A frozen legacy/page-assembly snapshot can itself be the object that a
    # deterministic quality rework must repair.  Permit that one caller to
    # construct a draft from the unsafe source, but keep the normalised draft
    # bounded and require Canvas safety again after every applied command and
    # before an immutable child can be frozen.
    canonical = _lg11_canvas_rehash(
        deepcopy(frozen["canonical_input"]),
        enforce_safety=not allow_unsafe_source_repair,
    )
    source_canvas_groups = deepcopy(list(dict(source_version.sections_json or {}).get("lg11", {}).get("canvas_element_groups") or []))
    source_canvas_groups = _lg11_canvas_validate_groups(canonical, source_canvas_groups)
    return _lg11_canvas_finalize_draft({
        "schema_version": _LG11_CANVAS_DRAFT_SCHEMA, "edit_run_id": edit_run_id,
        "source_detail_page_version_id": source_version.id, "parent_detail_page_version_id": source_version.id,
        "source_snapshot_hash": frozen["snapshot_hash"], "intent_id": intent_hash,
        "canonical_page_assembly_input": canonical, "element_groups": source_canvas_groups, "undo_stack": [], "redo_stack": [],
        "applied_operation_ids": [], "revision": 0,
    })


def _lg11_canvas_required(section: dict[str, Any]) -> bool:
    """Keep fact/spec-bearing source sections visible and structurally safe."""
    copy_ref = dict(section.get("copy_ref") or {})
    return bool(copy_ref.get("fact_ids") or copy_ref.get("evidence_ids_by_fact") or section.get("approved_assets"))


def _lg11_canvas_asset_replacement(*, canonical: dict[str, Any], asset_id: str, asset_content_hash: str, db: Session | None, project_id: str | None) -> dict[str, str]:
    """Return one immutable Canvas asset reference after the existing rights gate."""
    if (not db or not project_id or not asset_id or not _SHA256_HEX.fullmatch(asset_content_hash)
            or asset_id.startswith(("http:", "https:", "data:")) or any(token in asset_id for token in ("<", ">", "/"))):
        raise EditIntentValidationError("LG-11 Canvas asset replacement requires a local approved asset identity.")
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if asset is None or not _SHA256_HEX.fullmatch(str(asset.content_hash or "")) or asset.content_hash != asset_content_hash:
        raise EditIntentValidationError("LG-11 Canvas replacement asset hash is invalid.")
    if not asset.file_path or not os.path.isfile(asset.file_path) or image_sha256(asset.file_path) != asset.content_hash:
        raise EditIntentValidationError("LG-11 Canvas replacement asset bytes do not match its frozen SHA-256 identity.")
    approved = any(
        str(entry.get("asset_id") or "") == asset.id and str(entry.get("asset_content_hash") or "") == asset.content_hash
        for section in canonical.get("sections") or [] for entry in list(dict(section or {}).get("approved_assets") or [])
        if isinstance(entry, dict)
    )
    usage = str(asset.usage_status or "").lower()
    source = str(asset.source_type or "").lower()
    seller_owned = usage in {"seller_owned", "rights_confirmed"} and source not in REFERENCE_SOURCE_TYPES and not source.startswith("supplier")
    if not approved and not seller_owned:
        raise EditIntentValidationError("LG-11 Canvas replacement only permits approved or rights-confirmed seller-owned assets.")
    return {"asset_id": asset.id, "asset_content_hash": asset.content_hash}


def apply_lg11_canvas_command(*, canvas_draft: dict[str, Any], decision: str, command: dict[str, Any] | None,
                              db: Session | None = None, project_id: str | None = None) -> dict[str, Any]:
    """Apply one idempotent section or deterministic element Canvas command."""
    draft = deepcopy(dict(canvas_draft or {}))
    _lg11_canvas_validate_draft(draft)
    command = dict(command or {})
    operation_id = str(command.get("operation_id") or "")
    if not operation_id:
        raise EditIntentValidationError("LG-11 canvas commands require an operation_id.")
    if operation_id in set(str(value) for value in draft.get("applied_operation_ids") or []):
        return draft
    current = deepcopy(dict(draft["canonical_page_assembly_input"]))
    groups = deepcopy(list(draft.get("element_groups") or []))
    undo, redo = list(draft["undo_stack"]), list(draft["redo_stack"])
    if decision == "undo":
        if not undo:
            raise EditIntentValidationError("LG-11 canvas undo has no previous draft state.")
        redo.append(_lg11_canvas_history_snapshot(current, groups)); current, groups = _lg11_canvas_restore_history(undo.pop())
    elif decision == "redo":
        if not redo:
            raise EditIntentValidationError("LG-11 canvas redo has no later draft state.")
        undo.append(_lg11_canvas_history_snapshot(current, groups)); current, groups = _lg11_canvas_restore_history(redo.pop())
    elif decision == "apply":
        kind, section_id = str(command.get("kind") or ""), str(command.get("section_id") or "")
        sections = [dict(value or {}) for value in current.get("sections") or []]
        by_id = {str(section.get("section_id") or ""): index for index, section in enumerate(sections)}
        if kind not in {"reorder", "add", "remove", "duplicate", "set_visibility", "set_height", "move_element", "resize_element", "set_z_order", "set_lock", "group", "ungroup", "move_group", "create_element", "duplicate_element", "delete_element", "replace_element"}:
            raise EditIntentValidationError("LG-11 canvas operation is not allowed.")
        undo.append(_lg11_canvas_history_snapshot(current, groups)); redo = []
        elements = {
            str(element.get("element_id") or ""): element
            for section in sections for element in list(section.get("canvas_elements") or [])
        }
        element_section = {
            str(element.get("element_id") or ""): str(section.get("section_id") or "")
            for section in sections for element in list(section.get("canvas_elements") or [])
        }
        group_by_id = {str(group.get("group_id") or ""): group for group in groups}

        def editable_element(element_id: str) -> dict[str, Any]:
            element = elements.get(element_id)
            if element is None or bool(element.get("deleted")):
                raise EditIntentValidationError("LG-11 Canvas element is not in the frozen draft.")
            group = group_by_id.get(str(element.get("group_id") or ""))
            if bool(element.get("locked")) or group is not None and bool(group.get("locked")):
                raise EditIntentValidationError("LG-11 Canvas locked element cannot be changed.")
            return element

        if kind == "set_lock" and command.get("group_id"):
            group = group_by_id.get(str(command.get("group_id") or ""))
            locked = command.get("locked")
            if group is None or not isinstance(locked, bool):
                raise EditIntentValidationError("LG-11 Canvas group lock value is invalid.")
            group["locked"] = locked
        elif kind in {"move_element", "resize_element", "set_z_order", "set_lock", "duplicate_element", "delete_element", "replace_element"}:
            element_id = str(command.get("element_id") or "")
            element = elements.get(element_id)
            if element is None:
                raise EditIntentValidationError("LG-11 Canvas element is not in the frozen draft.")
            if kind == "set_lock":
                locked = command.get("locked")
                if not isinstance(locked, bool):
                    raise EditIntentValidationError("LG-11 Canvas lock value is invalid.")
                group = group_by_id.get(str(element.get("group_id") or ""))
                if group is not None and bool(group.get("locked")):
                    raise EditIntentValidationError("LG-11 Canvas locked group cannot be changed directly.")
                element["locked"] = locked
            elif kind == "duplicate_element":
                source = editable_element(element_id)
                duplicate_id = f"{element_section[element_id]}:{source['kind']}:duplicate-" + _canonical_hash({"run": draft["edit_run_id"], "op": operation_id})[:20]
                duplicate = {**deepcopy(source), "element_id": duplicate_id, "origin_element_id": str(source.get("origin_element_id") or element_id), "group_id": None, "locked": False, "deleted": False, "z_index": min(100, int(source["z_index"]) + 1)}
                target_section = sections[by_id[element_section[element_id]]]
                target_section["canvas_elements"] = [*list(target_section.get("canvas_elements") or []), duplicate]
            elif kind == "delete_element":
                element = editable_element(element_id)
                if element.get("group_id"):
                    raise EditIntentValidationError("LG-11 Canvas grouped elements must be ungrouped before deletion.")
                element["deleted"] = True
            elif kind == "replace_element":
                element = editable_element(element_id)
                if element.get("kind") != "asset":
                    raise EditIntentValidationError("LG-11 Canvas replacement only applies to asset elements.")
                asset = _lg11_canvas_asset_replacement(
                    canonical=current, asset_id=str(command.get("asset_id") or ""),
                    asset_content_hash=str(command.get("asset_content_hash") or ""), db=db, project_id=project_id,
                )
                element.update(asset)
            else:
                element = editable_element(element_id)
                if kind == "move_element":
                    dx, dy = command.get("dx"), command.get("dy")
                    if not isinstance(dx, int) or not isinstance(dy, int):
                        raise EditIntentValidationError("LG-11 Canvas movement is invalid.")
                    element["x"], element["y"] = element["x"] + dx, element["y"] + dy
                elif kind == "resize_element":
                    width, height = command.get("width"), command.get("height")
                    if not isinstance(width, int) or not isinstance(height, int):
                        raise EditIntentValidationError("LG-11 Canvas element size is invalid.")
                    element["width"], element["height"] = width, height
                else:
                    z_index = command.get("z_index")
                    if not isinstance(z_index, int):
                        raise EditIntentValidationError("LG-11 Canvas layer order is invalid.")
                    element["z_index"] = z_index
        elif kind == "group":
            child_ids = [str(value) for value in command.get("element_ids") or []]
            if len(child_ids) < 2 or len(child_ids) != len(set(child_ids)):
                raise EditIntentValidationError("LG-11 Canvas group requires at least two unique elements.")
            children = [editable_element(element_id) for element_id in child_ids]
            if len({element_section[element_id] for element_id in child_ids}) != 1 or any(element.get("group_id") for element in children):
                raise EditIntentValidationError("LG-11 Canvas group must contain ungrouped elements from one section.")
            group_id = "canvas-group-" + _canonical_hash({"run": draft["edit_run_id"], "op": operation_id})[:20]
            for element in children:
                element["group_id"] = group_id
            groups.append({"group_id": group_id, "section_id": element_section[child_ids[0]], "child_element_ids": sorted(child_ids), "locked": False})
        elif kind == "ungroup":
            group_id = str(command.get("group_id") or "")
            group = group_by_id.get(group_id)
            if group is None:
                raise EditIntentValidationError("LG-11 Canvas group is not in the frozen draft.")
            if bool(group.get("locked")):
                raise EditIntentValidationError("LG-11 Canvas locked group cannot be changed.")
            for element_id in group.get("child_element_ids") or []:
                elements[str(element_id)]["group_id"] = None
            groups = [item for item in groups if str(item.get("group_id") or "") != group_id]
        elif kind == "move_group":
            group_id, dx, dy = str(command.get("group_id") or ""), command.get("dx"), command.get("dy")
            group = group_by_id.get(group_id)
            if group is None or not isinstance(dx, int) or not isinstance(dy, int):
                raise EditIntentValidationError("LG-11 Canvas group movement is invalid.")
            if bool(group.get("locked")):
                raise EditIntentValidationError("LG-11 Canvas locked group cannot be changed.")
            for element_id in group.get("child_element_ids") or []:
                element = editable_element(str(element_id)); element["x"], element["y"] = element["x"] + dx, element["y"] + dy
        elif kind == "create_element":
            if section_id not in by_id:
                raise EditIntentValidationError("LG-11 Canvas target section is not in the frozen draft.")
            element_kind = str(command.get("element_kind") or "")
            if element_kind not in _LG11_CANVAS_ELEMENT_KINDS:
                raise EditIntentValidationError("LG-11 Canvas element kind is not allowed.")
            token = command.get("token")
            if element_kind in _LG11_CANVAS_DECORATIVE_TOKENS and token not in _LG11_CANVAS_DECORATIVE_TOKENS[element_kind]:
                raise EditIntentValidationError("LG-11 Canvas decorative token is not allowed.")
            new_id = f"{section_id}:{element_kind}:canvas-" + _canonical_hash({"run": draft["edit_run_id"], "op": operation_id})[:20]
            element = {"element_id": new_id, "kind": element_kind, "x": 0, "y": 0, "width": 160, "height": 80, "z_index": 10, "locked": False, "group_id": None, "deleted": False, "origin_element_id": f"{section_id}:{element_kind}"}
            if element_kind in _LG11_CANVAS_DECORATIVE_TOKENS:
                element["token"] = token
            if element_kind == "asset":
                element.update(_lg11_canvas_asset_replacement(canonical=current, asset_id=str(command.get("asset_id") or ""), asset_content_hash=str(command.get("asset_content_hash") or ""), db=db, project_id=project_id))
            sections[by_id[section_id]]["canvas_elements"] = [*list(sections[by_id[section_id]].get("canvas_elements") or []), element]
        elif kind == "add":
            position = command.get("position", len(sections))
            if not isinstance(position, int) or position < 0 or position > len(sections):
                raise EditIntentValidationError("LG-11 canvas add position is invalid.")
            new_id = "canvas-" + _canonical_hash({"run": draft["edit_run_id"], "op": operation_id})[:20]
            if new_id in by_id: raise EditIntentValidationError("LG-11 canvas section identity already exists.")
            template = deepcopy(sections[-1]) if sections else {}
            template.update({"section_id": new_id, "copy_ref": {"fields": [], "fact_ids": [], "evidence_ids_by_fact": {}}, "approved_assets": [], "seller_owned_fallback_assets": [], "rendering_mode": "information_only", "image_required": False, "canvas": {"is_visible": True, "height_px": None, "origin": "canvas_added"}})
            template.pop("canvas_elements", None)
            sections.insert(position, template)
        elif kind in {"reorder", "duplicate", "remove", "set_visibility", "set_height"}:
            if section_id not in by_id: raise EditIntentValidationError("LG-11 canvas target section is not in the frozen draft.")
            index = by_id[section_id]
            if kind == "reorder":
                position = command.get("position")
                if not isinstance(position, int) or position < 0 or position >= len(sections): raise EditIntentValidationError("LG-11 canvas reorder position is invalid.")
                sections.insert(position, sections.pop(index))
            elif kind == "duplicate":
                position = command.get("position", index + 1)
                if not isinstance(position, int) or position < 0 or position > len(sections): raise EditIntentValidationError("LG-11 canvas duplicate position is invalid.")
                duplicate = deepcopy(sections[index]); duplicate["section_id"] = "canvas-" + _canonical_hash({"run": draft["edit_run_id"], "op": operation_id})[:20]
                duplicate["canvas"] = {**dict(duplicate.get("canvas") or {}), "origin": "canvas_duplicate"}
                duplicate.pop("canvas_elements", None)
                sections.insert(position, duplicate)
            elif kind == "remove":
                if _lg11_canvas_required(sections[index]) or dict(sections[index].get("canvas") or {}).get("origin") not in {"canvas_added", "canvas_duplicate"}: raise EditIntentValidationError("LG-11 canvas cannot remove a frozen safety section.")
                sections.pop(index)
            elif kind == "set_visibility":
                value = command.get("is_visible")
                if not isinstance(value, bool) or not value and _lg11_canvas_required(sections[index]): raise EditIntentValidationError("LG-11 canvas cannot hide a frozen safety section.")
                sections[index]["canvas"] = {**dict(sections[index].get("canvas") or {}), "is_visible": value}
            else:
                height = command.get("height_px")
                if not isinstance(height, int) or height < 160 or height > 2400: raise EditIntentValidationError("LG-11 canvas height must be between 160 and 2400 pixels.")
                sections[index]["canvas"] = {**dict(sections[index].get("canvas") or {}), "height_px": height}
        current["sections"] = sections
    else:
        raise EditIntentValidationError("LG-11 canvas command decision is invalid.")
    canonical = _lg11_canvas_rehash(current)
    groups = _lg11_canvas_validate_groups(canonical, groups)
    draft.update({"canonical_page_assembly_input": canonical, "element_groups": groups, "undo_stack": undo, "redo_stack": redo,
                  "applied_operation_ids": [*draft.get("applied_operation_ids", []), operation_id], "revision": int(draft.get("revision") or 0) + 1})
    return _lg11_canvas_finalize_draft(draft)


def _apply_lg11_page_plan_successor(
    *, canonical: dict[str, Any], page_plan_reference: Mapping[str, Any],
    section_scene_contract: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Replace only frozen PagePlan identities after a verified plan successor.

    A Canvas reorder keeps all copy, assets, facts and unrelated sections in
    place.  This helper gives the child its own exact PagePlan/scene contract
    without mutating the source page or accepting an arbitrary caller ref.
    """

    plan_id = str(page_plan_reference.get("id") or "")
    plan_version = page_plan_reference.get("version")
    plan_hash = str(page_plan_reference.get("hash") or "")
    if not plan_id or not isinstance(plan_version, int) or plan_version < 1 or not _SHA256_HEX.fullmatch(plan_hash):
        raise EditIntentValidationError("LG-11 Canvas PagePlan successor identity is invalid.")
    contract = {str(item.get("section_id") or ""): dict(item) for item in section_scene_contract}
    value = deepcopy(canonical)
    sections = [dict(item) for item in list(value.get("sections") or [])]
    section_ids = [str(item.get("section_id") or "") for item in sections]
    if not sections or set(section_ids) != set(contract) or len(section_ids) != len(set(section_ids)):
        raise EditIntentValidationError("LG-11 Canvas PagePlan successor does not cover the frozen sections.")
    planning_refs = dict(value.get("planning_refs") or {})
    current_ref = dict(planning_refs.get("page_plan") or {})
    if not str(current_ref.get("artifact_id") or current_ref.get("id") or ""):
        raise EditIntentValidationError("LG-11 Canvas source has no frozen PagePlan reference.")
    planning_refs["page_plan"] = {
        **current_ref,
        "artifact_key": "page_planning",
        "artifact_id": plan_id,
        "artifact_version": plan_version,
        "artifact_hash": plan_hash,
    }
    value["planning_refs"] = planning_refs
    for section in sections:
        entry = contract[str(section["section_id"])]
        scene_ref = dict(section.get("scene_ref") or {})
        if not str(entry.get("scene_id") or "") or not str(entry.get("scene_type") or "") or not isinstance(entry.get("scene_order"), int):
            raise EditIntentValidationError("LG-11 Canvas PagePlan successor scene contract is incomplete.")
        section["scene_ref"] = {
            **scene_ref,
            "page_plan_id": plan_id,
            "page_plan_version": plan_version,
            "page_plan_hash": plan_hash,
            "scene_id": str(entry["scene_id"]),
            "scene_type": str(entry["scene_type"]),
            "scene_order": int(entry["scene_order"]),
        }
    value["sections"] = sections
    return _lg11_canvas_rehash(value)


def build_lg11_canvas_version_fork(*, run: AgentRun, source_version: DetailPageVersion, edit_run_id: str, intent: dict[str, Any], canvas_draft: dict[str, Any], page_plan_successor_ref: Mapping[str, Any] | None = None, page_plan_scene_contract: Sequence[Mapping[str, Any]] = (), quality_lineage_override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Commit a canvas draft as one immutable, deterministic child version."""
    frozen = _lg11_frozen_edit_targets(source_version); draft = deepcopy(canvas_draft); _lg11_canvas_validate_draft(draft)
    if str(draft.get("edit_run_id") or "") != edit_run_id or str(draft.get("source_detail_page_version_id") or "") != source_version.id: raise EditIntentValidationError("LG-11 canvas draft lineage does not match its edit run.")
    canonical = deepcopy(dict(draft["canonical_page_assembly_input"]))
    if page_plan_successor_ref is not None:
        canonical = _apply_lg11_page_plan_successor(
            canonical=canonical,
            page_plan_reference=page_plan_successor_ref,
            section_scene_contract=page_plan_scene_contract,
        )
    _lg11_validate_canvas_safety(canonical)
    try:
        assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical)
        rendered = render_lg10_canonical_page_html(canonical_page_assembly_input=canonical, page_assembly=assembly, copy_set=_lg11_copy_set_from_frozen_rendering(canonical_input=canonical, rendering=deepcopy(frozen["rendering"])), brand_tokens=deepcopy(dict(frozen["rendering"].get("brand_tokens") or {})))
    except (PageAssemblyInputError, ValueError) as error: raise EditIntentValidationError(str(error)) from error
    rendering_payload = {**rendered, "canonical_input_ref": {"schema_version": LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION, "input_hash": canonical["input_hash"]}, "page_assembly_ref": {"schema_version": LG10_PAGE_ASSEMBLY_SCHEMA_VERSION, "assembly_hash": assembly["assembly_hash"]}}
    rendering = {**rendering_payload, "render_hash": _canonical_hash(rendering_payload)}
    snapshot = deepcopy(dict(source_version.sections_json or {})); snapshot.pop("snapshot_hash", None)
    snapshot["lg10"] = {**dict(snapshot.get("lg10") or {}), "canonical_page_assembly_input": canonical, "page_assembly": assembly, "canonical_rendering": rendering}
    if quality_lineage_override is not None:
        override = deepcopy(dict(quality_lineage_override))
        required = {"schema_version", "creator_run_id", "source_snapshot_ref", "truth_ref", "confirmation_ref", "master_ref", "approved_asset_manifest_ref"}
        if set(override) != required or str(override.get("creator_run_id") or "") != run.id:
            raise EditIntentValidationError("LG-11 Canvas successor quality lineage is invalid.")
        snapshot["lg12_quality_lineage"] = override
    preview_sections = _lg10_preview_sections(rendering); tokens = dict(rendering.get("brand_tokens") or {})
    snapshot["commerce_renderer"] = {"theme_color": str((tokens.get("color_tokens") or {}).get("surface") or "#ffffff"), "font_family": str((tokens.get("typography") or {}).get("body_font") or "system-ui, sans-serif"), "brand_assets": _lg10_preview_brand_assets(rendering), "sections": preview_sections}; snapshot["sections"] = preview_sections
    intent_hash = str(intent.get("intent_hash") or "")
    snapshot["lg11"] = {"schema_version": _LG11_CANVAS_FORK_SCHEMA, "edit_run_id": edit_run_id, "source_detail_page_version_id": source_version.id, "parent_detail_page_version_id": source_version.id, "intent_id": intent_hash, "canvas_draft_hash": draft["draft_hash"], "canvas_revision": draft["revision"], "operation_ids": draft["applied_operation_ids"], "canvas_element_groups": deepcopy(list(draft.get("element_groups") or [])), "canvas_safety": deepcopy(dict(draft.get("safety_validation") or {}))}
    from src.services.page_visual_contract import validate_lg11_canvas_safety
    snapshot["lg11"]["canvas_safety"] = {
        channel: validate_lg11_canvas_safety(version_snapshot=snapshot, channel=channel)
        for channel in ("smartstore", "coupang")
    }
    snapshot = {**snapshot, "snapshot_hash": _canonical_hash(snapshot)}; version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sellform:lg11-canvas:{edit_run_id}:{rendering['render_hash']}"))
    return {"schema_version": _LG11_CANVAS_FORK_SCHEMA, "detail_page_version_id": version_id, "snapshot_hash": snapshot["snapshot_hash"], "source_detail_page_version_id": source_version.id, "parent_detail_page_version_id": source_version.id, "edit_run_id": edit_run_id, "intent_id": intent_hash, "snapshot": snapshot}


def persist_lg11_canvas_version_fork(*, run: AgentRun, canvas_version_fork: dict[str, Any], db: Session) -> DetailPageVersion:
    fork = deepcopy(dict(canvas_version_fork or {})); snapshot = dict(fork.get("snapshot") or {}); snapshot_hash = str(snapshot.pop("snapshot_hash", "") or ""); version_id = str(fork.get("detail_page_version_id") or "")
    if fork.get("schema_version") != _LG11_CANVAS_FORK_SCHEMA or not version_id or str(fork.get("edit_run_id") or "") != run.id or not _SHA256_HEX.fullmatch(snapshot_hash) or snapshot_hash != str(fork.get("snapshot_hash") or "") or _canonical_hash(snapshot) != snapshot_hash: raise EditIntentValidationError("LG-11 canvas fork checkpoint is not immutable.")
    lineage = dict(snapshot.get("lg11") or {})
    if lineage.get("schema_version") != _LG11_CANVAS_FORK_SCHEMA or str(lineage.get("edit_run_id") or "") != run.id or str(lineage.get("source_detail_page_version_id") or "") != str(fork.get("source_detail_page_version_id") or "") or str(fork.get("parent_detail_page_version_id") or "") != str(fork.get("source_detail_page_version_id") or ""): raise EditIntentValidationError("LG-11 canvas fork lineage is invalid.")
    source = db.query(DetailPageVersion).filter(DetailPageVersion.id == str(fork.get("source_detail_page_version_id") or ""), DetailPageVersion.project_id == run.project_id).first()
    if source is None: raise EditIntentValidationError("LG-11 canvas source version is not in this project.")
    _lg11_frozen_edit_targets(source); stored = {**snapshot, "snapshot_hash": snapshot_hash}; existing = db.query(DetailPageVersion).filter(DetailPageVersion.id == version_id, DetailPageVersion.project_id == run.project_id).first()
    if existing is not None:
        if existing.sections_json != stored: raise EditIntentValidationError("LG-11 canvas fork identity mismatch.")
        return existing
    db.query(DetailPageVersion).filter(DetailPageVersion.project_id == run.project_id, DetailPageVersion.is_final == True).update({"is_final": False})
    version = DetailPageVersion(id=version_id, project_id=run.project_id, name="LG-11 canvas edited detail page", style_key=source.style_key, sections_json=stored, is_final=True); db.add(version); db.flush(); return version


def build_lg11_scene_version_fork(*, source_version: DetailPageVersion, edit_run_id: str, intent: dict[str, Any], job: Any, db: Session) -> dict[str, Any]:
    """Freeze one approved LG-11 scene replacement while preserving sibling assets."""
    frozen = _lg11_frozen_edit_targets(source_version)
    scene_id = str((intent.get("target_ids") or [""])[0] or "")
    asset = db.query(Asset).filter(Asset.id == str(job.output_asset_id or ""), Asset.project_id == source_version.project_id).first()
    if not scene_id or job.status != "approved" or asset is None or not is_asset_final_output_eligible(asset) or not _SHA256_HEX.fullmatch(str(asset.content_hash or "")):
        raise EditIntentValidationError("LG-11 scene fork requires one approved final asset with a SHA-256 identity.")
    canonical = deepcopy(frozen["canonical_input"])
    manifest = deepcopy(dict(canonical.get("approved_asset_manifest") or {}))
    assets = list(manifest.get("assets") or [])
    replaced = False
    for entry in assets:
        if str(entry.get("scene_id") or "") == scene_id:
            try:
                frozen_quality_evidence = build_frozen_image_quality_evidence(asset=asset, job=job)
            except ProductIdentityValidationError as exc:
                raise EditIntentValidationError("LG-11 scene fork image evidence cannot be frozen safely.") from exc
            entry.update({"job_id": job.job_id, "generation_attempt": int(job.generation_attempt or 1), "asset_id": asset.id, "asset_content_hash": asset.content_hash, "provider": job.provider, "model": job.model, "lg12_frozen_image_evidence": frozen_quality_evidence})
            replaced = True
    if not replaced:
        raise EditIntentValidationError("LG-11 scene fork target is absent from the frozen approved manifest.")
    manifest_payload = {"schema_version": manifest.get("schema_version"), "run_id": manifest.get("run_id"), "project_id": manifest.get("project_id"), "assets": assets}
    manifest = {**manifest_payload, "manifest_hash": _canonical_hash(manifest_payload)}
    canonical["approved_asset_manifest"] = manifest; canonical["page_asset_manifest"] = deepcopy(manifest)
    for section in canonical.get("sections") or []:
        for entry in section.get("approved_assets") or []:
            if str(entry.get("scene_id") or "") == scene_id:
                entry.update({"job_id": job.job_id, "asset_id": asset.id, "asset_content_hash": asset.content_hash})
    payload = deepcopy(canonical); payload.pop("input_hash", None); canonical = {**payload, "input_hash": _canonical_hash(payload)}
    assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical)
    source_rendering = deepcopy(frozen["rendering"])
    rendering_payload = {**render_lg10_canonical_page_html(canonical_page_assembly_input=canonical, page_assembly=assembly, copy_set=_lg11_copy_set_from_frozen_rendering(canonical_input=canonical, rendering=source_rendering), brand_tokens=deepcopy(dict(source_rendering.get("brand_tokens") or {}))), "canonical_input_ref": {"schema_version": LG10_CANONICAL_PAGE_ASSEMBLY_SCHEMA_VERSION, "input_hash": canonical["input_hash"]}, "page_assembly_ref": {"schema_version": LG10_PAGE_ASSEMBLY_SCHEMA_VERSION, "assembly_hash": assembly["assembly_hash"]}}
    rendering = {**rendering_payload, "render_hash": _canonical_hash(rendering_payload)}
    snapshot = deepcopy(dict(source_version.sections_json or {})); snapshot.pop("snapshot_hash", None)
    snapshot["lg10"] = {**dict(snapshot.get("lg10") or {}), "canonical_page_assembly_input": canonical, "page_assembly": assembly, "canonical_rendering": rendering}
    preview_sections = _lg10_preview_sections(rendering); brand = dict(rendering.get("brand_tokens") or {})
    snapshot["commerce_renderer"] = {"theme_color": str((brand.get("color_tokens") or {}).get("surface") or "#ffffff"), "font_family": str((brand.get("typography") or {}).get("body_font") or "system-ui, sans-serif"), "brand_assets": _lg10_preview_brand_assets(rendering), "sections": preview_sections}; snapshot["sections"] = preview_sections
    source_asset = next(
        item for item in (dict(frozen["canonical_input"].get("approved_asset_manifest") or {}).get("assets") or [])
        if str(item.get("scene_id") or "") == scene_id
    )
    snapshot["lg11"] = {"schema_version": "lg11-scene-version-fork-v1", "edit_run_id": edit_run_id, "source_detail_page_version_id": source_version.id, "parent_detail_page_version_id": source_version.id, "intent_id": str(intent.get("intent_hash") or ""), "scene_change": {"scene_id": scene_id, "source_asset": source_asset, "replacement_asset_id": asset.id, "replacement_asset_content_hash": asset.content_hash, "replacement_job_id": job.job_id}}
    snapshot = {**snapshot, "snapshot_hash": _canonical_hash(snapshot)}
    return {"schema_version": "lg11-scene-version-fork-v1", "detail_page_version_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"sellform:lg11-scene:{edit_run_id}:{rendering['render_hash']}")), "snapshot_hash": snapshot["snapshot_hash"], "source_detail_page_version_id": source_version.id, "parent_detail_page_version_id": source_version.id, "edit_run_id": edit_run_id, "intent_id": str(intent.get("intent_hash") or ""), "snapshot": snapshot}


def persist_lg11_scene_version_fork(*, run: AgentRun, scene_version_fork: dict[str, Any], db: Session) -> DetailPageVersion:
    fork = deepcopy(dict(scene_version_fork or {})); snapshot = dict(fork.get("snapshot") or {}); snapshot_hash = str(snapshot.pop("snapshot_hash", "") or "")
    if fork.get("schema_version") != "lg11-scene-version-fork-v1" or str(fork.get("edit_run_id") or "") != run.id or not _SHA256_HEX.fullmatch(snapshot_hash) or _canonical_hash(snapshot) != snapshot_hash:
        raise EditIntentValidationError("LG-11 scene fork checkpoint is not immutable.")
    existing = db.query(DetailPageVersion).filter_by(id=str(fork.get("detail_page_version_id") or ""), project_id=run.project_id).first()
    stored = {**snapshot, "snapshot_hash": snapshot_hash}
    if existing is not None:
        if existing.sections_json != stored: raise EditIntentValidationError("LG-11 scene fork identity mismatch.")
        return existing
    source = db.query(DetailPageVersion).filter_by(id=str(fork.get("source_detail_page_version_id") or ""), project_id=run.project_id).first()
    if source is None: raise EditIntentValidationError("LG-11 scene source version is unavailable.")
    db.query(DetailPageVersion).filter(DetailPageVersion.project_id == run.project_id, DetailPageVersion.is_final == True).update({"is_final": False})  # noqa: E712
    version = DetailPageVersion(id=str(fork["detail_page_version_id"]), project_id=run.project_id, name="LG-11 scene edited detail page", style_key=source.style_key, sections_json=stored, is_final=True)
    db.add(version); db.flush(); return version


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
