"""UX-2D deterministic content-quality checks for sellable detail-page drafts."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Asset, AssetInspectionRecord, PageSection, ProductPage

PLACEHOLDER_COPY = {
    "구매 전 제품 정보 확인", "확인된 핵심 정보", "판매자 제공 사양",
    "상품 제품 정보 한눈에 보기", "구매 전 확인하면 좋은 정보",
}
SPEC_LABEL_PATTERN = r"(?:색상|모델명|정격(?:\s*(?:입력|주파수|소비전력))?|배터리(?:\s*용량)?|제품\s*크기|외부\s*포장(?:\s*크기|\s*구성)?)\s*[:：]"
FOREIGN_TEXT_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\u0400-\u04ff]")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)\d{3,4}[-.\s]?\d{4}(?!\d)")
PRICE_PATTERN = re.compile(r"(?:[$¥€₩]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:원|위안|元|rmb|usd|krw))", re.I)
MARKET_PATTERN = re.compile(r"(?:1688|taobao|淘宝|tmall|拼多多|aliexpress|amazon|coupang|쿠팡|smartstore|스마트스토어)", re.I)
SUPPLIER_PATTERN = re.compile(r"(?:factory|supplier|manufacturer|공장|도매|제조사|厂家|工厂|供应商)", re.I)
QR_PATTERN = re.compile(r"(?:\bqr\b|qrcode|二维码)", re.I)
ROLE_PREFERENCES = {
    "hero": {"product_main"},
    "feature_1": {"feature", "product_detail", "material_detail"},
    "feature_2": {"feature", "product_detail", "material_detail"},
    "feature_3": {"feature", "product_detail", "material_detail"},
    "usage_guide": {"usage_scene", "feature", "product_detail"},
    "details_components": {"components", "package", "spec_reference", "product_detail"},
}


@dataclass(frozen=True)
class ContentQualityIssue:
    section_id: str
    code: str
    severity: str  # blocker, review, recommendation
    message: str
    resolution: str
    asset_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def normalize_product_name(value: str | None, fallback_id: str = "") -> tuple[str, list[str]]:
    """Keep one product name from becoming a pasted specification document."""
    raw = " ".join((value or "").split()).strip()
    warnings: list[str] = []
    colon_pairs = len(re.findall(r"(?:^|\s)[^:]{1,24}:\s*[^:]{1,40}", raw))
    starts_with_spec_label = bool(re.match(rf"^{SPEC_LABEL_PATTERN}", raw))
    suspicious = len(raw) > 80 or colon_pairs >= 2 or raw.count("×") >= 2 or starts_with_spec_label
    if suspicious:
        warnings.append("product_name_looks_like_specification")
        # A pasted spec often starts with a real product phrase before its
        # first label. Do not invent a name if that is absent.
        candidate = re.split(rf"(?:^|\s+){SPEC_LABEL_PATTERN}", raw, maxsplit=1)[0].strip()
        raw = candidate if candidate and len(candidate) <= 80 and ":" not in candidate else ""
    if not raw:
        raw = f"상세페이지-{fallback_id[:8]}" if fallback_id else "상세페이지"
        warnings.append("product_name_fallback_used")
    return raw[:80], warnings


def export_slug(value: str | None, fallback_id: str = "") -> str:
    name, _ = normalize_product_name(value, fallback_id)
    slug = re.sub(r"\s+", "-", name.strip().lower())
    slug = re.sub(r"[^\wㄱ-ㅎㅏ-ㅣ가-힣-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return (slug or f"detail-page-{fallback_id[:8]}")[:60]


def _normalized_copy(value: str | None) -> str:
    compact = re.sub(r"[^0-9a-z가-힣]+", " ", (value or "").strip().lower())
    return re.sub(r"\s+", " ", compact).strip()


def _acknowledged(section: PageSection, code: str, asset_id: str | None) -> bool:
    entries = (section.visual_payload or {}).get("ux2d_quality_acknowledgements", [])
    return any(isinstance(item, dict) and item.get("code") == code and item.get("asset_id") == asset_id for item in entries)


def _asset_lineage(asset: Asset, db: Session) -> list[Asset]:
    """Return an asset followed by its source ancestors without looping."""
    lineage: list[Asset] = []
    current: Asset | None = asset
    visited: set[str] = set()
    while current and current.id not in visited:
        lineage.append(current)
        visited.add(current.id)
        current = db.get(Asset, current.source_asset_id) if current.source_asset_id else None
    return lineage


def _asset_ocr_text(asset: Asset, db: Session) -> str:
    """Include OCR evidence from the original photo when a derivative is used."""
    texts: list[str] = []
    for lineage_asset in _asset_lineage(asset, db):
        texts.append(lineage_asset.ocr_text or "")
        record = (db.query(AssetInspectionRecord).filter(AssetInspectionRecord.asset_id == lineage_asset.id)
                  .order_by(AssetInspectionRecord.analysis_version.desc()).first())
        blocks = (record.ocr_blocks if record else []) or []
        texts.extend(str(block.get("text") or "") for block in blocks if isinstance(block, dict))
    return "\n".join(text for text in texts if text).strip()


def _asset_risk_codes(asset: Asset, db: Session) -> list[str]:
    """Return explainable OCR/file-name risks without claiming text was removed."""
    text = _asset_ocr_text(asset, db)
    filename = "\n".join(
        lineage_asset.filename or ""
        for lineage_asset in _asset_lineage(asset, db)
    )
    combined = f"{text}\n{filename}"
    codes: list[str] = []
    if FOREIGN_TEXT_PATTERN.search(text):
        codes.append("foreign_text_exposed")
    if PHONE_PATTERN.search(text):
        codes.append("phone_number_exposed")
    if PRICE_PATTERN.search(text):
        codes.append("price_exposed")
    if QR_PATTERN.search(combined):
        codes.append("qr_code_review")
    if MARKET_PATTERN.search(combined):
        codes.append("market_or_competitor_text")
    if SUPPLIER_PATTERN.search(combined):
        codes.append("supplier_text_exposed")
    return codes


AUTO_PLACEMENT_BLOCKING_RISK_CODES = {
    "foreign_text_exposed",
    "phone_number_exposed",
    "price_exposed",
    "qr_code_review",
    "market_or_competitor_text",
    "supplier_text_exposed",
}


def auto_placement_risk_codes(asset: Asset, db: Session) -> list[str]:
    """Risks that keep a photo out of a new automatic seller-facing layout.

    This deliberately does not decide whether a seller may select the image
    manually. Manual choice remains possible only through UX-2D acknowledgement.
    """
    return [code for code in _asset_risk_codes(asset, db) if code in AUTO_PLACEMENT_BLOCKING_RISK_CODES]


def _similar_copy(left: str, right: str) -> bool:
    if not left or not right or min(len(left), len(right)) < 12:
        return False
    if left == right:
        return True
    if left in right or right in left:
        # A short confirmed fact can legitimately reappear inside the final
        # specification table. Treat containment as duplication only when the
        # two sections are comparable in length, not when one is a summary row.
        return min(len(left), len(right)) / max(len(left), len(right)) >= 0.72
    left_words, right_words = set(left.split()), set(right.split())
    if not left_words or not right_words:
        return False
    return len(left_words & right_words) / len(left_words | right_words) >= 0.82


def _section_issue_map(issues: list[ContentQualityIssue]) -> dict[str, list[str]]:
    by_section: dict[str, list[str]] = defaultdict(list)
    for issue in issues:
        by_section[issue.section_id].append(issue.code)
    return dict(by_section)


def inspect_content_quality(page: ProductPage, db: Session) -> dict[str, Any]:
    issues: list[ContentQualityIssue] = []
    project = page.project
    product_name, name_warnings = normalize_product_name(project.name if project else "", page.project_id)
    for code in name_warnings:
        issues.append(ContentQualityIssue("page", code, "review", "상품명에 스펙 전체가 포함되었거나 상품명이 비어 있습니다.", "상품명을 한 줄로 수정하세요."))

    visible = [section for section in page.sections if section.is_visible]
    seen_titles: dict[str, str] = {}
    seen_bodies: dict[str, str] = {}
    seen_assets: dict[str, str] = {}
    seen_asset_groups: dict[str, str] = {}
    acknowledged_asset_ids: set[str] = set()
    for section in visible:
        title = _normalized_copy(section.title)
        body = _normalized_copy(section.body_copy)
        if title:
            if any(marker in title for marker in PLACEHOLDER_COPY):
                issues.append(ContentQualityIssue(section.id, "placeholder_copy", "review", "임시·일반 문구가 최종 제목에 남아 있습니다.", "섹션 목적에 맞는 제목으로 수정하세요."))
            if title in seen_titles:
                issues.append(ContentQualityIssue(section.id, "duplicate_title", "review", "다른 섹션과 같은 제목이 반복됩니다.", "연결된 상품 사실을 사용해 제목을 구분하세요."))
            else:
                seen_titles[title] = section.id
        if body:
            matching_body = next((previous for previous in seen_bodies if _similar_copy(body, previous)), None)
            if matching_body:
                issues.append(ContentQualityIssue(section.id, "duplicate_copy", "review", "다른 섹션과 같은 또는 매우 비슷한 본문이 반복됩니다.", "연결된 상품 사실을 사용해 본문을 구분하세요."))
            else:
                seen_bodies[body] = section.id
        auto_replacement = (section.visual_payload or {}).get("ux2d1_auto_replacement")
        if isinstance(auto_replacement, dict):
            reason_codes = ", ".join(auto_replacement.get("reason_codes") or [])
            issues.append(ContentQualityIssue(section.id, "auto_replaced_with_information", "recommendation", f"자동 배치에서 위험 또는 중복 사진을 제외하고 정보형으로 전환했습니다{f' ({reason_codes})' if reason_codes else ''}.", "필요하면 깨끗한 사진을 선택하거나 정보형 내용을 검토하세요."))
        if not section.image_asset_id:
            continue
        asset = db.get(Asset, section.image_asset_id)
        if not asset:
            continue
        duplicate_group = asset.content_hash or f"asset:{asset.id}"
        duplicate_code = "duplicate_asset_group" if asset.content_hash else "duplicate_asset"
        duplicate_asset = asset.id in seen_assets
        duplicate_group_match = duplicate_group in seen_asset_groups and seen_asset_groups[duplicate_group] != section.id
        if duplicate_asset and not _acknowledged(section, "duplicate_asset", asset.id):
            issues.append(ContentQualityIssue(section.id, "duplicate_asset", "review", "같은 사진이 여러 이미지 중심 섹션에 배치되었습니다.", "다른 사진, HTML 정보형 또는 중복 사용 확인을 선택하세요.", asset.id))
        elif duplicate_group_match and not _acknowledged(section, duplicate_code, asset.id):
            issues.append(ContentQualityIssue(section.id, duplicate_code, "review", "같은 원본 또는 보정·복사본 사진이 여러 섹션에 배치되었습니다.", "다른 사진, HTML 정보형 또는 중복 사용 확인을 선택하세요.", asset.id))
        else:
            seen_assets[asset.id] = section.id
        if duplicate_group not in seen_asset_groups:
            seen_asset_groups[duplicate_group] = section.id
        preferred = ROLE_PREFERENCES.get(section.section_type)
        if preferred and asset.asset_role not in preferred:
            issues.append(ContentQualityIssue(section.id, "asset_role_mismatch", "recommendation", "사진 역할이 이 섹션의 목적과 다를 수 있습니다.", "섹션 추천 사진을 선택하거나 정보형으로 전환하세요.", asset.id))
        risk_messages = {
            "foreign_text_exposed": "사진에 외국어 판매 문구가 감지되었습니다.",
            "phone_number_exposed": "사진에 전화번호가 감지되었습니다.",
            "price_exposed": "사진에 가격 또는 통화 표기가 감지되었습니다.",
            "qr_code_review": "사진에 QR 코드 가능성이 감지되었습니다.",
            "market_or_competitor_text": "사진에 마켓·경쟁사 문구가 감지되었습니다.",
            "supplier_text_exposed": "사진에 공급처·제조사 문구가 감지되었습니다.",
        }
        for code in _asset_risk_codes(asset, db):
            if _acknowledged(section, code, asset.id):
                acknowledged_asset_ids.add(asset.id)
            else:
                issues.append(ContentQualityIssue(section.id, code, "review", risk_messages[code], "다른 사진, 안전한 자르기, 정보형 전환 또는 사용 확인을 선택하세요.", asset.id))
    blockers = [issue.as_dict() for issue in issues if issue.severity == "blocker"]
    reviews = [issue.as_dict() for issue in issues if issue.severity == "review"]
    recommendations = [issue.as_dict() for issue in issues if issue.severity == "recommendation"]
    section_codes = _section_issue_map(issues)
    return {
        "ready_for_sale": not blockers and not reviews,
        "product_name": product_name,
        "export_slug": export_slug(product_name, page.project_id),
        "blockers": blockers,
        "reviews": reviews,
        "recommendations": recommendations,
        "section_copy_quality_codes": section_codes,
        "seller_confirmed_usage": bool(acknowledged_asset_ids),
        "seller_confirmed_usage_count": len(acknowledged_asset_ids),
    }
