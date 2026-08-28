"""Sprint 5 storyboard-to-AI-redesign orchestration.

Supplier captures are useful as private reference inputs, but must never be
selected as the final output.  This service creates reviewable generation jobs
from an *approved* Sprint 4 storyboard and deliberately refuses to make the
old red/blue mock bitmap look like a finished commercial visual.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import (
    Asset,
    ImageGenerationJobRecord,
    ProductFact,
    ProductProject,
    ProductPage,
    PageSection,
    ScenePromptVersion,
)
from src.services.api_ready_generation_service import get_generation_plan, is_safe_generation_reference
from src.services.channel_export_service import image_sha256
from src.services.commerce_policy import CONFIRMED_FACT_STATUSES, resolved_asset_usage_status
from src.services.image_generation_service import _split_provider_error, execute_image_generation
from src.services.storyboard_service import record_storyboard_revision
from src.services.visual_prompt_compiler_service import (
    compile_scene_prompt,
    provider_prompt,
    scene_prompt_payload,
)


SCENE_ROLES = {
    "hero": "representative_product",
    # LG-3 commerce planning uses stable page-section types. They are first-
    # class generation scenes in LG-5R, not aliases that may silently drop all
    # but the hero from the cost/review workflow.
    "pain_point": "lifestyle_scene",
    "feature_1": "detail_closeup",
    "feature_2": "detail_closeup",
    "feature_3": "detail_closeup",
    "usage_guide": "lifestyle_scene",
    "details_components": "component_layout",
    "product_specifications": "function_visualization",
    "lifestyle_scene": "lifestyle_scene",
    "usage_scene": "lifestyle_scene",
    "charging_scene": "charging_storage_scene",
    "charging_or_power": "charging_storage_scene",
    "storage_scene": "charging_storage_scene",
    "function_visual": "function_visualization",
    "component_layout": "component_layout",
    "material_detail": "detail_closeup",
    "product_detail": "detail_closeup",
    "benefit_a": "detail_closeup",
    "benefit_b": "detail_closeup",
    "hero_reemphasize": "representative_product",
}
FINAL_IMAGE_STATUSES = {"approved", "rejected", "failed", "blocked"}
EDITABLE_STATUSES = {"planned", "awaiting_approval", "queued", "blocked", "failed", "rejected", "cancelled"}
MANUAL_FINAL_SOURCE_TYPES = {"uploaded", "self_shot"}
# One deliberate redesign direction is prepared for each scene. A seller can
# explicitly request a new direction later, instead of spending credits on two
# near-identical drafts up front.
VARIANT_COUNT = 1
LG5R_PROMPT_VERSION = "lg5r-scene-prompt-v1"


def storyboard_image_generation_is_available() -> bool:
    """Whether this runtime may create a real final image through an API.

    The client uses this capability flag to present the direct-upload workflow
    when a local development environment intentionally has no paid provider.
    """
    return (
        settings.SELLFORM_IMAGE_GENERATION_MODE.strip().lower() == "real"
        and settings.SELLFORM_IMAGE_PROVIDER.strip().lower() == "openai"
        and bool(settings.OPENAI_API_KEY)
    )
ESTIMATED_CREDITS_BY_TIER = {"standard": 1.0, "premium": 2.0}

NEGATIVE_PROMPT = (
    "Do not copy supplier layouts or Chinese text. Do not include text, logos, "
    "watermarks, prices, certification marks, medical or therapeutic claims. "
    "Do not invent buttons, ports, accessories, packaging, or product structure."
)


class StoryboardImageGenerationError(ValueError):
    pass


def _job_id(project_id: str, section_id: str, variant: int) -> str:
    digest = hashlib.sha1(f"{project_id}:{section_id}:{variant}".encode("utf-8")).hexdigest()[:16]
    return f"s5-{digest}-v{variant}"


def _versioned_job_id(base_job_id: str, prompt_hash: str) -> str:
    """Return a stable job identity for a changed immutable scene prompt."""
    return f"{base_job_id}-p{prompt_hash[:12]}"


def _replacement_job_for_prompt(
    previous: ImageGenerationJobRecord,
    compiled: ScenePromptVersion,
    db: Session,
) -> ImageGenerationJobRecord:
    """Keep the prior job stale and derive a new auditable job.

    A prompt revision must never rewrite the provider contract that was used by
    an older job. The derived job deliberately clears all dispatch/output data.
    """
    replacement_id = _versioned_job_id(previous.job_id.split("-p", 1)[0], compiled.prompt_hash)
    existing = db.query(ImageGenerationJobRecord).filter_by(job_id=replacement_id).first()
    if existing:
        return existing
    replacement = ImageGenerationJobRecord(
        project_id=previous.project_id,
        job_id=replacement_id,
        section_id=previous.section_id,
        scene_id=previous.scene_id or previous.section_id,
        role=previous.role,
        source_asset_ids=list(previous.source_asset_ids or []),
        prompt=previous.prompt,
        negative_prompt=previous.negative_prompt,
        preserve_product_identity=bool(previous.preserve_product_identity),
        output_size=previous.output_size,
        cost_tier=previous.cost_tier,
        status="awaiting_approval",
        provider=compiled.provider,
        model=compiled.model,
        attempt_count=0,
        input_snapshot=dict(previous.input_snapshot or {}),
        validation_result={"status": "pending"},
        estimated_cost=compiled.expected_cost,
        usage_metadata={},
        generation_attempt=1,
        required_for_completion=bool(previous.required_for_completion),
        supersedes_job_id=previous.job_id,
        scene_prompt_version_id=compiled.id,
        prompt_version=compiled.prompt_version,
        prompt_hash=compiled.prompt_hash,
        reference_hash=compiled.reference_hash,
        input_hash=compiled.input_hash,
    )
    db.add(replacement)
    db.flush()
    return replacement


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cards(project: ProductProject) -> list[dict[str, Any]]:
    return [
        card for card in (project.planning_draft or {}).get("cards") or []
        if card.get("is_enabled", True)
    ]


def _source_assets(
    project: ProductProject, card: dict[str, Any], db: Session, preferred_ids: list[str] | None = None
) -> list[Asset]:
    """Return a small, ordered identity pack, never a final-output selection.

    A card may only point to one image, while a seller has uploaded several
    views of the same product.  Using the card candidate first and then other
    product/detail views lets Sprint 5 request the side/control evidence it
    needs without inventing product structure.
    """
    candidate_ids = list(preferred_ids or card.get("candidate_asset_ids") or [])
    project_assets = (
        db.query(Asset)
        .filter(Asset.project_id == project.id, Asset.mime_type.like("image/%"))
        .order_by(Asset.intake_order.asc().nullslast(), Asset.created_at.asc())
        .all()
    )
    by_id = {asset.id: asset for asset in project_assets}
    # A seller chooses one *primary* visual reference.  We retain other
    # product/detail shots as private identity evidence so a one-photo choice
    # does not make the generator guess hidden controls or included parts.
    # The first item remains the requested primary reference.
    if preferred_ids is not None:
        ordered_ids = [*candidate_ids]
    else:
        ordered_ids = [*candidate_ids]
    ordered_ids.extend(
        asset.id
        for asset in project_assets
        if asset.asset_role in {"product_main", "product_detail", "product_component", "product_in_use", "usage_scene"}
    )
    selected: list[Asset] = []
    for asset_id in dict.fromkeys(ordered_ids):
        asset = by_id.get(asset_id)
        if not asset or not is_safe_generation_reference(asset, db):
            continue
        selected.append(asset)
        if len(selected) == 3:
            break

    # A scene can start with close-ups or a supplier specification crop. Keep
    # the seller's first choice, but make room for one overall and one
    # detail/in-use view whenever the initial three would make product identity
    # unverifiable. This prevents a valid product-main photo elsewhere in the
    # project from being silently excluded by three feature-only candidates.
    identity_ready, _ = _reference_assessment(selected)
    if identity_ready:
        return selected

    usable_assets = [
        asset for asset in project_assets
        if is_safe_generation_reference(asset, db)
    ]
    overall = next(
        (asset for asset in usable_assets if asset.asset_role in {"product_main", "product_in_use", "usage_scene"}),
        None,
    )
    detail = next(
        (asset for asset in usable_assets if asset.asset_role in {"product_detail", "product_component", "product_in_use", "usage_scene"}),
        None,
    )
    if not overall or not detail:
        return selected

    identity_pack: list[Asset] = []
    if selected:
        identity_pack.append(selected[0])
    for asset in (overall, detail):
        if asset.id not in {item.id for item in identity_pack}:
            identity_pack.append(asset)
    if len(identity_pack) < 2:
        identity_pack.extend(
            asset for asset in usable_assets
            if asset.id not in {item.id for item in identity_pack}
        )
    return identity_pack[:3]


def _reference_assessment(sources: list[Asset]) -> tuple[bool, list[str]]:
    """Require more than one visual view before changing a product's setting.

    Two photographs are the minimum local-MVP threshold: one overall product
    view plus a detail/control/in-use view.  We deliberately block instead of
    fabricating hidden ports, buttons or included parts from one ambiguous crop.
    """
    if not sources:
        return False, ["대표 상품 사진과 조작부·측면·후면 중 한 장 이상을 추가해 주세요."]
    roles = {asset.asset_role for asset in sources}
    # The intake analyser uses ``usage_scene`` for a seller-provided lifestyle
    # photo, while manually classified projects can use ``product_in_use``.
    # Both are valid secondary identity evidence when a product-main view is
    # present; do not reject a real seller upload merely because its role name
    # came from a different intake path.
    has_overall = bool(roles & {"product_main", "product_in_use", "usage_scene"})
    has_detail = bool(roles & {"product_detail", "product_component", "product_in_use", "usage_scene"})
    if len(sources) < 2 or not has_overall or not has_detail:
        return False, [
            "상품 정체성 기준 사진이 부족합니다. 대표 상품 사진과 조작부·측면·후면 또는 사용 장면을 2장 이상 확인해 주세요."
        ]
    return True, []


def _asset_summary(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "filename": asset.filename,
        "role": asset.asset_role,
        "usage_status": resolved_asset_usage_status(asset),
        "source_type": asset.source_type,
        "identity_status": asset.identity_status,
    }


POWER_FACT_PATTERN = re.compile(r"(?:charging|charge|power|battery|input|usb|type[- ]?c|충전|전원|배터리|정격\s*입력|소비전력)", re.I)
POWER_SCENE_TYPES = {"charging_scene", "charging_or_power"}
PROVIDER_DATA_POLICY = {
    "training": "not_used_by_default",
    "abuse_monitoring_retention": "up_to_30_days_by_default",
    "zero_data_retention": "eligible_when_organization_is_approved",
    "policy_url": "https://developers.openai.com/api/docs/guides/your-data",
}


def _confirmed_facts(project: ProductProject, card: dict[str, Any], db: Session) -> list[ProductFact]:
    requested = set(card.get("source_fact_ids") or [])
    query = db.query(ProductFact).filter(ProductFact.project_id == project.id)
    if requested:
        query = query.filter(ProductFact.id.in_(requested))
    return [
        fact for fact in query.all()
        if fact.verification_status in CONFIRMED_FACT_STATUSES and not fact.needs_review
    ]


def _fact_snapshot(fact: ProductFact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "field_key": fact.field_key,
        "text": fact.fact_text,
        "value": fact.normalized_value,
        "unit": fact.normalized_unit,
        "verification_status": fact.verification_status,
    }


def _plan_scene(project: ProductProject, card: dict[str, Any]) -> tuple[dict[str, Any] | None, int | None]:
    plan = get_generation_plan(project)
    if not plan:
        return None, None
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    scene = next((item for item in scenes if str(item.get("id")) == str(card.get("id"))), None)
    return (deepcopy(scene) if scene else None), plan.get("version")


def _generation_input_snapshot(
    project: ProductProject,
    card: dict[str, Any],
    draft: dict[str, Any],
    sources: list[Asset],
    facts: list[ProductFact],
) -> dict[str, Any]:
    scene, plan_version = _plan_scene(project, card)
    copy_draft = (scene or {}).get("copy_draft") or {}
    approved_copy = None
    if copy_draft.get("status") == "seller_approved":
        approved_copy = {
            "headline": copy_draft.get("headline"),
            "body": copy_draft.get("body"),
            "source_fact_ids": list(copy_draft.get("source_fact_ids") or []),
            "input_snapshot_hash": copy_draft.get("input_snapshot_hash"),
        }
    elif scene:
        scene.pop("copy_draft", None)
    return {
        "storyboard_revision": draft.get("revision"),
        "storyboard_status": draft.get("status"),
        "approval_source": "approved_storyboard",
        "plan_version": plan_version,
        "scene_plan_snapshot": scene,
        "section_type": card.get("type"),
        "scene_request": card.get("scene_request"),
        "confirmed_facts": [_fact_snapshot(fact) for fact in facts],
        "approved_copy": approved_copy,
        "reference_assets": [_asset_summary(asset) for asset in sources],
        "fixed_elements": _fixed_elements(),
        "provider_data_policy": deepcopy(PROVIDER_DATA_POLICY),
    }


def _power_scene_is_grounded(card: dict[str, Any], facts: list[ProductFact]) -> bool:
    if str(card.get("type") or "") not in POWER_SCENE_TYPES:
        return True
    return any(
        POWER_FACT_PATTERN.search(" ".join(filter(None, [fact.field_key, fact.fact_text, fact.normalized_value])))
        for fact in facts
    )


def _manual_final_asset_issues(project: ProductProject, asset: Asset, db: Session) -> list[str]:
    """Return non-bypassable reasons why an uploaded file cannot be final art.

    A user can legitimately upload a final image without an image API.  But a
    supplier capture can be uploaded again through that same path, which makes
    its ``source_type`` look like ``uploaded``.  Content hashes are already
    stored by Sprint 2, so compare an upload against the project's private
    reference-only captures before accepting a seller attestation.
    """
    issues: list[str] = []
    if asset.content_hash:
        matched_reference = (
            db.query(Asset.id)
            .filter(
                Asset.project_id == project.id,
                Asset.id != asset.id,
                Asset.usage_status == "reference_only",
                Asset.content_hash == asset.content_hash,
            )
            .first()
        )
        if matched_reference:
            issues.append(
                "이 파일은 프로젝트에 이미 등록된 공급처·참고 이미지와 동일합니다. "
                "원본 재업로드 파일은 최종 상세페이지에 사용할 수 없습니다."
            )

    # A Korean 판매용 최종 시안에 공급처 중국어 문구가 그대로 남아 있으면
    # 원본 레이아웃을 재사용했을 가능성이 높다. OCR 결과가 있을 때만 막아
    # 직접 촬영한 무문구 사진까지 과도하게 제한하지 않는다.
    if re.search(r"[\u4e00-\u9fff]", asset.ocr_text or ""):
        issues.append(
            "중국어 공급처 문구가 감지된 이미지는 최종 시안으로 승인할 수 없습니다. "
            "문구를 새로 구성한 리디자인 이미지 또는 직접 촬영본을 사용해 주세요."
        )
    return issues


def _reconcile_disallowed_manual_outputs(project: ProductProject, db: Session) -> bool:
    """Withdraw old final-output approvals that policy would reject today.

    This protects projects created before duplicate-reference detection was
    added.  It clears only the affected storyboard scene; original captures
    remain available as private generation references.
    """
    draft = deepcopy(project.planning_draft or {})
    cards = {card.get("id"): card for card in draft.get("cards") or []}
    changed = False
    jobs = (
        db.query(ImageGenerationJobRecord)
        .filter(ImageGenerationJobRecord.project_id == project.id)
        .all()
    )
    for job in jobs:
        # Older page assembly created ``source_asset`` jobs and marked a
        # supplier upload as approved.  Treat every persisted final output as
        # an output candidate here, not only the newer manual-upload path.
        # This makes the no-supplier-original rule durable across migrations
        # and prevents a legacy job from making the UI claim all scenes are
        # ready.
        if not job.output_asset_id:
            continue
        asset = db.query(Asset).filter(Asset.id == job.output_asset_id, Asset.project_id == project.id).first()
        if not asset:
            continue
        issues = _manual_final_asset_issues(project, asset, db)
        if not issues:
            continue
        job.status = "blocked"
        job.error_code = "SUPPLIER_REFERENCE_FINAL_OUTPUT_BLOCKED"
        job.output_asset_id = None
        job.warnings = issues
        job.validation_result = {"status": "blocked", "reasons": issues}
        card = cards.get(job.section_id)
        if card and str(card.get("image_asset_id") or "") == asset.id:
            card["image_asset_id"] = None
            card["image_requirement"] = "ai_redesign_required"
            card["missing_reasons"] = issues
        changed = True
    if changed:
        project.planning_draft = record_storyboard_revision(draft, "supplier_reference_final_output_blocked")
        db.commit()
    return changed


def _fixed_elements() -> list[str]:
    return ["제품 실루엣", "색상", "버튼·포트 위치", "주요 구조", "구성품", "로고 정책"]


def _validate_seller_instruction(instruction: str) -> None:
    """Reject requests that explicitly invent a product feature or a claim."""
    compact = " ".join((instruction or "").lower().split())
    if not compact:
        return
    forbidden_patterns = (
        r"\b(add|invent|create|include|show)\b.{0,45}\b(new|extra|additional)\b.{0,45}\b(button|port|usb|accessory|package|certificate|certification)\b",
        r"\b(add|invent|create|include|show)\b.{0,45}\b(logo|watermark|price|discount|medical|treatment|certification)\b",
        r"(없는|새로운|추가).{0,24}(버튼|포트|구성품|인증|로고|워터마크)",
        r"(치료|의료|완치|효능\s*보장|인증\s*마크|가격표|할인\s*문구)",
    )
    if any(re.search(pattern, compact, flags=re.IGNORECASE) for pattern in forbidden_patterns):
        raise StoryboardImageGenerationError(
            "확인되지 않은 버튼·포트·구성품·인증·의료 표현을 추가하는 장면 요청은 사용할 수 없습니다. 배경·조명·인물·구도만 수정해 주세요."
        )


def _prompt(project: ProductProject, card: dict[str, Any], variant: int) -> str:
    scene = (card.get("scene_request") or "").strip()
    product = project.name or "the supplied product"
    framing = "clean product-led composition" if variant == 1 else "a distinct but equally product-faithful composition"
    return (
        f"Create an original e-commerce visual for {product}. "
        f"Use the supplied product reference only to preserve the exact silhouette, color, "
        f"buttons, ports, material, and included parts. Scene: {scene}. "
        f"Use {framing}. The image must be a new composition, not a supplier-image reproduction."
    )


def _job_payload(record: ImageGenerationJobRecord, card: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = dict(record.input_snapshot or {})
    return {
        "job_id": record.job_id,
        "section_id": record.section_id,
        "section_type": (card or {}).get("type"),
        "section_title": (card or {}).get("title"),
        "role": record.role,
        "source_asset_ids": list(record.source_asset_ids or []),
        "prompt": record.prompt,
        "negative_prompt": record.negative_prompt or "",
        "preserve_product_identity": bool(record.preserve_product_identity),
        "output_size": record.output_size,
        "cost_tier": record.cost_tier,
        "status": record.status,
        "provider": record.provider,
        "model": record.model,
        "attempt_count": record.attempt_count,
        "output_asset_id": record.output_asset_id,
        "error_code": record.error_code,
        "warnings": list(record.warnings or []),
        "input_snapshot": snapshot,
        "reference_assets": list(snapshot.get("reference_assets") or []),
        "fixed_elements": list(snapshot.get("fixed_elements") or _fixed_elements()),
        "validation_result": dict(record.validation_result or {}),
        "estimated_cost": record.estimated_cost,
        "actual_cost": record.actual_cost,
        "usage_metadata": dict(record.usage_metadata or {}),
        "seed": record.seed,
        "requires_cost_approval": True,
        "reference_only_input": True,
        "dispatch_required": False,
        "scene_id": record.scene_id or record.section_id,
        "prompt_version": record.prompt_version,
        "prompt_hash": record.prompt_hash,
        "reference_hash": record.reference_hash,
        "planning_hash": record.planning_hash,
        "input_hash": record.input_hash,
        "generation_attempt": record.generation_attempt,
        "idempotency_key": record.idempotency_key,
        "required_for_completion": bool(record.required_for_completion),
        "scene_prompt_version_id": record.scene_prompt_version_id,
        "scene_prompt": scene_prompt_payload(record.scene_prompt_version) if record.scene_prompt_version else None,
    }


def build_storyboard_generation_contracts(
    project: ProductProject,
    db: Session,
    *,
    brand_kit_version_id: str | None = None,
    brand_kit_hash: str | None = None,
) -> list[dict[str, Any]]:
    """Build versioned, write-free LG-5R scene inputs from an approved draft.

    Cost approval uses this exact snapshot before any job or outbox record is
    created. Preparation recomputes it and refuses stale approvals.
    """

    draft = deepcopy(project.planning_draft or {})
    if draft.get("status") != "approved":
        raise StoryboardImageGenerationError("Approve the storyboard before preparing AI redesign images.")
    planning_hash = _canonical_hash(draft)
    contracts: list[dict[str, Any]] = []
    for card in _cards(project):
        scene_type = str(card.get("type") or "")
        if scene_type not in SCENE_ROLES or card.get("image_requirement") in {
            "seller_upload_required", "not_required", "derived_graphic",
        }:
            continue
        source_assets = _source_assets(project, card, db)
        facts = _confirmed_facts(project, card, db)
        compiled = compile_scene_prompt(
            project,
            card,
            db,
            brand_kit_version_id=brand_kit_version_id,
            brand_kit_hash=brand_kit_hash,
        )
        prompt, negative_prompt = provider_prompt(compiled)
        reference_hash = compiled.reference_hash
        prompt_hash = compiled.prompt_hash
        prompt_version = compiled.prompt_version
        snapshot = _generation_input_snapshot(project, card, draft, source_assets, facts)
        snapshot["scene_prompt"] = scene_prompt_payload(compiled)
        input_hash = _canonical_hash(
            {
                "scene_prompt_input_hash": compiled.input_hash,
                "prompt_hash": prompt_hash,
                "reference_hash": reference_hash,
            }
        )
        identity_ready, identity_warnings = _reference_assessment(source_assets)
        power_ready = _power_scene_is_grounded(card, facts)
        blocker_code = None
        blocker_warnings: list[str] = []
        if not power_ready:
            blocker_code = "POWER_FACT_REQUIRED"
            blocker_warnings = ["충전·전원 장면은 판매자가 확인한 전원 또는 배터리 사실이 필요합니다."]
        elif not identity_ready:
            blocker_code = "IDENTITY_REFERENCE_INSUFFICIENT"
            blocker_warnings = identity_warnings
        contracts.append(
            {
                "scene_id": str(card.get("id") or scene_type),
                "section_id": str(card.get("id") or scene_type),
                "scene_type": scene_type,
                "scene_title": str(card.get("title") or scene_type),
                "role": SCENE_ROLES[scene_type],
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "prompt_version": prompt_version,
                "prompt_hash": prompt_hash,
                "reference_hash": reference_hash,
                "planning_hash": planning_hash,
                "input_hash": input_hash,
                "source_asset_ids": list(compiled.reference_asset_ids or []),
                "input_snapshot": snapshot,
                "estimated_cost": compiled.expected_cost,
                "provider": compiled.provider,
                "model": compiled.model,
                "output_size": compiled.size,
                "cost_tier": compiled.quality,
                "scene_prompt_version_id": compiled.id,
                "required_for_completion": bool(card.get("is_enabled", True)),
                "blocker_code": blocker_code,
                "blocker_warnings": blocker_warnings,
            }
        )
    return contracts


def list_storyboard_jobs(project: ProductProject, db: Session) -> list[dict[str, Any]]:
    _reconcile_disallowed_manual_outputs(project, db)
    cards_by_id = {card.get("id"): card for card in _cards(project)}
    jobs = (
        db.query(ImageGenerationJobRecord)
        .filter(ImageGenerationJobRecord.project_id == project.id)
        .order_by(ImageGenerationJobRecord.created_at.asc(), ImageGenerationJobRecord.job_id.asc())
        .all()
    )
    return [_job_payload(job, cards_by_id.get(job.section_id)) for job in jobs if job.section_id in cards_by_id]


def prepare_storyboard_jobs(project: ProductProject, db: Session) -> list[dict[str, Any]]:
    draft = project.planning_draft or {}
    if draft.get("status") != "approved":
        raise StoryboardImageGenerationError("Approve the storyboard before preparing AI redesign images.")
    _reconcile_disallowed_manual_outputs(project, db)

    # ``asset_ready`` only means that the storyboard has a usable photo for a
    # normal preview.  It must not make the explicit "AI redesign scenes"
    # action a no-op: a seller may still want a new, original composition from
    # that photo.  Prepare jobs for every visual storyboard scene, while
    # continuing to keep every input photo reference-only inside the job.
    cards = [
        card
        for card in _cards(project)
        if str(card.get("type") or "") in SCENE_ROLES
        and card.get("image_requirement") != "seller_upload_required"
    ]
    existing = {
        job.job_id: job
        for job in db.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.project_id == project.id).all()
    }
    project_assets = {
        asset.id: asset
        for asset in db.query(Asset).filter(Asset.project_id == project.id).all()
    }
    for card in cards:
        compiled = compile_scene_prompt(project, card, db)
        compiled_prompt, compiled_negative = provider_prompt(compiled)
        confirmed_facts = _confirmed_facts(project, card, db)
        power_grounded = _power_scene_is_grounded(card, confirmed_facts)
        # A page reassembly used to remove the Sprint 5 jobs while leaving an
        # explicitly seller-approved storyboard image behind.  Recreate that
        # approval from the durable card instead of making the seller upload
        # the same final image a second time.
        selected_asset = project_assets.get(str(card.get("image_asset_id") or ""))
        manual_final_issues = (
            _manual_final_asset_issues(project, selected_asset, db)
            if selected_asset
            else []
        )
        restore_manual_approval = bool(
            card.get("image_requirement") == "asset_ready"
            and selected_asset
            and selected_asset.mime_type.startswith("image/")
            and selected_asset.source_type in MANUAL_FINAL_SOURCE_TYPES
            and resolved_asset_usage_status(selected_asset) == "seller_owned"
            and selected_asset.identity_status != "rejected"
            and selected_asset.quality_status != "rejected"
            and selected_asset.file_path
            and os.path.isfile(selected_asset.file_path)
            and not manual_final_issues
        )
        preferred_ids = (
            [selected_asset.id, *(card.get("candidate_asset_ids") or [])]
            if restore_manual_approval and selected_asset
            else None
        )
        source_assets = _source_assets(project, card, db, preferred_ids=preferred_ids)
        source_ids = [asset.id for asset in source_assets]
        identity_ready, identity_warnings = _reference_assessment(source_assets)
        for variant in range(1, VARIANT_COUNT + 1):
            job_id = _job_id(project.id, str(card.get("id")), variant)
            base_job = existing.get(job_id)
            if base_job and base_job.scene_prompt_version_id not in {None, compiled.id}:
                job_id = _versioned_job_id(job_id, compiled.prompt_hash)
            if job_id in existing:
                # Existing jobs are intentionally idempotent, but a seller can
                # add another usable photo after the first preparation. Recheck
                # only the identity-reference block so the “check scenes again”
                # action can recover the same durable job instead of creating a
                # duplicate chargeable candidate.
                job = existing[job_id]
                if job.status in EDITABLE_STATUSES:
                    job.source_asset_ids = list(compiled.reference_asset_ids or source_ids)
                    job.prompt = compiled_prompt
                    job.negative_prompt = compiled_negative
                    job.scene_prompt_version_id = compiled.id
                    job.prompt_version = compiled.prompt_version
                    job.prompt_hash = compiled.prompt_hash
                    job.reference_hash = compiled.reference_hash
                    job.input_hash = compiled.input_hash
                job.input_snapshot = _generation_input_snapshot(
                    project, card, draft, source_assets, confirmed_facts
                )
                if not power_grounded and job.status != "approved":
                    job.status = "blocked"
                    job.error_code = "POWER_FACT_REQUIRED"
                    job.warnings = ["충전·전원 장면은 판매자가 확인한 충전, 전원 또는 배터리 사실이 있어야 생성할 수 있습니다. 정보형 안내는 그대로 유지됩니다."]
                    job.validation_result = {"status": "blocked", "checks": {"confirmed_power_fact": "blocked"}}
                    continue
                if restore_manual_approval and selected_asset:
                    # This is already an explicitly seller-approved direct
                    # upload.  Do not retain the generic supplier-reference
                    # warning left by an earlier preparation run: it is both
                    # misleading in the UI and makes an approved output look
                    # blocked even though this job points at a seller-owned
                    # final asset.
                    job.source_asset_ids = source_ids
                    job.status = "approved"
                    job.provider = "manual_upload"
                    job.model = "seller-approved-existing-asset"
                    job.output_asset_id = selected_asset.id
                    job.error_code = None
                    job.warnings = []
                    job.validation_result = {
                        "status": "passed",
                        "reason": "Restored seller-approved direct-upload image from storyboard.",
                    }
                    job.usage_metadata = {
                        **dict(job.usage_metadata or {}),
                        "seller_usage_attested": True,
                        "restored_from_storyboard": True,
                    }
                    continue
                if job.status == "blocked" and job.error_code == "IDENTITY_REFERENCE_INSUFFICIENT":
                    job.source_asset_ids = source_ids
                    snapshot = dict(job.input_snapshot or {})
                    snapshot["reference_assets"] = [_asset_summary(asset) for asset in source_assets]
                    snapshot["fixed_elements"] = _fixed_elements()
                    job.input_snapshot = snapshot
                    job.status = "awaiting_approval" if identity_ready else "blocked"
                    job.error_code = None if identity_ready else "IDENTITY_REFERENCE_INSUFFICIENT"
                    job.warnings = identity_warnings if not identity_ready else [
                        "Supplier photos are reference inputs only and can never be used directly as final output."
                    ]
                    job.validation_result = {"status": "pending"}
                continue
            blocked = (not identity_ready or not power_grounded) and not restore_manual_approval
            block_error = "POWER_FACT_REQUIRED" if not power_grounded else "IDENTITY_REFERENCE_INSUFFICIENT"
            block_warnings = (
                ["충전·전원 장면은 판매자가 확인한 충전, 전원 또는 배터리 사실이 있어야 생성할 수 있습니다. 정보형 안내는 그대로 유지됩니다."]
                if not power_grounded else identity_warnings
            )
            job = ImageGenerationJobRecord(
                project_id=project.id,
                job_id=job_id,
                section_id=str(card.get("id")),
                role=SCENE_ROLES.get(str(card.get("type")), "representative_product"),
                source_asset_ids=list(compiled.reference_asset_ids or source_ids),
                prompt=compiled_prompt,
                negative_prompt=compiled_negative,
                preserve_product_identity=True,
                output_size="1024x1024",
                cost_tier="standard",
                status="approved" if restore_manual_approval else ("blocked" if blocked else "awaiting_approval"),
                provider="manual_upload" if restore_manual_approval else settings.SELLFORM_IMAGE_PROVIDER,
                model="seller-approved-existing-asset" if restore_manual_approval else settings.SELLFORM_IMAGE_MODEL,
                error_code=block_error if blocked else None,
                warnings=block_warnings if blocked else ["판매자 보유 기준 사진은 비공개 생성 입력으로만 사용하며 최종 출력과 나란히 검수합니다."],
                input_snapshot=_generation_input_snapshot(project, card, draft, source_assets, confirmed_facts),
                estimated_cost=ESTIMATED_CREDITS_BY_TIER["standard"],
                output_asset_id=selected_asset.id if restore_manual_approval and selected_asset else None,
                usage_metadata={
                    "seller_usage_attested": True,
                    "restored_from_storyboard": True,
                } if restore_manual_approval else {},
                validation_result={
                    "status": "passed",
                    "reason": "Restored seller-approved direct-upload image from storyboard.",
                } if restore_manual_approval else {"status": "pending"},
                scene_prompt_version_id=compiled.id,
                scene_id=str(card.get("id")),
                prompt_version=compiled.prompt_version,
                prompt_hash=compiled.prompt_hash,
                reference_hash=compiled.reference_hash,
                input_hash=compiled.input_hash,
            )
            db.add(job)
            existing[job_id] = job
    db.commit()
    return list_storyboard_jobs(project, db)


def update_storyboard_job(
    project: ProductProject,
    job_id: str,
    instruction: str | None,
    db: Session,
    source_asset_ids: list[str] | None = None,
) -> dict[str, Any]:
    job = _job_for_project(project, job_id, db)
    if job.status not in EDITABLE_STATUSES:
        raise StoryboardImageGenerationError("Only a not-yet-approved generation job can be edited.")
    clean = (instruction or "").strip()
    if len(clean) > 600:
        raise StoryboardImageGenerationError("Keep the scene adjustment within 600 characters.")
    _validate_seller_instruction(clean)
    card = {card.get("id"): card for card in _cards(project)}.get(job.section_id) or {}
    if source_asset_ids is not None and len(set(source_asset_ids)) < 2:
        raise StoryboardImageGenerationError(
            "제품 외형을 보존하려면 전체 제품 사진과 조작부·측면 또는 사용 장면 등 기준 사진을 2장 이상 선택해 주세요."
        )
    sources = _source_assets(project, card, db, preferred_ids=source_asset_ids or job.source_asset_ids)
    if source_asset_ids is not None and not set(source_asset_ids).issubset({asset.id for asset in sources}):
        raise StoryboardImageGenerationError("선택한 기준 사진 중 사용할 수 없는 파일이 있습니다. 프로젝트의 상품 사진만 선택해 주세요.")
    identity_ready, identity_warnings = _reference_assessment(sources)
    if source_asset_ids is not None:
        card = {**card, "candidate_asset_ids": [asset.id for asset in sources]}
    compiled = compile_scene_prompt(project, card, db, seller_adjustment=clean)
    compiled_prompt, compiled_negative = provider_prompt(compiled)
    if job.scene_prompt_version_id not in {None, compiled.id}:
        job = _replacement_job_for_prompt(job, compiled, db)
    job.source_asset_ids = [asset.id for asset in sources]
    job.prompt = compiled_prompt
    job.negative_prompt = compiled_negative
    job.scene_prompt_version_id = compiled.id
    job.prompt_version = compiled.prompt_version
    job.prompt_hash = compiled.prompt_hash
    job.reference_hash = compiled.reference_hash
    job.input_hash = compiled.input_hash
    job.idempotency_key = None
    snapshot = dict(job.input_snapshot or {})
    snapshot["reference_assets"] = [_asset_summary(asset) for asset in sources]
    snapshot["fixed_elements"] = _fixed_elements()
    job.input_snapshot = snapshot
    job.status = "awaiting_approval" if identity_ready else "blocked"
    job.error_code = None if identity_ready else "IDENTITY_REFERENCE_INSUFFICIENT"
    job.warnings = identity_warnings if not identity_ready else ["공급처·참고 이미지는 비공개 생성 입력으로만 사용하며 최종 출력으로 사용할 수 없습니다."]
    db.commit()
    return _job_payload(job, {card.get("id"): card for card in _cards(project)}.get(job.section_id))


def start_storyboard_job(
    project: ProductProject,
    job_id: str,
    cost_approved: bool,
    db: Session,
    *,
    allow_mock_provider: bool = False,
    commit_changes: bool = True,
) -> dict[str, Any]:
    persist = db.commit if commit_changes else db.flush
    job = _job_for_project(project, job_id, db)
    frozen_lg11_source = bool((job.usage_metadata or {}).get("lg11_source_version_id"))
    cards_by_id = {card.get("id"): card for card in _cards(project)}
    card = cards_by_id.get(job.section_id)
    # An LG-11 regeneration is derived from its frozen source version.  Its
    # dispatch must not depend on a later mutable planning-card projection
    # still containing the historical scene; that would make a valid frozen
    # rework unrecoverable after a planning edit.
    if card is None and not frozen_lg11_source:
        raise StoryboardImageGenerationError("The storyboard scene for this job no longer exists.")
    if job.status in {"approved", "needs_review", "running", "generating", "queued"}:
        return _job_payload(job, card)
    if not cost_approved:
        job.status = "awaiting_approval"
        persist()
        return _job_payload(job, card)

    if frozen_lg11_source:
        # An LG-11 child is derived from an immutable final version.  Preserve
        # the original LG-9 prompt/reference/fact snapshot verbatim rather
        # than re-reading mutable planning cards or facts during dispatch.
        source_ids = [str(asset_id) for asset_id in (job.source_asset_ids or []) if str(asset_id)]
        by_id = {
            asset.id: asset for asset in db.query(Asset).filter(
                Asset.project_id == project.id, Asset.id.in_(source_ids)
            ).all()
        }
        sources = [by_id[asset_id] for asset_id in source_ids if asset_id in by_id]
    else:
        sources = _source_assets(project, card, db, preferred_ids=job.source_asset_ids)
        job.source_asset_ids = [asset.id for asset in sources]
        snapshot = dict(job.input_snapshot or {})
        snapshot["reference_assets"] = [_asset_summary(asset) for asset in sources]
        snapshot["confirmed_facts"] = [_fact_snapshot(fact) for fact in _confirmed_facts(project, card, db)]
        job.input_snapshot = snapshot

    if frozen_lg11_source and not sources:
        job.status = "blocked"
        job.error_code = "FROZEN_REFERENCE_UNAVAILABLE"
        job.warnings = ["The frozen LG-11 source references are no longer available for regeneration."]
        persist()
        return _job_payload(job, card)

    confirmed_facts = [] if frozen_lg11_source else _confirmed_facts(project, card, db)
    if not frozen_lg11_source and not _power_scene_is_grounded(card, confirmed_facts):
        job.status = "blocked"
        job.error_code = "POWER_FACT_REQUIRED"
        job.warnings = ["충전·전원 장면은 판매자가 확인한 충전, 전원 또는 배터리 사실이 있어야 생성할 수 있습니다."]
        persist()
        return _job_payload(job, card)
    identity_ready, identity_warnings = _reference_assessment(sources)
    if not frozen_lg11_source and not identity_ready:
        job.status = "blocked"
        job.error_code = "IDENTITY_REFERENCE_INSUFFICIENT"
        job.warnings = identity_warnings
        persist()
        return _job_payload(job, card)
    if any(not asset.file_path or not os.path.isfile(asset.file_path) for asset in sources):
        job.status = "blocked"
        job.error_code = "REFERENCE_FILE_UNAVAILABLE"
        job.warnings = ["생성 전에 로컬에서 확인 가능한 상품 기준 사진이 필요합니다."]
        persist()
        return _job_payload(job, card)
    if not allow_mock_provider and not storyboard_image_generation_is_available():
        job.status = "blocked"
        job.error_code = "IMAGE_PROVIDER_NOT_CONFIGURED"
        job.warnings = [
            "AI image generation is not configured. Mock placeholders are never saved as final commercial images.",
            "Add an image provider API key and enable real image generation, then retry this reviewed scene.",
        ]
        persist()
        return _job_payload(job, card)

    job.status = "queued"
    job.error_code = None
    usage_metadata = dict(job.usage_metadata or {})
    attempt_history = list(usage_metadata.get("attempt_history") or [])
    attempt_history.append({
        "attempt": int(job.attempt_count or 0) + 1,
        "status": "queued",
        "storyboard_revision": (project.planning_draft or {}).get("revision"),
        "source_asset_ids": [asset.id for asset in sources],
    })
    usage_metadata["attempt_history"] = attempt_history
    job.usage_metadata = usage_metadata
    persist()
    payload = _job_payload(job, card)
    payload["dispatch_required"] = True
    return payload


def run_storyboard_job_worker(project_id: str, job_id: str, graph_run_id: str | None = None) -> None:
    """Execute a queued generation in a separate DB session.

    The HTTP request returns as soon as the durable queued status is saved; the
    UI polls the status endpoint.  This is deliberately compatible with a
    future worker queue while remaining runnable in local development.
    """
    from src.db.database import SessionLocal

    db = SessionLocal()
    try:
        project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
        if not project:
            return
        job = _job_for_project(project, job_id, db)
        if job.status != "queued":
            return
        job.status = "running"
        db.commit()
        execute_image_generation(project.id, job.job_id, db, cost_approved=True)
    except Exception as exc:  # execute_image_generation persists bounded provider failure state
        try:
            project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
            job = _job_for_project(project, job_id, db) if project else None
        except Exception:
            job = None
        if job is not None:
            if job.status not in FINAL_IMAGE_STATUSES:
                error_code, action = _split_provider_error(exc)
                job.status = "failed"
                job.error_code = error_code
                job.warnings = [action]
                db.commit()
    finally:
        db.close()
    # LG-5 workers resume only their own durable graph thread. This happens
    # after the job transaction has closed so the graph can collect the final
    # provider state without sharing an ORM session with the worker.
    if graph_run_id:
        try:
            from src.services.langgraph_run_service import LangGraphRunService

            LangGraphRunService.resume_provider_wait(graph_run_id)
        except Exception:
            logger.exception("Could not resume LangGraph provider wait for run %s", graph_run_id)


def restart_storyboard_job(project: ProductProject, job_id: str, db: Session) -> dict[str, Any]:
    job = _job_for_project(project, job_id, db)
    if job.status not in {"needs_review", "rejected", "failed", "blocked", "cancelled"}:
        raise StoryboardImageGenerationError("Only a reviewed, rejected, failed, or blocked image job can be regenerated.")
    card = {card.get("id"): card for card in _cards(project)}.get(job.section_id) or {}
    sources = _source_assets(project, card, db, preferred_ids=job.source_asset_ids)
    identity_ready, identity_warnings = _reference_assessment(sources)
    job.source_asset_ids = [asset.id for asset in sources]
    job.output_asset_id = None
    job.status = "awaiting_approval" if identity_ready else "blocked"
    job.error_code = None if identity_ready else "IDENTITY_REFERENCE_INSUFFICIENT"
    job.warnings = identity_warnings if not identity_ready else ["새 후보를 만들 준비가 되었습니다. 생성 전에 비용 승인과 상품 정체성 확인이 필요합니다."]
    job.validation_result = {"status": "pending"}
    db.commit()
    return _job_payload(job, card)


def cancel_storyboard_job(project: ProductProject, job_id: str, db: Session) -> dict[str, Any]:
    """Cancel a not-yet-completed seller generation without deleting its audit trail."""
    job = _job_for_project(project, job_id, db)
    if job.status in {"approved", "needs_review"}:
        raise StoryboardImageGenerationError("완료된 결과는 취소할 수 없습니다. 결과를 사용하지 않거나 다시 만들기를 선택해 주세요.")
    if job.status in {"running", "generating"}:
        raise StoryboardImageGenerationError("이미 제공자에 전송된 생성은 즉시 취소할 수 없습니다. 완료 후 결과를 사용하지 않을 수 있습니다.")
    job.status = "cancelled"
    job.error_code = "SELLER_CANCELLED"
    job.warnings = ["판매자가 생성 실행을 취소했습니다. 비용 승인 후 다시 시작할 수 있습니다."]
    metadata = dict(job.usage_metadata or {})
    history = list(metadata.get("attempt_history") or [])
    history.append({"attempt": int(job.attempt_count or 0), "status": "cancelled"})
    metadata["attempt_history"] = history
    job.usage_metadata = metadata
    db.commit()
    card = {card.get("id"): card for card in _cards(project)}.get(job.section_id)
    return _job_payload(job, card)


def attach_manual_storyboard_output(
    project: ProductProject,
    job_id: str,
    asset_id: str,
    seller_attested: bool,
    db: Session,
) -> dict[str, Any]:
    """Attach a seller-owned final visual when no image provider is configured.

    The file upload API deliberately labels ordinary seller uploads as
    ``seller_owned``.  This method adds the missing scene-level review step:
    an upload may be used only after the seller explicitly attests that it is
    an original/authorised final visual, never a supplier capture.  The job is
    still placed in ``needs_review`` so the existing identity confirmation is
    required before the storyboard itself is updated.
    """
    job = _job_for_project(project, job_id, db)
    if job.status == "approved":
        raise StoryboardImageGenerationError("이미 승인된 장면은 다시 업로드할 수 없습니다. 새 후보를 만들거나 장면을 수정해 주세요.")
    if not seller_attested:
        raise StoryboardImageGenerationError("직접 업로드한 최종 이미지가 공급처 원본이 아니며 사용 권한이 있음을 확인해 주세요.")

    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.project_id == project.id)
        .first()
    )
    if not asset or not asset.mime_type.startswith("image/"):
        raise StoryboardImageGenerationError("이 프로젝트에 업로드한 이미지 파일을 선택해 주세요.")
    if asset.source_type not in MANUAL_FINAL_SOURCE_TYPES or resolved_asset_usage_status(asset) != "seller_owned":
        raise StoryboardImageGenerationError("공급처 참고 이미지와 자동 수집 이미지는 최종 장면으로 사용할 수 없습니다. 직접 만든 이미지 또는 사용 허가된 파일로 업로드해 주세요.")
    manual_final_issues = _manual_final_asset_issues(project, asset, db)
    if manual_final_issues:
        raise StoryboardImageGenerationError(" ".join(manual_final_issues))
    if not asset.file_path or not os.path.isfile(asset.file_path):
        raise StoryboardImageGenerationError("업로드한 이미지 파일을 찾을 수 없습니다. 다시 업로드해 주세요.")
    if asset.identity_status == "rejected" or asset.quality_status == "rejected":
        raise StoryboardImageGenerationError("품질 또는 상품 정체성 검사에서 제외된 이미지는 사용할 수 없습니다.")

    if not asset.content_hash:
        asset.content_hash = image_sha256(asset.file_path)

    job.output_asset_id = asset.id
    job.provider = "manual_upload"
    job.model = "seller_final_asset"
    job.status = "needs_review"
    job.error_code = None
    job.warnings = [
        "직접 업로드한 최종 후보입니다. 공급처 원본이 아니며 사용 권한이 있는지, 상품 외형·버튼·포트·구성품이 기준 사진과 맞는지 확인한 뒤 사용해 주세요."
    ]
    job.validation_result = {
        "status": "needs_review",
        "manual_upload": True,
        "seller_usage_attested": True,
        "checks": {
            "source": "seller_owned",
            "identity": "seller_confirmation_required",
        },
    }
    job.usage_metadata = {
        **dict(job.usage_metadata or {}),
        "manual_upload": True,
        "seller_usage_attested": True,
        "source_asset_id": asset.id,
    }
    db.commit()
    card = {card.get("id"): card for card in _cards(project)}.get(job.section_id)
    return _job_payload(job, card)


def approve_storyboard_job(project: ProductProject, job_id: str, db: Session, identity_confirmed: bool = False) -> dict[str, Any]:
    job = _job_for_project(project, job_id, db)
    if job.status != "needs_review" or not job.output_asset_id:
        raise StoryboardImageGenerationError("Only a generated image waiting for review can be approved.")
    validation = dict(job.validation_result or {})
    if validation.get("status") == "blocked":
        raise StoryboardImageGenerationError("상품 정체성 또는 공급처 원본 복제 검사에 실패한 후보는 사용할 수 없습니다.")
    if validation.get("status") == "needs_review" and not identity_confirmed:
        raise StoryboardImageGenerationError("외형·버튼·포트·구성품을 기준 사진과 비교한 뒤 확인을 선택해 주세요.")
    asset = db.query(Asset).filter(Asset.id == job.output_asset_id, Asset.project_id == project.id).first()
    if not asset:
        raise StoryboardImageGenerationError("Generated output file is unavailable for review.")
    is_generated_output = (
        (asset.source_type or "").lower()
        in {"ai_generated", "ai-generated", "generated_image", "mock-generated", "real-generated"}
        and resolved_asset_usage_status(asset) in {"blocked", "ai_generated"}
        and (job.provider or "").lower() != "mock"
    )
    is_attested_manual_output = (
        (job.provider or "").lower() == "manual_upload"
        and asset.source_type in MANUAL_FINAL_SOURCE_TYPES
        and resolved_asset_usage_status(asset) == "seller_owned"
        and bool((job.usage_metadata or {}).get("seller_usage_attested"))
    )
    if not (is_generated_output or is_attested_manual_output):
        raise StoryboardImageGenerationError("A supplier capture or mock placeholder cannot be approved as final output.")
    if is_attested_manual_output:
        manual_final_issues = _manual_final_asset_issues(project, asset, db)
        if manual_final_issues:
            raise StoryboardImageGenerationError(" ".join(manual_final_issues))
    if not asset.file_path or not os.path.isfile(asset.file_path):
        raise StoryboardImageGenerationError("Generated output file is unavailable for review.")
    if asset.identity_status == "rejected" or asset.quality_status == "rejected":
        raise StoryboardImageGenerationError("안전 또는 정체성 검사에서 제외된 결과는 사용할 수 없습니다.")

    if not asset.content_hash:
        asset.content_hash = image_sha256(asset.file_path)

    frozen_lg11_source = bool((job.usage_metadata or {}).get("lg11_source_version_id"))
    draft = deepcopy(project.planning_draft or {})
    matched = next((card for card in draft.get("cards") or [] if card.get("id") == job.section_id), None)
    if matched is None and not frozen_lg11_source:
        raise StoryboardImageGenerationError("The storyboard scene for this job no longer exists.")
    if matched is not None:
        matched["image_asset_id"] = asset.id
        matched["image_requirement"] = "asset_ready"
        matched["missing_reasons"] = []
        matched["candidate_asset_ids"] = [asset.id, *(matched.get("candidate_asset_ids") or [])]
        matched["candidate_asset_ids"] = list(dict.fromkeys(matched["candidate_asset_ids"]))
        project.planning_draft = record_storyboard_revision(draft, "ai_redesign_approved")
        # A seller may have assembled a text-first page while waiting for API
        # budget or credentials. Once this scene is approved, upgrade the matching
        # live page section in place instead of forcing the seller to rebuild the
        # entire page and lose their later text/layout edits.
        page = db.query(ProductPage).filter(ProductPage.project_id == project.id).first()
        if page:
            section = (
                db.query(PageSection)
                .filter(PageSection.page_id == page.id, PageSection.section_type == matched.get("type"))
                .order_by(PageSection.sort_order.asc())
                .first()
            )
            if section:
                section.image_asset_id = asset.id
                section.visual_kind = "image"
                section.visual_payload = {
                    **dict(section.visual_payload or {}),
                    "image_generation_pending": False,
                }
    job.status = "approved"
    if is_generated_output:
        # Promote only the explicitly approved candidate into the final-output
        # manifest. Other generated candidates remain blocked/reference-only.
        asset.usage_status = "ai_generated"
    validation["seller_identity_confirmed"] = bool(identity_confirmed)
    if is_attested_manual_output:
        validation["manual_upload_confirmed"] = True
    job.validation_result = validation
    db.commit()
    return _job_payload(job, matched)


def reject_storyboard_job(project: ProductProject, job_id: str, db: Session) -> dict[str, Any]:
    job = _job_for_project(project, job_id, db)
    if job.status not in {"needs_review", "failed", "blocked"}:
        raise StoryboardImageGenerationError("This image job cannot be rejected in its current state.")
    job.status = "rejected"
    db.commit()
    return _job_payload(job, {card.get("id"): card for card in _cards(project)}.get(job.section_id))


def _job_for_project(project: ProductProject, job_id: str, db: Session) -> ImageGenerationJobRecord:
    job = (
        db.query(ImageGenerationJobRecord)
        .filter(ImageGenerationJobRecord.project_id == project.id, ImageGenerationJobRecord.job_id == job_id)
        .first()
    )
    if not job:
        raise StoryboardImageGenerationError("Storyboard image job was not found.")
    return job
