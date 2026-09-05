"""LG-8 provider-neutral, versioned visual prompt compiler.

The compiler is deterministic infrastructure, not an autonomous agent.  It
locks approved facts, seller-owned identity references and Brand Kit visual
rules before a provider adapter renders a final provider request.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import (
    Asset,
    AssetInspectionRecord,
    BrandKitVersion,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ProductFact,
    ProductProject,
    ScenePromptVersion,
)
from src.services.api_ready_generation_service import is_safe_generation_reference
from src.services.brand_kit_service import resolved_project_version
from src.services.commerce_policy import CONFIRMED_FACT_STATUSES, resolved_asset_usage_status


COMPILER_VERSION = "lg8-visual-prompt-compiler-v1"
PROMPT_SCHEMA_VERSION = "scene-prompt-v1"
IDENTITY_FEATURE_REGION_SCHEMA_VERSION = "identity-feature-regions-v1"
IDENTITY_FEATURE_KEYWORDS = {
    "buttons": (
        "button", "buttons", "control", "controls", "switch", "dial",
        "버튼", "조작", "컨트롤", "스위치", "다이얼", "按键",
    ),
    "ports": (
        "port", "ports", "connector", "connectors", "usb", "type-c", "charging",
        "포트", "커넥터", "단자", "충전구", "충전 포트", "充电口",
    ),
    "components": (
        "component", "components", "accessory", "accessories", "included part", "included parts",
        "구성품", "부속", "액세서리", "부속품",
    ),
    "logo": (
        "logo", "brand mark", "brandmark", "로고", "브랜드 마크", "상표",
    ),
}
TEXT_POLICY = {
    "mode": "no_rasterized_copy",
    "final_copy_owner": "deterministic_renderer",
    "allow_in_image_text": False,
    "allow_spec_table": False,
    "allow_price_or_cta": False,
}
INSTRUCTION_PRIORITY = [
    "safety",
    "approved_facts_and_legal",
    "product_identity",
    "channel_pack",
    "category_pack",
    "seller_direction",
    "creative_brief",
    "scene_objective",
    "provider_adapter",
]
BASE_NEGATIVE_CONSTRAINTS = [
    "no text, letters, numbers, Korean copy, Chinese copy or specification tables",
    "no provider-rendered logo, watermark, QR code, barcode, certification mark, price or CTA",
    "no invented buttons, ports, accessories, packaging or product structure",
    "no medical, therapeutic, safety, superiority or performance claim",
    "no supplier layout reproduction and no rasterized marketing copy",
]

SCENE_PROFILES: dict[str, dict[str, Any]] = {
    "hero": {"objective": "Recognizable representative product hero", "composition": "single product, generous negative space", "camera": "three-quarter product view", "lighting": "soft premium studio", "background": "clean brand-neutral gradient"},
    "pain_point": {"objective": "Contextual problem scene without factual claims", "composition": "human-scale context with product as solution cue", "camera": "natural medium view", "lighting": "credible daylight", "background": "uncluttered everyday context"},
    "feature_1": {"objective": "Show one approved feature visually", "composition": "feature-led product close-up", "camera": "macro detail", "lighting": "controlled edge lighting", "background": "minimal neutral"},
    "feature_2": {"objective": "Show one approved feature visually", "composition": "feature-led product close-up", "camera": "macro detail", "lighting": "controlled edge lighting", "background": "minimal neutral"},
    "feature_3": {"objective": "Show one approved feature visually", "composition": "feature-led product close-up", "camera": "macro detail", "lighting": "controlled edge lighting", "background": "minimal neutral"},
    "material_detail": {"objective": "Reveal verified material and finish", "composition": "material texture detail", "camera": "macro texture view", "lighting": "raking light", "background": "neutral seamless"},
    "product_detail": {"objective": "Reveal verified control or construction detail", "composition": "isolated component close-up", "camera": "orthographic close-up", "lighting": "soft technical studio", "background": "neutral seamless"},
    "details_components": {"objective": "Show included components only", "composition": "ordered flat-lay component arrangement", "camera": "top-down", "lighting": "even catalog lighting", "background": "clean solid surface"},
    "component_layout": {"objective": "Show included components only", "composition": "ordered flat-lay component arrangement", "camera": "top-down", "lighting": "even catalog lighting", "background": "clean solid surface"},
    "product_specifications": {"objective": "Reserve a factual specification section background", "composition": "product visual with clear renderer-owned text zones", "camera": "front product view", "lighting": "neutral technical studio", "background": "low-detail information backdrop"},
    "function_visual": {"objective": "Visualize a verified function without overclaiming", "composition": "product-led functional diagram background", "camera": "clear explanatory angle", "lighting": "neutral technical", "background": "clean information field"},
    "usage_guide": {"objective": "Demonstrate a verified use step", "composition": "one action per frame with product visible", "camera": "instructional medium close-up", "lighting": "bright natural", "background": "simple usage context"},
    "usage_scene": {"objective": "Show the verified product in a plausible use context", "composition": "product-first lifestyle scene", "camera": "natural human perspective", "lighting": "credible daylight", "background": "uncluttered lifestyle context"},
    "lifestyle_scene": {"objective": "Show the verified product in a plausible use context", "composition": "product-first lifestyle scene", "camera": "natural human perspective", "lighting": "credible daylight", "background": "uncluttered lifestyle context"},
    "charging_scene": {"objective": "Show verified charging or storage context", "composition": "product and verified charging interface", "camera": "clear functional close-up", "lighting": "neutral technical", "background": "tidy desktop or storage context"},
    "charging_or_power": {"objective": "Show verified charging or power context", "composition": "product and verified power interface", "camera": "clear functional close-up", "lighting": "neutral technical", "background": "tidy desktop context"},
    "cta": {"objective": "Final product reassurance visual; CTA text added later", "composition": "confident product closing hero with empty CTA zone", "camera": "three-quarter hero", "lighting": "premium studio", "background": "brand palette gradient"},
    "hero_reemphasize": {"objective": "Final product reassurance visual", "composition": "confident closing product hero", "camera": "three-quarter hero", "lighting": "premium studio", "background": "brand palette gradient"},
    "benefit_a": {"objective": "Visualize one approved benefit without overclaiming", "composition": "product-led benefit scene with one clear visual idea", "camera": "clear explanatory angle", "lighting": "credible commercial studio", "background": "minimal brand-neutral context"},
    "benefit_b": {"objective": "Visualize one approved benefit without overclaiming", "composition": "product-led benefit scene with one clear visual idea", "camera": "clear explanatory angle", "lighting": "credible commercial studio", "background": "minimal brand-neutral context"},
    "storage_scene": {"objective": "Show a verified storage context", "composition": "product stored neatly without invented accessories", "camera": "natural medium close-up", "lighting": "soft credible daylight", "background": "tidy storage context"},
}

# Image-generation roles are deliberately distinct from storyboard section
# types. Keep both vocabularies first-class so every production scene receives
# the intended LG-8 template instead of a generic fallback (PRM-10).
SCENE_PROFILES.update({
    "representative_product": deepcopy(SCENE_PROFILES["hero"]),
    "detail_closeup": deepcopy(SCENE_PROFILES["product_detail"]),
    "function_visualization": deepcopy(SCENE_PROFILES["function_visual"]),
    "charging_storage_scene": deepcopy(SCENE_PROFILES["charging_or_power"]),
})


class VisualPromptCompileError(ValueError):
    """A seller-correctable visual prompt compilation failure."""

    def __init__(self, code: str, message: str, resolution: str):
        self.code = code
        self.message = message
        self.resolution = resolution
        super().__init__(f"{code}: {message} 해결 방법: {resolution}")


_COPY_OR_MARK_RE = re.compile(
    r"(?:"
    r"(?:로고|워터마크|큐알|qr|바코드|글자|문구|텍스트|카피|헤드라인|가격|할인|cta|인증마크)"
    r".{0,18}(?:넣|추가|표시|노출|작성|삽입|렌더|사용|배치)"
    r"|(?:넣|추가|표시|노출|작성|삽입|렌더|사용|배치)"
    r".{0,18}(?:로고|워터마크|큐알|qr|바코드|글자|문구|텍스트|카피|헤드라인|가격|할인|cta|인증마크)"
    r"|(?:add|include|render|show|write|place|insert).{0,24}"
    r"(?:logo|watermark|qr|barcode|text|copy|headline|price|discount|cta|certification)"
    r")",
    re.IGNORECASE,
)
_UNSAFE_CLAIM_RE = re.compile(
    r"(?:치료|완치|의학적 효능|효능 보장|안전성 보장|100\s*%|무조건|최고|1위|유일|"
    r"cure|treat(?:ment)?|guaranteed|100\s*%|best|number\s*one)",
    re.IGNORECASE,
)


def validate_seller_adjustment(value: str | None) -> str:
    """Allow visual direction only; copy and unverifiable claims stay outside providers."""
    adjustment = (value or "").strip()
    if not adjustment:
        return ""
    if _COPY_OR_MARK_RE.search(adjustment):
        raise VisualPromptCompileError(
            "RASTER_TEXT_OR_MARK_REQUEST_BLOCKED",
            "이미지 안에 문구·가격·로고·워터마크 등을 직접 넣는 요청은 사용할 수 없습니다.",
            "색감, 배경, 구도, 조명처럼 글자가 필요 없는 시각 방향만 입력해 주세요.",
        )
    if _UNSAFE_CLAIM_RE.search(adjustment):
        raise VisualPromptCompileError(
            "UNVERIFIED_VISUAL_CLAIM_BLOCKED",
            "검증되지 않은 효능·우월성·보장 표현이 포함되어 있습니다.",
            "확정 사실을 바꾸지 않는 장면 분위기와 촬영 방향만 입력해 주세요.",
        )
    return adjustment


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _visual_brand_payload(version: BrandKitVersion | None) -> dict[str, Any]:
    if version is None:
        return {"palette": {}, "visual_keywords": [], "forbidden": [], "logo_policy": "none"}
    image_style = dict(version.image_style or {})
    constraints = dict(version.constraints or {})
    logo_ids = list(version.logo_asset_ids or [])
    return {
        "palette": dict(version.color_tokens or {}),
        "visual_keywords": list(image_style.get("keywords") or image_style.get("style_keywords") or []),
        "image_style": image_style,
        "layout_rules": dict(version.layout_rules or {}),
        "background_rules": dict(version.background_rules or {}),
        "forbidden": list(constraints.get("forbidden_visual_elements") or []),
        "logo_policy": "renderer_only" if logo_ids else "none",
        "logo_asset_ids": logo_ids,
        "watermark_policy": dict(version.watermark_policy or {}),
    }


def visual_brand_hash(version: BrandKitVersion | None) -> str:
    """Hash only image-affecting values, never Brand Kit provenance or tone."""
    return canonical_hash(_visual_brand_payload(version))


def _reference_rights_snapshot(db: Session, assets: list[Asset]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for asset in assets:
        inspection = (
            db.query(AssetInspectionRecord)
            .filter(AssetInspectionRecord.asset_id == asset.id)
            .order_by(AssetInspectionRecord.analysis_version.desc(), AssetInspectionRecord.created_at.desc())
            .first()
        )
        snapshots.append({
            "asset_id": asset.id,
            "content_hash": asset.content_hash or "",
            "source_type": asset.source_type,
            "usage_status": resolved_asset_usage_status(asset),
            "rights_status": inspection.rights_status if inspection else "unverified",
            "final_output_eligible": bool(inspection.final_output_eligible) if inspection else False,
            "reference_only": True,
        })
    return snapshots


def _scene_assets(project: ProductProject, card: dict[str, Any], db: Session) -> list[Asset]:
    rows = db.query(Asset).filter(Asset.project_id == project.id, Asset.mime_type.like("image/%")).order_by(
        Asset.intake_order.asc().nullslast(), Asset.created_at.asc()).all()
    by_id = {row.id: row for row in rows}
    ordered_ids = list(card.get("candidate_asset_ids") or [])
    ordered_ids.extend(row.id for row in rows if row.asset_role in {
        "product_main", "product_detail", "product_component", "components", "product_in_use", "usage_scene"})
    selected: list[Asset] = []
    for asset_id in dict.fromkeys(ordered_ids):
        asset = by_id.get(asset_id)
        if asset and is_safe_generation_reference(asset, db):
            selected.append(asset)
        if len(selected) == 3:
            break
    return selected


def _scene_facts(project: ProductProject, card: dict[str, Any], db: Session) -> list[ProductFact]:
    requested = set(card.get("source_fact_ids") or [])
    query = db.query(ProductFact).filter(ProductFact.project_id == project.id)
    if requested:
        query = query.filter(ProductFact.id.in_(requested))
    return [row for row in query.all() if row.verification_status in CONFIRMED_FACT_STATUSES and not row.needs_review]


def _contains_identity_feature_keyword(text: str, keyword: str) -> bool:
    if keyword.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
    return keyword in text


def _identity_feature_regions(assets: list[Asset]) -> dict[str, list[dict[str, Any]]]:
    """Snapshot only explicit, frame-level identity evidence.

    The current asset contract has no segmentation coordinates. A seller- or
    inspector-classified close-up can still provide a deterministic region:
    its full normalized frame. Ambiguous ``product_detail`` assets are not
    assigned to a feature unless their filename/OCR explicitly names it.
    """

    regions: dict[str, list[dict[str, Any]]] = {
        feature: [] for feature in IDENTITY_FEATURE_KEYWORDS
    }
    for reference_index, asset in enumerate(assets):
        role = str(asset.asset_role or "").lower()
        evidence_text = " ".join((str(asset.filename or ""), str(asset.ocr_text or ""))).lower()
        explicit_features: set[str] = set()
        if role in {"product_detail", "feature"}:
            explicit_features = {
                feature
                for feature, keywords in IDENTITY_FEATURE_KEYWORDS.items()
                if any(_contains_identity_feature_keyword(evidence_text, keyword) for keyword in keywords)
            }
        if role in {"components", "product_component"}:
            explicit_features.add("components")

        for feature in sorted(explicit_features):
            regions[feature].append({
                "feature": feature,
                "reference_asset_id": asset.id,
                "reference_index": reference_index,
                "reference_box": [0.0, 0.0, 1.0, 1.0],
                "output_box": [0.0, 0.0, 1.0, 1.0],
                "coordinate_space": "normalized",
                "evidence_source": (
                    "asset_role" if feature == "components" and role in {"components", "product_component"}
                    else "asset_metadata"
                ),
                "reference_role": asset.asset_role,
            })
    return regions


def _identity_constraints(project: ProductProject, assets: list[Asset], facts: list[ProductFact]) -> dict[str, Any]:
    return {
        "product_name": project.name,
        "preserve_exactly": ["silhouette", "color", "material", "buttons", "ports", "components", "included_parts"],
        "reference_roles": [asset.asset_role for asset in assets],
        "feature_region_schema_version": IDENTITY_FEATURE_REGION_SCHEMA_VERSION,
        "feature_regions": _identity_feature_regions(assets),
        "fact_constraints": [
            {"id": fact.id, "field": fact.field_key, "value": fact.normalized_value or fact.fact_text, "unit": fact.normalized_unit}
            for fact in facts
        ],
        "unknown_structure_policy": "do_not_invent",
    }


def _stale_previous_scene(db: Session, previous: ScenePromptVersion, reason: str) -> None:
    previous.status = "stale"
    previous.stale_reason = reason
    previous.stale_at = datetime.datetime.utcnow()
    previous.stale_impact = {"scene_ids": [previous.scene_id], "artifact_types": ["scene_prompt", "image_job"]}
    jobs = db.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == previous.project_id,
        ImageGenerationJobRecord.scene_id == previous.scene_id,
        ImageGenerationJobRecord.scene_prompt_version_id == previous.id,
        ImageGenerationJobRecord.status.notin_(["cancelled", "stale"]),
    ).all()
    for job in jobs:
        job.status = "stale"
        job.error_code = "SCENE_PROMPT_STALE"
        job.warnings = ["장면 프롬프트 또는 기준 사진이 변경되어 이 장면만 다시 생성해야 합니다."]
        outbox = db.query(ImageGenerationOutboxRecord).filter_by(image_job_id=job.id).first()
        if outbox and outbox.status in {"queued", "leased", "retry_wait"}:
            outbox.status = "cancelled"
            outbox.last_error_code = "SCENE_PROMPT_STALE"


def compile_scene_prompt(
    project: ProductProject,
    card: dict[str, Any],
    db: Session,
    *,
    run_id: str | None = None,
    seller_adjustment: str | None = None,
    brand_kit_version_id: str | None = None,
    brand_kit_hash: str | None = None,
) -> ScenePromptVersion:
    scene_id = str(card.get("id") or card.get("type") or "scene")
    scene_type = str(card.get("type") or "hero")
    profile = deepcopy(SCENE_PROFILES.get(scene_type) or SCENE_PROFILES["product_detail"])
    safe_seller_adjustment = validate_seller_adjustment(
        seller_adjustment if seller_adjustment is not None else card.get("visual_prompt_adjustment")
    )
    assets = _scene_assets(project, card, db)
    facts = _scene_facts(project, card, db)
    # A LangGraph run pins the Brand Kit in its CompiledPromptArtifact and
    # Creative Brief.  Never re-resolve "the currently active" version while
    # that same run is compiling prompts or preparing provider jobs: an admin
    # may activate a newer Brand Kit between two interrupts.  Manual/API
    # compilation outside a run intentionally keeps the current-version path.
    if brand_kit_version_id:
        brand = db.query(BrandKitVersion).filter_by(
            id=brand_kit_version_id,
            workspace_id=project.workspace_id,
        ).first()
        if brand is None:
            raise VisualPromptCompileError(
                "PINNED_BRAND_KIT_NOT_FOUND",
                "이 실행에 고정된 Brand Kit 버전을 찾을 수 없습니다.",
                "실행을 새로 만들거나 Brand Kit 버전 연결 상태를 확인해 주세요.",
            )
        if brand_kit_hash and brand.content_hash != brand_kit_hash:
            raise VisualPromptCompileError(
                "PINNED_BRAND_KIT_HASH_MISMATCH",
                "이 실행의 Brand Kit 해시가 저장된 버전과 일치하지 않습니다.",
                "현재 실행을 중단하고 입력 자료부터 새 실행을 만들어 주세요.",
            )
    else:
        brand = resolved_project_version(db, project.workspace_id, project.id)
    brand_payload = _visual_brand_payload(brand)
    references = [{"id": a.id, "hash": a.content_hash or "", "role": a.asset_role} for a in assets]
    reference_hash = canonical_hash(references)
    rights_snapshot = _reference_rights_snapshot(db, assets)
    identity = _identity_constraints(project, assets, facts)
    negative = [*BASE_NEGATIVE_CONSTRAINTS, *brand_payload.get("forbidden", [])]
    canonical = {
        "schema_version": PROMPT_SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "scene_id": scene_id,
        "scene_type": scene_type,
        "objective": profile["objective"],
        "scene_instruction": card.get("scene_request") or "",
        "seller_adjustment": safe_seller_adjustment,
        "identity_lock": identity,
        "composition": {"instruction": profile["composition"], "renderer_text_zone_required": True},
        "camera": {"instruction": profile["camera"]},
        "lighting": {"instruction": profile["lighting"]},
        "background": {"instruction": profile["background"], **dict(brand_payload.get("background_rules") or {})},
        "palette": dict(brand_payload.get("palette") or {}),
        "material": {"preserve_from_reference": True},
        "brand_visual": brand_payload,
        "logo_policy": brand_payload.get("logo_policy", "none"),
        "negative_constraints": negative,
        "text_policy": TEXT_POLICY,
        "rights_snapshot": rights_snapshot,
        "instruction_priority": INSTRUCTION_PRIORITY,
        "reference_assets": references,
        "approved_fact_ids": [fact.id for fact in facts],
    }
    input_hash = canonical_hash(canonical)
    current = db.query(ScenePromptVersion).filter_by(project_id=project.id, scene_id=scene_id, status="active").order_by(
        ScenePromptVersion.version.desc()).first()
    if current and current.input_hash == input_hash:
        return current
    if current:
        reason = "brand_visual_changed" if current.brand_kit_visual_hash != visual_brand_hash(brand) else "scene_input_changed"
        _stale_previous_scene(db, current, reason)
    next_version = int(db.query(func.max(ScenePromptVersion.version)).filter_by(
        project_id=project.id, scene_id=scene_id).scalar() or 0) + 1
    prompt_hash = canonical_hash(canonical)
    record = ScenePromptVersion(
        workspace_id=project.workspace_id, project_id=project.id, run_id=run_id,
        section_id=scene_id, scene_id=scene_id, scene_type=scene_type, version=next_version,
        status="active", objective=profile["objective"], approved_fact_ids=[f.id for f in facts],
        reference_asset_ids=[a.id for a in assets], reference_hash=reference_hash,
        identity_constraints=identity, composition=canonical["composition"], camera=canonical["camera"],
        lighting=canonical["lighting"], background=canonical["background"], palette=canonical["palette"],
        material=canonical["material"], negative_constraints=negative, text_policy=TEXT_POLICY,
        rights_snapshot=rights_snapshot, instruction_priority=INSTRUCTION_PRIORITY,
        provider=settings.SELLFORM_IMAGE_PROVIDER, model=settings.SELLFORM_IMAGE_MODEL,
        size="1024x1024", quality="standard", expected_cost=1.0,
        prompt_version=f"{PROMPT_SCHEMA_VERSION}:v{next_version}", prompt_hash=prompt_hash, input_hash=input_hash,
        brand_kit_version_id=brand.id if brand else None, brand_kit_visual_hash=visual_brand_hash(brand),
        canonical_prompt=canonical, seller_adjustment=canonical["seller_adjustment"],
        supersedes_version_id=current.id if current else None,
    )
    db.add(record)
    db.flush()
    return record


def compile_project_scene_prompts(
    project: ProductProject,
    db: Session,
    *,
    run_id: str | None = None,
    brand_kit_version_id: str | None = None,
    brand_kit_hash: str | None = None,
) -> list[ScenePromptVersion]:
    cards = [card for card in (project.planning_draft or {}).get("cards") or [] if card.get("is_enabled", True)]
    records = [
        compile_scene_prompt(
            project,
            card,
            db,
            run_id=run_id,
            brand_kit_version_id=brand_kit_version_id,
            brand_kit_hash=brand_kit_hash,
        )
        for card in cards
    ]
    db.commit()
    return records


def provider_prompt(record: ScenePromptVersion) -> tuple[str, str]:
    """Adapt the canonical contract at the provider boundary only."""
    item = dict(record.canonical_prompt or {})
    identity = item.get("identity_lock") or {}
    brand = item.get("brand_visual") or {}
    # Storyboard scene_request may contain a headline/body-copy instruction.
    # Raster image providers must never receive that copy: Korean typography is
    # owned by the deterministic renderer (PRM-12).  Only visual-only seller
    # adjustments that survived the service validation are sent downstream.
    visual_keywords = [
        str(value)
        for value in (brand.get("visual_keywords") or [])
        if not any(
            blocked in str(value).lower()
            for blocked in ("text", "copy", "letter", "logo", "watermark", "price", "cta")
        )
    ]
    prompt = " ".join(filter(None, [
        f"Create an original e-commerce visual for {identity.get('product_name') or 'the supplied product'}.",
        f"Objective: {item.get('objective')}.",
        f"Composition: {(item.get('composition') or {}).get('instruction')}.",
        f"Camera: {(item.get('camera') or {}).get('instruction')}.",
        f"Lighting: {(item.get('lighting') or {}).get('instruction')}.",
        f"Background: {(item.get('background') or {}).get('instruction')}.",
        f"Preserve exact product identity from reference assets: {', '.join(identity.get('preserve_exactly') or [])}.",
        f"Visual style: {', '.join(visual_keywords)}." if visual_keywords else "",
        str(item.get("seller_adjustment") or ""),
        "Keep the visual uncluttered with generous negative space.",
    ]))
    return prompt, "; ".join(record.negative_constraints or BASE_NEGATIVE_CONSTRAINTS)


def scene_prompt_payload(record: ScenePromptVersion) -> dict[str, Any]:
    return {
        "id": record.id, "scene_id": record.scene_id, "section_id": record.section_id,
        "scene_type": record.scene_type, "version": record.version, "status": record.status,
        "objective": record.objective, "reference_asset_ids": list(record.reference_asset_ids or []),
        "reference_hash": record.reference_hash, "prompt_version": record.prompt_version,
        "prompt_hash": record.prompt_hash, "input_hash": record.input_hash,
        "brand_kit_version_id": record.brand_kit_version_id,
        "brand_kit_visual_hash": record.brand_kit_visual_hash,
        "identity_constraints": dict(record.identity_constraints or {}),
        "composition": dict(record.composition or {}), "camera": dict(record.camera or {}),
        "lighting": dict(record.lighting or {}), "background": dict(record.background or {}),
        "palette": dict(record.palette or {}), "negative_constraints": list(record.negative_constraints or []),
        "text_policy": dict(record.text_policy or {}), "provider": record.provider,
        "rights_snapshot": list(record.rights_snapshot or []),
        "instruction_priority": list(record.instruction_priority or []),
        "logo_policy": (record.canonical_prompt or {}).get("logo_policy", "none"),
        "model": record.model, "size": record.size, "quality": record.quality,
        "expected_cost": record.expected_cost, "seller_adjustment": record.seller_adjustment,
        "stale_reason": record.stale_reason, "stale_impact": dict(record.stale_impact or {}),
    }
