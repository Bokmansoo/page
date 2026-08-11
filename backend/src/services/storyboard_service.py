"""Sprint 4 purchase-flow storyboard planning.

The storyboard is intentionally provider-free: it only plans the scenes and
the eligible asset slots that Sprint 5 may later generate.  Keeping it inside
``planning_draft`` preserves compatibility with existing project drafts while
adding a versioned, fact-snapshotted contract.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from sqlalchemy.orm import Session

from src.db.models import Asset, ProductFact, ProductProject
from src.services.commerce_policy import (
    CONFIRMED_FACT_STATUSES,
    is_asset_final_output_eligible,
    resolved_asset_usage_status,
)
from src.services.detail_page_template_service import DetailPageTemplateService
from src.services.fact_evidence_service import approved_fact_snapshot
from src.services.planning_draft_service import PlanningDraftService


STORYBOARD_VERSION = 1
IMAGE_SECTION_TYPES = {
    "hero", "lifestyle_scene", "usage_scene", "material_detail", "product_detail",
    "benefit_a", "benefit_b", "hero_reemphasize", "cta",
}
FINAL_SPEC_TYPES = {"specifications", "final_specifications", "product_specifications"}
MOCK_ASSET_SOURCE_TYPES = {"mock-generated", "mock_generated", "mock"}
# The local mock image provider writes a tiny, highly-compressible red/blue
# bitmap.  Older projects persisted those files as ordinary ``ai_generated``
# assets, so source_type alone is not enough to identify them.  A genuine
# product visual should comfortably exceed this conservative byte threshold.
MIN_GENERATED_STORYBOARD_BYTES = 4 * 1024
SECTION_ROLE = {
    "hero": "product_main",
    "lifestyle_scene": "usage_scene",
    "usage_scene": "usage_scene",
    "material_detail": "material_detail",
    "product_detail": "product_detail",
    "benefit_a": "feature",
    "benefit_b": "feature",
    "hero_reemphasize": "product_main",
}


class StoryboardValidationError(ValueError):
    pass


def _is_storyboard_ready_asset(asset: Asset) -> bool:
    """Return whether an asset can satisfy a final storyboard image slot.

    Sprint 4 may run after older mock-mode image jobs.  Those jobs created
    placeholder bitmaps but labelled them ``ai_generated``.  Treating them as
    finished product imagery hides the real Sprint 5 scene requests and can
    lead to a storyboard being approved with no usable images.
    """
    if not is_asset_final_output_eligible(asset):
        return False
    if (asset.quality_status or "").strip().lower() == "rejected":
        return False

    source_type = (asset.source_type or "").strip().lower()
    usage_status = resolved_asset_usage_status(asset)
    if source_type in MOCK_ASSET_SOURCE_TYPES:
        return False
    if usage_status == "ai_generated":
        if asset.file_size is not None and asset.file_size <= MIN_GENERATED_STORYBOARD_BYTES:
            return False
        if asset.width is not None and asset.height is not None and min(asset.width, asset.height) <= 16:
            return False
    return True


def _eligible_assets(assets: Iterable[Asset]) -> list[Asset]:
    return [asset for asset in assets if _is_storyboard_ready_asset(asset)]


def _reference_assets(assets: Iterable[Asset]) -> list[Asset]:
    return [asset for asset in assets if resolved_asset_usage_status(asset) == "reference_only"]


def _scene_request(project: ProductProject, card_type: str, title: str) -> str | None:
    product = project.name or "상품"
    requests = {
        "hero": f"{product}의 실제 실루엣과 조작부를 유지한 제품 단독 HERO 장면. 배경·조명·구도만 새로 구성하고 이미지 안 텍스트는 넣지 않습니다.",
        "lifestyle_scene": f"{product}를 올바른 사용 환경에서 보여 주는 사용 장면. 제품 구조와 사용법을 새로 만들지 않습니다.",
        "usage_scene": f"{product}의 사용 흐름을 보여 주는 장면. 손·접촉 위치와 제품 버튼·포트는 기준 이미지와 일치해야 합니다.",
        "material_detail": f"{product}의 확인된 소재·구조를 가까이 보여 주는 디테일 장면. 원본의 중국어 문구·레이아웃은 재현하지 않습니다.",
        "product_detail": f"{product}의 버튼·포트·구성품을 식별할 수 있는 근접 장면. 확인되지 않은 기능이나 액세서리는 넣지 않습니다.",
        "benefit_a": f"{product}의 확인된 핵심 기능을 뒷받침하는 상품 장면. 문구는 이미지에 넣지 않습니다.",
        "benefit_b": f"{product}의 확인된 보조 기능을 뒷받침하는 상품 장면. 문구는 이미지에 넣지 않습니다.",
        "hero_reemphasize": f"{product}의 제품 정체성을 유지한 보조 HERO 장면. 첫 HERO와 다른 구도를 사용합니다.",
        "cta": f"{product}의 구매 전 마지막 인상을 위한 깔끔한 제품 장면. 과장된 효능·인증 표시는 넣지 않습니다.",
    }
    return requests.get(card_type)


def _rendering_template(card_type: str) -> str:
    if card_type in FINAL_SPEC_TYPES:
        return "final_spec_table"
    if card_type in {"features", "benefits_summary", "comparison"}:
        return "fact_cards"
    if card_type in IMAGE_SECTION_TYPES:
        return "image_copy_split"
    return "copy_only"


def _clone_card(card: dict[str, Any]) -> dict[str, Any]:
    cloned = deepcopy(card)
    cloned["source_fact_ids"] = list(cloned.get("source_fact_ids") or [])
    cloned["bullets"] = list(cloned.get("bullets") or [])
    return cloned


def _extra_card(project: ProductProject, card_type: str, sort_order: int, fact_ids: list[str]) -> dict[str, Any]:
    product = project.name or "상품"
    copy = {
        "lifestyle_scene": ("일상 속에서 자연스럽게 쓰는 순간", ["사용 장면은 다음 단계에서 상품 정체성을 유지한 새 이미지로 준비합니다."]),
        "usage_scene": ("사용 흐름을 한눈에 확인하세요", ["확인된 사용 조건을 바탕으로 장면을 준비합니다."]),
        "material_detail": ("소재와 구조를 가까이 살펴보세요", ["확인된 디테일만 사용해 정보 그래픽 또는 새 장면으로 구성합니다."]),
        "product_detail": ("조작부와 구성 요소를 확인하세요", ["제품에 실제로 확인된 요소만 보여 줍니다."]),
    }
    title, bullets = copy[card_type]
    return {
        "id": f"storyboard-{card_type}-{sort_order}",
        "type": card_type,
        "label": {"lifestyle_scene": "사용 장면", "usage_scene": "사용 방법", "material_detail": "소재·디테일", "product_detail": "조작·구성"}[card_type],
        "title": f"{product} {title}" if card_type == "lifestyle_scene" else title,
        "bullets": bullets,
        "source_fact_ids": fact_ids,
        "visual_strategy": "lifestyle_image" if card_type in {"lifestyle_scene", "usage_scene"} else "image_overlay",
        "is_enabled": True,
        "sort_order": sort_order,
    }


def _normalize_order(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    final = [card for card in cards if card.get("type") in FINAL_SPEC_TYPES]
    normal = [card for card in cards if card.get("type") not in FINAL_SPEC_TYPES]
    ordered = normal + final
    for index, card in enumerate(ordered):
        card["sort_order"] = index
    return ordered


def _variant_cards(project: ProductProject, base_cards: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    cards = [_clone_card(card) for card in base_cards]
    specs = [card for card in cards if card.get("type") in FINAL_SPEC_TYPES]
    content = [card for card in cards if card.get("type") not in FINAL_SPEC_TYPES]
    source_ids = [fact_id for card in content for fact_id in card.get("source_fact_ids") or []]
    source_ids = list(dict.fromkeys(source_ids))

    if key == "visual_story":
        insert_at = min(len(content), 4)
        content.insert(insert_at, _extra_card(project, "lifestyle_scene", insert_at, source_ids[:2]))
        content.insert(insert_at + 1, _extra_card(project, "material_detail", insert_at + 1, source_ids[2:4]))
    elif key == "information_graphic":
        insert_at = min(len(content), 4)
        content.insert(insert_at, _extra_card(project, "product_detail", insert_at, source_ids[:2]))
        content.insert(insert_at + 1, _extra_card(project, "usage_scene", insert_at + 1, source_ids[2:4]))
    return _normalize_order(content + specs)


def _decorate_cards(project: ProductProject, cards: list[dict[str, Any]], assets: list[Asset]) -> list[dict[str, Any]]:
    eligible = _eligible_assets(assets)
    references = _reference_assets(assets)
    used_assets: set[str] = set()
    decorated: list[dict[str, Any]] = []
    for raw in cards:
        card = _clone_card(raw)
        card_type = str(card.get("type") or "")
        wanted_role = SECTION_ROLE.get(card_type)
        matching = [asset for asset in eligible if asset.id not in used_assets and (not wanted_role or asset.asset_role == wanted_role)]
        fallback = [asset for asset in eligible if asset.id not in used_assets]
        candidate_assets = matching or fallback
        card["candidate_asset_ids"] = [asset.id for asset in candidate_assets[:3]]
        card["image_asset_id"] = None
        card["rendering_template"] = _rendering_template(card_type)
        card["facts_stale"] = False
        card["missing_reasons"] = []
        scene = _scene_request(project, card_type, str(card.get("title") or ""))
        card["scene_request"] = scene

        if card_type not in IMAGE_SECTION_TYPES:
            card["image_requirement"] = "derived_graphic" if card_type in {"features", "benefits_summary", "comparison", *FINAL_SPEC_TYPES} else "not_required"
        elif candidate_assets:
            selected = candidate_assets[0]
            card["image_asset_id"] = selected.id
            card["image_requirement"] = "asset_ready"
            used_assets.add(selected.id)
        elif references:
            card["image_requirement"] = "ai_redesign_required"
            card["missing_reasons"].append("공급처 참고 이미지는 최종 출력에 직접 사용할 수 없습니다. AI 리디자인 장면이 필요합니다.")
            card["candidate_asset_ids"] = [asset.id for asset in references[:3]]
        else:
            card["image_requirement"] = "seller_upload_required"
            card["missing_reasons"].append("최종 출력에 쓸 수 있는 상품 이미지가 없습니다. 대표컷 또는 필요한 장면을 올려 주세요.")
        decorated.append(card)
    return decorated


def _recommended_candidates(project: ProductProject, base_cards: list[dict[str, Any]], assets: list[Asset]) -> list[dict[str, Any]]:
    has_final_assets = bool(_eligible_assets(assets))
    definitions = [
        ("safe_information", "안전 정보형", "승인된 사실과 정보 그래픽을 우선해 이미지가 부족해도 근거를 유지합니다.", "information_graphic"),
        ("visual_story", "이미지 중심형", "HERO·사용·소재 장면을 분리해 구매 흐름을 풍부하게 만듭니다.", "visual_story"),
        ("balanced_sales", "균형 판매형", "설득 문구와 핵심 기능·최종 사양을 균형 있게 배치합니다.", "balanced"),
    ]
    candidates = []
    for key, label, reason, mode in definitions:
        variant_key = "information_graphic" if key == "safe_information" else "visual_story" if key == "visual_story" else "balanced"
        cards = _decorate_cards(project, _variant_cards(project, base_cards, variant_key), assets)
        missing = [
            {"section_id": card["id"], "section_type": card["type"], "requirement": card["image_requirement"], "scene_request": card.get("scene_request")}
            for card in cards if card.get("image_requirement") in {"ai_redesign_required", "seller_upload_required"}
        ]
        candidates.append({
            "key": key,
            "label": label,
            "reason": reason,
            "visual_mode": mode,
            "cards": cards,
            "missing_images": missing,
            "warnings": ([] if has_final_assets else ["최종 출력 가능 이미지가 부족합니다. Sprint 5 AI 리디자인 또는 판매자 업로드가 필요합니다."]),
            "estimated_cost": round(len(missing) * 0.0, 2),
        })
    return candidates


def _revision_snapshot(draft: dict[str, Any], revision: int, action: str) -> dict[str, Any]:
    return {
        "revision": revision,
        "action": action,
        "selected_candidate_key": draft.get("selected_candidate_key"),
        "cards": deepcopy(draft.get("cards") or []),
    }


def record_storyboard_revision(draft: dict[str, Any], action: str) -> dict[str, Any]:
    """Append a bounded, restore-safe snapshot without nesting history itself."""
    updated = deepcopy(draft)
    revision = int(updated.get("revision") or 0) + 1
    history = list(updated.get("revision_history") or [])
    history.append(_revision_snapshot(updated, revision, action))
    updated["revision"] = revision
    updated["revision_history"] = history[-10:]
    return updated


def generate_storyboard(project: ProductProject, facts: list[ProductFact], assets: list[Asset], db: Session, user_id: str | None) -> dict[str, Any]:
    base = PlanningDraftService.generate_draft(project, facts, db)
    base_cards = _normalize_order([_clone_card(card) for card in base.get("cards") or []])
    candidates = _recommended_candidates(project, base_cards, assets)
    selected = "balanced_sales" if _eligible_assets(assets) else "safe_information"
    selected_cards = next(candidate["cards"] for candidate in candidates if candidate["key"] == selected)
    snapshot = approved_fact_snapshot(db, project.id, user_id, purpose="storyboard")
    return {
        "cards": selected_cards,
        "storyboard_version": STORYBOARD_VERSION,
        "selected_candidate_key": selected,
        "recommendations": candidates,
        "fact_snapshot_id": snapshot.id,
        "fact_snapshot_hash": snapshot.snapshot_hash,
        "status": "draft",
        "stale_fact_ids": [],
        "estimated_cost": 0.0,
        "revision": 1,
        "revision_history": [{"revision": 1, "action": "generated", "selected_candidate_key": selected, "cards": deepcopy(selected_cards)}],
        "template_id": base.get("template_id"),
        "template_name": base.get("template_name"),
    }


def select_recommendation(draft: dict[str, Any], candidate_key: str) -> dict[str, Any]:
    updated = deepcopy(draft)
    candidate = next((item for item in updated.get("recommendations") or [] if item.get("key") == candidate_key), None)
    if candidate is None:
        raise StoryboardValidationError("Unknown storyboard recommendation.")
    updated["selected_candidate_key"] = candidate_key
    updated["cards"] = _normalize_order([_clone_card(card) for card in candidate.get("cards") or []])
    updated["status"] = "draft"
    return record_storyboard_revision(updated, "recommendation_selected")


def restore_storyboard_revision(draft: dict[str, Any], revision: int) -> dict[str, Any]:
    snapshot = next((item for item in draft.get("revision_history") or [] if item.get("revision") == revision), None)
    if snapshot is None:
        raise StoryboardValidationError("Requested storyboard revision was not found.")
    updated = deepcopy(draft)
    updated["cards"] = _normalize_order([_clone_card(card) for card in snapshot.get("cards") or []])
    updated["selected_candidate_key"] = snapshot.get("selected_candidate_key")
    updated["status"] = "draft"
    return record_storyboard_revision(updated, f"restored_from_{revision}")


def mark_storyboard_assets_stale(project: ProductProject, asset_ids: Iterable[str]) -> bool:
    """Invalidate an approved storyboard when one of its selected assets changes."""
    changed = set(asset_ids)
    draft = deepcopy(project.planning_draft or {})
    if not draft or not changed:
        return False

    affected = False
    for card in draft.get("cards") or []:
        if card.get("image_asset_id") in changed or changed.intersection(card.get("candidate_asset_ids") or []):
            card["facts_stale"] = True
            affected = True
    for recommendation in draft.get("recommendations") or []:
        for card in recommendation.get("cards") or []:
            if card.get("image_asset_id") in changed or changed.intersection(card.get("candidate_asset_ids") or []):
                card["facts_stale"] = True
                recommendation["assets_stale"] = True
                affected = True
    if affected:
        draft["status"] = "stale"
        draft["stale_asset_ids"] = list(dict.fromkeys([*(draft.get("stale_asset_ids") or []), *changed]))
        project.planning_draft = draft
    return affected


def validate_storyboard(draft: dict[str, Any], assets: list[Asset], confirmed_fact_ids: set[str]) -> None:
    cards = [card for card in draft.get("cards") or [] if card.get("is_enabled", True)]
    if not cards:
        raise StoryboardValidationError("At least one storyboard section is required.")
    if len(cards) > 12:
        raise StoryboardValidationError("A storyboard can contain at most 12 visible sections.")
    if not cards[-1].get("type") in FINAL_SPEC_TYPES:
        raise StoryboardValidationError("Final product specifications must be the last visible storyboard section.")

    assets_by_id = {asset.id: asset for asset in assets}
    assigned_assets: set[str] = set()
    for card in cards:
        fact_ids = set(card.get("source_fact_ids") or [])
        if not fact_ids.issubset(confirmed_fact_ids):
            raise StoryboardValidationError("Storyboard copy can only reference confirmed facts.")
        asset_id = card.get("image_asset_id")
        if not asset_id:
            continue
        asset = assets_by_id.get(asset_id)
        if asset is None:
            raise StoryboardValidationError("Selected storyboard asset does not belong to this project.")
        if not _is_storyboard_ready_asset(asset):
            raise StoryboardValidationError(
                "Reference-only, rejected, or mock placeholder assets cannot be assigned to final storyboard sections."
            )
        if asset_id in assigned_assets:
            raise StoryboardValidationError("The same final asset cannot be automatically repeated across storyboard sections.")
        assigned_assets.add(asset_id)


def approve_storyboard(project: ProductProject, assets: list[Asset], facts: list[ProductFact], db: Session, user_id: str | None) -> dict[str, Any]:
    draft = deepcopy(project.planning_draft or {})
    confirmed_ids = {fact.id for fact in facts if fact.verification_status in CONFIRMED_FACT_STATUSES and not fact.needs_review}
    validate_storyboard(draft, assets, confirmed_ids)
    snapshot = approved_fact_snapshot(db, project.id, user_id, purpose="storyboard_approval")
    draft["fact_snapshot_id"] = snapshot.id
    draft["fact_snapshot_hash"] = snapshot.snapshot_hash
    draft["status"] = "approved"
    draft["stale_fact_ids"] = []
    draft = record_storyboard_revision(draft, "approved")
    project.planning_draft = draft
    return draft
