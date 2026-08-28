"""V2 regression baseline catalogue and policy-aware evaluation.

Supplier source material can be registered as evidence, but it is explicitly
kept separate from assets that the final seller detail page may render.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.models import Asset, CommerceStoryBaselineRecord, ExportJob, PageSection, ProductFact, ProductPage
from src.services.commerce_policy import (
    CONFIRMED_FACT_STATUSES,
    final_spec_is_last,
    has_final_spec_section,
    is_asset_final_output_eligible,
    resolved_asset_usage_status,
)


@dataclass(frozen=True)
class BaselineFactConflict:
    field_key: str
    candidates: tuple[str, ...]
    status: str = "conflicted"


@dataclass(frozen=True)
class BaselineProduct:
    key: str
    category: str
    label: str
    source_reference: str
    required_image_types: tuple[str, ...]
    reference_structure: tuple[str, ...]
    known_risks: tuple[str, ...] = ()
    fact_conflicts: tuple[BaselineFactConflict, ...] = ()


BASELINE_PRODUCTS: tuple[BaselineProduct, ...] = (
    BaselineProduct(
        key="yl-t02-massage-pillow",
        category="생활가전",
        label="YL-T02 목·어깨 마사지 베개",
        source_reference="1688 offer 996262285530 (seller-provided capture)",
        required_image_types=("대표 상품", "조작/충전", "사용 장면", "소재/디테일"),
        reference_structure=("문제/공감", "HERO", "핵심 기능", "사용 장면", "신뢰/CTA", "최종 스펙"),
        known_risks=("마사지 헤드 수 4개/6개 이상 상충", "의료·치료 효능 표현 금지"),
        fact_conflicts=(
            BaselineFactConflict(field_key="massage_head_count", candidates=("4개", "6개 이상")),
        ),
    ),
    BaselineProduct(
        key="roundlab-birch-moisture-cream",
        category="뷰티",
        label="라운드랩 자작나무 수분 크림",
        source_reference="internal seller-provided beauty baseline pack",
        required_image_types=("대표 상품", "제형/성분", "사용 장면", "패키지/디테일"),
        reference_structure=("문제/공감", "HERO", "핵심 기능", "사용 장면", "신뢰/CTA", "최종 스펙"),
        known_risks=("효능·성분·인체 적용 표현은 근거 필요",),
    ),
    BaselineProduct(
        key="locknlock-bisfree-container-set",
        category="생활용품",
        label="락앤락 비스프리 밀폐용기 세트",
        source_reference="internal seller-provided living baseline pack",
        required_image_types=("대표 상품", "구성품", "사용 장면", "크기/디테일"),
        reference_structure=("문제/공감", "HERO", "핵심 기능", "사용 장면", "신뢰/CTA", "최종 스펙"),
        known_risks=("수치·내구·친환경 표현은 근거 필요",),
    ),
)


EVALUATION_ITEMS = {
    "hero_identifiable": "대표 상품이 HERO에서 식별되는가",
    "section_visual_variety": "섹션 목적에 맞는 서로 다른 이미지·그래픽이 있는가",
    "reference_only_policy": "공급처 원본 캡처가 최종 출력에 사용되지 않았는가",
    "grounded_claims": "수치·효능·성능 표현이 확인된 사실에 근거하는가",
    "story_sequence": "문제→제품→기능→사용→신뢰/CTA→최종 스펙 순서인가",
    "no_empty_sections": "빈 섹션 없이 완성되었는가",
    "preview_export_parity": "미리보기와 기준 JPG 출력이 일치하는가",
}


class BaselineIssue(BaseModel):
    code: str
    severity: str
    message: str
    section_id: str | None = None


class BaselineProductResponse(BaseModel):
    key: str
    category: str
    label: str
    source_reference: str
    required_image_types: list[str]
    reference_structure: list[str]
    known_risks: list[str]
    fact_conflicts: list[dict[str, object]]
    evaluation_items: dict[str, str]
    baseline_registered: bool = False
    project_id: str | None = None
    reference_capture_asset_id: str | None = None
    baseline_export_asset_id: str | None = None
    evaluation: dict[str, bool] = Field(default_factory=dict)
    ready: bool = False


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


class CommerceStoryBaselineReport(BaseModel):
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


def list_baseline_products() -> tuple[BaselineProduct, ...]:
    return BASELINE_PRODUCTS


def get_baseline_product(key: str) -> BaselineProduct | None:
    return next((product for product in BASELINE_PRODUCTS if product.key == key), None)


def serialize_baseline_product(
    product: BaselineProduct,
    registration: CommerceStoryBaselineRecord | None = None,
) -> BaselineProductResponse:
    evaluation = dict(getattr(registration, "evaluation_json", None) or {})
    ready = bool(
        registration
        and registration.reference_capture_asset_id
        and registration.baseline_export_asset_id
        and all(evaluation.get(key, False) for key in EVALUATION_ITEMS)
    )
    return BaselineProductResponse(
        key=product.key,
        category=product.category,
        label=product.label,
        source_reference=product.source_reference,
        required_image_types=list(product.required_image_types),
        reference_structure=list(product.reference_structure),
        known_risks=list(product.known_risks),
        fact_conflicts=[
            {
                "field_key": conflict.field_key,
                "candidates": list(conflict.candidates),
                "status": conflict.status,
            }
            for conflict in product.fact_conflicts
        ],
        evaluation_items=EVALUATION_ITEMS,
        baseline_registered=registration is not None,
        project_id=getattr(registration, "project_id", None),
        reference_capture_asset_id=getattr(registration, "reference_capture_asset_id", None),
        baseline_export_asset_id=getattr(registration, "baseline_export_asset_id", None),
        evaluation=evaluation,
        ready=ready,
    )


def inspect_commerce_story_baseline(
    db: Session,
    page: ProductPage,
    *,
    assets: Iterable[Asset] | None = None,
    baseline_key: str | None = None,
    workspace_id: str | None = None,
) -> CommerceStoryBaselineReport:
    baseline = get_baseline_product(baseline_key) if baseline_key else None
    if baseline_key and baseline is None:
        raise ValueError(f"Unknown V2 commerce-story baseline: {baseline_key}")
    registration = _get_registration(db, workspace_id=workspace_id, baseline_key=baseline_key)
    all_assets = list(assets) if assets is not None else list(
        db.query(Asset).filter(Asset.project_id == page.project_id).all()
    )
    image_assets = [
        asset for asset in all_assets
        if (asset.mime_type or "").startswith("image/") and asset.quality_status != "rejected"
    ]
    final_images = [asset for asset in image_assets if is_asset_final_output_eligible(asset)]
    representative = next((asset for asset in final_images if asset.is_representative), None)
    issues: list[BaselineIssue] = []

    if baseline_key and registration is None:
        issues.append(BaselineIssue(code="baseline_project_unregistered", severity="blocker", message="Register the project, reference capture, evaluation and baseline JPG."))
    if registration and registration.project_id != page.project_id:
        issues.append(BaselineIssue(code="baseline_project_mismatch", severity="blocker", message="The baseline registration belongs to another project."))
    if baseline_key and registration and not registration.reference_capture_asset_id:
        issues.append(BaselineIssue(code="reference_capture_missing", severity="blocker", message="A supplier/reference capture is required as comparison evidence."))
    if len(final_images) < 1:
        issues.append(BaselineIssue(code="final_image_missing", severity="blocker", message="At least one seller-owned, AI-generated or derived final asset is required."))
    if representative is None and final_images:
        issues.append(BaselineIssue(code="representative_image_missing", severity="warning", message="Choose a representative product image for the HERO."))

    visible_sections = sorted(
        (section for section in page.sections if getattr(section, "is_visible", True)),
        key=lambda section: section.sort_order,
    )
    if not has_final_spec_section(visible_sections):
        issues.append(BaselineIssue(code="final_specification_missing", severity="blocker", message="A final specifications/notices section is required."))
    elif not final_spec_is_last(visible_sections):
        issues.append(BaselineIssue(code="final_specification_not_last", severity="blocker", message="Final specifications/notices must be the final visible section."))

    assets_by_id = {asset.id: asset for asset in all_assets}
    body_ids = [section.image_asset_id for section in visible_sections if section.image_asset_id and section.section_type != "hero"]
    repeats = {asset_id: count for asset_id, count in Counter(body_ids).items() if count > 1}
    for asset_id, count in repeats.items():
        issues.append(BaselineIssue(code="body_image_repeated", severity="warning", message=f"Asset {asset_id} repeats in {count} body sections."))

    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == page.project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES),
    ).all()
    for section in visible_sections:
        asset = assets_by_id.get(section.image_asset_id or "")
        if asset and not is_asset_final_output_eligible(asset):
            issues.append(BaselineIssue(code="reference_only_asset_used", severity="blocker", section_id=section.id, message=f"{resolved_asset_usage_status(asset)} asset cannot be used in final output."))
        if asset and re.search(r"[\u4e00-\u9fff]", asset.ocr_text or ""):
            issues.append(BaselineIssue(code="supplier_banner_exposed", severity="blocker", section_id=section.id, message="Chinese supplier-page copy remains visible in a final asset."))
        if not (section.title or "").strip() and not (section.body_copy or "").strip() and not section.image_asset_id and not section.visual_payload:
            issues.append(BaselineIssue(code="empty_visible_section", severity="blocker", section_id=section.id, message="Visible section is empty."))
        linked_facts = [
            fact for fact in db.query(ProductFact).filter(ProductFact.id.in_(section.associated_fact_ids or [])).all()
        ]
        if any(fact.verification_status not in CONFIRMED_FACT_STATUSES for fact in linked_facts):
            issues.append(BaselineIssue(code="unconfirmed_fact_used", severity="blocker", section_id=section.id, message="A linked fact is not confirmed."))
        _check_numeric_claims(section, confirmed_facts, issues)

    evaluation = {key: bool((getattr(registration, "evaluation_json", None) or {}).get(key, False)) for key in EVALUATION_ITEMS}
    if baseline_key and registration:
        for key, passed in evaluation.items():
            if not passed:
                issues.append(BaselineIssue(code="evaluation_pending", severity="blocker", message=f"Evaluation not completed: {key}."))
    completed_jpg_export = _has_completed_jpg_export(db, page.project_id, getattr(registration, "baseline_export_asset_id", None))
    if not completed_jpg_export:
        issues.append(BaselineIssue(
            code="baseline_jpg_missing",
            severity="blocker" if baseline_key else "warning",
            message="Save one completed JPG export as baseline evidence.",
        ))

    return CommerceStoryBaselineReport(
        source_image_count=len(final_images),
        baseline_key=baseline.key if baseline else None,
        baseline_registered=bool(registration and registration.project_id == page.project_id),
        reference_capture_asset_id=getattr(registration, "reference_capture_asset_id", None),
        baseline_export_asset_id=getattr(registration, "baseline_export_asset_id", None),
        evaluation=evaluation,
        representative_asset_id=representative.id if representative else None,
        completed_jpg_export=completed_jpg_export,
        image_repeat_count=sum(count - 1 for count in repeats.values()),
        issues=issues,
        ready_for_commerce_story=not any(issue.severity == "blocker" for issue in issues),
        manual_checks=[
            "Confirm supplier captures are evidence only, never exported layout/copy.",
            "Check the completed JPG against the preview and verify final specs are last.",
        ],
    )


def _check_numeric_claims(section: PageSection, confirmed_facts: list[ProductFact], issues: list[BaselineIssue]) -> None:
    combined = f"{section.title or ''} {section.body_copy or ''}"
    for token in re.findall(r"\b\d[\d,.]*\s*(?:mAh|Ah|kg|g|W|V|Hz|cm|mm|ml|L|%|분|시간)\b", combined, flags=re.IGNORECASE):
        if not any(token.replace(" ", "") in f"{fact.fact_text} {fact.source_text or ''}".replace(" ", "") for fact in confirmed_facts):
            issues.append(BaselineIssue(code="unsupported_numeric_claim", severity="blocker", section_id=section.id, message=f"Numeric claim '{token}' has no confirmed source."))


def _has_completed_jpg_export(db: Session, project_id: str, registered_export_asset_id: str | None) -> bool:
    candidates: list[Asset] = []
    if registered_export_asset_id:
        asset = db.query(Asset).filter(Asset.id == registered_export_asset_id, Asset.project_id == project_id).first()
        if asset:
            candidates.append(asset)
    for job in db.query(ExportJob).filter(ExportJob.project_id == project_id, ExportJob.status == "completed").all():
        for output_url in job.output_images or []:
            asset_id = str(output_url).rstrip("/").split("/page/export/download/")[-1]
            asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
            if asset:
                candidates.append(asset)
    return any(asset.source_type == "exported_image" and (asset.mime_type == "image/jpeg" or asset.filename.lower().endswith((".jpg", ".jpeg"))) for asset in candidates)


def _get_registration(db: Session, *, workspace_id: str | None, baseline_key: str | None) -> CommerceStoryBaselineRecord | None:
    if not workspace_id or not baseline_key:
        return None
    return db.query(CommerceStoryBaselineRecord).filter(
        CommerceStoryBaselineRecord.workspace_id == workspace_id,
        CommerceStoryBaselineRecord.baseline_key == baseline_key,
    ).first()
