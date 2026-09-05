"""Shared baseline catalogue and quality checks for the Coupang-style roadmap.

Sprint 0 deliberately keeps this independent from the page generator.  The
catalogue is the contract used by later sprints and the inspection function
turns the plan's qualitative rules into a repeatable project report.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.models import Asset, CommerceStoryBaselineRecord, ExportJob, PageSection, ProductPage
from src.services.page_readiness_service import inspect_page_readiness


@dataclass(frozen=True)
class BaselineProduct:
    """A seller-provided product pack used for regression, never scraped data."""

    key: str
    category: str
    label: str
    required_image_types: tuple[str, ...]
    reference_structure: tuple[str, ...]


BASELINE_PRODUCTS: tuple[BaselineProduct, ...] = (
    BaselineProduct(
        key="small-appliance",
        category="소형 가전",
        label="바디프랜드 미니 마사지건",
        required_image_types=("대표컷", "기능/상세컷", "기능/상세컷", "기능/상세컷"),
        reference_structure=("HERO", "핵심 기능", "사용 장면", "구성품/디테일", "스펙", "CTA"),
    ),
    BaselineProduct(
        key="beauty",
        category="뷰티",
        label="라운드랩 자작나무 수분 크림",
        required_image_types=("대표컷", "제형/성분/상세컷", "제형/성분/상세컷", "제형/성분/상세컷"),
        reference_structure=("HERO", "핵심 기능", "사용 장면", "구성품/디테일", "스펙", "CTA"),
    ),
    BaselineProduct(
        key="living-set",
        category="생활용품",
        label="락앤락 비스프리 밀폐용기 세트",
        required_image_types=("대표컷", "구성품/상세컷", "구성품/상세컷", "구성품/상세컷"),
        reference_structure=("HERO", "핵심 기능", "사용 장면", "구성품/디테일", "스펙", "CTA"),
    ),
)


class BaselineIssue(BaseModel):
    code: str
    severity: str
    message: str
    section_id: str | None = None


class BaselineProductResponse(BaseModel):
    key: str
    category: str
    label: str
    required_image_types: list[str]
    reference_structure: list[str]
    evaluation_items: dict[str, str]


class BaselineRegistrationRequest(BaseModel):
    project_id: str
    reference_capture_asset_id: str | None = None
    baseline_export_asset_id: str | None = None
    evaluation: dict[str, bool] = Field(default_factory=dict)


class BaselineRegistrationResponse(BaseModel):
    baseline_key: str
    project_id: str
    reference_capture_asset_id: str | None = None
    baseline_export_asset_id: str | None = None
    evaluation: dict[str, bool]


class CoupangStyleBaselineReport(BaseModel):
    """Machine-readable Sprint 0 report for a generated project."""

    required_image_count: int = 4
    source_image_count: int
    baseline_key: str | None = None
    baseline_registered: bool = False
    reference_capture_asset_id: str | None = None
    baseline_export_asset_id: str | None = None
    evaluation: dict[str, bool] = Field(default_factory=dict)
    representative_asset_id: str | None = None
    completed_jpg_export: bool
    image_repeat_count: int
    issues: list[BaselineIssue] = Field(default_factory=list)
    manual_checks: list[str] = Field(default_factory=list)
    ready_for_commerce_story: bool


_SELLER_SOURCE_TYPES = {
    "uploaded",
    "self_shot",
    "sourced",
    "url-imported",
    "url-extracted",
}

EVALUATION_ITEMS = {
    "hero": "HERO가 제품을 크게 보여주고 핵심 소구점을 전달하는가",
    "features": "각 핵심 기능이 서로 다른 근거 이미지 또는 사실과 연결되는가",
    "usage_scene": "사용 장면 또는 사용 방법이 구매자가 이해할 수 있게 제시되는가",
    "components_detail": "구성품 또는 제품 디테일이 확인 가능한가",
    "specifications": "수치와 스펙이 확인된 상품 사실에 근거하는가",
    "cta": "구매 전 확인 또는 CTA가 페이지 마지막에 있는가",
    "image_repetition": "본문에서 같은 이미지가 반복되지 않는가",
    "grounding": "근거 없는 성능·효능·구성품 주장이 없는가",
    "empty_sections": "빈 섹션이 없는가",
    "preview_export_parity": "미리보기와 기준선 JPG의 순서·문구·이미지가 같은가",
}


def list_baseline_products() -> tuple[BaselineProduct, ...]:
    """Return the fixed three-product regression pack in a stable order."""

    return BASELINE_PRODUCTS


def get_baseline_product(key: str) -> BaselineProduct | None:
    return next((product for product in BASELINE_PRODUCTS if product.key == key), None)


def serialize_baseline_product(product: BaselineProduct) -> BaselineProductResponse:
    return BaselineProductResponse(
        key=product.key,
        category=product.category,
        label=product.label,
        required_image_types=list(product.required_image_types),
        reference_structure=list(product.reference_structure),
        evaluation_items=EVALUATION_ITEMS,
    )


def inspect_coupang_style_baseline(
    db: Session,
    page: ProductPage,
    *,
    assets: Iterable[Asset] | None = None,
    baseline_key: str | None = None,
    workspace_id: str | None = None,
) -> CoupangStyleBaselineReport:
    """Evaluate Sprint 0's objective, project-level baseline checks.

    This is intentionally a *quality report*, not an export blocker.  A small
    data pack may still produce a truthful short page, but it is not sufficient
    evidence to claim the Coupang-style commerce story is ready.
    """

    baseline = get_baseline_product(baseline_key) if baseline_key else None
    if baseline_key and baseline is None:
        raise ValueError(f"Unknown Coupang-style baseline: {baseline_key}")
    registration = _get_registration(
        db,
        workspace_id=workspace_id,
        baseline_key=baseline_key,
    )
    source_assets = list(assets) if assets is not None else list(
        db.query(Asset)
        .filter(Asset.project_id == page.project_id)
        .order_by(Asset.created_at.asc())
        .all()
    )
    seller_images = [
        asset
        for asset in source_assets
        if asset.source_type in _SELLER_SOURCE_TYPES
        and (asset.mime_type or "").startswith("image/")
        and asset.quality_status != "rejected"
        and asset.id != getattr(registration, "reference_capture_asset_id", None)
    ]
    representative = next((asset for asset in seller_images if asset.is_representative), None)
    issues: list[BaselineIssue] = []

    if baseline_key and registration is None:
        issues.append(
            BaselineIssue(
                code="baseline_project_unregistered",
                severity="blocker",
                message="이 기준 상품에 연결할 프로젝트·참고 캡처·평가표를 등록해 주세요.",
            )
        )
    if registration is not None and registration.project_id != page.project_id:
        issues.append(
            BaselineIssue(
                code="baseline_project_mismatch",
                severity="blocker",
                message="이 프로젝트는 선택한 기준 상품에 등록된 프로젝트와 다릅니다.",
            )
        )
    if baseline_key and registration and not registration.reference_capture_asset_id:
        issues.append(
            BaselineIssue(
                code="reference_capture_missing",
                severity="blocker",
                message="참고 상세페이지 캡처를 기준 상품에 등록해 주세요.",
            )
        )
    evaluation = {
        key: bool((getattr(registration, "evaluation_json", None) or {}).get(key, False))
        for key in EVALUATION_ITEMS
    }
    if baseline_key and registration:
        for key, description in EVALUATION_ITEMS.items():
            if not evaluation[key]:
                issues.append(
                    BaselineIssue(
                        code="evaluation_pending",
                        severity="warning",
                        message=f"평가표 미확인: {description}",
                    )
                )

    if len(seller_images) < 4:
        issues.append(
            BaselineIssue(
                code="source_image_pack_incomplete",
                severity="blocker",
                message=(
                    "쿠팡형 상세페이지 기준선에는 대표컷 1장과 기능/상세 이미지 3장 이상이 "
                    f"필요합니다. 현재 사용 가능한 판매자 이미지: {len(seller_images)}장"
                ),
            )
        )
    if representative is None:
        issues.append(
            BaselineIssue(
                code="representative_image_missing",
                severity="blocker",
                message="기준선 HERO에 쓸 대표 상품 사진을 선택해 주세요.",
            )
        )

    visible_sections = [
        section for section in page.sections if getattr(section, "is_visible", True)
    ]
    image_ids_in_body = [
        section.image_asset_id
        for section in visible_sections
        if section.section_type != "hero" and section.image_asset_id
    ]
    repeated_ids = {
        asset_id: count
        for asset_id, count in Counter(image_ids_in_body).items()
        if count > 1
    }
    for asset_id, count in repeated_ids.items():
        issues.append(
            BaselineIssue(
                code="body_image_repeated",
                severity="warning",
                message=f"같은 상품 이미지가 HERO 외 본문에서 {count}회 반복됩니다.",
            )
        )

    for section in visible_sections:
        has_copy = bool((section.title or "").strip() or (section.body_copy or "").strip())
        has_visual = bool(section.image_asset_id or section.visual_payload)
        if not has_copy and not has_visual:
            issues.append(
                BaselineIssue(
                    code="empty_visible_section",
                    severity="blocker",
                    message="빈 섹션은 상세페이지에 표시할 수 없습니다.",
                    section_id=section.id,
                )
            )

    readiness = inspect_page_readiness(page, db)
    for warning in readiness.warnings:
        issues.append(
            BaselineIssue(
                code="grounding_or_readiness_warning",
                severity="warning",
                message=warning.message,
                section_id=warning.section_id,
            )
        )

    completed_jpg_export = _has_completed_jpg_export(
        db,
        page.project_id,
        registered_export_asset_id=getattr(registration, "baseline_export_asset_id", None),
    )
    if not completed_jpg_export:
        issues.append(
            BaselineIssue(
                code="baseline_jpg_missing",
                severity="warning",
                message="현재 결과를 기준선 JPG로 1회 저장해 이후 Sprint와 비교해 주세요.",
            )
        )

    return CoupangStyleBaselineReport(
        source_image_count=len(seller_images),
        baseline_key=baseline.key if baseline else None,
        baseline_registered=registration is not None and registration.project_id == page.project_id,
        reference_capture_asset_id=getattr(registration, "reference_capture_asset_id", None),
        baseline_export_asset_id=getattr(registration, "baseline_export_asset_id", None),
        evaluation=evaluation,
        representative_asset_id=representative.id if representative else None,
        completed_jpg_export=completed_jpg_export,
        image_repeat_count=sum(count - 1 for count in repeated_ids.values()),
        issues=issues,
        ready_for_commerce_story=not any(issue.severity == "blocker" for issue in issues),
        manual_checks=[
            "참고 상세페이지 캡처와 생성 페이지의 HERO·기능·사용 장면·구성품·스펙·CTA 흐름을 비교하세요.",
            "미리보기와 저장한 JPG의 섹션 순서·문구·이미지가 같은지 확인하세요.",
        ],
    )


def _has_completed_jpg_export(
    db: Session,
    project_id: str,
    *,
    registered_export_asset_id: str | None = None,
) -> bool:
    if registered_export_asset_id:
        asset = (
            db.query(Asset)
            .filter(
                Asset.id == registered_export_asset_id,
                Asset.project_id == project_id,
            )
            .first()
        )
        if _is_jpg(asset):
            return True
    completed_jobs = (
        db.query(ExportJob)
        .filter(ExportJob.project_id == project_id, ExportJob.status == "completed")
        .all()
    )
    for job in completed_jobs:
        for output_url in job.output_images or []:
            asset_id = str(output_url).rstrip("/").split("/page/export/download/")[-1]
            asset = db.query(Asset).filter(Asset.id == asset_id).first()
            if _is_jpg(asset):
                return True
    return False


def _is_jpg(asset: Asset | None) -> bool:
    return bool(
        asset
        and (
            asset.mime_type == "image/jpeg"
            or asset.filename.lower().endswith((".jpg", ".jpeg"))
        )
    )


def _get_registration(
    db: Session,
    *,
    workspace_id: str | None,
    baseline_key: str | None,
) -> CommerceStoryBaselineRecord | None:
    if not workspace_id or not baseline_key:
        return None
    return (
        db.query(CommerceStoryBaselineRecord)
        .filter(
            CommerceStoryBaselineRecord.workspace_id == workspace_id,
            CommerceStoryBaselineRecord.baseline_key == baseline_key,
        )
        .first()
    )
