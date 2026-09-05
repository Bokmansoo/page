"""Deterministic, safe outputs used by the local Mock generation pipeline."""

from __future__ import annotations

import re


FINAL_OUTPUT_SOURCE_TYPES = {"uploaded", "self_shot"}

# A local Mock run does not have the database inspection record available in
# every code path.  Keep this small, conservative screen here as a first line
# of defence; the persisted page materializer performs the full inspection
# again using AssetInspectionRecord before a page is saved.
FOREIGN_TEXT_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\u0400-\u04ff]")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)\d{3,4}[-.\s]?\d{4}(?!\d)")
PRICE_PATTERN = re.compile(r"(?:[$¥€₩]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:원|위안|元|rmb|usd|krw))", re.IGNORECASE)
QR_PATTERN = re.compile(r"(?:\bqr\b|qrcode|二维码)", re.IGNORECASE)
MARKET_PATTERN = re.compile(r"(?:1688|taobao|淘宝|tmall|拼多多|aliexpress|amazon|coupang|쿠팡|smartstore|스마트스토어)", re.IGNORECASE)
SUPPLIER_PATTERN = re.compile(r"(?:factory|supplier|manufacturer|공장|도매|제조사|厂家|工厂|供应商)", re.IGNORECASE)


def build_mock_product_understanding(product_name: str, description: str = "") -> dict:
    return {
        "product_type": product_name or "상품",
        "target_customer": "상품 정보를 확인하고 구매를 검토하는 고객",
        "verified_facts": [item for item in [product_name, description] if item],
        "assumptions": [],
        "verification_required": ["모델·규격·구성품은 판매자 입력 정보를 확인합니다."],
        "forbidden_claims": ["인증", "안전성", "치료·효능", "보증", "A/S"],
    }


def build_mock_sales_strategy(product_name: str, description: str = "") -> dict:
    return {
        "hook_headline": f"{product_name or '상품'} 정보를 한눈에 확인하세요",
        "selling_points": ["판매자 입력 정보 중심", "구매 전 사양 확인", "과장 표현 제외"],
        "tone_and_manner": "차분하고 명확한 정보형",
    }


def build_mock_page_plan(product_name: str) -> dict:
    return {
        "layout_concept": "쿠팡형 세로 정보 페이지",
        "sections": [
            {"id": "hero", "name": "대표 상품 소개"},
            {"id": "pain_point", "name": "구매 전 확인 포인트"},
            {"id": "feature_1", "name": "확인된 핵심 정보 1"},
            {"id": "feature_2", "name": "확인된 핵심 정보 2"},
            {"id": "feature_3", "name": "확인된 핵심 정보 3"},
            {"id": "usage_guide", "name": "사용 방법 또는 충전 안내"},
            {"id": "details_components", "name": "제품 디테일과 구성품"},
            {"id": "product_information", "name": "제품 사양·주의사항·필수 고지"},
        ],
    }


def build_mock_copy_set(product_name: str, description: str = "", **context) -> dict:
    from src.services.rule_based_copy_service import build_rule_based_copy

    return build_rule_based_copy(product_name, description=description, **context)


def build_mock_visual_plan(product_name: str) -> dict:
    return {
        "hero_image_prompt": f"Seller-owned product photo of {product_name}",
        "detail_image_prompt": f"Seller-owned detail photo of {product_name}",
        "color_palette": ["#10B981", "#14B8A6", "#FFFFFF", "#F3F4F6"],
    }


def build_mock_generated_assets(product_name: str, uploaded_assets: list | None = None, product_url: str | None = None) -> dict:
    return {"images": list(uploaded_assets or [])}


def _automatic_placement_risk_codes(asset: dict) -> list[str]:
    text = " ".join(
        str(asset.get(key) or "")
        for key in ("filename", "ocr_text", "caption", "alt_text", "description")
    )
    return [
        code
        for code, pattern in (
            ("foreign_text_exposed", FOREIGN_TEXT_PATTERN),
            ("phone_number_exposed", PHONE_PATTERN),
            ("price_exposed", PRICE_PATTERN),
            ("qr_code_review", QR_PATTERN),
            ("market_or_competitor_text", MARKET_PATTERN),
            ("supplier_text_exposed", SUPPLIER_PATTERN),
        )
        if pattern.search(text)
    ]


def _allowed_asset(asset: dict) -> bool:
    return (
        (asset.get("source_type") or "").lower() in FINAL_OUTPUT_SOURCE_TYPES
        and (asset.get("usage_status") or "seller_owned").lower() == "seller_owned"
        and not _automatic_placement_risk_codes(asset)
    )


def _automatic_candidate(asset: dict) -> bool:
    return (
        (asset.get("source_type") or "").lower() in FINAL_OUTPUT_SOURCE_TYPES
        and (asset.get("usage_status") or "seller_owned").lower() == "seller_owned"
        and str(asset.get("mime_type") or "image/jpeg").startswith("image/")
        and asset.get("quality_status") != "rejected"
    )


def _duplicate_candidate_ids(assets: list[dict]) -> set[str]:
    """Return only copies discarded by the one-original automatic policy."""
    seen_groups: set[str] = set()
    duplicates: set[str] = set()
    for asset in assets:
        content_hash = str(asset.get("content_hash") or "")
        asset_id = str(asset.get("id") or "")
        if not content_hash or not asset_id:
            continue
        if content_hash in seen_groups:
            duplicates.add(asset_id)
        else:
            seen_groups.add(content_hash)
    return duplicates


def _visual_slot(asset: dict | None, role: str) -> tuple[str | None, dict]:
    if asset is None:
        return None, {
            "source_type": "html-graphic",
            "asset_id": None,
            "label": "HTML 정보 섹션",
            "role": role,
        }
    return asset["id"], {
        "source_type": asset.get("source_type") or "uploaded",
        "asset_id": asset["id"],
        "label": asset.get("filename") or "상품 사진",
        "role": role,
    }


def build_mock_page_assembly(
    product_name: str,
    uploaded_assets: list | None = None,
    product_url: str | None = None,
    copy_set: dict | None = None,
) -> dict:
    """Build the UX-2 page without using supplier or URL reference images."""
    copy = copy_set or build_mock_copy_set(product_name)
    section_fact_ids = copy.get("section_fact_ids") or {}
    source_assets = list(uploaded_assets or [])
    automatic_candidates = [
        {**asset, "mime_type": asset.get("mime_type") or "image/jpeg"}
        for asset in source_assets
        if _automatic_candidate(asset)
    ]
    allowed_assets = [asset for asset in automatic_candidates if _allowed_asset(asset)]

    definitions = [
        ("hero", "hero", "hero_title", "hero_subtitle"),
        ("pain_point", "comparison", "painpoint_title", "painpoint_body"),
        ("feature_1", "detail_1", "feature_1_title", "feature_1_body"),
        ("feature_2", "detail_2", "feature_2_title", "feature_2_body"),
        ("feature_3", "detail_3", "feature_3_title", "feature_3_body"),
        ("usage_guide", "usage_guide", "usage_title", "usage_body"),
        ("details_components", "details_components", "details_title", "details_body"),
    ]
    from src.services.image_asset_mapper import map_with_upload_order_fallback

    section_inputs = [
        {"id": section_id, "section_type": section_id}
        for section_id, _, _, _ in definitions
    ]
    assignments = map_with_upload_order_fallback(section_inputs, allowed_assets)
    # Map the original candidate sequence once more for explanation only.
    # Giving every candidate a temporary unique group lets us identify the
    # *specific* section that would have received a blocked OCR image or a
    # same-hash copy. The actual assignment above remains deduplicated.
    explanation_assets = [
        {**asset, "content_hash": f"explanation:{asset.get('id')}"}
        for asset in automatic_candidates
    ]
    explanation_assignments = map_with_upload_order_fallback(
        section_inputs, explanation_assets
    )
    assigned_asset_ids = {
        str(item["section_id"]): str(item["asset_id"]) for item in assignments
    }
    assets_by_id = {str(asset["id"]): asset for asset in allowed_assets}
    candidate_by_id = {str(asset["id"]): asset for asset in automatic_candidates}
    explanation_asset_by_section = {
        str(item["section_id"]): str(item["asset_id"])
        for item in explanation_assignments
    }
    duplicate_candidate_ids = _duplicate_candidate_ids(automatic_candidates)
    sections: list[dict] = []
    for index, (section_id, visual_role, title_key, body_key) in enumerate(definitions):
        asset = assets_by_id.get(assigned_asset_ids.get(section_id, ""))
        image_id, visual_slot = _visual_slot(asset, visual_role)
        assignment = next(
            (item for item in assignments if item["section_id"] == section_id),
            None,
        )
        section = {
            "id": section_id,
            "section_type": section_id,
            "title": copy.get(title_key) or title_key.replace("_", " "),
            "body": copy.get(body_key) or "판매자 입력 상품 정보를 기준으로 안내합니다.",
            "visual_role": visual_role,
            "image_id": image_id,
            "visual_slot": visual_slot,
            "image_assignment": assignment,
            "associated_fact_ids": list(section_fact_ids.get(section_id) or []),
        }
        explanation_asset_id = explanation_asset_by_section.get(section_id)
        explanation_asset = candidate_by_id.get(explanation_asset_id or "")
        replacement_reasons = (
            _automatic_placement_risk_codes(explanation_asset)
            if explanation_asset else []
        )
        if explanation_asset_id in duplicate_candidate_ids:
            replacement_reasons.append("duplicate_asset_group")
        if image_id is None and replacement_reasons:
            section["ux2d1_auto_replacement"] = {
                "strategy": "html_information",
                "reason_codes": sorted(set(replacement_reasons)),
            }
        sections.append(section)
    return {"sections": sections}


def build_mock_qa_report(product_name: str) -> dict:
    return {
        "status": "passed",
        "checked_at": "2026-08-06T00:00:00Z",
        "warnings": [],
        "passed_checks": ["근거 없는 인증·안전·효능·보증 문구를 사용하지 않았습니다."],
    }
