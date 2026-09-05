from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PRIMARY_IMAGE_SECTION_TYPES = {"header", "hero", "problem_statement", "main_claim"}
# Sprint 2 completion rule: one source photo is never silently repeated in
# multiple body sections. Additional sections must use another asset, an
# HTML graphic, or a separately generated visual.
MAX_REUSE_PER_ASSET = 1
AUTO_HERO_BLOCKING_WARNINGS = {
    "LOW_RESOLUTION",
    "EXTREME_ASPECT_RATIO",
    "DUPLICATE_FILE",
    "IMAGE_INTEGRITY_WARNING",
    "SAFE_CROP_REVIEW_REQUIRED",
}
PERSISTED_ROLE_TO_MAPPER_ROLE = {
    "product_main": "product_main",
    "product_detail": "detail_closeup",
    "feature": "detail_closeup",
    "usage_scene": "lifestyle_scene",
    "components": "package_or_components",
    "material_detail": "detail_closeup",
    "package": "package_or_components",
    "shipping_info": "package_or_components",
    "spec_reference": "certification",
}

IMAGE_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "product_main": (
        "main",
        "hero",
        "product",
        "front",
        "대표",
        "상품",
        "제품",
        "정면",
    ),
    "lifestyle_scene": (
        "life",
        "lifestyle",
        "use",
        "scene",
        "room",
        "outdoor",
        "사용",
        "활용",
        "생활",
        "장면",
        "거실",
        "야외",
    ),
    "detail_closeup": (
        "detail",
        "feature",
        "closeup",
        "close-up",
        "macro",
        "기능",
        "디테일",
        "근접",
        "확대",
    ),
    "package_or_components": (
        "package",
        "box",
        "component",
        "components",
        "accessory",
        "구성품",
        "패키지",
        "박스",
        "부속품",
    ),
    "certification": (
        "kc",
        "cert",
        "certificate",
        "certification",
        "label",
        "spec",
        "chart",
        "인증",
        "라벨",
        "스펙",
        "도표",
        "시험",
    ),
    "background": (
        "background",
        "backdrop",
        "texture",
        "배경",
        "텍스처",
    ),
}

SECTION_ROLE_PREFERENCES: dict[str, tuple[str, ...]] = {
    "header": ("product_main", "lifestyle_scene", "background"),
    "hero": ("product_main", "lifestyle_scene", "background"),
    "problem_statement": ("lifestyle_scene", "product_main"),
    "main_claim": ("product_main", "detail_closeup", "lifestyle_scene"),
    "secondary_benefit": ("lifestyle_scene", "detail_closeup", "product_main"),
    "main_claim_support": ("certification", "detail_closeup", "product_main"),
    "benefit_list": ("detail_closeup", "product_main", "lifestyle_scene"),
    "features": ("detail_closeup", "product_main"),
    # UX-2C one-click page section types. Keep the first preference specific
    # enough that four distinct seller photos naturally land in representative,
    # feature, usage and components/spec positions.
    "feature_1": ("detail_closeup", "product_main"),
    "feature_2": ("detail_closeup", "product_main"),
    "feature_3": ("detail_closeup", "product_main"),
    "usage_guide": ("lifestyle_scene", "detail_closeup", "product_main"),
    "details_components": (
        "package_or_components",
        "detail_closeup",
        "certification",
        "product_main",
    ),
    "summary_claim": ("lifestyle_scene", "product_main", "background"),
    "product_information": (
        "package_or_components",
        "certification",
        "detail_closeup",
        "product_main",
    ),
    "specifications": (
        "certification",
        "package_or_components",
        "detail_closeup",
        "product_main",
    ),
}


@dataclass(frozen=True)
class ClassifiedImageAsset:
    asset_id: str
    primary_role: str
    confidence: float
    signals: tuple[str, ...]


def _asset_text(asset: dict[str, Any]) -> tuple[str, set[str]]:
    metadata = asset.get("metadata") or {}
    parts: list[str] = [str(asset.get("filename") or "")]
    signals: set[str] = {"filename"} if parts[0] else set()
    for key in ("caption", "ocr_text", "alt_text", "description"):
        value = metadata.get(key) or asset.get(key)
        if value:
            parts.append(str(value))
            signals.add(key)
    if asset.get("source_type"):
        parts.append(str(asset["source_type"]))
        signals.add("source_type")
    return " ".join(parts).lower(), signals


def classify_image_asset(
    asset: dict[str, Any], metadata: dict[str, Any] | None = None
) -> ClassifiedImageAsset:
    enriched = dict(asset)
    if metadata:
        enriched["metadata"] = {**(asset.get("metadata") or {}), **metadata}
    persisted_role = PERSISTED_ROLE_TO_MAPPER_ROLE.get(str(enriched.get("asset_role") or ""))
    if persisted_role:
        return ClassifiedImageAsset(
            asset_id=str(asset.get("id") or ""),
            primary_role=persisted_role,
            confidence=float(enriched.get("role_confidence") or 0.5),
            signals=("persisted_asset_role",),
        )
    text, available_signals = _asset_text(enriched)

    role_hits: dict[str, int] = {}
    for role, keywords in IMAGE_ROLE_KEYWORDS.items():
        role_hits[role] = sum(1 for keyword in keywords if keyword in text)

    primary_role, hit_count = max(role_hits.items(), key=lambda item: item[1])
    if hit_count == 0:
        primary_role = "unknown"
        confidence = 0.25
    else:
        metadata_bonus = 0.15 if available_signals & {"caption", "ocr_text", "alt_text"} else 0.0
        confidence = min(0.95, 0.5 + hit_count * 0.12 + metadata_bonus)

    return ClassifiedImageAsset(
        asset_id=str(asset.get("id") or ""),
        primary_role=primary_role,
        confidence=round(confidence, 2),
        signals=tuple(sorted(available_signals)),
    )


def _section_preferences(section_type: str) -> tuple[str, ...]:
    return SECTION_ROLE_PREFERENCES.get((section_type or "").lower(), ())


def _unique_image_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one automatic candidate per file-hash duplicate group.

    A seller can still deliberately choose a duplicate in the UI, but automatic
    placement must never fill two sections with an original and its copy.
    """
    selected: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for asset in assets:
        group = str(asset.get("content_hash") or f"asset:{asset.get('id')}")
        if group in seen_groups:
            continue
        seen_groups.add(group)
        selected.append(asset)
    return selected


def _match_score(
    section_type: str,
    asset: dict[str, Any],
    classified: ClassifiedImageAsset,
    used_count: int,
) -> int:
    preferences = _section_preferences(section_type)
    if not preferences or classified.primary_role == "unknown":
        return 0

    try:
        preference_index = preferences.index(classified.primary_role)
    except ValueError:
        return 0

    score = max(20, 60 - preference_index * 20)
    if section_type.lower() in PRIMARY_IMAGE_SECTION_TYPES and asset.get("is_representative"):
        score += 40
    if classified.confidence >= 0.7:
        score += 20
    if used_count == 0:
        score += 10

    section_hint = str((asset.get("metadata") or {}).get("section_hint") or "").lower()
    if section_hint and section_hint == (section_type or "").lower():
        score += 20
    score -= used_count * 15
    return max(score, 0)


def map_image_assets_to_sections(
    sections: list[dict[str, Any]], assets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    image_assets = _unique_image_assets([
        asset
        for asset in assets
        if str(asset.get("mime_type") or "").startswith("image/")
        and asset.get("quality_status") != "rejected"
    ])
    if not image_assets:
        return []

    classified_by_id = {
        str(asset["id"]): classify_image_asset(asset) for asset in image_assets
    }
    assignments: list[dict[str, Any]] = []
    used_counts = {str(asset["id"]): 0 for asset in image_assets}
    single_image_mode = len(image_assets) == 1

    for section in sections:
        section_type = str(section.get("section_type") or section.get("key") or "")
        if single_image_mode:
            if assignments or section_type.lower() not in PRIMARY_IMAGE_SECTION_TYPES:
                continue

        candidates: list[tuple[int, float, int, dict[str, Any], ClassifiedImageAsset]] = []
        for asset_index, asset in enumerate(image_assets):
            asset_id = str(asset["id"])
            if used_counts[asset_id] >= MAX_REUSE_PER_ASSET:
                continue
            if (
                section_type.lower() in PRIMARY_IMAGE_SECTION_TYPES
                and AUTO_HERO_BLOCKING_WARNINGS.intersection(asset.get("quality_warnings") or [])
            ):
                # A seller can still select it manually after seeing the warning,
                # but low-quality images are never automatic HERO candidates.
                continue
            classified = classified_by_id[asset_id]
            score = _match_score(
                section_type, asset, classified, used_counts[asset_id]
            )
            if score <= 0:
                continue
            candidates.append(
                (
                    score,
                    classified.confidence,
                    -asset_index,
                    asset,
                    classified,
                )
            )

        if not candidates:
            continue

        score, _, _, best_asset, classified = max(
            candidates, key=lambda item: (item[0], item[1], item[2])
        )
        asset_id = str(best_asset["id"])
        assignments.append(
            {
                "section_id": section["id"],
                "section_type": section_type,
                "asset_id": asset_id,
                "filename": str(best_asset.get("filename") or ""),
                "asset_role": classified.primary_role,
                "confidence": round(min(1.0, score / 110), 2),
                "score": score,
                "reason": (
                    f"{classified.primary_role} 역할과 {section_type} 섹션의 "
                    f"적합도 {score}점"
                ),
            }
        )
        used_counts[asset_id] += 1

    return assignments


def map_with_upload_order_fallback(
    sections: list[dict[str, Any]], assets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Map role-aware photos, then fill remaining slots in upload order.

    The fallback is intentionally deterministic and still enforces one photo
    per section. It gives unclassified direct uploads a useful HERO-first
    placement without weakening the role-aware result for inspected photos.
    """
    assignments = map_image_assets_to_sections(sections, assets)
    assigned_section_ids = {str(item["section_id"]) for item in assignments}
    used_asset_ids = {str(item["asset_id"]) for item in assignments}
    remaining_assets = [
        asset
        for asset in _unique_image_assets(assets)
        if str(asset.get("mime_type") or "").startswith("image/")
        and asset.get("quality_status") != "rejected"
        and str(asset.get("id") or "") not in used_asset_ids
    ]
    remaining_sections = [
        section
        for section in sections
        if str(section.get("id") or "") not in assigned_section_ids
        and str(section.get("section_type") or section.get("key") or "").lower()
        != "product_information"
    ]
    for section, asset in zip(remaining_sections, remaining_assets):
        asset_id = str(asset.get("id") or "")
        classified = classify_image_asset(asset)
        assignments.append(
            {
                "section_id": str(section.get("id") or ""),
                "section_type": str(
                    section.get("section_type") or section.get("key") or ""
                ),
                "asset_id": asset_id,
                "filename": str(asset.get("filename") or ""),
                "asset_role": classified.primary_role,
                "confidence": classified.confidence,
                "score": 1,
                "reason": "역할 미분류 사진을 업로드 순서에 따라 빈 섹션에 제안",
            }
        )
    return assignments


def find_missing_image_roles(
    sections: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    assignments: list[dict[str, Any]] | None = None,
) -> list[str]:
    image_assets = [
        asset
        for asset in assets
        if str(asset.get("mime_type") or "").startswith("image/")
    ]
    available_roles = {
        classify_image_asset(asset).primary_role for asset in image_assets
    }
    required_roles = {
        preferences[0]
        for section in sections
        if (
            preferences := _section_preferences(
                str(section.get("section_type") or section.get("key") or "")
            )
        )
    }
    mapped_roles = {
        str(item.get("asset_role"))
        for item in (assignments or [])
        if item.get("asset_role")
    }
    return sorted(
        role
        for role in required_roles
        if role not in available_roles and role not in mapped_roles
    )
