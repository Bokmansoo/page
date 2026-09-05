"""UX-2E-0 provider-free product brief and scene-plan contract.

This module deliberately prepares a future generation request without calling
an LLM, OCR provider, or image provider.  It gives the UI an honest answer:
which scenes can use a seller asset today and which scenes must wait for a
real provider connection.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from src.db.models import Asset, ProductFact, ProductProject
from src.services.commerce_content_quality_service import auto_placement_risk_codes
from src.services.commerce_policy import CONFIRMED_FACT_STATUSES


PLAN_KEY = "ux2e0_generation_plan"
PLAN_VERSION = 2
SAFE_SOURCE_TYPES = {"uploaded", "self_shot"}
DEFAULT_FORBIDDEN_CLAIMS = ["치료·효능 보장", "인증·안전성 단정", "근거 없는 경쟁 우위", "가격·할인"]


def _intake_bundle(project: ProductProject) -> dict[str, Any]:
    snapshot = project.intake_snapshot if isinstance(project.intake_snapshot, dict) else {}
    return snapshot.get("input_bundle") if isinstance(snapshot.get("input_bundle"), dict) else {}


def _first_fact_value(facts: list[ProductFact], *field_keys: str) -> str | None:
    requested = {value.lower() for value in field_keys}
    for fact in facts:
        if (fact.field_key or "").lower() in requested:
            return fact.normalized_value or fact.fact_text
    return None


def _split_options(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]


def _identity_criteria(reference_asset_ids: list[str], color: str | None, model_option: str | None) -> dict[str, Any]:
    return {
        "reference_asset_ids": reference_asset_ids,
        "color": color,
        "model_option": model_option,
        "must_preserve": ["제품 형태", "색상", "버튼", "포트", "구성품"],
        "seller_notes": "",
    }


def _fact_payload(fact: ProductFact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "field_key": fact.field_key or "product_information",
        "text": fact.fact_text,
        "value": fact.normalized_value,
        "unit": fact.normalized_unit,
        "model_option": fact.model_option,
        "verification_status": fact.verification_status,
        "source_asset_id": fact.source_asset_id,
        "scope": fact.scope or "product",
        "conflict_group_key": fact.conflict_group_key,
    }


def _safe_asset_payload(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "filename": asset.filename,
        "asset_role": asset.asset_role,
        "content_hash": asset.content_hash,
        "is_representative": bool(asset.is_representative),
        "source_type": asset.source_type,
    }


def is_safe_generation_reference(asset: Asset, db: Session) -> bool:
    """Return whether an asset may leave the server as an AI image input.

    Supplier captures and OCR-risk images remain useful evidence for planning,
    but UX-2E-2 deliberately excludes them from provider-bound requests.
    """
    return (
        (asset.source_type or "").lower() in SAFE_SOURCE_TYPES
        and (asset.usage_status or "seller_owned").lower() == "seller_owned"
        and (asset.mime_type or "").startswith("image/")
        and asset.quality_status != "rejected"
        and not auto_placement_risk_codes(asset, db)
    )


def _scene_type(card_type: str) -> str:
    normalized = (card_type or "").lower()
    if normalized == "hero":
        return "hero_product"
    if normalized in {"usage", "usage_guide", "lifestyle_scene", "target_customer"}:
        return "usage_scene"
    if normalized in {"comparison", "problem"}:
        return "comparison"
    if normalized in {"specifications", "product_info", "details_components"}:
        return "spec_graphic"
    if normalized in {"caution", "notice"}:
        return "notice"
    if normalized in {"charging", "charging_or_power"}:
        return "charging_or_power"
    return "feature_closeup"


def _default_scene_cards() -> list[dict[str, str]]:
    return [
        {"id": "hero", "type": "hero", "label": "대표 제품 소개", "title": "대표 제품 컷"},
        {"id": "usage", "type": "usage_guide", "label": "사용 장면", "title": "사용 부위와 사용 장면"},
        {"id": "feature", "type": "features", "label": "핵심 기능", "title": "제품 특징 강조"},
        {"id": "power", "type": "charging_or_power", "label": "전원·충전 안내", "title": "전원 또는 충전 안내"},
        {"id": "comparison", "type": "comparison", "label": "구매 전 확인", "title": "확인된 구매 포인트"},
        {"id": "spec", "type": "specifications", "label": "사양·주의사항", "title": "제품 사양과 필수 고지"},
    ]


def _prompt_blueprint(project: ProductProject, scene_type: str, fact_ids: list[str]) -> dict[str, Any]:
    return {
        "prompt_version": "ux2e0-v1",
        "scene_type": scene_type,
        "product_name": project.name or "상품",
        "allowed_fact_ids": fact_ids,
        "instruction": "기준 제품 사진의 형태·색상·버튼·포트·구성품을 유지하고, 판매자 승인 사실만 사용합니다.",
        "negative_constraints": [
            "외국어 또는 한국어 문구를 이미지 안에 생성하지 않음",
            "가격, 전화번호, QR, 마켓·타사 로고를 넣지 않음",
            "기준 제품의 형태·색상·버튼·포트·구성품을 변경하지 않음",
        ],
    }


def _copy_blueprint(scene_type: str, fact_ids: list[str]) -> dict[str, Any]:
    return {
        "scene_type": scene_type,
        "allowed_fact_ids": fact_ids,
        "headline_goal": "확인된 제품 정보를 구매자가 이해하기 쉽게 안내",
        "body_length": "2문장 이내",
        "forbidden_claims": list(DEFAULT_FORBIDDEN_CLAIMS),
    }


def _scene_status(scene_type: str, reference_ids: list[str], has_verified_comparison: bool) -> tuple[str, str]:
    if scene_type in {"spec_graphic", "notice"}:
        return "information_fallback", "html_information"
    if scene_type == "comparison" and not has_verified_comparison:
        return "information_fallback", "html_information"
    if reference_ids:
        return "ready_with_existing_asset", "existing_photo"
    return "generation_pending", "generated_image"


def _scene_fact_ids(scene_type: str, facts: list[ProductFact]) -> list[str]:
    """Choose facts relevant to a scene instead of attaching arbitrary facts."""
    scene_keys = {
        "hero_product": {"model", "model_name", "color", "product_size", "product_name"},
        "usage_scene": {"usage_time", "recommended_use_time", "usage_method", "target_area", "product_size"},
        "feature_closeup": {"feature", "function", "heating", "massage_mode", "material", "rated_power"},
        "charging_or_power": {"rated_input", "rated_power", "battery_capacity", "charging_port", "frequency"},
        "comparison": {"comparison", "comparison_basis", "competitive_comparison"},
        "spec_graphic": set(),
        "notice": {"caution", "warning", "recommended_age", "usage_time"},
    }
    keys = scene_keys.get(scene_type, set())
    if scene_type == "spec_graphic":
        return [fact.id for fact in facts]
    return [fact.id for fact in facts if (fact.field_key or "").lower() in keys]


def _expected_copy(project: ProductProject, scene_type: str, fact_ids: list[str], facts_by_id: dict[str, ProductFact]) -> dict[str, str]:
    fact_texts = [facts_by_id[fact_id].fact_text for fact_id in fact_ids if fact_id in facts_by_id]
    product_name = project.name or "상품"
    if fact_texts:
        body = " · ".join(fact_texts[:2])
    else:
        body = "판매자가 확인한 제품 정보와 기준 사진을 바탕으로 안내합니다."
    headline_by_scene = {
        "hero_product": product_name,
        "usage_scene": "사용 전 제품 정보 확인",
        "feature_closeup": "확인된 제품 특징",
        "charging_or_power": "전원·배터리 정보 확인",
        "comparison": "구매 전 제품 정보 확인",
        "spec_graphic": "제품 사양·주의사항",
        "notice": "사용 전 안내",
    }
    return {"headline": headline_by_scene.get(scene_type, product_name), "body": body}


def _source_states(project: ProductProject, safe_assets: list[Asset]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    if project.raw_input_url:
        sources.append({"kind": "link", "value": project.raw_input_url, "status": "reference_only"})
    if project.raw_input_text:
        sources.append({"kind": "seller_input", "value": "판매자 직접 입력", "status": "seller_provided"})
    if safe_assets:
        sources.append({"kind": "seller_assets", "value": f"안전 기준 사진 {len(safe_assets)}개", "status": "seller_owned"})
    return sources


def _regeneration_entry(reason: str, *, event: str = "plan_created") -> dict[str, str]:
    return {"event": event, "reason": reason, "at": datetime.now(timezone.utc).isoformat()}


def _summary(scenes: Iterable[dict[str, Any]], safe_assets: list[dict[str, Any]], needs_review: list[dict[str, Any]]) -> dict[str, int]:
    scene_list = list(scenes)
    return {
        "scene_count": len(scene_list),
        "generation_pending_count": sum(item["mock_status"] == "generation_pending" for item in scene_list),
        "information_fallback_count": sum(item["mock_status"] == "information_fallback" for item in scene_list),
        "ready_with_existing_asset_count": sum(item["mock_status"] == "ready_with_existing_asset" for item in scene_list),
        "safe_reference_asset_count": len(safe_assets),
        "seller_confirmation_needed_count": len(needs_review),
    }


def build_generation_plan(project: ProductProject, db: Session) -> dict[str, Any]:
    """Build a deterministic, provider-free generation contract."""
    all_facts = db.query(ProductFact).filter(ProductFact.project_id == project.id).all()
    confirmed_facts = [fact for fact in all_facts if fact.verification_status in CONFIRMED_FACT_STATUSES and not fact.needs_review]
    all_assets = db.query(Asset).filter(Asset.project_id == project.id).order_by(Asset.created_at.asc()).all()
    safe_assets = [asset for asset in all_assets if is_safe_generation_reference(asset, db)]
    safe_payloads = [_safe_asset_payload(asset) for asset in safe_assets]
    safe_ids = {asset.id for asset in safe_assets}
    needs_review = [
        {
            "id": fact.id,
            "text": fact.fact_text,
            "status": fact.verification_status,
            "reason": "사실 충돌 해결 필요" if fact.verification_status == "conflicted" else "판매자 확인 또는 근거 보강 필요",
        }
        for fact in all_facts
        if fact.id not in {confirmed.id for confirmed in confirmed_facts}
    ]
    reference_assets = [asset for asset in safe_assets if asset.is_representative] or safe_assets
    role_candidates = {
        "hero_product": [asset for asset in safe_assets if asset.is_representative or asset.asset_role == "product_main"],
        "usage_scene": [asset for asset in safe_assets if asset.asset_role == "usage_scene"],
        "feature_closeup": [asset for asset in safe_assets if asset.asset_role in {"feature", "material_detail"}],
        "charging_or_power": [asset for asset in safe_assets if asset.asset_role in {"feature", "product_detail"}],
    }
    has_verified_comparison = any(
        (fact.field_key or "").lower() in {"comparison", "comparison_basis", "competitive_comparison"}
        for fact in confirmed_facts
    )
    draft_cards = (project.planning_draft or {}).get("cards") or _default_scene_cards()
    fact_ids = [fact.id for fact in confirmed_facts]
    facts_by_id = {fact.id: fact for fact in confirmed_facts}
    scenes: list[dict[str, Any]] = []
    for index, card in enumerate(draft_cards):
        if not card.get("is_enabled", True):
            continue
        scene_type = _scene_type(str(card.get("type") or ""))
        linked_fact_ids = [fact_id for fact_id in (card.get("source_fact_ids") or []) if fact_id in fact_ids]
        if not linked_fact_ids:
            linked_fact_ids = _scene_fact_ids(scene_type, confirmed_facts)
        requested_ids = [asset_id for asset_id in ([card.get("image_asset_id")] + list(card.get("candidate_asset_ids") or [])) if asset_id]
        approved_reference_ids = [asset_id for asset_id in requested_ids if asset_id in safe_ids]
        if not approved_reference_ids:
            matching_assets = role_candidates.get(scene_type, [])
            if scene_type == "hero_product" and not matching_assets:
                matching_assets = reference_assets
            approved_reference_ids = [asset.id for asset in matching_assets[:1]]
        status, output_kind = _scene_status(scene_type, approved_reference_ids, has_verified_comparison)
        reason = (
            "비교 기준이 확인되지 않아 자사 정보 안내로 대체합니다."
            if scene_type == "comparison" and not has_verified_comparison
            else "실제 AI 이미지 API 연결 전에는 생성 대기 상태입니다."
            if status == "generation_pending"
            else "확정 사실 기반 HTML 정보형으로 미리보기 합니다."
            if status == "information_fallback"
            else "안전한 판매자 보유 사진을 기준 사진으로 사용합니다."
        )
        scenes.append({
            "id": str(card.get("id") or f"scene-{index + 1}"),
            "sort_order": index,
            "scene_type": scene_type,
            "label": card.get("label") or scene_type,
            "objective": card.get("title") or card.get("label") or "구매 정보 안내",
            "source_fact_ids": linked_fact_ids,
            "reference_asset_ids": approved_reference_ids,
            "requested_output": output_kind,
            "mock_status": status,
            "generation_reason": reason,
            "prompt_blueprint": _prompt_blueprint(project, scene_type, linked_fact_ids),
            "copy_blueprint": _copy_blueprint(scene_type, linked_fact_ids),
            "expected_copy": _expected_copy(project, scene_type, linked_fact_ids, facts_by_id),
            "rendering_strategy": (
                "safe_existing_photo" if status == "ready_with_existing_asset"
                else "html_information_fallback" if status == "information_fallback"
                else "safe_information_until_generated"
            ),
            "seller_note": "",
            "seller_approved": False,
            "provider_status": "api_not_connected",
            "regeneration_history": [_regeneration_entry("API 연결 전 초기 장면 계획", event="plan_created")],
        })

    intake = _intake_bundle(project)
    model_option = _first_fact_value(confirmed_facts, "model", "model_name") or intake.get("model_options")
    color = _first_fact_value(confirmed_facts, "color", "colour")
    options = _split_options(intake.get("model_options"))
    identity_reference_ids = [asset.id for asset in reference_assets[:2]]
    brief = {
        "product_name": project.name,
        "category": project.category,
        "selected_style": project.selected_style,
        "model_option": model_option,
        "options": options,
        "color": color,
        "sales_channel": intake.get("sales_channel"),
        "confirmed_facts": [_fact_payload(fact) for fact in confirmed_facts],
        "seller_input": project.raw_input_text or "",
        "forbidden_claims": list(DEFAULT_FORBIDDEN_CLAIMS),
        "source_url": project.raw_input_url,
        "source_url_usage": "reference_only" if project.raw_input_url else None,
        "source_states": _source_states(project, safe_assets),
        "safe_reference_assets": safe_payloads,
        "identity_reference_asset_ids": identity_reference_ids,
        "identity_criteria": _identity_criteria(identity_reference_ids, color, model_option),
        "needs_seller_confirmation": needs_review,
    }
    plan = {
        "version": PLAN_VERSION,
        "provider_mode": "api_not_connected",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "product_brief": brief,
        "scenes": scenes,
        "summary": _summary(scenes, safe_payloads, needs_review),
        "rendering_policy": {
            "api_connected": False,
            "generated_scene_fallback": "confirmed_facts_html_or_safe_existing_photo",
            "export_label": "AI 생성 대기 장면은 안전한 원본 사진 또는 정보형 미리보기로 출력됩니다.",
            "no_fake_generated_assets": True,
        },
    }
    return plan


def get_generation_plan(project: ProductProject) -> dict[str, Any] | None:
    snapshot = project.intake_snapshot or {}
    value = snapshot.get(PLAN_KEY)
    return deepcopy(value) if isinstance(value, dict) else None


def generation_rendering_contract(plan: dict[str, Any]) -> dict[str, Any]:
    """Freeze the no-fake-image policy alongside preview/export snapshots.

    The existing renderer remains responsible for actual PageSection markup. This
    contract tells every renderer which plan items are allowed to use a seller
    photo and which must remain as a factual HTML fallback until an API exists.
    """
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    return {
        "provider_mode": plan.get("provider_mode", "api_not_connected"),
        "no_fake_generated_assets": True,
        "download_label": (plan.get("rendering_policy") or {}).get(
            "export_label", "AI 생성 대기 장면은 안전한 정보형으로 출력됩니다."
        ),
        "scene_fallbacks": [
            {
                "scene_id": scene.get("id"),
                "status": scene.get("mock_status"),
                "strategy": scene.get("rendering_strategy", "html_information_fallback"),
                "reference_asset_ids": list(scene.get("reference_asset_ids") or []),
                "fact_ids": list(scene.get("source_fact_ids") or []),
            }
            for scene in scenes
        ],
        # Later image/render sprints may consume this hand-off only. Drafts,
        # rejections and stale approvals are intentionally absent.
        "approved_copy_drafts": [
            {
                "scene_id": scene.get("id"),
                "headline": (scene.get("copy_draft") or {}).get("headline"),
                "body": (scene.get("copy_draft") or {}).get("body"),
                "source_fact_ids": list((scene.get("copy_draft") or {}).get("source_fact_ids") or []),
                "input_snapshot_hash": (scene.get("copy_draft") or {}).get("input_snapshot_hash"),
            }
            for scene in scenes
            if (scene.get("copy_draft") or {}).get("status") == "seller_approved"
        ],
    }


def save_generation_plan(project: ProductProject, plan: dict[str, Any]) -> None:
    snapshot = dict(project.intake_snapshot or {})
    snapshot[PLAN_KEY] = deepcopy(plan)
    project.intake_snapshot = snapshot


def create_or_refresh_generation_plan(project: ProductProject, db: Session) -> dict[str, Any]:
    plan = build_generation_plan(project, db)
    save_generation_plan(project, plan)
    return plan


def _append_regeneration_history(scene: dict[str, Any], reason: str, event: str) -> None:
    history = list(scene.get("regeneration_history") or [])
    history.append(_regeneration_entry(reason, event=event))
    scene["regeneration_history"] = history[-20:]


def _invalidate_copy_draft(scene: dict[str, Any], reason: str) -> None:
    draft = scene.get("copy_draft")
    if not isinstance(draft, dict):
        return
    draft["status"] = "stale"
    draft["stale_reason"] = reason
    draft["invalidated_at"] = datetime.now(timezone.utc).isoformat()


def _update_product_brief(plan: dict[str, Any], update: dict[str, Any] | None) -> None:
    if not update:
        return
    brief = plan.setdefault("product_brief", {})
    editable_fields = {
        "product_name", "category", "model_option", "options", "color", "sales_channel",
        "seller_input", "forbidden_claims", "identity_criteria",
    }
    for field, value in update.items():
        if field in editable_fields and value is not None:
            brief[field] = value
    if any(field in editable_fields for field in update):
        for scene in plan.get("scenes") or []:
            _invalidate_copy_draft(scene, "상품 브리프 또는 금지 표현이 변경되었습니다.")


def update_generation_plan(
    project: ProductProject,
    db: Session,
    updates: list[dict[str, Any]],
    product_brief_update: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Allow seller edits without allowing unsafe reference photos into a plan."""
    plan = get_generation_plan(project) or create_or_refresh_generation_plan(project, db)
    safe_ids = {
        asset.id
        for asset in db.query(Asset).filter(Asset.project_id == project.id).all()
        if is_safe_generation_reference(asset, db)
    }
    scenes = {scene["id"]: scene for scene in plan.get("scenes") or []}
    confirmed_fact_ids = {
        str(fact.get("id")) for fact in plan.get("product_brief", {}).get("confirmed_facts") or []
    }
    _update_product_brief(plan, product_brief_update)
    for update in updates:
        scene = scenes.get(update.get("id"))
        if not scene:
            raise ValueError("Scene not found")
        if "objective" in update:
            objective = str(update["objective"] or "").strip()
            if objective and objective != scene["objective"]:
                scene["objective"] = objective
                _append_regeneration_history(scene, update.get("regeneration_reason") or "장면 목적 수정", "objective_updated")
                _invalidate_copy_draft(scene, "장면 목적이 변경되었습니다.")
        if "reference_asset_ids" in update:
            requested = list(dict.fromkeys(update["reference_asset_ids"] or []))
            if any(asset_id not in safe_ids for asset_id in requested):
                raise ValueError("위험·참고 전용 사진은 생성 기준 사진으로 선택할 수 없습니다.")
            scene["reference_asset_ids"] = requested
            status, output_kind = _scene_status(
                scene["scene_type"], requested,
                any(fact.get("field_key") in {"comparison", "comparison_basis", "competitive_comparison"} for fact in plan["product_brief"]["confirmed_facts"]),
            )
            scene["mock_status"] = status
            scene["requested_output"] = output_kind
            _append_regeneration_history(scene, update.get("regeneration_reason") or "기준 사진 변경", "reference_updated")
        if "source_fact_ids" in update:
            requested_fact_ids = list(dict.fromkeys(update["source_fact_ids"] or []))
            if any(fact_id not in confirmed_fact_ids for fact_id in requested_fact_ids):
                raise ValueError("확정되지 않았거나 다른 상품의 사실은 장면 근거로 선택할 수 없습니다.")
            scene["source_fact_ids"] = requested_fact_ids
            scene["prompt_blueprint"]["allowed_fact_ids"] = requested_fact_ids
            scene["copy_blueprint"]["allowed_fact_ids"] = requested_fact_ids
            _append_regeneration_history(scene, update.get("regeneration_reason") or "장면 근거 사실 변경", "facts_updated")
            _invalidate_copy_draft(scene, "장면 근거 사실이 변경되었습니다.")
        if "expected_copy" in update:
            expected_copy = update["expected_copy"] or {}
            headline = str(expected_copy.get("headline") or "").strip()
            body = str(expected_copy.get("body") or "").strip()
            if not headline and not body:
                raise ValueError("예상 문구에는 제목 또는 본문이 필요합니다.")
            scene["expected_copy"] = {"headline": headline, "body": body}
            _append_regeneration_history(scene, update.get("regeneration_reason") or "예상 문구 수정", "copy_updated")
        if "seller_note" in update:
            scene["seller_note"] = str(update["seller_note"] or "").strip()
        if "seller_approved" in update:
            approved = bool(update["seller_approved"])
            if approved != scene.get("seller_approved", False):
                scene["seller_approved"] = approved
                _append_regeneration_history(scene, "판매자 장면 계획 승인" if approved else "판매자 장면 계획 승인 해제", "seller_approval_changed")
    plan["updated_at"] = datetime.now(timezone.utc).isoformat()
    plan["summary"] = _summary(
        plan.get("scenes") or [],
        plan.get("product_brief", {}).get("safe_reference_assets") or [],
        plan.get("product_brief", {}).get("needs_seller_confirmation") or [],
    )
    save_generation_plan(project, plan)
    return plan
