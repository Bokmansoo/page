"""Persistence and frozen-target validation for the TASK-12.2 QA contract."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import zipfile
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import or_
from sqlalchemy.orm import Session
from PIL import Image, UnidentifiedImageError

from src.db.models import (
    AgentRun, Asset, BrandKitVersion, CommerceCreativeMasterVersion, DetailPageVersion, ExportArtifact, ProductProject,
    ImageGenerationJobRecord, ProductSourceSnapshotVersion, ProductTruthVersion, QualityAssessmentReportVersion,
    QualityThresholdProfileVersion, SellerConfirmationVersion,
)
from src.schemas.lg12_quality_report import (
    QUALITY_DOMAIN_IDS, QUALITY_REPORT_TARGET_ARTIFACT_TYPE, QUALITY_THRESHOLD_PROFILE_SCHEMA_VERSION,
    QualityAssessmentContractError,
    canonical_quality_finding_hash,
    normalize_quality_assessment_report, normalize_quality_threshold_profile,
    quality_assessment_projection,
)
from src.services.commerce_policy import (
    AI_SOURCE_TYPES,
    REFERENCE_SOURCE_TYPES,
    SELLER_OWNED_SOURCE_TYPES,
    is_asset_final_output_eligible,
    resolved_asset_usage_status,
)
from src.services.product_intake_version_service import (
    IntakeVersionContractError,
    lg12i_approved_asset_manifest_reference,
    resolve_lg12i_final_use_assets,
    _truth_normalization_from_source,
    validate_lg12i_brand_kit_scope,
    validate_immutable_version,
)
from src.services.page_finalization_service import resolve_lg10_brand_renderer_tokens
from src.services.export_service import (
    FrozenExportSnapshotError,
    LG12_CHANNEL_TRANSFORM_VERSION,
    LG12_FROZEN_EXPORT_PARITY_EVIDENCE_SCHEMA_VERSION,
    LG12_STANDALONE_TRANSFORM_VERSION,
    frozen_preview_parity_evidence,
    load_lg12_frozen_export_parity_evidence,
    parse_lg11_export_artifact_token,
)
from src.services.channel_export_service import get_channel_preset, image_sha256, supported_channel_keys
from src.services.page_visual_contract import lg10_renderer_direction_tokens, validate_lg11_canvas_safety
from src.services.prompt_intelligence_service import canonical_hash
from src.services.renderer import (
    LG10_CANONICAL_RENDER_SCHEMA_VERSION,
    LG12_LAYOUT_EVIDENCE_SCHEMA_VERSION,
    lg12_renderer_typography_role_tokens,
)
from src.services.product_identity_validator import (
    LG12_FROZEN_IMAGE_EVIDENCE_SCHEMA_VERSION,
    ProductIdentityValidationError,
    inspect_frozen_image_file,
)


FACTUAL_RIGHTS_POLICY_EVALUATOR_VERSION = "lg12-factual-rights-policy-v1"
IMAGE_IDENTITY_QUALITY_EVALUATOR_VERSION = "lg12-image-identity-quality-v1"
KOREAN_COPY_READABILITY_EVALUATOR_VERSION = "lg12-korean-copy-readability-v2"
LAYOUT_TYPOGRAPHY_BRAND_FLOW_EVALUATOR_VERSION = "lg12-layout-typography-brand-flow-v2"
CHANNEL_PREVIEW_EXPORT_PARITY_EVALUATOR_VERSION = "lg12-channel-preview-export-parity-v1"
_MEASUREMENT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(ml|l|g|kg|mm|cm|m|mah|wh|w|v)\b", re.IGNORECASE)
_CERTIFICATION_RE = re.compile(r"(?:\b(?:kc|ks|iso|ce|fda)\b|인증|인증받)", re.IGNORECASE)
_MEDICAL_RE = re.compile(r"(?:의료|치료|예방|통증|질병|건강\s*개선|효능)", re.IGNORECASE)
_PRICE_ADVANTAGE_RE = re.compile(
    r"(?:최저가|가장\s*저렴|제일\s*저렴|가격\s*대비\s*(?:최고|우수)|가성비\s*(?:최고|1위)|"
    r"(?:동급(?:\s*제품)?|타사|경쟁사)(?:\s*(?:제품))?\s*(?:대비|보다)\s*(?:더\s*)?(?:저렴(?:하다)?|싸다))"
)
_CHINESE_COPY_RE = re.compile(r"[\u4e00-\u9fff]")
_RISK_SIGNAL_TYPES = frozenset({"qr_code", "watermark", "third_party_logo", "suspicious_foreign_brand_text", "price_or_promotion"})
_FORBIDDEN_ASSET_SOURCE_TYPES = frozenset({"supplier", "reference", "competitor", "blocked", *REFERENCE_SOURCE_TYPES})
_FACTUAL_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("material", re.compile(r"(?:sus\s*\d+|스테인리스|알루미늄|실리콘|유리|플라스틱|bpa\s*(?:free|프리)?)(?:\s*(?:소재|재질))?", re.IGNORECASE)),
    ("construction", re.compile(r"\d+\s*중\s*(?:구조|레이어|코팅)")),
    ("component", re.compile(r"(?:구성품|포함(?:되어)?|부품|액세서리|필터|충전기|케이블)")),
    ("color_option", re.compile(r"(?:색상|컬러|옵션|화이트|블랙|베이지|핑크|블루|레드)")),
    ("model_identity", re.compile(r"(?:모델|sku|품번|정품|브랜드)\s*[:：]?\s*[a-z0-9가-힣-]+", re.IGNORECASE)),
    ("ingredient", re.compile(r"(?:성분|무첨가|함유|추출물)")),
    ("capability", re.compile(r"(?:무선\s*충전|방수|호환(?:됩니다|가능|지원)?|사용\s*가능|지원)")),
    ("performance", re.compile(r"(?:보온|보냉|흡입력|지속\s*시간|성능|효율|강력한|빠른\s*충전|고성능)")),
    ("origin", re.compile(r"(?:원산지|제조국|국산)")),
)
_CLAIM_SPLIT_RE = re.compile(r"(?:\r?\n|[,，;；·]|(?<=[.!?])\s+)")
_UNIT_FACTORS = {
    "ml": ("volume", Decimal("1")), "l": ("volume", Decimal("1000")),
    "g": ("mass", Decimal("1")), "kg": ("mass", Decimal("1000")),
    "mm": ("length", Decimal("1")), "cm": ("length", Decimal("10")), "m": ("length", Decimal("1000")),
    "mah": ("capacity", Decimal("1")), "wh": ("energy", Decimal("1")),
    "w": ("power", Decimal("1")), "v": ("voltage", Decimal("1")),
}

# Product Truth preserves field IDs in SellerConfirmationVersion. Keep this
# intentionally small and exact: unknown fields must not authorize a factual
# copy span merely because their value happens to be the same string.
_CLAIM_FACT_FIELD_COMPATIBILITY: dict[str, frozenset[str]] = {
    "material": frozenset({"material", "material_grade", "material_type"}),
    "construction": frozenset({"construction", "construction_type", "coating", "layer_count"}),
    "component": frozenset({"component", "components", "included_components", "composition"}),
    "color_option": frozenset({"color", "color_option", "colour"}),
    "model_identity": frozenset({"product_identity", "product_name", "model", "model_name", "sku", "brand", "brand_name"}),
    "brand": frozenset({"brand", "brand_name"}),
    "ingredient": frozenset({"ingredient", "ingredients", "composition"}),
    "capability": frozenset({"capability", "compatibility", "compatible_model", "waterproof_rating"}),
    "performance": frozenset({"performance", "insulation_duration", "cooling_duration", "usage_duration", "waterproof_rating"}),
    "origin": frozenset({"origin", "country_of_origin", "manufacturer"}),
    "certification": frozenset({"certification", "certification_code", "kc_certification"}),
    "health": frozenset({"health_claim", "medical_claim", "efficacy"}),
    "price_advantage": frozenset({"price_advantage", "price_comparison"}),
}
_NUMERIC_FACT_FIELDS: dict[str, frozenset[str]] = {
    "volume": frozenset({"capacity", "volume"}),
    "mass": frozenset({"weight", "mass", "exact_weight"}),
    "length": frozenset({"dimensions", "dimension", "length", "size", "product_dimensions"}),
    "capacity": frozenset({"battery_capacity"}),
    "energy": frozenset({"battery_capacity", "energy"}),
    "power": frozenset({"power"}),
    "voltage": frozenset({"voltage"}),
}

# TASK-12.5 currently has numeric guidance only for headline and subcopy.
# Keep the ruleset deliberately narrow: CTA, badge, body, bullet, and unknown
# renderer fields retain their non-numeric readability checks, but do not gain
# an invented maximum until a versioned threshold contract defines one.
# Font metrics and visual overflow remain TASK-12.6 concerns.
_COPY_ROLE_LENGTH_LIMITS = {
    "headline": 36,
    "subheadline": 90,
}
_COPY_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_COPY_MOJIBAKE_RE = re.compile(r"(?:\ufffd|(?:Ã.|Â.|â..){2,})")
_COPY_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_COPY_SPECIAL_REPEAT_RE = re.compile(r"([!?~])\1{2,}")
_COPY_ALL_CAPS_RE = re.compile(r"\b[A-Z]{7,}\b")
_COPY_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF]")
_COPY_UNIT_STYLE_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(mah|wh|ml|kg|mm|cm|l|g|m|w|v|%|원)(?![A-Za-z])",
    re.IGNORECASE,
)
_COPY_CTA_ACTION_RE = re.compile(
    r"(?:구매|주문|담기|선택하기|확인|보기|알아보기|신청|문의|시작|받기|살펴보기|buy|shop|order|view|learn)",
    re.IGNORECASE,
)
_COPY_EXAGGERATION_RE = re.compile(r"(?:완벽|혁명|기적|압도적|최고|최강|무조건|절대|필수|끝판왕)")


def _page_snapshot_reference(version: DetailPageVersion) -> dict[str, str]:
    snapshot = deepcopy(dict(version.sections_json or {}))
    snapshot_hash = str(snapshot.pop("snapshot_hash", "") or "")
    if not version.is_final or not snapshot_hash or canonical_hash(snapshot) != snapshot_hash:
        raise QualityAssessmentContractError("QA reports require a persisted immutable frozen DetailPageVersion.")
    schema_version = str(snapshot.get("schema_version") or "")
    if not schema_version:
        raise QualityAssessmentContractError("Frozen DetailPageVersion is missing its snapshot schema version.")
    return {"id": str(version.id), "version": schema_version, "hash": snapshot_hash, "type": QUALITY_REPORT_TARGET_ARTIFACT_TYPE}


def _frozen_manifest_hash(version: DetailPageVersion) -> str:
    snapshot = dict(version.sections_json or {})
    canonical_input = dict(dict(snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {})
    manifest = dict(canonical_input.get("approved_asset_manifest") or {})
    manifest_hash = str(manifest.get("manifest_hash") or "")
    manifest_body = deepcopy(manifest)
    manifest_body.pop("manifest_hash", None)
    if not manifest_hash or canonical_hash(manifest_body) != manifest_hash:
        raise QualityAssessmentContractError("Frozen DetailPageVersion is missing its approved asset manifest hash.")
    return manifest_hash


def _require_run(db: Session, report: Mapping[str, Any]) -> AgentRun:
    run = db.query(AgentRun).filter_by(
        id=report["creator_run_id"], workspace_id=report["workspace_id"], project_id=report["project_id"],
    ).one_or_none()
    if run is None:
        raise QualityAssessmentContractError("QA report run/project/workspace identity is not persisted.")
    return run


def _require_target(db: Session, report: Mapping[str, Any]) -> DetailPageVersion:
    target = report["target_artifact"]
    page = db.query(DetailPageVersion).filter_by(id=target["id"], project_id=report["project_id"]).one_or_none()
    project = db.query(ProductProject).filter_by(id=report["project_id"], workspace_id=report["workspace_id"]).one_or_none()
    if page is None or project is None:
        raise QualityAssessmentContractError("QA target cannot cross a persisted project or workspace boundary.")
    if target != _page_snapshot_reference(page):
        raise QualityAssessmentContractError("QA target ID/version/hash does not match the frozen DetailPageVersion.")
    if report["approved_asset_manifest_hash"] != _frozen_manifest_hash(page):
        raise QualityAssessmentContractError("QA report approved asset manifest hash does not match the frozen target.")
    return page


def _exact_reference(row: Any) -> dict[str, Any]:
    return {"id": str(row.id), "version": int(row.version), "hash": str(row.canonical_hash)}


def _require_lineage(db: Session, *, run: AgentRun, report: Mapping[str, Any]) -> None:
    lineage = report["input_lineage"]
    rows = {}
    for key, model in (
        ("source_snapshot_ref", ProductSourceSnapshotVersion),
        ("truth_ref", ProductTruthVersion),
        ("confirmation_ref", SellerConfirmationVersion),
        ("master_ref", CommerceCreativeMasterVersion),
    ):
        requested = lineage[key]
        row = db.query(model).filter_by(id=requested["id"], project_id=run.project_id, workspace_id=run.workspace_id).one_or_none()
        if row is None or _exact_reference(row) != requested:
            raise QualityAssessmentContractError(f"QA report {key} is not a persisted matching reference.")
        validate_immutable_version(db, row)
        rows[key] = row
    source, truth, confirmation, master = (
        rows["source_snapshot_ref"], rows["truth_ref"], rows["confirmation_ref"], rows["master_ref"]
    )
    if any(str(row.creator_run_id) != run.id for row in (source, truth, confirmation, master)):
        raise QualityAssessmentContractError("QA report lineage must belong to the report's creator run.")
    if (
        truth.source_snapshot_version_id != source.id
        or confirmation.truth_version_id != truth.id
        or master.source_snapshot_version_id != source.id
        or master.truth_version_id != truth.id
        or master.confirmation_version_id != confirmation.id
    ):
        raise QualityAssessmentContractError("QA report lineage is not the frozen Source -> Truth -> Confirmation -> Master chain.")


def _require_profile(db: Session, *, report: Mapping[str, Any]) -> QualityThresholdProfileVersion:
    ref = report["threshold_profile_ref"]
    profile = db.query(QualityThresholdProfileVersion).filter_by(
        id=ref["id"], workspace_id=report["workspace_id"], project_id=report["project_id"],
    ).one_or_none()
    if profile is None or {"id": str(profile.id), "version": int(profile.version), "hash": str(profile.canonical_hash)} != ref:
        raise QualityAssessmentContractError("QA threshold profile ID/version/hash does not match a persisted project profile.")
    validate_quality_threshold_profile_version(db, profile)
    if not set(report["target_channels"]).issubset(set(profile.applicable_channels_json or [])):
        raise QualityAssessmentContractError("QA threshold profile does not apply to every report channel.")
    return profile


def validate_quality_threshold_profile_version(
    db: Session, profile: QualityThresholdProfileVersion, _visited: set[str] | None = None,
) -> None:
    """Verify profile self-hash and immutable predecessor identity."""
    visited = _visited if _visited is not None else set()
    if profile.id in visited:
        raise QualityAssessmentContractError("Threshold profile lineage cannot contain a cycle.")
    visited.add(profile.id)
    normalized = normalize_quality_threshold_profile(profile.payload())
    if normalized["canonical_hash"] != profile.canonical_hash:
        raise QualityAssessmentContractError("Persisted QA threshold profile integrity check failed.")
    if profile.parent_profile_id:
        parent = db.query(QualityThresholdProfileVersion).filter_by(
            id=profile.parent_profile_id, workspace_id=profile.workspace_id, project_id=profile.project_id,
        ).one_or_none()
        if parent is None:
            raise QualityAssessmentContractError("Threshold profile successor parent is missing.")
        validate_quality_threshold_profile_version(db, parent, visited)
        if (
            profile.parent_profile_version != parent.version
            or profile.parent_profile_hash != parent.canonical_hash
            or profile.version <= parent.version
        ):
            raise QualityAssessmentContractError("Threshold profile successor parent version/hash is not pinned.")
    elif profile.parent_profile_version is not None or profile.parent_profile_hash is not None:
        raise QualityAssessmentContractError("Initial threshold profile may not pin parent identity.")


def create_quality_threshold_profile(
    db: Session, *, workspace_id: str, project_id: str, payload: Mapping[str, Any], parent_profile_id: str | None = None,
) -> QualityThresholdProfileVersion:
    profile = normalize_quality_threshold_profile(payload)
    if db.query(ProductProject).filter_by(id=project_id, workspace_id=workspace_id).one_or_none() is None:
        raise QualityAssessmentContractError("Threshold profile project/workspace identity is invalid.")
    parent = None
    if parent_profile_id:
        parent = db.query(QualityThresholdProfileVersion).filter_by(
            id=parent_profile_id, workspace_id=workspace_id, project_id=project_id,
        ).one_or_none()
        if parent is None:
            raise QualityAssessmentContractError("Threshold profile successor parent is missing.")
        if profile.get("parent_profile_ref") != {"id": str(parent.id), "version": int(parent.version), "hash": str(parent.canonical_hash)}:
            raise QualityAssessmentContractError("Threshold profile parent ID/version/hash is not pinned.")
        validate_quality_threshold_profile_version(db, parent)
        if profile["profile_version"] <= parent.version:
            raise QualityAssessmentContractError("Threshold profile successor version must increase.")
    elif profile.get("parent_profile_ref") is not None:
        raise QualityAssessmentContractError("Initial threshold profile may not pin a parent.")
    if db.query(QualityThresholdProfileVersion).filter_by(project_id=project_id, canonical_hash=profile["canonical_hash"]).first() is not None:
        raise QualityAssessmentContractError("Threshold profile content is already registered; immutable overwrite is forbidden.")
    if db.query(QualityThresholdProfileVersion).filter_by(id=profile["profile_id"]).first() is not None:
        raise QualityAssessmentContractError("Threshold profile ID is already registered; immutable overwrite is forbidden.")
    row = QualityThresholdProfileVersion(
        id=profile["profile_id"], workspace_id=workspace_id, project_id=project_id,
        version=profile["profile_version"], schema_version=profile["schema_version"],
        parent_profile_id=str(parent.id) if parent else None,
        parent_profile_version=int(parent.version) if parent else None,
        parent_profile_hash=str(parent.canonical_hash) if parent else None,
        applicable_artifact_type=profile["applicable_artifact_type"], applicable_channels_json=profile["applicable_channels"],
        thresholds_json={key: profile[key] for key in (
            "overall_minimum", "per_domain_minimum", "max_critical_violations", "max_major_findings", "max_warning_findings",
        ) if key in profile},
        status=profile["status"], effective_from=profile["effective_from"], canonical_hash=profile["canonical_hash"],
    )
    db.add(row); db.flush()
    return row


def create_quality_assessment_report(db: Session, *, payload: Mapping[str, Any]) -> QualityAssessmentReportVersion:
    report = normalize_quality_assessment_report(payload)
    run = _require_run(db, report)
    _require_target(db, report)
    _require_lineage(db, run=run, report=report)
    _require_profile(db, report=report)
    if db.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id, canonical_hash=report["canonical_hash"]).first() is not None:
        raise QualityAssessmentContractError("Quality report content is already registered; immutable overwrite is forbidden.")
    if db.query(QualityAssessmentReportVersion).filter_by(id=report["report_id"]).first() is not None:
        raise QualityAssessmentContractError("Quality report ID is already registered; immutable overwrite is forbidden.")
    row = QualityAssessmentReportVersion(
        id=report["report_id"], workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
        version=report["report_version"], schema_version=report["schema_version"],
        evaluator_bundle_version=report["evaluator_bundle_version"], target_detail_page_version_id=report["target_artifact"]["id"],
        target_artifact_version=str(report["target_artifact"]["version"]), target_artifact_hash=report["target_artifact"]["hash"],
        approved_asset_manifest_hash=report["approved_asset_manifest_hash"], target_channels_json=report["target_channels"],
        threshold_profile_id=report["threshold_profile_ref"]["id"], threshold_profile_version=report["threshold_profile_ref"]["version"],
        threshold_profile_hash=report["threshold_profile_ref"]["hash"], report_json=report, canonical_hash=report["canonical_hash"],
    )
    db.add(row); db.flush()
    return row


def validate_quality_assessment_report_version(db: Session, row: QualityAssessmentReportVersion) -> None:
    """Fail closed if a persisted report no longer matches its frozen identity."""
    report = normalize_quality_assessment_report(dict(row.report_json or {}))
    if report["canonical_hash"] != row.canonical_hash:
        raise QualityAssessmentContractError("Persisted QualityAssessmentReport canonical hash is invalid.")
    expected_columns = {
        "id": str(row.id), "version": int(row.version), "schema_version": row.schema_version,
        "evaluator_bundle_version": row.evaluator_bundle_version, "project_id": row.project_id,
        "workspace_id": row.workspace_id, "creator_run_id": row.creator_run_id,
        "target_detail_page_version_id": row.target_detail_page_version_id,
        "target_artifact_version": row.target_artifact_version, "target_artifact_hash": row.target_artifact_hash,
        "approved_asset_manifest_hash": row.approved_asset_manifest_hash,
        "threshold_profile_id": row.threshold_profile_id, "threshold_profile_version": row.threshold_profile_version,
        "threshold_profile_hash": row.threshold_profile_hash,
    }
    actual_columns = {
        "id": report["report_id"], "version": report["report_version"], "schema_version": report["schema_version"],
        "evaluator_bundle_version": report["evaluator_bundle_version"], "project_id": report["project_id"],
        "workspace_id": report["workspace_id"], "creator_run_id": report["creator_run_id"],
        "target_detail_page_version_id": report["target_artifact"]["id"],
        "target_artifact_version": str(report["target_artifact"]["version"]), "target_artifact_hash": report["target_artifact"]["hash"],
        "approved_asset_manifest_hash": report["approved_asset_manifest_hash"],
        "threshold_profile_id": report["threshold_profile_ref"]["id"],
        "threshold_profile_version": report["threshold_profile_ref"]["version"],
        "threshold_profile_hash": report["threshold_profile_ref"]["hash"],
    }
    if actual_columns != expected_columns or list(row.target_channels_json or []) != report["target_channels"]:
        raise QualityAssessmentContractError("Persisted QualityAssessmentReport columns do not match its bounded report payload.")
    run = _require_run(db, report)
    _require_target(db, report)
    _require_lineage(db, run=run, report=report)
    _require_profile(db, report=report)


def quality_report_durable_projection(row: QualityAssessmentReportVersion) -> dict[str, Any]:
    """Project/rebuild using the exact same normalized report serialization."""
    report = normalize_quality_assessment_report(dict(row.report_json or {}))
    if report["canonical_hash"] != row.canonical_hash:
        raise QualityAssessmentContractError("Persisted QualityAssessmentReport canonical hash is invalid.")
    return quality_assessment_projection(report)


def _qa_typed_reference(reference: Mapping[str, Any], artifact_type: str) -> dict[str, Any]:
    """Convert an immutable LG reference to the bounded QA reference shape."""

    return {
        "id": str(reference["id"]), "version": reference["version"],
        "hash": str(reference["hash"]), "type": artifact_type,
    }


def _qa_row_reference(row: Any, artifact_type: str) -> dict[str, Any]:
    return _qa_typed_reference(_exact_reference(row), artifact_type)


def _frozen_assembly_input(page: DetailPageVersion) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read only the already-hashed frozen page input; never consult a draft."""

    snapshot = deepcopy(dict(page.sections_json or {}))
    snapshot_hash = str(snapshot.pop("snapshot_hash", "") or "")
    if not snapshot_hash or canonical_hash(snapshot) != snapshot_hash:
        raise QualityAssessmentContractError("Factual QA requires an untampered frozen DetailPageVersion.")
    canonical = deepcopy(dict(dict(snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {}))
    if not canonical:
        raise QualityAssessmentContractError("Frozen DetailPageVersion is missing its canonical assembly input.")
    manifest = deepcopy(dict(canonical.get("approved_asset_manifest") or {}))
    body = deepcopy(manifest); manifest_hash = str(body.pop("manifest_hash", "") or "")
    if not manifest_hash or canonical_hash(body) != manifest_hash:
        raise QualityAssessmentContractError("Frozen DetailPageVersion approved asset manifest is tampered.")
    return snapshot, canonical


def _as_mappings(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, Mapping)]


def _reference_identity(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(item.get("id") or ""), str(item.get("version") or ""), str(item.get("hash") or ""))


def _frozen_sections(snapshot: Mapping[str, Any], canonical: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = canonical.get("sections")
    if not isinstance(candidates, list):
        candidates = dict(snapshot.get("commerce_renderer") or {}).get("sections")
    if not isinstance(candidates, list):
        candidates = snapshot.get("sections")
    return [dict(item) for item in list(candidates or []) if isinstance(item, Mapping)]


def _claim_type(text: str) -> str | None:
    """Classify only deterministic product facts; ordinary prose stays narrative."""

    if _text_measurements(text):
        return "numeric"
    if _CERTIFICATION_RE.search(text):
        return "certification"
    if _MEDICAL_RE.search(text):
        return "health"
    if _PRICE_ADVANTAGE_RE.search(text):
        return "price_advantage"
    for claim_type, pattern in _FACTUAL_CLAIM_PATTERNS:
        if pattern.search(text):
            return claim_type
    return None


def _claim_reference(*, section_id: str, copy_text: str, ordinal: int, claim_text: str, claim_type: str) -> dict[str, Any]:
    return _qa_typed_reference(
        {
            "id": f"claim:{section_id}:{ordinal}",
            "version": 1,
            "hash": canonical_hash({
                "section_id": section_id, "copy_text": copy_text, "ordinal": ordinal,
                "text": claim_text, "claim_type": claim_type,
            }),
        },
        "copy_claim",
    )


def _section_factual_claims(section: Mapping[str, Any], *, section_id: str, copy_text: str) -> list[dict[str, Any]]:
    """Return deterministic factual spans without promoting narrative prose.

    New copy artifacts may pin explicit ``copy_ref.claims``.  Existing frozen
    LG-10/11 copy is segmented on stable visible delimiters and classified only
    by the narrow deterministic taxonomy above.
    """

    copy_ref = dict(section.get("copy_ref") or {}) if isinstance(section.get("copy_ref"), Mapping) else {}
    explicit = _as_mappings(copy_ref.get("claims"))
    claims: list[dict[str, Any]] = []
    if explicit:
        for ordinal, item in enumerate(explicit):
            text = " ".join(str(item.get("text") or item.get("text_span") or "").split())
            claim_type = str(item.get("claim_type") or _claim_type(text) or "")
            if not text or not claim_type:
                continue
            claims.append({
                "text": text,
                "claim_type": claim_type,
                "fact_ids": [str(value) for value in list(item.get("fact_ids") or []) if isinstance(value, str)],
                "evidence_refs": _as_mappings(item.get("evidence_refs")),
                "reference": _claim_reference(
                    section_id=section_id, copy_text=copy_text, ordinal=ordinal, claim_text=text, claim_type=claim_type,
                ),
            })
        return claims
    fact_ids = [str(value) for value in list(copy_ref.get("fact_ids") or section.get("fact_ids") or []) if isinstance(value, str)]
    spans: list[tuple[str, str]] = []
    for raw_span in _CLAIM_SPLIT_RE.split(copy_text):
        text = " ".join(raw_span.split())
        if not text:
            continue
        for match in _MEASUREMENT_RE.finditer(text):
            spans.append(("numeric", match.group(0)))
        for claim_type, pattern in _FACTUAL_CLAIM_PATTERNS:
            for match in pattern.finditer(text):
                spans.append((claim_type, match.group(0)))
        for claim_type, pattern in (
            ("certification", _CERTIFICATION_RE), ("health", _MEDICAL_RE),
            ("price_advantage", _PRICE_ADVANTAGE_RE),
        ):
            if pattern.search(text):
                spans.append((claim_type, text))
    for ordinal, (claim_type, text) in enumerate(sorted(set(spans), key=lambda item: (item[0], item[1]))):
        claims.append({
            "text": text,
            "claim_type": claim_type,
            # Legacy copy has only element-level fact IDs.  Matching below
            # still requires a fact's frozen value to support this exact span.
            "fact_ids": fact_ids,
            "evidence_refs": [],
            "reference": _claim_reference(
                section_id=section_id, copy_text=copy_text, ordinal=ordinal, claim_text=text, claim_type=claim_type,
            ),
        })
    return claims


def _section_copy(section: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    copy_ref = dict(section.get("copy_ref") or {}) if isinstance(section.get("copy_ref"), Mapping) else {}
    fact_ids = [str(item) for item in list(copy_ref.get("fact_ids") or section.get("fact_ids") or []) if isinstance(item, str)]
    values: list[str] = []
    for key in ("title", "message", "text", "copy", "body", "headline", "subheadline"):
        value = section.get(key)
        if isinstance(value, str) and value.strip():
            values.append(" ".join(value.split()))
    for key in ("title", "message", "text", "copy", "body", "headline", "subheadline"):
        value = copy_ref.get(key)
        if isinstance(value, str) and value.strip():
            values.append(" ".join(value.split()))
    return fact_ids, values


def _section_asset_references(section: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read explicit frozen asset identities without accepting arbitrary object trees."""

    found: list[dict[str, Any]] = []
    for key in ("approved_assets", "asset_refs", "assets", "seller_owned_fallback_assets"):
        for item in _as_mappings(section.get(key)):
            asset_id = str(item.get("asset_id") or item.get("id") or "")
            asset_hash = str(item.get("asset_content_hash") or item.get("hash") or "")
            if asset_id:
                found.append({"asset_id": asset_id, "asset_content_hash": asset_hash})
    if isinstance(section.get("asset_id"), str):
        found.append({
            "asset_id": str(section["asset_id"]),
            "asset_content_hash": str(section.get("asset_content_hash") or ""),
        })
    return found


def _measurement(value: str | None, unit: str | None) -> tuple[str, Decimal] | None:
    if value is None or unit is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    normalized_unit = str(unit).strip().lower()
    factor = _UNIT_FACTORS.get(normalized_unit)
    return (factor[0], amount * factor[1]) if factor else None


def _text_measurements(text: str) -> set[tuple[str, Decimal]]:
    result: set[tuple[str, Decimal]] = set()
    for match in _MEASUREMENT_RE.finditer(text):
        parsed = _measurement(match.group(1), match.group(2))
        if parsed is not None:
            result.add(parsed)
    return result


def _factual_finding(
    *, rule_id: str, code: str, severity: str, target_refs: Sequence[Mapping[str, Any]],
    evidence_refs: Sequence[Mapping[str, Any]], expected: Any, observed: Any, message: str, remediation: str,
) -> dict[str, Any]:
    identity = {
        "rule_id": rule_id, "code": code,
        "targets": sorted((_reference_identity(ref) for ref in target_refs)),
        "expected": expected, "observed": observed,
    }
    return {
        "finding_id": f"lg12-factual:{canonical_hash(identity)[:32]}",
        "domain": "factual_rights_policy", "severity": severity, "rule_id": rule_id,
        "code": code, "message": message, "target_refs": list(target_refs),
        "evidence_refs": list(evidence_refs), "expected": expected, "observed": observed,
        "remediation_hint": remediation,
    }


def _confirmed_fact_field_id(fact: Mapping[str, Any]) -> str:
    """Return the persisted Product Truth field identity, never a caller alias."""

    field_id = str(fact.get("field_id") or "").strip().lower().replace("-", "_")
    # LG-10/11 fixtures and existing frozen copy use the explicit ``fact:``
    # namespace.  Strip that exact compatibility prefix only; arbitrary
    # prefixes/suffixes never participate in taxonomy matching.
    if field_id.startswith("fact:"):
        field_id = field_id.removeprefix("fact:")
    return field_id


def _claim_accepts_confirmed_field(claim: Mapping[str, Any], field_id: str) -> bool:
    """Apply exact Product Truth field compatibility before comparing values."""

    claim_type = str(claim.get("claim_type") or "")
    if claim_type == "numeric":
        dimensions = {dimension for dimension, _amount in _text_measurements(str(claim.get("text") or ""))}
        if len(dimensions) != 1:
            return False
        return field_id in _NUMERIC_FACT_FIELDS.get(next(iter(dimensions)), frozenset())
    return field_id in _CLAIM_FACT_FIELD_COMPATIBILITY.get(claim_type, frozenset())


def _confirmed_fact_supports_claim(fact: Mapping[str, Any], claim: Mapping[str, Any]) -> bool:
    """Require a confirmed fact to support this claim, not just its container."""

    text = str(claim["text"])
    claim_type = str(claim["claim_type"])
    if not _claim_accepts_confirmed_field(claim, _confirmed_fact_field_id(fact)):
        return False
    value = str(fact.get("normalized_value") or "").strip()
    unit = fact.get("unit")
    expected_measurement = _measurement(value, str(unit) if unit is not None else None)
    if expected_measurement is not None:
        return expected_measurement in _text_measurements(text)
    normalized_value = " ".join(value.split()).lower()
    if normalized_value:
        # A populated confirmed value must support this span itself.  A
        # generic field ID such as ``fact:material`` cannot authorize a
        # second, unrelated material claim in the same copy element.
        return normalized_value in text.lower()
    # Confirmed-fact value provenance requires a concrete value.  Do not let a
    # generic field name stand in for missing source-backed claim evidence.
    return False


def _require_frozen_page_master_binding(
    *, page: DetailPageVersion, snapshot: Mapping[str, Any], run: AgentRun,
    source: ProductSourceSnapshotVersion, truth: ProductTruthVersion,
    confirmation: SellerConfirmationVersion, master: CommerceCreativeMasterVersion,
) -> dict[str, Any]:
    """Anchor a frozen page to exactly the LG-12I Master that produced it."""

    lineage = dict(snapshot.get("lg12_quality_lineage") or {})
    if lineage.get("schema_version") != "lg12-detail-page-quality-lineage-v1":
        raise QualityAssessmentContractError("Frozen DetailPageVersion is missing its LG-12 Master lineage.")
    if str(lineage.get("creator_run_id") or "") != str(run.id):
        raise QualityAssessmentContractError("Frozen DetailPageVersion belongs to a different creator run.")
    expected = {
        "source_snapshot_ref": _exact_reference(source),
        "truth_ref": _exact_reference(truth),
        "confirmation_ref": _exact_reference(confirmation),
        "master_ref": _exact_reference(master),
        "approved_asset_manifest_ref": dict(master.approved_asset_manifest_ref_json or {}),
    }
    for key, reference in expected.items():
        if dict(lineage.get(key) or {}) != reference:
            raise QualityAssessmentContractError(f"Frozen DetailPageVersion {key} does not match the persisted Master lineage.")
    return lineage


def _require_master_asset_manifest_parity(
    db: Session, *, source: ProductSourceSnapshotVersion,
    confirmation: SellerConfirmationVersion, master: CommerceCreativeMasterVersion,
) -> dict[str, dict[str, Any]]:
    """Return the only live final-use assets permitted by the persisted Master."""

    usable, _exclusions = resolve_lg12i_final_use_assets(
        db, project_id=master.project_id, source=source, confirmation=confirmation,
    )
    expected_manifest = lg12i_approved_asset_manifest_reference(
        source_reference=_exact_reference(source), usable_asset_refs=usable,
    )
    if dict(master.approved_asset_manifest_ref_json or {}) != expected_manifest:
        raise QualityAssessmentContractError("Persisted Master approved asset manifest is stale or tampered.")
    return {str(item["id"]): dict(item) for item in usable}


def _master_permitted_generated_output(
    *,
    run: AgentRun,
    asset: Asset,
    job: ImageGenerationJobRecord | None,
    master_assets: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Allow only an approved LG-9 output derived from Master-approved inputs.

    A Commerce Creative Master indexes the seller-controlled *source* assets;
    it intentionally does not mutate when LG-9 later creates a reviewed output
    asset.  A frozen page may therefore use that distinct output only when its
    exact approved generation record is anchored to one or more of those
    source identities.  This is not a general ai-generated-asset exception.
    """

    if (
        job is None
        or str(job.project_id or "") != str(run.project_id)
        or str(job.status or "") != "approved"
        or str(job.output_asset_id or "") != str(asset.id)
        or str(asset.source_type or "").lower() not in AI_SOURCE_TYPES
        or not is_asset_final_output_eligible(asset)
    ):
        return False
    job_run_id = str(dict(job.usage_metadata or {}).get("langgraph_run_id") or "")
    if job_run_id and job_run_id != str(run.id):
        return False
    source_ids = {str(value) for value in list(job.source_asset_ids or []) if str(value)}
    return bool(source_ids) and source_ids.issubset(set(master_assets))


def _domain_result(
    value: Mapping[str, Any], *, report_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # Reuse the TASK-12.2 domain normalizer rather than keeping a second
    # finding/hash contract in this evaluator.
    from src.schemas.lg12_quality_report import (  # type: ignore[attr-defined]
        _frozen_domain_target_binding,
        _normalize_domain,
    )

    payload = dict(value)
    if report_payload is not None:
        payload.update(_frozen_domain_target_binding(report_payload))
    return _normalize_domain(payload, label="factual_rights_policy")


def _copy_role(field: str) -> str:
    normalized = field.lower()
    if "cta" in normalized or normalized in {"action", "action_text"}:
        return "cta"
    if "badge" in normalized or "label" in normalized:
        return "badge"
    if "subtitle" in normalized or "subheadline" in normalized or "subcopy" in normalized:
        return "subheadline"
    if "title" in normalized or "headline" in normalized:
        return "headline"
    if "bullet" in normalized or "point" in normalized:
        return "bullet"
    return "body"


def _normalized_copy_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _copy_text_similarity(left: str, right: str) -> bool:
    if not left or not right or min(len(left), len(right)) < 12:
        return False
    if left == right:
        return True
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right)) >= 0.72
    return SequenceMatcher(a=left, b=right, autojunk=False).ratio() >= 0.9


def _copy_artifact_reference(section_id: str, copy_ref: Mapping[str, Any]) -> dict[str, Any] | None:
    artifact_key = str(copy_ref.get("artifact_key") or "")
    schema_version = str(copy_ref.get("schema_version") or "")
    artifact_hash = str(copy_ref.get("artifact_hash") or "")
    if (
        artifact_key != "copywriting"
        or not schema_version
        or len(artifact_hash) != 64
        or any(char not in "0123456789abcdef" for char in artifact_hash)
    ):
        return None
    return _qa_typed_reference(
        {"id": f"copy-artifact:{artifact_key}:{section_id}", "version": schema_version, "hash": artifact_hash},
        "copy_artifact",
    )


def _frozen_copy_records(snapshot: Mapping[str, Any], canonical: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return only the copy frozen in the renderer snapshot, never a live copy set."""

    canonical_rendering = dict(dict(snapshot.get("lg10") or {}).get("canonical_rendering") or {})
    renderer_sections = {
        str(item.get("section_id") or item.get("id") or ""): dict(item)
        for item in _as_mappings(canonical_rendering.get("sections"))
        if str(item.get("section_id") or item.get("id") or "")
    }
    records: list[dict[str, Any]] = []
    for index, section in enumerate(_frozen_sections(snapshot, canonical)):
        section_id = str(section.get("section_id") or section.get("id") or f"section:{index}")
        rendered = renderer_sections.get(section_id)
        copy_ref = dict(section.get("copy_ref") or {}) if isinstance(section.get("copy_ref"), Mapping) else {}
        section_ref = _qa_typed_reference(
            {"id": section_id, "version": 1, "hash": canonical_hash(section)}, "section",
        )
        if rendered is not None and not bool(dict(rendered.get("canvas") or {}).get("is_visible", True)):
            continue
        if rendered is None:
            records.append({"section_id": section_id, "section_ref": section_ref, "state": "missing_renderer_copy"})
            continue
        artifact_ref = _copy_artifact_reference(section_id, copy_ref)
        if artifact_ref is None:
            records.append({"section_id": section_id, "section_ref": section_ref, "state": "missing_copy_artifact"})
            continue
        planning_copy = dict(dict(canonical.get("planning_refs") or {}).get("copy") or {})
        if any(copy_ref.get(key) != planning_copy.get(key) for key in ("artifact_key", "schema_version", "artifact_hash")):
            records.append({"section_id": section_id, "section_ref": section_ref, "artifact_ref": artifact_ref, "state": "copy_artifact_mismatch"})
            continue
        text_layer = _as_mappings(rendered.get("text_layer"))
        fields = [str(item.get("field") or "") for item in text_layer]
        if not text_layer or not all(fields) or len(fields) != len(set(fields)):
            records.append({"section_id": section_id, "section_ref": section_ref, "artifact_ref": artifact_ref, "state": "missing_renderer_copy"})
            continue
        declared_fields = [str(field) for field in list(copy_ref.get("fields") or []) if isinstance(field, str) and field]
        if declared_fields and set(declared_fields) != set(fields):
            records.append({"section_id": section_id, "section_ref": section_ref, "artifact_ref": artifact_ref, "state": "copy_field_mismatch"})
            continue
        for item in text_layer:
            field = str(item["field"])
            text = item.get("text")
            if not isinstance(text, str):
                records.append({"section_id": section_id, "section_ref": section_ref, "artifact_ref": artifact_ref, "field": field, "state": "invalid_copy_text"})
                continue
            field_ref = _qa_typed_reference(
                {
                    "id": f"copy-field:{section_id}:{field}", "version": 1,
                    "hash": canonical_hash({"section_id": section_id, "copy_artifact_hash": artifact_ref["hash"], "field": field, "text": text}),
                },
                "copy_field",
            )
            records.append({
                "section_id": section_id, "section_ref": section_ref, "artifact_ref": artifact_ref,
                "field": field, "field_ref": field_ref, "role": _copy_role(field), "text": text, "state": "ready",
            })
    return records


def _copy_finding(
    *, page_ref: Mapping[str, Any], record: Mapping[str, Any], code: str, severity: str,
    expected: Any, observed: Any, message: str, remediation: str,
) -> dict[str, Any]:
    targets = [dict(page_ref), dict(record["section_ref"])]
    evidence = []
    if isinstance(record.get("artifact_ref"), Mapping):
        targets.append(dict(record["artifact_ref"])); evidence.append(dict(record["artifact_ref"]))
    if isinstance(record.get("field_ref"), Mapping):
        targets.append(dict(record["field_ref"])); evidence.append(dict(record["field_ref"]))
    identity = {
        "code": code, "severity": severity, "targets": targets,
        "expected": expected, "observed": observed,
    }
    return {
        "finding_id": f"lg12-copy:{canonical_hash(identity)[:32]}",
        "domain": "korean_copy_readability", "severity": severity,
        "rule_id": f"copy.{code}", "code": code, "message": message,
        "target_refs": targets, "evidence_refs": evidence,
        "expected": expected, "observed": observed,
        "remediation_hint": remediation,
    }


def evaluate_korean_copy_readability_domain(db: Session, *, report_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only, deterministic Korean copy evaluation of frozen renderer text.

    This is deliberately not a fact/evidence evaluator and never reads a
    mutable copywriting artifact.  It supplies a single QA-domain result; the
    overall Quality Bar, rework routing, and provider-backed linguistic review
    remain later TASK-12 work.
    """

    report = normalize_quality_assessment_report(report_payload)
    run = _require_run(db, report)
    page = _require_target(db, report)
    _require_lineage(db, run=run, report=report)
    source = db.query(ProductSourceSnapshotVersion).filter_by(id=report["input_lineage"]["source_snapshot_ref"]["id"]).one()
    truth = db.query(ProductTruthVersion).filter_by(id=report["input_lineage"]["truth_ref"]["id"]).one()
    confirmation = db.query(SellerConfirmationVersion).filter_by(id=report["input_lineage"]["confirmation_ref"]["id"]).one()
    master = db.query(CommerceCreativeMasterVersion).filter_by(id=report["input_lineage"]["master_ref"]["id"]).one()
    snapshot, canonical = _frozen_assembly_input(page)
    _require_frozen_page_master_binding(
        page=page, snapshot=snapshot, run=run, source=source, truth=truth,
        confirmation=confirmation, master=master,
    )
    page_ref = _page_snapshot_reference(page)
    records = _frozen_copy_records(snapshot, canonical)
    findings: list[dict[str, Any]] = []
    ready_records = [item for item in records if item.get("state") == "ready"]
    needs_review = False

    for record in records:
        if record.get("state") == "ready":
            continue
        needs_review = True
        code = str(record.get("state") or "missing_renderer_copy")
        findings.append(_copy_finding(
            page_ref=page_ref, record=record, code=code, severity="major",
            expected="frozen copy artifact and renderer text snapshot", observed=code,
            message="The frozen section cannot be evaluated because its copy identity or text snapshot is incomplete.",
            remediation="Freeze the matching copy artifact and editable renderer text before quality evaluation.",
        ))

    seen_headlines: dict[str, dict[str, Any]] = {}
    seen_ctas: dict[str, dict[str, Any]] = {}
    seen_copy: list[tuple[str, dict[str, Any]]] = []
    unit_styles: dict[str, set[bool]] = {}
    for record in ready_records:
        text = str(record["text"])
        normalized = _normalized_copy_text(text)
        role = str(record["role"])
        limit = _COPY_ROLE_LENGTH_LIMITS.get(role)
        if not normalized:
            needs_review = True
            findings.append(_copy_finding(
                page_ref=page_ref, record=record, code="missing_copy_role", severity="major",
                expected=f"non-empty {role} copy", observed="empty",
                message="A frozen copy role is empty and cannot be treated as a complete readability result.",
                remediation="Provide reviewed copy for this frozen field.",
            ))
            continue
        if limit is not None and len(text) > limit:
            findings.append(_copy_finding(
                page_ref=page_ref, record=record, code=f"overlong_{role}", severity="major",
                expected={"value": limit, "unit": "characters", "comparison": "lte"},
                observed={"value": len(text), "unit": "characters", "comparison": "gte"},
                message="Frozen copy exceeds the established role-aware readability length guidance.",
                remediation="Shorten this field without changing factual meaning or evidence scope.",
            ))
        if _COPY_CONTROL_RE.search(text) or _COPY_MOJIBAKE_RE.search(text):
            findings.append(_copy_finding(
                page_ref=page_ref, record=record, code="broken_korean_text", severity="major",
                expected="readable Unicode text", observed="control_or_mojibake_signal",
                message="Frozen copy contains a broken Unicode or control-character signal.",
                remediation="Replace the corrupted text from the reviewed frozen copy artifact.",
            ))
        if len(_COPY_CJK_RE.findall(text)) >= 2:
            findings.append(_copy_finding(
                page_ref=page_ref, record=record, code="foreign_language_mix", severity="major",
                expected="reviewed Korean copy with permitted brand/model terms", observed="unreviewed_cjk_signal",
                message="Frozen copy contains an untranslated foreign-language signal.",
                remediation="Review and replace the affected copy field; factual/policy authority remains TASK-12.3.",
            ))
        # A single frozen field can contain an arbitrarily excessive
        # whitespace run. Keep its bounded normalisation-unit count in the
        # finding metadata instead of copying text/spans into the report.
        spacing_violation_count = sum(
            # For spaces/tabs, every extra character beyond the first is a
            # deterministic normalisation defect.  A very long trailing run
            # therefore cannot hide behind one aggregate boolean finding.
            max(1, len(match.group(0)) - 1)
            if "\n" not in match.group(0)
            # Three line breaks are the first violation; subsequent breaks
            # are independently removed by the same cosmetic normalizer.
            else max(1, match.group(0).count("\n") - 2)
            for match in re.finditer(r"[ \t]{2,}|(?:\r?\n){3,}", text)
        )
        if spacing_violation_count:
            findings.append(_copy_finding(
                page_ref=page_ref, record=record, code="spacing_inconsistency", severity="minor",
                expected="normalized sentence spacing",
                observed={"value": spacing_violation_count, "unit": "repeated_whitespace_runs"},
                message="Frozen copy contains unnecessary repeated whitespace or line breaks.",
                remediation="Normalize spacing without changing the frozen copy meaning.",
            ))
        if _COPY_SPECIAL_REPEAT_RE.search(text):
            findings.append(_copy_finding(
                page_ref=page_ref, record=record, code="punctuation_overuse", severity="minor",
                expected="bounded punctuation emphasis", observed="repeated_punctuation",
                message="Frozen copy overuses repeated punctuation.",
                remediation="Reduce punctuation emphasis while preserving the intended tone.",
            ))
        if len(_COPY_EMOJI_RE.findall(text)) >= 3 or _COPY_ALL_CAPS_RE.search(text):
            findings.append(_copy_finding(
                page_ref=page_ref, record=record, code="emphasis_overuse", severity="minor",
                expected="bounded visual emphasis", observed="excessive_emoji_or_all_caps",
                message="Frozen copy uses excessive emoji or all-caps emphasis.",
                remediation="Use emphasis sparingly in this copy field.",
            ))
        if len(_COPY_EXAGGERATION_RE.findall(text)) >= 2:
            findings.append(_copy_finding(
                page_ref=page_ref, record=record, code="excessive_promotional_tone", severity="minor",
                expected="bounded promotional tone", observed="repeated_exaggeration_cues",
                message="Frozen copy repeats exaggerated promotional language.",
                remediation="Reduce repeated emphasis; factual and policy review remains TASK-12.3.",
            ))
        for match in _COPY_UNIT_STYLE_RE.finditer(text):
            unit_styles.setdefault(match.group(2).lower(), set()).add(bool(re.search(r"\s", match.group(0))))
        sentences = [
            value.strip()
            for value in re.split(r"(?:[.!?。！？]+|\r?\n)+", normalized)
            if len(value.strip()) >= 8
        ]
        if any(count >= 2 for count in Counter(sentences).values()):
            findings.append(_copy_finding(
                page_ref=page_ref, record=record, code="repeated_sentence", severity="major",
                expected="non-repeated sentence copy", observed="repeated_sentence",
                message="Frozen copy repeats the same sentence within one field.",
                remediation="Keep one concise instance of the repeated sentence.",
            ))
        if role == "cta":
            if not _COPY_CTA_ACTION_RE.search(text):
                findings.append(_copy_finding(
                    page_ref=page_ref, record=record, code="cta_action_unclear", severity="major",
                    expected="clear action-oriented CTA", observed="no_action_intent",
                    message="Frozen CTA copy has no deterministic action intent.",
                    remediation="Use a concise action phrase such as view, buy, or check.",
                ))
        if role == "headline":
            previous = seen_headlines.get(normalized)
            if previous is not None:
                findings.append(_copy_finding(
                    page_ref=page_ref, record=record, code="duplicate_headline", severity="major",
                    expected="section-specific headline", observed=f"duplicate_with:{previous['section_id']}:{previous['field']}",
                    message="Frozen page repeats the same headline across sections.",
                    remediation="Differentiate this section headline without changing factual scope.",
                ))
            else:
                seen_headlines[normalized] = record
        if role == "cta":
            copy_ref = dict(next((section.get("copy_ref") or {} for section in _frozen_sections(snapshot, canonical) if str(section.get("section_id") or section.get("id") or "") == record["section_id"]), {}))
            if copy_ref.get("allow_repeated_cta") is not True:
                previous = seen_ctas.get(normalized)
                if previous is not None:
                    findings.append(_copy_finding(
                        page_ref=page_ref, record=record, code="duplicate_cta", severity="major",
                        expected="non-repeated CTA unless frozen structural exception is explicit",
                        observed=f"duplicate_with:{previous['section_id']}:{previous['field']}",
                        message="Frozen page repeats the same CTA across sections.",
                        remediation="Differentiate this CTA or pin an explicit structural-repeat exception.",
                    ))
                else:
                    seen_ctas[normalized] = record
        for prior_text, prior_record in seen_copy:
            if _copy_text_similarity(normalized, prior_text):
                findings.append(_copy_finding(
                    page_ref=page_ref, record=record, code="duplicate_copy", severity="minor",
                    expected="non-duplicated section copy", observed=f"similar_to:{prior_record['section_id']}:{prior_record['field']}",
                    message="Frozen copy is materially similar to an earlier section field.",
                    remediation="Remove repetitive wording while preserving the intended factual content.",
                ))
                break
        seen_copy.append((normalized, record))

    for unit, styles in sorted(unit_styles.items()):
        if len(styles) < 2:
            continue
        representative = next(
            item
            for item in ready_records
            if any(match.group(2).lower() == unit for match in _COPY_UNIT_STYLE_RE.finditer(str(item["text"])))
        )
        findings.append(_copy_finding(
            page_ref=page_ref, record=representative, code="numeric_unit_spacing_inconsistency", severity="minor",
            expected=f"consistent spacing before {unit}", observed="mixed_spacing_styles",
            message="Frozen copy mixes numeric/unit spacing styles.",
            remediation="Use one numeric/unit spacing style without changing factual values.",
        ))

    deduped = {item["finding_id"]: item for item in findings}
    ordered = [deduped[key] for key in sorted(deduped)]
    evidence = {(_reference_identity(ref), str(ref.get("type") or "")): ref for item in ordered for ref in item["evidence_refs"]}
    language_codes = {"broken_korean_text", "foreign_language_mix"}
    punctuation_codes = {"spacing_inconsistency", "punctuation_overuse", "emphasis_overuse", "numeric_unit_spacing_inconsistency"}
    repetition_codes = {"repeated_sentence", "duplicate_copy", "duplicate_headline", "duplicate_cta"}
    cta_codes = {"missing_copy_role", "cta_action_unclear", "duplicate_cta"}
    density_codes = {"missing_copy_role", "overlong_subheadline"}

    def metric(metric_id: str, codes: set[str]) -> dict[str, Any]:
        failed = any(item["code"] in codes for item in ordered)
        return {"metric_id": metric_id, "value": 0 if failed else 1, "status": "failed" if failed else "passed"}

    major_count = sum(item["severity"] == "major" for item in ordered)
    minor_count = sum(item["severity"] == "minor" for item in ordered)
    # ``spacing_inconsistency`` represents a bounded count of independent
    # formatting runs in one field.  The first run is already represented by
    # the finding itself; each additional run receives the same established
    # minor-finding penalty without creating raw span/body output.
    spacing_runs = sum(
        int(dict(item.get("observed") or {}).get("value") or 1)
        for item in ordered
        if item["code"] == "spacing_inconsistency" and isinstance(item.get("observed"), Mapping)
    )
    weighted_minor_count = minor_count + max(0, spacing_runs - sum(
        item["code"] == "spacing_inconsistency" for item in ordered
    ))
    domain = _domain_result({
        "domain_id": "korean_copy_readability", "score": max(0, 100 - 12 * major_count - 4 * weighted_minor_count),
        "status": "needs_review" if needs_review else "complete",
        "evaluator_version": KOREAN_COPY_READABILITY_EVALUATOR_VERSION,
        "findings": ordered, "critical_count": 0, "warning_count": len(ordered),
        "evidence_refs": [value for _, value in sorted(evidence.items())],
        "evaluated_at": f"frozen:{page_ref['hash']}", "metric_source": "automatic",
        # A human Korean rubric is a distinct bounded slot.  This deterministic
        # evaluator never invents one and never embeds human notes/body text.
        "human_rubric": {"status": "not_requested"},
        "submetrics": [
            metric("headline_length_quality", {"overlong_headline"}),
            metric("body_density", density_codes),
            metric("repetition", repetition_codes),
            metric("punctuation_quality", punctuation_codes),
            metric("language_consistency", language_codes),
            metric("cta_clarity", cta_codes),
        ],
    }, report_payload=report_payload)
    return {"domain": domain, "critical_violations": []}


def _layout_artifact_identity(value: Mapping[str, Any] | None) -> tuple[str, str, str]:
    """Read either production artifact-reference spelling without widening it."""

    reference = dict(value or {})
    return (
        str(reference.get("id") or reference.get("artifact_id") or ""),
        str(reference.get("version") or reference.get("artifact_version") or ""),
        str(reference.get("hash") or reference.get("artifact_hash") or ""),
    )


def _layout_artifact_reference(value: Mapping[str, Any] | None, artifact_type: str) -> dict[str, Any] | None:
    identifier, version, digest = _layout_artifact_identity(value)
    if not identifier or not version or not digest:
        return None
    return _qa_typed_reference({"id": identifier, "version": version, "hash": digest}, artifact_type)


def _layout_section_reference(section_id: str) -> dict[str, Any]:
    return _qa_typed_reference(
        {"id": section_id, "version": 1, "hash": canonical_hash({"section_id": section_id})},
        "frozen_section",
    )


def _layout_element_reference(section_id: str, element_id: str) -> dict[str, Any]:
    return _qa_typed_reference(
        {
            # Canvas element IDs already carry their stable section namespace.
            # Storing ``section_id:element_id`` here made Quality Bar targets
            # impossible for the existing Canvas executor to resolve.
            "id": element_id, "version": 1,
            "hash": canonical_hash({"section_id": section_id, "element_id": element_id}),
        },
        "frozen_canvas_element",
    )


def _layout_finding(
    *, page_ref: Mapping[str, Any], code: str, severity: str, message: str,
    expected: Any, observed: Any, section_id: str | None = None,
    element_id: str | None = None, evidence_refs: Sequence[Mapping[str, Any]] = (),
    additional_target_refs: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    targets: list[dict[str, Any]] = [dict(page_ref)]
    if section_id:
        targets.append(_layout_section_reference(section_id))
    if section_id and element_id:
        targets.append(_layout_element_reference(section_id, element_id))
    targets.extend(dict(value) for value in additional_target_refs)
    evidence = [dict(item) for item in evidence_refs]
    identity = {
        "code": code, "severity": severity, "targets": targets,
        "expected": expected, "observed": observed,
    }
    return {
        "finding_id": f"lg12-layout:{canonical_hash(identity)[:32]}",
        "domain": "layout_typography_brand_flow", "severity": severity,
        "rule_id": f"layout.{code}", "code": code, "message": message,
        "target_refs": targets, "evidence_refs": evidence,
        "expected": expected, "observed": observed,
        "remediation_hint": "Freeze a corrected renderer/Canvas/Brand Kit successor version; do not edit this frozen page.",
    }


def _critical_violations_from_findings(findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project persisted critical findings into the report's blocking schema."""

    violations: list[dict[str, Any]] = []
    for item in findings:
        if str(item.get("severity") or "") != "critical":
            continue
        targets = [dict(value) for value in list(item.get("target_refs") or [])]
        if not targets:
            raise QualityAssessmentContractError("Critical quality finding is missing a frozen target reference.")
        finding_hash = canonical_quality_finding_hash(item)
        violation = {
            "violation_id": f"lg12-critical:{finding_hash[:32]}",
            "domain": str(item.get("domain") or ""),
            "rule_id": str(item.get("rule_id") or ""),
            "target_ref": targets[-1],
            "evidence_refs": [dict(value) for value in list(item.get("evidence_refs") or [])],
            "reason_code": str(item.get("code") or ""),
            "blocking": True,
        }
        if (
            not violation["violation_id"].removeprefix("lg12-critical:")
            or not violation["domain"]
            or not violation["rule_id"]
        ):
            raise QualityAssessmentContractError("Critical quality finding has incomplete immutable identity.")
        violations.append(violation)
    return violations


_LAYOUT_EVIDENCE_TOP_LEVEL_FIELDS = frozenset({
    "schema_version", "renderer_version", "renderer_hash", "renderer_token", "renderer_width",
    "section_spacing_px", "title_scale", "page_plan_ref", "brand_kit_ref", "color_tokens",
    "typography", "contrast", "sections",
})
_LAYOUT_EVIDENCE_SECTION_FIELDS = frozenset({
    "section_id", "sort_order", "visible", "component_id", "layout_token", "bounds",
    "spacing_token", "section_spacing_px", "padding_token", "alignment", "typography_roles",
    "scene", "elements",
})
_LAYOUT_EVIDENCE_ELEMENT_FIELDS = frozenset({"element_id", "kind", "bounds", "locked", "group_id", "visible"})
_LAYOUT_EVIDENCE_ROLE_FIELDS = frozenset({
    "field", "role", "font_token", "font_family", "size_token", "weight_token",
    "line_height_token", "letter_spacing_token", "color_token", "alignment_token",
})
_LAYOUT_EVIDENCE_SCENE_FIELDS = frozenset({"scene_id", "scene_type", "scene_order", "page_plan_ref"})


def _layout_reference_complete(value: Any) -> bool:
    reference = dict(value or {}) if isinstance(value, Mapping) else {}
    return bool(
        str(reference.get("id") or "")
        and reference.get("version") is not None
        and bool(str(reference.get("hash") or ""))
    )


def _layout_bounds_complete(value: Any) -> bool:
    bounds = dict(value or {}) if isinstance(value, Mapping) else {}
    try:
        return all(isinstance(bounds[key], int) for key in ("x", "y", "width", "height")) and bounds["width"] > 0 and bounds["height"] > 0
    except KeyError:
        return False


def validate_layout_evidence_completeness(evidence: Mapping[str, Any]) -> dict[str, bool]:
    """Return evaluability for every required TASK-12.6 frozen dimension.

    Missing evidence is deliberately distinct from a hash or shape violation:
    the former is a deterministic ``needs_review`` outcome, while the latter
    is handled fail-closed by the evidence reader below.
    """

    sections = [dict(item) for item in list(evidence.get("sections") or []) if isinstance(item, Mapping)]
    section_identity = bool(sections) and all(
        bool(str(item.get("section_id") or "")) and isinstance(item.get("sort_order"), int)
        for item in sections
    )
    geometry = section_identity and all(
        _layout_bounds_complete(item.get("bounds"))
        and isinstance(item.get("elements"), list)
        and bool(item.get("elements"))
        and all(
            bool(str(dict(element).get("element_id") or "")) and _layout_bounds_complete(dict(element).get("bounds"))
            for element in item.get("elements") if isinstance(element, Mapping)
        )
        and all(isinstance(element, Mapping) for element in item.get("elements"))
        for item in sections
    )
    typography = section_identity and all(
        isinstance(item.get("typography_roles"), list)
        and bool(item.get("typography_roles"))
        and all(
            isinstance(role, Mapping)
            and _LAYOUT_EVIDENCE_ROLE_FIELDS <= set(role)
            and all(bool(str(role.get(key) or "")) for key in _LAYOUT_EVIDENCE_ROLE_FIELDS)
            for role in item.get("typography_roles")
        )
        for item in sections
    )
    spacing_alignment = section_identity and all(
        bool(str(item.get("spacing_token") or ""))
        and isinstance(item.get("section_spacing_px"), int)
        and bool(str(item.get("padding_token") or ""))
        and isinstance(item.get("alignment"), Mapping)
        and bool(str(dict(item["alignment"]).get("expected_token") or ""))
        and bool(str(dict(item["alignment"]).get("actual_token") or ""))
        for item in sections
    )
    scene_flow = section_identity and all(
        isinstance(item.get("scene"), Mapping)
        and _LAYOUT_EVIDENCE_SCENE_FIELDS <= set(dict(item["scene"]))
        and bool(str(dict(item["scene"]).get("scene_id") or ""))
        and bool(str(dict(item["scene"]).get("scene_type") or ""))
        and isinstance(dict(item["scene"]).get("scene_order"), int)
        and _layout_reference_complete(dict(item["scene"]).get("page_plan_ref"))
        for item in sections
    )
    contrast = dict(evidence.get("contrast") or {})
    contrast_evaluable = (
        bool(str(contrast.get("foreground_token") or ""))
        and bool(str(contrast.get("background_token") or ""))
        and (contrast.get("minimum_ratio") is None or isinstance(contrast.get("minimum_ratio"), (int, float)))
    )
    return {
        "renderer_evaluable": (
            str(evidence.get("renderer_version") or "") == LG10_CANONICAL_RENDER_SCHEMA_VERSION
            and bool(str(evidence.get("renderer_hash") or ""))
        ),
        "geometry_evaluable": bool(geometry),
        "typography_evaluable": bool(typography),
        "spacing_alignment_evaluable": bool(spacing_alignment),
        "scene_flow_evaluable": bool(scene_flow),
        "pageplan_evaluable": _layout_reference_complete(evidence.get("page_plan_ref")),
        "brand_evaluable": _layout_reference_complete(evidence.get("brand_kit_ref")),
        "contrast_evaluable": bool(contrast_evaluable),
    }


def _layout_evidence_from_frozen_rendering(rendering: Mapping[str, Any]) -> dict[str, Any] | None:
    evidence = deepcopy(dict(rendering.get("lg12_layout_evidence") or {}))
    evidence_hash = str(evidence.pop("evidence_hash", "") or "")
    if not evidence or evidence.get("schema_version") != LG12_LAYOUT_EVIDENCE_SCHEMA_VERSION:
        return None
    # Missing evidence is evaluability debt (needs review); a present but
    # mismatched hash is an integrity violation and therefore fail-closed.
    if not evidence_hash:
        return None
    if canonical_hash(evidence) != evidence_hash:
        raise QualityAssessmentContractError("Frozen layout evidence hash is invalid.")
    # The evidence schema is deliberately compact and reference/measurement
    # only.  This protects the QA domain from accidentally becoming a second
    # HTML, copy, or pixel artifact store.
    if set(evidence) - _LAYOUT_EVIDENCE_TOP_LEVEL_FIELDS:
        raise QualityAssessmentContractError("Frozen layout evidence has unsupported raw fields.")
    if not isinstance(evidence.get("sections"), list):
        raise QualityAssessmentContractError("Frozen layout evidence is missing bounded section geometry.")
    for section in evidence["sections"]:
        if not isinstance(section, Mapping) or set(section) - _LAYOUT_EVIDENCE_SECTION_FIELDS:
            raise QualityAssessmentContractError("Frozen layout evidence contains unsupported section data.")
        for element in list(section.get("elements") or []):
            if not isinstance(element, Mapping) or set(element) - _LAYOUT_EVIDENCE_ELEMENT_FIELDS:
                raise QualityAssessmentContractError("Frozen layout evidence contains unsupported element data.")
        for role in list(section.get("typography_roles") or []):
            if not isinstance(role, Mapping) or set(role) - _LAYOUT_EVIDENCE_ROLE_FIELDS:
                raise QualityAssessmentContractError("Frozen layout evidence contains unsupported typography data.")
        scene = section.get("scene")
        if scene is not None and (not isinstance(scene, Mapping) or set(scene) - _LAYOUT_EVIDENCE_SCENE_FIELDS):
            raise QualityAssessmentContractError("Frozen layout evidence contains unsupported scene data.")
    return {**evidence, "evidence_hash": evidence_hash}


def _layout_issue_finding(
    *, page_ref: Mapping[str, Any], issue: Mapping[str, Any], evidence_ref: Mapping[str, Any],
    additional_target_refs: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    code = str(issue.get("code") or "")
    supported: dict[str, tuple[str, str]] = {
        "element_overlap": ("major", "Visible Canvas elements overlap without an allowed decorative relationship."),
        "element_overflow": ("major", "A visible Canvas element exceeds its frozen rendered section bounds."),
        "invalid_element_geometry": ("critical", "A Canvas element has invalid frozen geometry."),
        "section_height_out_of_bounds": ("major", "A frozen section has invalid renderer height."),
        "brand_overflow": ("critical", "Frozen Brand Kit geometry exceeds the rendered page."),
        "invalid_brand_geometry": ("critical", "Frozen Brand Kit geometry is unavailable or invalid."),
        "final_spec_position": ("critical", "The final specification section is not visible and last."),
    }
    if code not in supported:
        return None
    severity, message = supported[code]
    section_id = str(issue.get("section_id") or "") or None
    element_id = str(issue.get("element_id") or "") or None
    observed = str(issue.get("reason") or code)
    # Two independent overlap pairs can share a selected left-hand element.
    # Keep the conflicting frozen element in the bounded finding identity so
    # the quality score and rework evidence do not silently collapse distinct
    # Canvas safety defects into one generic warning.
    conflicting_element_id = str(issue.get("conflicting_element_id") or "")
    if code == "element_overlap" and conflicting_element_id:
        observed = f"{observed} (conflicts_with:{conflicting_element_id})"
    return _layout_finding(
        page_ref=page_ref, code=code, severity=severity, message=message,
        expected="frozen renderer composition contract", observed=observed,
        section_id=section_id, element_id=element_id, evidence_refs=[evidence_ref],
        additional_target_refs=additional_target_refs,
    )


def _layout_contrast_ratio(foreground: Any, background: Any) -> float | None:
    """Calculate a ratio only for frozen six-digit renderer color tokens."""

    def luminance(value: Any) -> float | None:
        text = str(value or "")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
            return None
        channels = [int(text[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = luminance(foreground), luminance(background)
    if first is None or second is None:
        return None
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def evaluate_layout_typography_brand_flow_domain(db: Session, *, report_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate only frozen renderer composition and Brand Kit parity.

    This does not perform channel/export parity, a final Quality Bar verdict,
    rework routing, screenshot analysis, or any provider work.  It preserves
    LG-11's exact hidden/decorative-overlap semantics by reading its existing
    frozen Canvas safety validator rather than recreating geometry rules.
    """

    report = normalize_quality_assessment_report(report_payload)
    run = _require_run(db, report)
    page = _require_target(db, report)
    _require_lineage(db, run=run, report=report)
    source = db.query(ProductSourceSnapshotVersion).filter_by(id=report["input_lineage"]["source_snapshot_ref"]["id"]).one()
    truth = db.query(ProductTruthVersion).filter_by(id=report["input_lineage"]["truth_ref"]["id"]).one()
    confirmation = db.query(SellerConfirmationVersion).filter_by(id=report["input_lineage"]["confirmation_ref"]["id"]).one()
    master = db.query(CommerceCreativeMasterVersion).filter_by(id=report["input_lineage"]["master_ref"]["id"]).one()
    snapshot, canonical = _frozen_assembly_input(page)
    _require_frozen_page_master_binding(
        page=page, snapshot=snapshot, run=run, source=source, truth=truth,
        confirmation=confirmation, master=master,
    )
    page_ref = _page_snapshot_reference(page)
    rendering = dict(dict(snapshot.get("lg10") or {}).get("canonical_rendering") or {})
    rendering_body = deepcopy(rendering)
    frozen_render_hash = str(rendering_body.pop("render_hash", "") or "")
    if frozen_render_hash and canonical_hash(rendering_body) != frozen_render_hash:
        raise QualityAssessmentContractError("Frozen canonical renderer hash is invalid.")
    evidence = _layout_evidence_from_frozen_rendering(rendering)
    renderer_identity_body = deepcopy(rendering)
    # ``canonical_input_ref`` / ``page_assembly_ref`` are the immutable
    # LG-10 wrapper added after the renderer returns.  The evidence hash pins
    # the renderer body itself, so exclude that wrapper exactly as the
    # renderer did when freezing the evidence.
    for key in ("render_hash", "lg12_layout_evidence", "canonical_input_ref", "page_assembly_ref"):
        renderer_identity_body.pop(key, None)
    base_evidence = [
        _qa_row_reference(source, "ProductSourceSnapshotVersion"),
        _qa_row_reference(truth, "ProductTruthVersion"),
        _qa_row_reference(confirmation, "SellerConfirmationVersion"),
        _qa_row_reference(master, "CommerceCreativeMasterVersion"),
    ]
    findings: list[dict[str, Any]] = []
    needs_review = evidence is None or not frozen_render_hash
    if evidence is None:
        findings.append(_layout_finding(
            page_ref=page_ref, code="missing_frozen_layout_evidence", severity="major",
            message="The frozen renderer does not carry the bounded layout evidence required for deterministic evaluation.",
            expected="lg12-frozen-layout-evidence-v1", observed="missing", evidence_refs=base_evidence,
        ))
        domain = _domain_result({
            "domain_id": "layout_typography_brand_flow", "score": 0, "status": "needs_review",
            "evaluator_version": LAYOUT_TYPOGRAPHY_BRAND_FLOW_EVALUATOR_VERSION,
            "findings": findings, "critical_count": 0, "warning_count": len(findings),
            "evidence_refs": base_evidence, "evaluated_at": f"frozen:{page_ref['hash']}", "metric_source": "automatic",
            "human_rubric": {"status": "not_requested"},
            "submetrics": [
                {"metric_id": metric, "value": 0, "status": "needs_review"}
                for metric in ("layout_geometry", "typography", "brand_kit", "scene_flow", "contrast", "visual_hierarchy")
            ],
        }, report_payload=report_payload)
        return {"domain": domain, "critical_violations": []}

    if str(evidence.get("renderer_version") or "") != LG10_CANONICAL_RENDER_SCHEMA_VERSION:
        needs_review = True
    evidence_renderer_hash = str(evidence.get("renderer_hash") or "")
    if evidence_renderer_hash and evidence_renderer_hash != canonical_hash(renderer_identity_body):
        raise QualityAssessmentContractError("Frozen layout evidence renderer hash is invalid.")
    completeness = validate_layout_evidence_completeness(evidence)
    missing_dimensions = [name for name, evaluable in completeness.items() if not evaluable]
    if missing_dimensions:
        needs_review = True
        for dimension in missing_dimensions:
            findings.append(_layout_finding(
                page_ref=page_ref, code=f"missing_{dimension}", severity="major",
                message="A required frozen layout evidence dimension is not evaluable.",
                expected="complete bounded frozen evidence", observed=dimension, evidence_refs=base_evidence,
            ))

    if not frozen_render_hash:
        findings.append(_layout_finding(
            page_ref=page_ref, code="missing_frozen_renderer_hash", severity="major",
            message="The frozen canonical renderer has no render hash and cannot be treated as complete layout evidence.",
            expected="canonical renderer hash", observed="missing", evidence_refs=base_evidence,
        ))
    layout_ref = _qa_typed_reference(
        {"id": f"layout-evidence:{page.id}", "version": 1, "hash": evidence["evidence_hash"]},
        "frozen_renderer_layout_evidence",
    )
    base_evidence.append(layout_ref)
    if frozen_render_hash:
        base_evidence.append(_qa_typed_reference(
            {"id": f"canonical-renderer:{page.id}", "version": 1, "hash": frozen_render_hash},
            "frozen_canonical_renderer",
        ))
    brand_kit = db.query(BrandKitVersion).filter_by(
        id=master.brand_kit_version_id, workspace_id=run.workspace_id,
    ).one_or_none()
    try:
        validate_lg12i_brand_kit_scope(brand_kit, workspace_id=run.workspace_id, project_id=run.project_id)
    except IntakeVersionContractError as exc:
        raise QualityAssessmentContractError("Frozen Master Brand Kit scope is invalid.") from exc
    if (
        brand_kit is None
        or int(brand_kit.version) != int(master.brand_kit_version or 0)
        or str(brand_kit.content_hash) != str(master.brand_kit_hash)
    ):
        raise QualityAssessmentContractError("Frozen Master Brand Kit ID/version/hash is not persisted exactly.")
    brand_ref = _qa_typed_reference(
        {"id": brand_kit.id, "version": brand_kit.version, "hash": brand_kit.content_hash}, "BrandKitVersion",
    )
    base_evidence.append(brand_ref)

    frozen_brand_ref = dict(canonical.get("brand_kit_ref") or {})
    evidence_brand_ref = dict(evidence.get("brand_kit_ref") or {})
    if (
        str(frozen_brand_ref.get("brand_kit_version_id") or "") != str(brand_kit.id)
        or str(frozen_brand_ref.get("brand_kit_hash") or "") != str(brand_kit.content_hash)
        or _reference_identity(evidence_brand_ref) != _reference_identity(brand_ref)
    ):
        findings.append(_layout_finding(
            page_ref=page_ref, code="brand_kit_identity_mismatch", severity="critical",
            message="Frozen page Brand Kit identity does not match its persisted Commerce Creative Master.",
            expected=brand_ref, observed="frozen_brand_kit_identity_mismatch", evidence_refs=[brand_ref, layout_ref],
            additional_target_refs=[brand_ref],
        ))

    expected_tokens = resolve_lg10_brand_renderer_tokens(
        run=run,
        brand_kit_ref={"brand_kit_version_id": brand_kit.id, "brand_kit_hash": brand_kit.content_hash},
        db=db,
    )
    frozen_tokens = dict(rendering.get("brand_tokens") or {})
    expected_colors = dict(expected_tokens.get("color_tokens") or {})
    frozen_colors = dict(frozen_tokens.get("color_tokens") or {})
    for color_name in ("accent", "text", "surface", "muted_surface"):
        if str(frozen_colors.get(color_name) or "") != str(expected_colors.get(color_name) or ""):
            findings.append(_layout_finding(
                page_ref=page_ref, code="brand_color_token_mismatch", severity="major",
                message="Frozen renderer color token differs from the immutable Brand Kit token.",
                expected=f"{color_name}:{str(expected_colors.get(color_name) or '')}",
                observed=f"{color_name}:{str(frozen_colors.get(color_name) or '')}",
                evidence_refs=[brand_ref, layout_ref],
            ))
    expected_font = str(dict(expected_tokens.get("typography") or {}).get("body_font") or "")
    frozen_font = str(dict(frozen_tokens.get("typography") or {}).get("body_font") or "")
    if frozen_font != expected_font:
        findings.append(_layout_finding(
            page_ref=page_ref, code="brand_font_token_mismatch", severity="major",
            message="Frozen renderer font token differs from the immutable Brand Kit token.",
            expected=expected_font, observed=frozen_font, evidence_refs=[brand_ref, layout_ref],
        ))
    frozen_brand_assets = dict(frozen_tokens.get("asset_layer") or {})
    expected_brand_assets = dict(expected_tokens.get("asset_layer") or {})
    allowed_brand_asset_ids = {str(item) for item in list(brand_kit.logo_asset_ids or []) if item}
    for role in ("logo", "watermark"):
        frozen_identity = frozen_brand_assets.get(role)
        expected_identity = expected_brand_assets.get(role)
        if expected_identity is not None and not isinstance(frozen_identity, Mapping):
            findings.append(_layout_finding(
                page_ref=page_ref, code=f"brand_{role}_missing", severity="major",
                message=f"A rights-approved frozen Brand Kit {role} is missing from the renderer asset layer.",
                expected=f"approved {role} identity", observed="missing", evidence_refs=[brand_ref, layout_ref],
            ))
            continue
        if frozen_identity is None:
            continue
        identity = dict(frozen_identity) if isinstance(frozen_identity, Mapping) else {}
        asset_id = str(identity.get("asset_id") or "")
        asset_hash = str(identity.get("asset_content_hash") or "")
        asset = db.query(Asset).join(ProductProject).filter(
            Asset.id == asset_id, ProductProject.workspace_id == run.workspace_id,
        ).one_or_none() if asset_id else None
        if (
            asset is None or asset_id not in allowed_brand_asset_ids
            or str(asset.content_hash or "") != asset_hash
            or str(resolved_asset_usage_status(asset) or "") not in {"seller_owned", "rights_confirmed"}
            or str(asset.source_type or "").lower() in _FORBIDDEN_ASSET_SOURCE_TYPES
        ):
            findings.append(_layout_finding(
                page_ref=page_ref, code=f"brand_{role}_asset_integrity_mismatch", severity="critical",
                message=f"Frozen Brand Kit {role} is not a persisted rights-approved asset for this workspace.",
                expected="persisted rights-approved Brand Kit asset ID/hash", observed=asset_id or "missing",
                evidence_refs=[brand_ref, layout_ref],
            ))

    expected_direction = lg10_renderer_direction_tokens(
        design_direction=str(canonical.get("design_direction") or "safe_information"),
    )
    if dict(rendering.get("renderer_tokens") or {}) != expected_direction:
        findings.append(_layout_finding(
            page_ref=page_ref, code="renderer_token_mismatch", severity="critical",
            message="Frozen renderer tokens do not match the frozen canonical design direction.",
            expected=expected_direction.get("renderer_token"),
            observed=str(dict(rendering.get("renderer_tokens") or {}).get("renderer_token") or ""),
            evidence_refs=[layout_ref],
        ))

    page_plan_ref = _layout_artifact_reference(master.page_plan_artifact_ref_json, "PagePlanVersion")
    frozen_plan_ref = _layout_artifact_reference(dict(canonical.get("planning_refs") or {}).get("page_plan"), "PagePlanVersion")
    evidence_plan_ref = _layout_artifact_reference(evidence.get("page_plan_ref"), "PagePlanVersion")
    if page_plan_ref is None or frozen_plan_ref is None:
        needs_review = True
        findings.append(_layout_finding(
            page_ref=page_ref, code="missing_frozen_page_plan_identity", severity="major",
            message="Frozen page has no exact PagePlan identity for section-flow evaluation.",
            expected="PagePlanVersion id/version/hash", observed="missing", evidence_refs=base_evidence,
        ))
    elif (
        evidence_plan_ref is None
        or _reference_identity(page_plan_ref) != _reference_identity(frozen_plan_ref)
        or _reference_identity(page_plan_ref) != _reference_identity(evidence_plan_ref)
    ):
        findings.append(_layout_finding(
            page_ref=page_ref, code="page_plan_identity_mismatch", severity="critical",
            message="Frozen page planning identity does not match the persisted Master PagePlan.",
            expected=page_plan_ref, observed=frozen_plan_ref if evidence_plan_ref is None else evidence_plan_ref,
            evidence_refs=[page_plan_ref, frozen_plan_ref, layout_ref],
        ))
    else:
        base_evidence.append(page_plan_ref)

    canonical_sections = [dict(item) for item in list(canonical.get("sections") or []) if isinstance(item, Mapping)]
    rendered_sections = [dict(item) for item in list(rendering.get("sections") or []) if isinstance(item, Mapping)]
    canonical_ids = [str(item.get("section_id") or "") for item in canonical_sections]
    rendered_ids = [str(item.get("section_id") or "") for item in rendered_sections]
    if len(rendered_ids) != len(set(rendered_ids)):
        duplicate = next(item for item in rendered_ids if rendered_ids.count(item) > 1)
        findings.append(_layout_finding(
            page_ref=page_ref, code="duplicate_frozen_section", severity="major",
            message="Frozen renderer contains a duplicate section identity.", expected="unique section IDs", observed=duplicate,
            section_id=duplicate, evidence_refs=[layout_ref],
        ))
    if canonical_ids != rendered_ids:
        for section_id in sorted(set(canonical_ids) - set(rendered_ids)):
            findings.append(_layout_finding(
                page_ref=page_ref, code="missing_planned_section", severity="major",
                message="A frozen planned section is missing from the renderer output.", expected="present", observed="missing",
                section_id=section_id, evidence_refs=[layout_ref],
            ))
        for section_id in sorted(set(rendered_ids) - set(canonical_ids)):
            findings.append(_layout_finding(
                page_ref=page_ref, code="unplanned_frozen_section", severity="major",
                message="Frozen renderer contains a section absent from its canonical PagePlan input.", expected="planned section", observed="unplanned",
                section_id=section_id, evidence_refs=[layout_ref],
            ))
        if set(canonical_ids) == set(rendered_ids):
            findings.append(_layout_finding(
                page_ref=page_ref, code="section_order_mismatch", severity="major",
            message="Frozen section order differs from the canonical PagePlan order.",
            expected="|".join(canonical_ids), observed="|".join(rendered_ids),
                evidence_refs=[layout_ref], additional_target_refs=[page_plan_ref] if page_plan_ref else [],
            ))

    safety = validate_lg11_canvas_safety(version_snapshot=snapshot, channel="smartstore")
    for issue in _as_mappings(safety.get("issues")):
        plan_target = [page_plan_ref] if (
            str(issue.get("code") or "") == "final_spec_position" and page_plan_ref is not None
        ) else []
        finding = _layout_issue_finding(
            page_ref=page_ref, issue=issue, evidence_ref=layout_ref,
            additional_target_refs=plan_target,
        )
        if finding is not None:
            findings.append(finding)

    visible_scene_assets: dict[str, str] = {}
    for section in rendered_sections:
        section_id = str(section.get("section_id") or "")
        visible = bool(dict(section.get("canvas") or {}).get("is_visible", True))
        if not visible:
            continue
        for asset in _as_mappings(section.get("asset_layer")):
            asset_id = str(asset.get("asset_id") or "")
            if not asset_id:
                continue
            previous = visible_scene_assets.get(asset_id)
            if previous and previous != section_id:
                findings.append(_layout_finding(
                    page_ref=page_ref, code="duplicate_scene_asset", severity="minor",
                    message="The same frozen scene asset is repeated in multiple visible sections.",
                    expected="scene asset diversity", observed=asset_id, section_id=section_id, evidence_refs=[layout_ref],
                ))
            else:
                visible_scene_assets[asset_id] = section_id

    evidence_sections = [dict(item) for item in list(evidence.get("sections") or []) if isinstance(item, Mapping)]
    if [str(item.get("section_id") or "") for item in evidence_sections] != rendered_ids:
        needs_review = True
        findings.append(_layout_finding(
            page_ref=page_ref, code="layout_evidence_section_mismatch", severity="major",
            message="Frozen layout evidence does not match the frozen renderer section sequence.",
            expected="|".join(rendered_ids),
            observed="|".join(str(item.get("section_id") or "") for item in evidence_sections),
            evidence_refs=[layout_ref],
        ))
    expected_scene_sequence: list[tuple[str, str, int, tuple[str, str, str]]] = []
    for order, section in enumerate(canonical_sections) if completeness["scene_flow_evaluable"] and completeness["pageplan_evaluable"] else []:
        scene_ref = dict(section.get("scene_ref") or {})
        scene_id = str(scene_ref.get("scene_id") or "")
        scene_type = str(scene_ref.get("scene_type") or "")
        scene_plan_ref = _layout_artifact_reference({
            "id": scene_ref.get("page_plan_id"), "version": scene_ref.get("page_plan_version"), "hash": scene_ref.get("page_plan_hash"),
        }, "PagePlanVersion")
        if not scene_id or not scene_type or scene_plan_ref is None:
            needs_review = True
            findings.append(_layout_finding(
                page_ref=page_ref, code="missing_frozen_scene_flow_contract", severity="major",
                message="Frozen PagePlan scene identity is not available for deterministic scene-flow evaluation.",
                expected="scene ID/type/order and PagePlan reference", observed=str(section.get("section_id") or ""),
                section_id=str(section.get("section_id") or "") or None, evidence_refs=[layout_ref],
            ))
            continue
        expected_order = scene_ref.get("scene_order")
        expected_scene_sequence.append((
            scene_id, scene_type, int(expected_order) if isinstance(expected_order, int) else order,
            _reference_identity(scene_plan_ref),
        ))

    actual_scene_sequence: list[tuple[str, str, int, tuple[str, str, str]]] = []
    for section in evidence_sections:
        section_id = str(section.get("section_id") or "")
        if completeness["spacing_alignment_evaluable"] and int(section.get("section_spacing_px") or -1) != int(expected_direction.get("section_spacing") or -2):
            findings.append(_layout_finding(
                page_ref=page_ref, code="spacing_token_mismatch", severity="minor",
                message="Frozen section spacing differs from the renderer design-direction token.",
                expected=int(expected_direction.get("section_spacing") or 0), observed=section.get("section_spacing_px"),
                section_id=section_id, evidence_refs=[layout_ref],
            ))
        alignment = dict(section.get("alignment") or {})
        if completeness["spacing_alignment_evaluable"] and (
            str(alignment.get("expected_token") or "") != "renderer_text_left"
            or str(alignment.get("actual_token") or "") != str(alignment.get("expected_token") or "")
        ):
            findings.append(_layout_finding(
                page_ref=page_ref, code="alignment_token_mismatch", severity="minor",
                message="Frozen alignment does not match the renderer-owned alignment token.",
                expected="renderer_text_left", observed=str(alignment.get("actual_token") or ""),
                section_id=section_id, evidence_refs=[layout_ref],
            ))
        for index, role in enumerate(_as_mappings(section.get("typography_roles")) if completeness["typography_evaluable"] else []):
            expected_role = lg12_renderer_typography_role_tokens(
                field=str(role.get("field") or ""), index=index,
                renderer_tokens=dict(rendering.get("renderer_tokens") or {}), brand_tokens=frozen_tokens,
            )
            mismatched = [
                key for key, expected_value in expected_role.items()
                if str(role.get(key) or "") != str(expected_value or "")
            ]
            if mismatched:
                findings.append(_layout_finding(
                    page_ref=page_ref, code="typography_role_token_mismatch", severity="major",
                    message="Frozen text role does not resolve to a permitted renderer/Brand Kit typography token.",
                    expected="frozen renderer typography token", observed=",".join(sorted(mismatched)),
                    section_id=section_id, evidence_refs=[layout_ref],
                ))
                if any(key in {"role", "size_token", "weight_token"} for key in mismatched):
                    findings.append(_layout_finding(
                        page_ref=page_ref, code="visual_hierarchy_token_mismatch", severity="major",
                        message="Frozen role hierarchy does not match the renderer-owned role/style contract.",
                        expected="renderer role hierarchy", observed=",".join(sorted(mismatched)),
                        section_id=section_id, evidence_refs=[layout_ref],
                    ))
        if completeness["scene_flow_evaluable"]:
            scene = dict(section.get("scene") or {})
            scene_ref = _layout_artifact_reference(scene.get("page_plan_ref"), "PagePlanVersion")
            scene_order = scene.get("scene_order")
            actual_scene_sequence.append((
                str(scene.get("scene_id") or ""), str(scene.get("scene_type") or ""),
                int(scene_order) if isinstance(scene_order, int) else -1,
                _reference_identity(scene_ref) if scene_ref else ("", "", ""),
            ))

    if expected_scene_sequence and actual_scene_sequence:
        expected_scene_ids = [item[0] for item in expected_scene_sequence]
        actual_scene_ids = [item[0] for item in actual_scene_sequence]
        if len(actual_scene_ids) != len(set(actual_scene_ids)):
            duplicate_scene = next(item for item in actual_scene_ids if actual_scene_ids.count(item) > 1)
            findings.append(_layout_finding(
                page_ref=page_ref, code="duplicate_scene_identity", severity="major",
                message="Frozen renderer repeats a PagePlan scene identity.", expected="unique scene IDs", observed=duplicate_scene,
                evidence_refs=[layout_ref],
            ))
        if expected_scene_ids != actual_scene_ids:
            for scene_id in sorted(set(expected_scene_ids) - set(actual_scene_ids)):
                findings.append(_layout_finding(
                    page_ref=page_ref, code="missing_planned_scene", severity="major",
                    message="A PagePlan scene is missing from frozen renderer evidence.", expected="present", observed="missing",
                    evidence_refs=[layout_ref],
                ))
            for scene_id in sorted(set(actual_scene_ids) - set(expected_scene_ids)):
                findings.append(_layout_finding(
                    page_ref=page_ref, code="unexpected_frozen_scene", severity="major",
                    message="Frozen renderer evidence contains an unplanned scene.", expected="planned scene", observed=scene_id,
                    evidence_refs=[layout_ref],
                ))
            if set(expected_scene_ids) == set(actual_scene_ids):
                findings.append(_layout_finding(
                    page_ref=page_ref, code="scene_order_mismatch", severity="major",
                    message="Frozen scene order differs from the frozen PagePlan sequence.",
                    expected="|".join(expected_scene_ids), observed="|".join(actual_scene_ids),
                    evidence_refs=[layout_ref], additional_target_refs=[page_plan_ref] if page_plan_ref else [],
                ))
        if expected_scene_sequence != actual_scene_sequence:
            for expected_scene, actual_scene in zip(expected_scene_sequence, actual_scene_sequence):
                if expected_scene[0] == actual_scene[0] and expected_scene != actual_scene:
                    findings.append(_layout_finding(
                        page_ref=page_ref, code="scene_identity_mismatch", severity="major",
                        message="Frozen scene type/order/PagePlan identity differs from the expected frozen PagePlan scene.",
                        expected=expected_scene[0], observed=actual_scene[0], evidence_refs=[layout_ref],
                        additional_target_refs=[page_plan_ref] if page_plan_ref else [],
                    ))

    contrast = dict(evidence.get("contrast") or {})
    evidence_colors = dict(evidence.get("color_tokens") or {})
    foreground = str(evidence_colors.get(str(contrast.get("foreground_token") or "")) or "")
    background = str(evidence_colors.get(str(contrast.get("background_token") or "")) or "")
    minimum_ratio = contrast.get("minimum_ratio")
    if minimum_ratio is not None:
        ratio = _layout_contrast_ratio(foreground, background)
        if ratio is None:
            needs_review = True
            findings.append(_layout_finding(
                page_ref=page_ref, code="contrast_not_evaluable", severity="major",
                message="Frozen contrast tokens cannot be evaluated against the pinned renderer contract.",
                expected="valid frozen color tokens", observed="invalid", evidence_refs=[layout_ref],
            ))
        elif ratio < float(minimum_ratio):
            findings.append(_layout_finding(
                page_ref=page_ref, code="contrast_ratio_below_contract", severity="major",
                message="Frozen renderer contrast is below the explicitly pinned Brand Kit contrast contract.",
                expected=float(minimum_ratio), observed=round(ratio, 4), evidence_refs=[layout_ref],
            ))

    deduped = {item["finding_id"]: item for item in findings}
    ordered = [deduped[key] for key in sorted(deduped)]
    critical = [item for item in ordered if item["severity"] == "critical"]
    major_count = sum(item["severity"] == "major" for item in ordered)
    minor_count = sum(item["severity"] == "minor" for item in ordered)
    code_sets = {
        "layout_geometry": {"element_overlap", "element_overflow", "invalid_element_geometry", "section_height_out_of_bounds", "brand_overflow", "invalid_brand_geometry", "alignment_token_mismatch", "spacing_token_mismatch"},
        "typography": {"brand_font_token_mismatch", "typography_role_token_mismatch"},
        "brand_kit": {
            "brand_kit_identity_mismatch", "brand_color_token_mismatch", "brand_logo_missing",
            "brand_watermark_missing", "brand_logo_asset_integrity_mismatch", "brand_watermark_asset_integrity_mismatch",
        },
        "scene_flow": {"duplicate_frozen_section", "missing_planned_section", "unplanned_frozen_section", "section_order_mismatch", "final_spec_position", "missing_frozen_page_plan_identity", "page_plan_identity_mismatch", "missing_frozen_scene_flow_contract", "duplicate_scene_asset", "duplicate_scene_identity", "missing_planned_scene", "unexpected_frozen_scene", "scene_order_mismatch", "scene_identity_mismatch"},
        "contrast": {"contrast_not_evaluable", "contrast_ratio_below_contract"},
        "visual_hierarchy": {"renderer_token_mismatch", "layout_evidence_section_mismatch", "visual_hierarchy_token_mismatch"},
    }
    metric_dimensions = {
        "layout_geometry": ("renderer_evaluable", "geometry_evaluable"),
        "typography": ("renderer_evaluable", "typography_evaluable"),
        "brand_kit": ("renderer_evaluable", "brand_evaluable"),
        "scene_flow": ("renderer_evaluable", "scene_flow_evaluable", "pageplan_evaluable"),
        "contrast": ("renderer_evaluable", "contrast_evaluable"),
        "visual_hierarchy": ("renderer_evaluable", "typography_evaluable"),
    }
    def metric(metric_id: str, codes: set[str]) -> dict[str, Any]:
        if not all(completeness.get(dimension, False) for dimension in metric_dimensions[metric_id]):
            return {"metric_id": metric_id, "value": 0, "status": "needs_review"}
        if metric_id == "contrast" and dict(evidence.get("contrast") or {}).get("minimum_ratio") is None:
            return {"metric_id": metric_id, "value": 1, "status": "skipped_no_pinned_threshold"}
        has_issue = any(item["code"] in codes for item in ordered)
        return {"metric_id": metric_id, "value": 0 if has_issue else 1, "status": "failed" if has_issue else "passed"}
    domain = _domain_result({
        "domain_id": "layout_typography_brand_flow",
        "score": 0 if needs_review else max(0, 100 - 30 * len(critical) - 12 * major_count - 4 * minor_count),
        "status": "needs_review" if needs_review else "complete",
        "evaluator_version": LAYOUT_TYPOGRAPHY_BRAND_FLOW_EVALUATOR_VERSION,
        "findings": ordered, "critical_count": len(critical), "warning_count": len(ordered) - len(critical),
        "evidence_refs": [value for _, value in sorted({(_reference_identity(ref), str(ref.get("type") or "")): ref for ref in base_evidence}.items())],
        "evaluated_at": f"frozen:{page_ref['hash']}", "metric_source": "automatic",
        "human_rubric": {"status": "not_requested"},
        "submetrics": [metric(metric_id, codes) for metric_id, codes in code_sets.items()],
    }, report_payload=report_payload)
    return {"domain": domain, "critical_violations": _critical_violations_from_findings(critical)}


# TASK-12.7 stores only bounded, hash-pinned output identities.  Export bodies
# remain in their original files; a quality report never becomes an alternate
# HTML, screenshot, PNG, or ZIP store.
_PARITY_EVIDENCE_FIELDS = frozenset({
    "schema_version", "artifact_ref", "artifact_type", "channel", "format", "file_sha256",
    "page_ref", "preview_ref", "renderer_ref", "manifest_hash", "sections", "element_refs", "preview_dimensions", "asset_refs",
    "copy_refs", "layout_evidence_hash", "page_plan_ref", "brand_kit_ref", "preset",
    "transform_version", "evidence_hash",
})
_PARITY_SECTION_FIELDS = frozenset({"section_id", "sort_order", "visible", "height_px"})
_PARITY_ELEMENT_FIELDS = frozenset({"section_id", "element_id", "element_hash"})
_PARITY_ASSET_FIELDS = frozenset({"asset_id", "asset_content_hash"})
_PARITY_COPY_FIELDS = frozenset({"field", "text_hash"})
_PARITY_PRESET_FIELDS = frozenset({"key", "version", "width", "max_segment_height", "default_format"})
_PARITY_TYPED_REFERENCE_TYPES = {
    "artifact_ref": "ExportArtifact",
    "page_ref": "DetailPageVersion",
    "preview_ref": "frozen_preview",
    "renderer_ref": "frozen_renderer",
    "page_plan_ref": "PagePlanVersion",
    "brand_kit_ref": "BrandKitVersion",
}


def _parity_reference_identity(value: Any) -> tuple[str, str, str, str]:
    ref = dict(value or {}) if isinstance(value, Mapping) else {}
    return (
        str(ref.get("id") or ""), str(ref.get("version") or ""),
        str(ref.get("hash") or ""), str(ref.get("type") or ""),
    )


def _parity_finding(
    *, page_ref: Mapping[str, Any], code: str, severity: str, message: str,
    expected: Any, observed: Any, evidence_refs: Sequence[Mapping[str, Any]],
    artifact_ref: Mapping[str, Any] | None = None,
    additional_target_refs: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    targets = [dict(page_ref)]
    if artifact_ref is not None:
        targets.append(dict(artifact_ref))
    targets.extend(dict(item) for item in additional_target_refs)
    identity = {"code": code, "severity": severity, "targets": targets, "expected": expected, "observed": observed}
    return {
        "finding_id": f"lg12-channel-parity:{canonical_hash(identity)[:32]}",
        "domain": "channel_preview_export_parity", "severity": severity,
        "rule_id": f"channel_parity.{code}", "code": code, "message": message,
        "target_refs": targets, "evidence_refs": [dict(item) for item in evidence_refs],
        "expected": expected, "observed": observed,
        "remediation_hint": "Create a corrected frozen export from the same frozen DetailPageVersion; do not substitute mutable preview state.",
    }


def _parity_typed_reference_is_complete(value: Any, expected_type: str) -> bool:
    reference = dict(value or {}) if isinstance(value, Mapping) else {}
    return (
        set(reference) == {"id", "version", "hash", "type"}
        and str(reference.get("type") or "") == expected_type
        and bool(str(reference.get("id") or ""))
        and bool(str(reference.get("version") or ""))
        and bool(re.fullmatch(r"[0-9a-f]{64}", str(reference.get("hash") or "")))
    )


def _parity_evidence_completeness_errors(evidence: Mapping[str, Any]) -> list[str]:
    """Return evaluability gaps separately from sidecar tamper/shape errors."""

    missing: list[str] = []
    for name, expected_type in _PARITY_TYPED_REFERENCE_TYPES.items():
        if not _parity_typed_reference_is_complete(evidence.get(name), expected_type):
            missing.append(name)
    for name in ("file_sha256", "manifest_hash", "layout_evidence_hash", "evidence_hash"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get(name) or "")):
            missing.append(name)
    preset = dict(evidence.get("preset") or {}) if isinstance(evidence.get("preset"), Mapping) else {}
    if (
        set(preset) != _PARITY_PRESET_FIELDS
        or not str(preset.get("key") or "")
        or not str(preset.get("version") or "")
        or not isinstance(preset.get("width"), int)
        or not isinstance(preset.get("max_segment_height"), int)
        or not str(preset.get("default_format") or "")
    ):
        missing.append("preset")
    for name in ("channel", "artifact_type", "format", "transform_version"):
        if not str(evidence.get(name) or ""):
            missing.append(name)
    return missing


def _parity_preview_completeness_errors(preview: Mapping[str, Any]) -> list[str]:
    """The preview has no artifact/file fields, but its frozen identity is mandatory."""

    return [
        name
        for name in ("page_ref", "preview_ref", "renderer_ref", "page_plan_ref", "brand_kit_ref", "layout_evidence_hash", "manifest_hash")
        if (
            not _parity_typed_reference_is_complete(preview.get(name), _PARITY_TYPED_REFERENCE_TYPES[name])
            if name in _PARITY_TYPED_REFERENCE_TYPES
            else not re.fullmatch(r"[0-9a-f]{64}", str(preview.get(name) or ""))
        )
    ]


def _validate_parity_evidence_shape(evidence: Mapping[str, Any]) -> None:
    """Reject raw or copied export content even when its hash is internally valid."""

    if not set(evidence) <= _PARITY_EVIDENCE_FIELDS:
        raise QualityAssessmentContractError("Frozen export parity evidence has unsupported fields.")
    if evidence.get("schema_version") != LG12_FROZEN_EXPORT_PARITY_EVIDENCE_SCHEMA_VERSION:
        raise QualityAssessmentContractError("Frozen export parity evidence schema is unsupported.")
    for name, expected_type in _PARITY_TYPED_REFERENCE_TYPES.items():
        if name not in evidence:
            continue
        ref = dict(evidence.get(name) or {}) if isinstance(evidence.get(name), Mapping) else {}
        if set(ref) != {"id", "version", "hash", "type"}:
            raise QualityAssessmentContractError("Frozen export parity evidence has an invalid typed reference.")
        if str(ref.get("type") or "") != expected_type:
            raise QualityAssessmentContractError("Frozen export parity evidence typed reference has an invalid type.")
        if str(ref.get("hash") or "") and not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("hash") or "")):
            raise QualityAssessmentContractError("Frozen export parity evidence reference hash is invalid.")
    if "sections" in evidence and (not isinstance(evidence.get("sections"), list) or len(evidence["sections"]) > 64):
        raise QualityAssessmentContractError("Frozen export parity evidence sections are invalid.")
    for item in list(evidence.get("sections") or []):
        if not isinstance(item, Mapping) or set(item) != _PARITY_SECTION_FIELDS or not str(item.get("section_id") or "") or not isinstance(item.get("sort_order"), int) or not isinstance(item.get("visible"), bool) or not isinstance(item.get("height_px"), int) or item["height_px"] < 0:
            raise QualityAssessmentContractError("Frozen export parity evidence section is invalid.")
    if "element_refs" in evidence and (not isinstance(evidence.get("element_refs"), list) or len(evidence["element_refs"]) > 256):
        raise QualityAssessmentContractError("Frozen export parity evidence element references are invalid.")
    for item in list(evidence.get("element_refs") or []):
        if (
            not isinstance(item, Mapping) or set(item) != _PARITY_ELEMENT_FIELDS
            or not str(item.get("section_id") or "") or not str(item.get("element_id") or "")
            or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("element_hash") or ""))
        ):
            raise QualityAssessmentContractError("Frozen export parity evidence element reference is invalid.")
    dimensions = dict(evidence.get("preview_dimensions") or {}) if isinstance(evidence.get("preview_dimensions"), Mapping) else {}
    if "preview_dimensions" in evidence and (set(dimensions) != {"width", "height"} or any(not isinstance(dimensions.get(key), int) or dimensions[key] < 0 for key in dimensions)):
        raise QualityAssessmentContractError("Frozen export parity evidence preview dimensions are invalid.")
    if "asset_refs" in evidence and (not isinstance(evidence.get("asset_refs"), list) or len(evidence["asset_refs"]) > 32):
        raise QualityAssessmentContractError("Frozen export parity evidence asset references are invalid.")
    for item in list(evidence.get("asset_refs") or []):
        if not isinstance(item, Mapping) or set(item) != _PARITY_ASSET_FIELDS or not str(item.get("asset_id") or "") or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("asset_content_hash") or "")):
            raise QualityAssessmentContractError("Frozen export parity evidence asset reference is invalid.")
    if "copy_refs" in evidence and (not isinstance(evidence.get("copy_refs"), list) or len(evidence["copy_refs"]) > 128):
        raise QualityAssessmentContractError("Frozen export parity evidence copy references are invalid.")
    for item in list(evidence.get("copy_refs") or []):
        if not isinstance(item, Mapping) or set(item) != _PARITY_COPY_FIELDS or not str(item.get("field") or "") or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("text_hash") or "")):
            raise QualityAssessmentContractError("Frozen export parity evidence copy reference is invalid.")
    preset = dict(evidence.get("preset") or {}) if isinstance(evidence.get("preset"), Mapping) else {}
    if "preset" in evidence and (set(preset) != _PARITY_PRESET_FIELDS or not isinstance(preset.get("width"), int) or not isinstance(preset.get("max_segment_height"), int)):
        raise QualityAssessmentContractError("Frozen export parity evidence preset is invalid.")
    for key in ("file_sha256", "manifest_hash", "evidence_hash"):
        if key in evidence and str(evidence.get(key) or "") and not re.fullmatch(r"[0-9a-f]{64}", str(evidence[key])):
            raise QualityAssessmentContractError("Frozen export parity evidence hash is invalid.")
    if evidence.get("layout_evidence_hash") not in (None, "") and not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("layout_evidence_hash") or "")):
        raise QualityAssessmentContractError("Frozen export parity layout evidence hash is invalid.")


def _parity_export_ref(artifact: ExportArtifact, digest: str) -> dict[str, Any]:
    return _qa_typed_reference({"id": str(artifact.id), "version": 1, "hash": digest}, "ExportArtifact")


def _channel_scoped_frozen_export_artifacts(*, db: Session, project_id: str, page_id: str, channel: str) -> list[ExportArtifact]:
    """Discover only artifacts whose persisted token is scoped to ``channel``.

    Explicit caller selections are checked separately below.  Discovery must
    not turn a valid frozen output for another supported channel into an
    error for the requested channel.
    """

    return (
        db.query(ExportArtifact)
        .filter(
            ExportArtifact.project_id == project_id,
            ExportArtifact.version_id == page_id,
            or_(
                ExportArtifact.artifact_type.like(f"channel_long:{channel}:%"),
                ExportArtifact.artifact_type.like(f"channel_package:{channel}:%"),
                ExportArtifact.artifact_type == f"lg10_copyable_html:{channel}",
                ExportArtifact.artifact_type == f"lg10_standalone_package:{channel}",
            ),
        )
        .order_by(ExportArtifact.created_at.asc(), ExportArtifact.id.asc())
        .all()
    )


def _channel_package_contract_error(*, file_path: str, preset: Any) -> str | None:
    """Validate the existing channel-export ZIP manifest without unpacking it into QA output."""

    try:
        with zipfile.ZipFile(file_path) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if not isinstance(manifest, Mapping):
                return "manifest"
            package_preset = dict(manifest.get("preset") or {})
            required_preset = {
                "key": preset.key, "version": preset.version, "width": preset.width,
                "max_segment_height": preset.max_segment_height, "default_format": preset.default_format,
            }
            if any(package_preset.get(key) != value for key, value in required_preset.items()):
                return "preset"
            # The ZIP token describes the package.  Its manifest must instead
            # pin the image encoding already defined by the production preset.
            normalized_format = "jpg" if str(preset.default_format).lower() == "jpeg" else str(preset.default_format).lower()
            manifest_format = "jpg" if str(manifest.get("format") or "").lower() == "jpeg" else str(manifest.get("format") or "").lower()
            if manifest_format != normalized_format:
                return "format"
            master_name = str(manifest.get("master") or "")
            master_bytes = archive.read(master_name)
            if hashlib.sha256(master_bytes).hexdigest() != str(manifest.get("master_sha256") or ""):
                return "master_hash"
            with Image.open(BytesIO(master_bytes)) as master:
                if master.width != preset.width or ("jpg" if str(master.format or "").upper() == "JPEG" else str(master.format or "").lower()) != normalized_format:
                    return "master_image"
                master_height = master.height
            parts = list(manifest.get("parts") or [])
            if not parts:
                return "parts"
            cursor = 0
            for part in parts:
                if not isinstance(part, Mapping):
                    return "parts"
                top, bottom = int(part.get("top")), int(part.get("bottom"))
                if top != cursor or bottom <= top or bottom - top > preset.max_segment_height:
                    return "split_bounds"
                payload = archive.read(str(part.get("filename") or ""))
                with Image.open(BytesIO(payload)) as image:
                    actual_format = "jpg" if str(image.format or "").upper() == "JPEG" else str(image.format or "").lower()
                    if image.width != preset.width or image.height != bottom - top or actual_format != normalized_format:
                        return "split_image"
                cursor = bottom
            if cursor != master_height:
                return "split_coverage"
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, UnidentifiedImageError):
        return "manifest"
    return None


def evaluate_channel_preview_export_parity_domain(
    db: Session,
    *,
    report_payload: Mapping[str, Any],
    channel: str,
    export_artifact_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Evaluate pre-existing frozen preview/export artifacts without rendering.

    The function is intentionally read-only: it does not call an export worker,
    a provider, or a browser.  Missing frozen evidence is evaluability debt;
    tamper and cross-channel identity violations are fail-closed or critical.
    """

    report = normalize_quality_assessment_report(report_payload)
    if channel not in supported_channel_keys() or channel not in report["target_channels"]:
        raise QualityAssessmentContractError("Channel parity requires one explicit report target channel.")
    run = _require_run(db, report)
    page = _require_target(db, report)
    _require_lineage(db, run=run, report=report)
    source = db.query(ProductSourceSnapshotVersion).filter_by(id=report["input_lineage"]["source_snapshot_ref"]["id"]).one()
    truth = db.query(ProductTruthVersion).filter_by(id=report["input_lineage"]["truth_ref"]["id"]).one()
    confirmation = db.query(SellerConfirmationVersion).filter_by(id=report["input_lineage"]["confirmation_ref"]["id"]).one()
    master = db.query(CommerceCreativeMasterVersion).filter_by(id=report["input_lineage"]["master_ref"]["id"]).one()
    snapshot, canonical = _frozen_assembly_input(page)
    _require_frozen_page_master_binding(
        page=page, snapshot=snapshot, run=run, source=source, truth=truth,
        confirmation=confirmation, master=master,
    )
    # The exact Master/manifest/Asset/storage chain is input integrity, not a
    # second image-quality score.  Reuse the TASK-12.4 helper rather than
    # trusting the page's local manifest label.
    _image_asset_contexts(
        db, run=run, page=page, snapshot=snapshot, canonical=canonical,
        source=source, confirmation=confirmation, master=master,
    )
    if channel not in list(master.target_channels or []):
        raise QualityAssessmentContractError("Channel parity channel is not pinned by the persisted Commerce Creative Master.")
    page_ref = _page_snapshot_reference(page)
    try:
        preview = frozen_preview_parity_evidence(page, channel=channel)
    except FrozenExportSnapshotError as exc:
        raise QualityAssessmentContractError("Frozen preview identity is invalid.") from exc
    preset = get_channel_preset(channel)
    base_evidence = [
        _qa_typed_reference(preview["preview_ref"], "frozen_preview"),
        _qa_typed_reference(preview["renderer_ref"], "frozen_renderer"),
    ]
    findings: list[dict[str, Any]] = []
    needs_review = False
    # Equality between two empty sidecars is not frozen evidence.  Treat
    # absence as evaluability debt before any preview/export comparison.
    for missing in _parity_preview_completeness_errors(preview):
        needs_review = True
        findings.append(_parity_finding(
            page_ref=page_ref, code=f"missing_frozen_preview_{missing}", severity="major",
            message="Frozen preview lacks mandatory parity evidence.", expected=missing,
            observed="missing", evidence_refs=base_evidence,
        ))
    persisted_plan_ref = _layout_artifact_reference(master.page_plan_artifact_ref_json, "PagePlanVersion")
    brand_kit = db.query(BrandKitVersion).filter_by(id=master.brand_kit_version_id, workspace_id=run.workspace_id).one_or_none()
    try:
        validate_lg12i_brand_kit_scope(brand_kit, workspace_id=run.workspace_id, project_id=run.project_id)
    except IntakeVersionContractError as exc:
        raise QualityAssessmentContractError("Frozen Master Brand Kit scope is invalid for channel parity.") from exc
    if (
        persisted_plan_ref is None
        or brand_kit is None
        or int(brand_kit.version) != int(master.brand_kit_version or 0)
        or str(brand_kit.content_hash) != str(master.brand_kit_hash)
    ):
        raise QualityAssessmentContractError("Frozen Master PagePlan or Brand Kit reference is not persisted exactly.")
    persisted_brand_ref = _qa_typed_reference(
        {"id": brand_kit.id, "version": brand_kit.version, "hash": brand_kit.content_hash}, "BrandKitVersion",
    )
    if not _parity_preview_completeness_errors(preview):
        if _parity_reference_identity(preview["page_plan_ref"]) != _parity_reference_identity(persisted_plan_ref):
            raise QualityAssessmentContractError("Frozen preview PagePlan reference differs from the persisted Master.")
        if _parity_reference_identity(preview["brand_kit_ref"]) != _parity_reference_identity(persisted_brand_ref):
            # A preview that disagrees with both the frozen page and its
            # Master is tampered/incomplete evidence and remains fail-closed.
            # A preview that exactly mirrors the page's own pinned (but
            # Master-divergent) Brand Kit is a deterministic style defect:
            # keep it as a structured critical so TASK-12.9 can invoke the
            # existing pinned Brand Kit reassembly instead of treating a
            # repairable frozen style version as a storage-integrity error.
            frozen_brand = dict(canonical.get("brand_kit_ref") or {})
            frozen_brand_ref = _qa_typed_reference(
                {
                    "id": str(frozen_brand.get("brand_kit_version_id") or ""),
                    "version": int(frozen_brand.get("brand_kit_version") or 1),
                    "hash": str(frozen_brand.get("brand_kit_hash") or ""),
                },
                "BrandKitVersion",
            )
            if _parity_reference_identity(preview["brand_kit_ref"]) != _parity_reference_identity(frozen_brand_ref):
                raise QualityAssessmentContractError("Frozen preview Brand Kit reference differs from its frozen page and persisted Master.")
            findings.append(_parity_finding(
                page_ref=page_ref, code="preview_brand_kit_ref_mismatch", severity="critical",
                message="Frozen preview retains a Brand Kit that differs from the Master-pinned Brand Kit.",
                expected=persisted_brand_ref, observed=frozen_brand_ref,
                evidence_refs=[*base_evidence, persisted_brand_ref],
                additional_target_refs=[persisted_brand_ref],
            ))
    safety = dict(preview.get("canvas_safety") or {})
    if not safety.get("safe", False):
        for issue in _as_mappings(safety.get("issues")):
            issue_targets: list[dict[str, Any]] = []
            section_id = str(issue.get("section_id") or "")
            element_id = str(issue.get("element_id") or "")
            if section_id:
                issue_targets.append(_qa_typed_reference(
                    {"id": section_id, "version": 1, "hash": canonical_hash({"section_id": section_id})}, "section",
                ))
            if element_id:
                issue_targets.append(_qa_typed_reference(
                    {"id": element_id, "version": 1, "hash": canonical_hash({"element_id": element_id})}, "element",
                ))
            findings.append(_parity_finding(
                page_ref=page_ref, code=f"unsafe_channel_{str(issue.get('code') or 'output')}", severity="critical",
                message="Frozen preview/export is unsafe for the selected explicit channel.",
                expected="safe frozen LG-11 channel contract", observed=str(issue.get("reason") or issue.get("code") or "unsafe"),
                evidence_refs=base_evidence, additional_target_refs=issue_targets,
            ))

    query = db.query(ExportArtifact).filter_by(project_id=run.project_id, version_id=page.id)
    if export_artifact_ids is not None:
        ids = [str(item) for item in export_artifact_ids]
        if not ids or len(set(ids)) != len(ids):
            raise QualityAssessmentContractError("Channel parity requires unique explicit export artifact identities.")
        artifacts = query.filter(ExportArtifact.id.in_(ids)).all()
        if len(artifacts) != len(ids):
            raise QualityAssessmentContractError("Channel parity export artifact cannot cross a project/page boundary.")
    else:
        artifacts = _channel_scoped_frozen_export_artifacts(
            db=db, project_id=run.project_id, page_id=page.id, channel=channel,
        )
    selected: list[ExportArtifact] = []
    for artifact in artifacts:
        parsed = parse_lg11_export_artifact_token(artifact.artifact_type)
        if parsed is None:
            if str(artifact.artifact_type).startswith(("channel_long:", "channel_package:", "lg10_copyable_html:", "lg10_standalone_package:")):
                findings.append(_parity_finding(
                    page_ref=page_ref, code="malformed_export_artifact_token", severity="critical",
                    message="Frozen export artifact token does not carry a valid channel and format.",
                    expected="channel-bound artifact token", observed="malformed", evidence_refs=base_evidence,
                ))
            continue
        if parsed["channel"] != channel:
            findings.append(_parity_finding(
                page_ref=page_ref, code="cross_channel_export_artifact", severity="critical",
                message="Frozen export artifact channel differs from the selected preview channel.",
                expected=channel, observed=parsed["channel"], evidence_refs=base_evidence,
            ))
            continue
        selected.append(artifact)
    if not selected:
        needs_review = True
        findings.append(_parity_finding(
            page_ref=page_ref, code="missing_frozen_export_artifact", severity="major",
            message="No channel-bound frozen export artifact is available for parity evaluation.",
            expected=channel, observed="missing", evidence_refs=base_evidence,
        ))

    expected_sections = list(preview["sections"])
    expected_elements = list(preview["element_refs"])
    expected_assets = list(preview["asset_refs"])
    expected_copy = list(preview["copy_refs"])
    expected_page = _parity_reference_identity(preview["page_ref"])
    expected_preview = _parity_reference_identity(preview["preview_ref"])
    expected_renderer = _parity_reference_identity(preview["renderer_ref"])
    expected_preset = {"key": preset.key, "version": preset.version, "width": preset.width, "max_segment_height": preset.max_segment_height, "default_format": preset.default_format}
    for artifact in selected:
        parsed = parse_lg11_export_artifact_token(artifact.artifact_type)
        assert parsed is not None
        try:
            evidence = load_lg12_frozen_export_parity_evidence(artifact=artifact)
        except FrozenExportSnapshotError as exc:
            raise QualityAssessmentContractError("Frozen export artifact parity evidence is invalid.") from exc
        if evidence is None:
            needs_review = True
            findings.append(_parity_finding(
                page_ref=page_ref, code="missing_frozen_export_evidence", severity="major",
                message="Frozen export artifact is missing bounded parity evidence.", expected="hash-pinned export evidence", observed="missing",
                evidence_refs=base_evidence,
            ))
            continue
        _validate_parity_evidence_shape(evidence)
        missing_evidence = _parity_evidence_completeness_errors(evidence)
        if missing_evidence:
            needs_review = True
            for missing in sorted(set(missing_evidence)):
                findings.append(_parity_finding(
                    page_ref=page_ref, code=f"missing_frozen_export_{missing}", severity="major",
                    message="Frozen export lacks mandatory parity evidence.", expected=missing,
                    observed="missing", evidence_refs=base_evidence,
                ))
            continue
        actual_hash = image_sha256(artifact.file_path) if artifact.file_path and Path(artifact.file_path).is_file() else ""
        if actual_hash != str(evidence.get("file_sha256") or ""):
            raise QualityAssessmentContractError("Frozen export artifact bytes do not match its parity evidence hash.")
        artifact_ref = _parity_export_ref(artifact, actual_hash)
        evidence_refs = [*base_evidence, artifact_ref]
        comparisons = {
            "artifact_ref": (_parity_reference_identity(evidence.get("artifact_ref")), _parity_reference_identity(artifact_ref)),
            "page_ref": (_parity_reference_identity(evidence.get("page_ref")), expected_page),
            "preview_ref": (_parity_reference_identity(evidence.get("preview_ref")), expected_preview),
            "renderer_ref": (_parity_reference_identity(evidence.get("renderer_ref")), expected_renderer),
            "manifest_hash": (str(evidence.get("manifest_hash") or ""), str(preview["manifest_hash"])),
            "sections": (list(evidence.get("sections") or []), expected_sections),
            "element_refs": (list(evidence.get("element_refs") or []), expected_elements),
            "preview_dimensions": (dict(evidence.get("preview_dimensions") or {}), dict(preview.get("preview_dimensions") or {})),
            "asset_refs": (list(evidence.get("asset_refs") or []), expected_assets),
            "copy_refs": (list(evidence.get("copy_refs") or []), expected_copy),
            "layout_evidence_hash": (evidence.get("layout_evidence_hash"), preview.get("layout_evidence_hash")),
            "page_plan_ref": (dict(evidence.get("page_plan_ref") or {}), dict(preview.get("page_plan_ref") or {})),
            "brand_kit_ref": (dict(evidence.get("brand_kit_ref") or {}), dict(preview.get("brand_kit_ref") or {})),
            "preset": (dict(evidence.get("preset") or {}), expected_preset),
        }
        for name, (observed, expected) in comparisons.items():
            if observed != expected:
                findings.append(_parity_finding(
                    page_ref=page_ref, artifact_ref=artifact_ref, code=f"preview_export_{name}_mismatch", severity="critical",
                    message="Frozen preview and export do not share the same immutable parity identity.",
                    expected=name, observed="mismatch", evidence_refs=evidence_refs,
                ))
            if _parity_reference_identity(evidence.get("page_plan_ref")) != _parity_reference_identity(persisted_plan_ref):
                raise QualityAssessmentContractError("Frozen export PagePlan reference differs from the persisted Master.")
            if _parity_reference_identity(evidence.get("brand_kit_ref")) != _parity_reference_identity(persisted_brand_ref):
                # The coherent page/preview/export style mismatch above is a
                # repairable frozen style defect.  Any disagreement within
                # that trio remains a fail-closed parity-integrity failure.
                if _parity_reference_identity(evidence.get("brand_kit_ref")) != _parity_reference_identity(preview["brand_kit_ref"]):
                    raise QualityAssessmentContractError("Frozen export Brand Kit reference differs from the frozen preview and persisted Master.")
        if str(evidence.get("channel") or "") != channel or str(evidence.get("artifact_type") or "") != parsed["artifact_type"] or str(evidence.get("format") or "") != parsed["format"]:
            findings.append(_parity_finding(
                page_ref=page_ref, artifact_ref=artifact_ref, code="export_channel_binding_mismatch", severity="critical",
                message="Frozen export evidence channel/type/format does not match its persisted artifact token.",
                expected=f"{channel}:{parsed['artifact_type']}:{parsed['format']}", observed="mismatch", evidence_refs=evidence_refs,
            ))
        expected_transform = LG12_CHANNEL_TRANSFORM_VERSION if parsed["artifact_type"] in {"channel_long", "channel_package"} else LG12_STANDALONE_TRANSFORM_VERSION
        if str(evidence.get("transform_version") or "") != expected_transform:
            findings.append(_parity_finding(
                page_ref=page_ref, artifact_ref=artifact_ref, code="unauthorized_channel_transform", severity="critical",
                message="Export carries a transform not pinned by the production channel contract.",
                expected=expected_transform, observed=str(evidence.get("transform_version") or ""), evidence_refs=evidence_refs,
            ))
        try:
            if parsed["artifact_type"] == "channel_long":
                with Image.open(artifact.file_path) as image:
                    actual_format = "jpg" if str(image.format or "").upper() == "JPEG" else str(image.format or "").lower()
                    if image.width != preset.width or actual_format not in {"jpg" if parsed["format"] == "jpeg" else parsed["format"]}:
                        findings.append(_parity_finding(
                            page_ref=page_ref, artifact_ref=artifact_ref, code="channel_image_contract_mismatch", severity="critical",
                            message="Frozen channel image dimensions or format violate the pinned production preset.",
                            expected=f"{preset.width}px/{parsed['format']}", observed=f"{image.width}px/{actual_format}", evidence_refs=evidence_refs,
                        ))
            elif parsed["artifact_type"] == "channel_package":
                package_error = _channel_package_contract_error(
                    file_path=artifact.file_path, preset=preset,
                )
                if package_error:
                    findings.append(_parity_finding(
                        page_ref=page_ref, artifact_ref=artifact_ref, code="channel_package_contract_mismatch", severity="critical",
                        message="Frozen channel package violates its pinned manifest, format, or split contract.",
                        expected="channel package manifest/split contract", observed=package_error, evidence_refs=evidence_refs,
                    ))
            elif parsed["artifact_type"] == "lg10_standalone_package" and not zipfile.is_zipfile(artifact.file_path):
                findings.append(_parity_finding(
                    page_ref=page_ref, artifact_ref=artifact_ref, code="channel_package_format_mismatch", severity="critical",
                    message="Frozen package artifact is not a ZIP file.", expected="zip", observed="invalid", evidence_refs=evidence_refs,
                ))
        except (OSError, UnidentifiedImageError) as exc:
            raise QualityAssessmentContractError("Frozen channel export cannot be decoded for its pinned format contract.") from exc

    deduped = {item["finding_id"]: item for item in findings}
    ordered = [deduped[key] for key in sorted(deduped)]
    critical = [item for item in ordered if item["severity"] == "critical"]
    metrics = {
        "channel_binding": {"cross_channel_export_artifact", "malformed_export_artifact_token", "export_channel_binding_mismatch", "preview_export_artifact_ref_mismatch"},
        "preview_identity": {"preview_export_page_ref_mismatch", "preview_export_renderer_ref_mismatch", "preview_export_layout_evidence_hash_mismatch", "preview_export_page_plan_ref_mismatch", "preview_export_brand_kit_ref_mismatch", "preview_export_preview_dimensions_mismatch"},
        "export_identity": {"missing_frozen_export_artifact", "missing_frozen_export_evidence", "channel_image_contract_mismatch", "channel_package_format_mismatch", "channel_package_contract_mismatch", "preview_export_preset_mismatch"},
        "preview_export_parity": {"preview_export_manifest_hash_mismatch", "preview_export_sections_mismatch", "preview_export_element_refs_mismatch", "preview_export_asset_refs_mismatch", "preview_export_copy_refs_mismatch"},
        "channel_contract": {"unauthorized_channel_transform"},
    }
    submetrics = []
    for metric_id, codes in metrics.items():
        if needs_review and metric_id in {"preview_identity", "export_identity", "preview_export_parity"}:
            submetrics.append({"metric_id": metric_id, "value": 0, "status": "needs_review"})
        else:
            has_issue = any(
                item["code"] in codes
                or (metric_id == "channel_contract" and str(item["code"]).startswith("unsafe_channel_"))
                for item in ordered
            )
            submetrics.append({"metric_id": metric_id, "value": 0 if has_issue else 1, "status": "failed" if has_issue else "passed"})
    domain = _domain_result({
        "domain_id": "channel_preview_export_parity", "score": 0 if needs_review else max(0, 100 - 30 * len(critical)),
        "status": "needs_review" if needs_review else "complete",
        "evaluator_version": CHANNEL_PREVIEW_EXPORT_PARITY_EVALUATOR_VERSION,
        "findings": ordered, "critical_count": len(critical), "warning_count": len(ordered) - len(critical),
        "evidence_refs": sorted(base_evidence, key=lambda value: _reference_identity(value)),
        "evaluated_at": f"frozen:{page_ref['hash']}:{channel}", "metric_source": "automatic",
        "human_rubric": {"status": "not_requested"}, "submetrics": submetrics,
    }, report_payload=report_payload)
    return {"domain": domain, "critical_violations": _critical_violations_from_findings(critical)}


def evaluate_factual_rights_policy_domain(db: Session, *, report_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one frozen page's facts, rights, and policy boundaries.

    This deliberately returns only a TASK-12.2 *domain* result plus its
    structured critical violations.  Aggregation, verdicts, graph routing,
    rework, and persistence belong to later LG-12 tasks.
    """

    report = normalize_quality_assessment_report(report_payload)
    run = _require_run(db, report)
    page = _require_target(db, report)
    _require_lineage(db, run=run, report=report)
    source = db.query(ProductSourceSnapshotVersion).filter_by(id=report["input_lineage"]["source_snapshot_ref"]["id"]).one()
    truth = db.query(ProductTruthVersion).filter_by(id=report["input_lineage"]["truth_ref"]["id"]).one()
    confirmation = db.query(SellerConfirmationVersion).filter_by(id=report["input_lineage"]["confirmation_ref"]["id"]).one()
    master = db.query(CommerceCreativeMasterVersion).filter_by(id=report["input_lineage"]["master_ref"]["id"]).one()
    snapshot, canonical = _frozen_assembly_input(page)
    _require_frozen_page_master_binding(
        page=page, snapshot=snapshot, run=run, source=source, truth=truth,
        confirmation=confirmation, master=master,
    )
    master_assets = _require_master_asset_manifest_parity(
        db, source=source, confirmation=confirmation, master=master,
    )
    page_ref = _page_snapshot_reference(page)
    lineage_evidence = [
        _qa_row_reference(source, "ProductSourceSnapshotVersion"),
        _qa_row_reference(truth, "ProductTruthVersion"),
        _qa_row_reference(confirmation, "SellerConfirmationVersion"),
        _qa_row_reference(master, "CommerceCreativeMasterVersion"),
    ]

    confirmed = {str(item.get("id")): item for item in _as_mappings(confirmation.confirmed_fact_refs_json)}
    rejected = {str(item.get("id")): item for item in _as_mappings(confirmation.rejected_fact_refs_json)}
    unknown = {str(item.get("id")): item for item in _as_mappings(confirmation.unknown_fact_refs_json)}
    truth_normalization = dict(truth.normalization_json or {})
    conflicts = {
        str(dict(item).get("reference", {}).get("id") or dict(item).get("fact_id") or ""): dict(item)
        for item in _as_mappings(truth_normalization.get("conflict_facts"))
    }
    prohibited = {
        str(dict(item).get("reference", {}).get("id") or dict(item).get("fact_id") or dict(item).get("inference_id") or ""): dict(item)
        for item in _as_mappings(truth_normalization.get("prohibited_inferences"))
    }
    findings: list[dict[str, Any]] = []

    for index, section in enumerate(_frozen_sections(snapshot, canonical)):
        section_id = str(section.get("section_id") or section.get("id") or f"section:{index}")
        section_ref = _qa_typed_reference(
            {"id": section_id, "version": 1, "hash": canonical_hash(section)}, "section",
        )
        fact_ids, copies = _section_copy(section)
        copy_text = " ".join(copies)
        copy_ref = _qa_typed_reference(
            {"id": f"copy:{section_id}", "version": 1, "hash": canonical_hash({"section_id": section_id, "text": copy_text})}, "copy",
        )
        targets = [page_ref, section_ref, copy_ref]
        for claim in _section_factual_claims(section, section_id=section_id, copy_text=copy_text):
            claim_targets = [*targets, claim["reference"]]
            candidate_ids = sorted(set(claim["fact_ids"]))
            claim_evidence = [*lineage_evidence, *[
                _qa_typed_reference(item, str(item.get("artifact_key") or "evidence"))
                for item in claim["evidence_refs"]
            ]]
            state_error: tuple[str, str, str] | None = None
            supported = False
            numeric_mismatch = False
            for fact_id in candidate_ids:
                fact_ref = confirmed.get(fact_id) or rejected.get(fact_id) or unknown.get(fact_id) or conflicts.get(fact_id) or prohibited.get(fact_id)
                if isinstance(fact_ref, Mapping):
                    claim_evidence.extend(
                        _qa_typed_reference(item, str(item.get("artifact_key") or "evidence"))
                        for item in _as_mappings(fact_ref.get("evidence_refs")) + _as_mappings(fact_ref.get("source_refs"))
                    )
                if fact_id in rejected:
                    state_error = ("fact.rejected_used", "rejected_fact_used", "A seller-rejected fact is presented in frozen copy.")
                    continue
                if fact_id in unknown:
                    state_error = ("fact.unknown_promoted", "unknown_fact_used", "An unknown fact is presented as confirmed copy.")
                    continue
                if fact_id in conflicts:
                    state_error = ("fact.conflict_promoted", "unresolved_conflict_used", "An unresolved fact conflict is presented as confirmed copy.")
                    continue
                if fact_id in prohibited:
                    state_error = ("policy.prohibited_inference", "prohibited_inference_used", "A prohibited inference is used in frozen copy.")
                    continue
                confirmed_item = confirmed.get(fact_id)
                if confirmed_item is None:
                    continue
                if _confirmed_fact_supports_claim(confirmed_item, claim):
                    supported = True
                    break
                if _measurement(
                    str(confirmed_item.get("normalized_value") or ""),
                    str(confirmed_item.get("unit")) if confirmed_item.get("unit") is not None else None,
                ) is not None and claim["claim_type"] == "numeric":
                    numeric_mismatch = True
            if supported:
                continue
            if state_error is not None:
                rule_id, code, message = state_error
            elif numeric_mismatch:
                rule_id, code, message = (
                    "fact.numeric_unit_parity", "numeric_unit_mismatch",
                    "Frozen copy changes a confirmed numeric fact or unit.",
                )
            else:
                rule_id, code, message = (
                    "fact.approved_provenance", f"unapproved_{claim['claim_type']}_claim",
                    "Frozen copy contains a factual claim without matching confirmed provenance.",
                )
            findings.append(_factual_finding(
                rule_id=rule_id, code=code, severity="critical", target_refs=claim_targets,
                evidence_refs=claim_evidence,
                expected="matching seller-confirmed fact provenance",
                observed=claim["text"],
                message=message, remediation="Attach the matching confirmed fact or remove the factual claim.",
            ))

        if copy_text and _CERTIFICATION_RE.search(copy_text) and not any("cert" in str(item.get("field_id") or "").lower() for item in confirmed.values()):
            findings.append(_factual_finding(
                rule_id="policy.unsupported_certification", code="unsupported_certification", severity="critical", target_refs=targets,
                evidence_refs=lineage_evidence, expected="confirmed certification evidence", observed="certification claim",
                message="Frozen copy makes a certification claim without a confirmed fact.", remediation="Remove the claim or confirm its evidence.",
            ))
        if copy_text and _MEDICAL_RE.search(copy_text) and not any("health" in str(item.get("field_id") or "").lower() for item in confirmed.values()):
            findings.append(_factual_finding(
                rule_id="policy.unsupported_health", code="unsupported_medical_health_claim", severity="critical", target_refs=targets,
                evidence_refs=lineage_evidence, expected="confirmed health/efficacy evidence", observed="medical or health claim",
                message="Frozen copy makes an unsupported medical or health claim.", remediation="Remove the claim unless confirmed evidence is available.",
            ))
        has_confirmed_price_comparison = any(
            any(token in str(item.get(key) or "").lower() for token in ("price_advantage", "price_comparison"))
            for item in confirmed.values() for key in ("fact_id", "field_id")
        )
        if copy_text and _PRICE_ADVANTAGE_RE.search(copy_text) and not has_confirmed_price_comparison:
            findings.append(_factual_finding(
                rule_id="policy.price_advantage", code="unsupported_price_advantage", severity="critical", target_refs=targets,
                evidence_refs=lineage_evidence, expected="supported price-comparison evidence", observed="price advantage claim",
                message="Frozen copy claims a price advantage without allowed evidence.", remediation="Remove the comparison or keep only source-backed price observation.",
            ))
        if copy_text and _CHINESE_COPY_RE.search(copy_text):
            findings.append(_factual_finding(
                rule_id="policy.foreign_copy_signal", code="unreviewed_chinese_copy", severity="critical", target_refs=targets,
                evidence_refs=lineage_evidence, expected="reviewed Korean product copy", observed="Chinese-language copy signal",
                message="Frozen copy contains an unreviewed Chinese-language signal.", remediation="Replace it with reviewed product copy.",
            ))
        for item in prohibited.values():
            claim = str(item.get("attempted_claim") or item.get("value") or "").strip()
            if claim and claim in copy_text:
                findings.append(_factual_finding(
                    rule_id="policy.prohibited_inference", code="prohibited_inference_used", severity="critical", target_refs=targets,
                    evidence_refs=lineage_evidence, expected="prohibited inferences excluded", observed=item.get("inference_type") or "prohibited inference",
                    message="Frozen copy repeats a prohibited source inference.", remediation="Remove the unsupported inference.",
                ))

    manifest = dict(canonical.get("approved_asset_manifest") or {})
    manifest_assets = {str(item.get("asset_id") or ""): dict(item) for item in _as_mappings(manifest.get("assets"))}
    used_assets: dict[str, dict[str, Any]] = {}
    for section in _frozen_sections(snapshot, canonical):
        for asset_ref in _section_asset_references(section):
            used_assets[asset_ref["asset_id"]] = asset_ref
    for asset_id, used_ref in sorted(used_assets.items()):
        entry = manifest_assets.get(asset_id)
        asset_target = _qa_typed_reference(
            {"id": asset_id, "version": 1, "hash": str(used_ref.get("asset_content_hash") or canonical_hash({"asset": asset_id}))}, "asset",
        )
        if entry is None:
            findings.append(_factual_finding(
                rule_id="rights.manifest_membership", code="asset_missing_approved_manifest", severity="critical", target_refs=[page_ref, asset_target],
                evidence_refs=lineage_evidence, expected="asset present in approved manifest", observed=asset_id,
                message="A frozen page asset is absent from the approved manifest.", remediation="Reassemble from an approved asset manifest.",
            )); continue
        frozen_hash = str(entry.get("asset_content_hash") or "")
        if used_ref.get("asset_content_hash") and str(used_ref["asset_content_hash"]) != frozen_hash:
            findings.append(_factual_finding(
                rule_id="rights.manifest_asset_parity", code="page_asset_manifest_mismatch", severity="critical", target_refs=[page_ref, asset_target],
                evidence_refs=lineage_evidence, expected=frozen_hash, observed=str(used_ref["asset_content_hash"]),
                message="Frozen page asset hash differs from its manifest identity.", remediation="Use the exact approved manifest asset.",
            )); continue
        asset = db.query(Asset).filter_by(id=asset_id, project_id=run.project_id).one_or_none()
        if asset is None or str(asset.content_hash or "") != frozen_hash:
            findings.append(_factual_finding(
                rule_id="rights.persisted_asset_identity", code="persisted_asset_hash_mismatch", severity="critical", target_refs=[page_ref, asset_target],
                evidence_refs=lineage_evidence, expected=frozen_hash, observed=str(getattr(asset, "content_hash", "missing")),
                message="Approved manifest asset does not match the persisted asset identity.", remediation="Restore the approved persisted asset.",
            )); continue
        frozen_evidence = _frozen_image_evidence(entry, frozen_hash=frozen_hash)
        exact_job = _exact_frozen_generation_job(db, run=run, asset=asset, evidence=frozen_evidence)
        master_asset = master_assets.get(asset_id)
        master_permitted = (
            master_asset is not None and str(master_asset.get("hash") or "") == frozen_hash
        ) or _master_permitted_generated_output(
            run=run, asset=asset, job=exact_job, master_assets=master_assets,
        )
        if not master_permitted:
            findings.append(_factual_finding(
                rule_id="rights.master_manifest_parity", code="asset_missing_master_manifest", severity="critical", target_refs=[page_ref, asset_target],
                evidence_refs=lineage_evidence, expected="asset present in the exact persisted Master manifest or approved derived output", observed=asset_id,
                message="Frozen page asset is not permitted by its bound Commerce Creative Master.", remediation="Reassemble from the bound Master approved asset manifest.",
            )); continue
        try:
            actual_hash = hashlib.sha256(Path(str(asset.file_path)).read_bytes()).hexdigest()
        except OSError:
            findings.append(_factual_finding(
                rule_id="rights.persisted_asset_identity", code="asset_storage_unavailable", severity="critical", target_refs=[page_ref, asset_target],
                evidence_refs=lineage_evidence, expected="readable approved asset bytes", observed="storage unavailable",
                message="The approved asset cannot be verified from persisted storage.", remediation="Restore the approved asset bytes before final use.",
            )); continue
        if actual_hash != frozen_hash:
            findings.append(_factual_finding(
                rule_id="rights.persisted_asset_identity", code="asset_actual_hash_mismatch", severity="critical", target_refs=[page_ref, asset_target],
                evidence_refs=lineage_evidence, expected=frozen_hash, observed=actual_hash,
                message="Persisted asset bytes differ from the frozen approved manifest.", remediation="Restore the approved asset bytes.",
            )); continue
        source_type = str(asset.source_type or "").lower()
        usage = resolved_asset_usage_status(asset)
        rights = str(entry.get("rights_status") or "").lower()
        forbidden = source_type in _FORBIDDEN_ASSET_SOURCE_TYPES or usage in {"reference_only", "blocked"}
        allowed = _master_permitted_generated_output(
            run=run, asset=asset, job=exact_job, master_assets=master_assets,
        ) or (
            not forbidden and rights in {"rights_confirmed", "seller_owned", "confirmed"} and (
                (usage == "seller_owned" and source_type in SELLER_OWNED_SOURCE_TYPES) or rights == "rights_confirmed"
            )
        )
        if not allowed:
            findings.append(_factual_finding(
                rule_id="rights.final_use_provenance", code="ineligible_final_use_asset", severity="critical", target_refs=[page_ref, asset_target],
                evidence_refs=lineage_evidence, expected="seller_owned or rights_confirmed asset", observed=usage or source_type or "unknown",
                message="Frozen page uses an asset without permitted final-use provenance.", remediation="Replace it with a seller-owned or rights-confirmed approved asset.",
            ))
    for risk in _as_mappings(truth_normalization.get("observation_risks")):
        risk_type = str(risk.get("risk_type") or "")
        if risk_type not in _RISK_SIGNAL_TYPES:
            continue
        for asset_ref in _as_mappings(risk.get("source_asset_refs")):
            asset_id = str(asset_ref.get("id") or "")
            if asset_id not in used_assets:
                continue
            asset_target = _qa_typed_reference(asset_ref, "asset")
            risk_ref = risk.get("observation_ref") if isinstance(risk.get("observation_ref"), Mapping) else None
            risk_evidence = list(lineage_evidence)
            if risk_ref is not None:
                risk_evidence.append(_qa_typed_reference(risk_ref, "observation"))
            findings.append(_factual_finding(
                rule_id="policy.asset_risk_signal", code=f"unreviewed_{risk_type}", severity="critical", target_refs=[page_ref, asset_target],
                evidence_refs=risk_evidence, expected="no unreviewed final-use asset policy signal", observed=risk_type,
                message="Frozen page uses an asset with an unresolved policy-risk observation.", remediation="Replace or explicitly resolve the risky asset before final use.",
            ))

    deduped = {item["finding_id"]: item for item in findings}
    ordered = [deduped[key] for key in sorted(deduped)]
    evidence = {(_reference_identity(ref), str(ref.get("type") or "")): ref for item in ordered for ref in item["evidence_refs"]}
    critical_count = sum(item["severity"] == "critical" for item in ordered)
    domain = _domain_result({
        "domain_id": "factual_rights_policy", "score": max(0, 100 - 25 * critical_count - 10 * sum(item["severity"] == "major" for item in ordered)),
        "status": "blocked" if critical_count else "complete", "evaluator_version": FACTUAL_RIGHTS_POLICY_EVALUATOR_VERSION,
        "findings": ordered, "critical_count": critical_count, "warning_count": sum(item["severity"] != "critical" for item in ordered),
        "evidence_refs": [value for _, value in sorted(evidence.items())],
        "evaluated_at": f"frozen:{_page_snapshot_reference(page)['hash']}", "metric_source": "automatic",
    }, report_payload=report_payload)
    criticals = []
    for item in domain["findings"]:
        if item["severity"] != "critical":
            continue
        violation = {
            "violation_id": f"lg12-critical:{item['finding_hash'][:32]}", "domain": item["domain"],
            "rule_id": item["rule_id"], "target_ref": item["target_refs"][1] if len(item["target_refs"]) > 1 else item["target_refs"][0],
            "evidence_refs": item["evidence_refs"], "reason_code": item["code"], "blocking": True,
        }
        body = deepcopy(violation)
        violation["canonical_hash"] = canonical_hash(body)
        criticals.append(violation)
    return {
        "domain": domain,
        "critical_violations": criticals,
    }


def _image_finding(
    *, rule_id: str, code: str, severity: str, target_refs: Sequence[Mapping[str, Any]],
    evidence_refs: Sequence[Mapping[str, Any]], expected: Any, observed: Any, message: str, remediation: str,
) -> dict[str, Any]:
    """Create a bounded TASK-12.2 finding without copying image metadata."""

    identity = {
        "rule_id": rule_id, "code": code,
        "targets": sorted((_reference_identity(ref) for ref in target_refs)),
        "expected": expected, "observed": observed,
    }
    return {
        "finding_id": f"lg12-image-identity:{canonical_hash(identity)[:32]}",
        "domain": "image_identity_quality", "severity": severity, "rule_id": rule_id,
        "code": code, "message": message, "target_refs": list(target_refs),
        "evidence_refs": list(evidence_refs), "expected": expected, "observed": observed,
        "remediation_hint": remediation,
    }


_VISUAL_IDENTITY_FIELDS = {
    "product_identity": {"product_identity", "product_name", "model", "model_name", "sku"},
    "variant": {"variant", "product_variant"},
    "color": {"color", "colour", "color_option"},
    "material_finish": {"material", "material_grade", "material_type", "finish"},
    "components": {"component", "components", "component_count", "included_components"},
}


def _identity_key(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text.startswith("fact:"):
        text = text[5:]
    return text or None


def _identity_bucket(field_id: Any) -> str | None:
    field = _identity_key(field_id)
    if field is None:
        return None
    return next((key for key, values in _VISUAL_IDENTITY_FIELDS.items() if field in values), None)


def _identity_value(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("value") or value.get("normalized_value")
    if not isinstance(value, (str, int, float)):
        return None
    normalized = " ".join(str(value).strip().lower().split())
    return normalized or None


def _has_identity_reference_list(value: Any) -> bool:
    """Require bounded immutable identity refs before using a Truth observation.

    ProductTruth candidates are not commercial/claim-approved facts.  They can
    nevertheless provide a safe visual-comparison baseline when their frozen
    source, observation, and evidence chains are all present.  Do not let a
    caller-shaped candidate with only a matching value become that baseline.
    """

    if not isinstance(value, list) or not value:
        return False
    return all(
        isinstance(item, Mapping)
        and isinstance(item.get("id"), str)
        and bool(item["id"])
        and isinstance(item.get("version"), int)
        and item["version"] >= 1
        and isinstance(item.get("hash"), str)
        and len(item["hash"]) == 64
        for item in value
    )


def _source_backed_identity_candidate(
    db: Session, *, run: AgentRun, source: ProductSourceSnapshotVersion,
    truth: ProductTruthVersion, item: Mapping[str, Any],
) -> tuple[str, str] | None:
    """Return an eligible Truth visual-identity observation, never an approved fact.

    TASK-12I.6 deliberately persists source observations as
    ``candidate_not_approved``.  That state remains ineligible for commercial
    claims, but an identity-taxonomy field with its complete immutable
    provenance can be compared with frozen image metadata.  Unknown,
    conflict, prohibited, rejected, and unprovenanced entries fail closed.
    """

    bucket = _identity_bucket(item.get("field_id") or item.get("field"))
    value = _identity_value(item.get("value") or item.get("normalized_value"))
    if not bucket or not value:
        return None
    if str(item.get("state") or "").lower() != "candidate_not_approved":
        return None
    if str(item.get("approval_status") or "").lower() != "candidate_not_approved":
        return None
    if not all(_has_identity_reference_list(item.get(name)) for name in ("source_refs", "observation_refs", "evidence_refs")):
        return None
    # Never turn caller-shaped candidate refs into visual evidence.  The
    # persisted source row must be the exact Truth/run/page lineage and the
    # candidate must be reproducible from its pinned, hash-checked artifact.
    if (
        source.workspace_id != run.workspace_id
        or source.project_id != run.project_id
        or source.creator_run_id != run.id
        or truth.workspace_id != run.workspace_id
        or truth.project_id != run.project_id
        or truth.creator_run_id != run.id
        or truth.source_snapshot_version_id != source.id
        or truth.source_snapshot_version != source.version
        or truth.source_snapshot_hash != source.canonical_hash
    ):
        return None
    try:
        _normalization, persisted_candidates, _unknowns, _conflicts, _prohibited, _risks = (
            _truth_normalization_from_source(db, source=source)
        )
    except IntakeVersionContractError:
        # Artifact/source-reference integrity is a fail-closed eligibility
        # boundary.  The evaluator reports it as not-evaluable below rather
        # than allowing a guessed identity through.
        return None
    if not any(dict(item) == dict(persisted) for persisted in persisted_candidates):
        return None
    return bucket, value


def _identity_state_bucket(item: Mapping[str, Any]) -> str | None:
    # SellerConfirmation fact-state references are intentionally compact; the
    # immutable fact identity is carried by ``id`` when a display field is not
    # repeated.  Treat that persisted ID as the taxonomy input, never a caller
    # supplied free-form label.
    return _identity_bucket(item.get("field_id") or item.get("field") or item.get("type") or item.get("id"))


def _expected_product_identity(
    db: Session, *, run: AgentRun, source: ProductSourceSnapshotVersion,
    truth: ProductTruthVersion, confirmation: SellerConfirmationVersion,
) -> tuple[dict[str, str], set[str], dict[str, set[str]]]:
    """Read frozen visual identity with confirmation overriding source observations.

    The returned unresolved buckets represent a claimed identity observation
    whose value lacks the frozen provenance required for direct comparison.
    They must keep the image domain out of ``complete`` rather than allowing a
    normal score to mask an unevaluable identity.
    """

    expected: dict[str, str] = {}
    provenance_gaps: set[str] = set()
    unresolved_states: dict[str, set[str]] = {}

    def mark_unresolved(item: Mapping[str, Any], state: str) -> None:
        bucket = _identity_state_bucket(item)
        if bucket:
            unresolved_states.setdefault(bucket, set()).add(state)

    for item in _as_mappings(dict(truth.normalization_json or {}).get("fact_candidates")):
        bucket = _identity_bucket(item.get("field_id") or item.get("field"))
        value = _identity_value(item.get("value") or item.get("normalized_value"))
        if not bucket or not value:
            continue
        candidate = _source_backed_identity_candidate(db, run=run, source=source, truth=truth, item=item)
        if candidate is None:
            provenance_gaps.add(bucket)
            continue
        expected.setdefault(*candidate)
    for item in _as_mappings(dict(truth.normalization_json or {}).get("unknown_facts")):
        mark_unresolved(item, "unknown")
    for item in _as_mappings(dict(truth.normalization_json or {}).get("conflict_facts")):
        if str(item.get("resolution_status") or "unresolved").lower() == "unresolved":
            mark_unresolved(item, "conflict")
    for item in _as_mappings(dict(truth.normalization_json or {}).get("prohibited_inferences")):
        mark_unresolved(item, "prohibited")
    for item in _as_mappings(confirmation.rejected_fact_refs_json):
        bucket = _identity_state_bucket(item)
        if bucket:
            expected.pop(bucket, None)
            provenance_gaps.discard(bucket)
            unresolved_states.setdefault(bucket, set()).add("rejected")
    for item in _as_mappings(confirmation.unknown_fact_refs_json):
        mark_unresolved(item, "unknown")
    # Seller-confirmed facts are the authoritative correction/selection layer.
    for item in _as_mappings(confirmation.confirmed_fact_refs_json):
        bucket = _identity_bucket(item.get("field_id") or item.get("field") or item.get("type"))
        value = _identity_value(item.get("normalized_value") or item.get("value"))
        if bucket and value:
            expected[bucket] = value
            provenance_gaps.discard(bucket)
            unresolved_states.pop(bucket, None)
    return dict(sorted(expected.items())), provenance_gaps, unresolved_states


def _frozen_identity_value(identity_metadata: Mapping[str, Any], bucket: str) -> str | None:
    """Resolve only explicit frozen visual labels into the limited taxonomy."""

    direct = _identity_value(identity_metadata.get(bucket))
    if direct:
        return direct
    for field in _VISUAL_IDENTITY_FIELDS[bucket]:
        value = _identity_value(identity_metadata.get(field))
        if value:
            return value
    return None


def _frozen_image_evidence(manifest_item: Mapping[str, Any], *, frozen_hash: str) -> dict[str, Any]:
    evidence = dict(manifest_item.get("lg12_frozen_image_evidence") or {})
    body = deepcopy(evidence)
    evidence_hash = str(body.pop("evidence_hash", "") or "")
    if (
        evidence.get("schema_version") != LG12_FROZEN_IMAGE_EVIDENCE_SCHEMA_VERSION
        or not evidence_hash
        or canonical_hash(body) != evidence_hash
    ):
        raise QualityAssessmentContractError("Frozen image QA evidence is missing or tampered.")
    asset_ref = dict(evidence.get("asset") or {})
    file_ref = dict(evidence.get("file") or {})
    if str(asset_ref.get("hash") or "") != frozen_hash or str(file_ref.get("content_hash") or "") != frozen_hash:
        raise QualityAssessmentContractError("Frozen image QA evidence does not match the approved manifest asset hash.")
    if not str(asset_ref.get("id") or "") or not str(file_ref.get("format") or ""):
        raise QualityAssessmentContractError("Frozen image QA evidence is incomplete.")
    return evidence


def _exact_frozen_generation_job(db: Session, *, run: AgentRun, asset: Asset, evidence: Mapping[str, Any]) -> ImageGenerationJobRecord | None:
    generation = evidence.get("generation")
    if generation is None:
        return None
    frozen = dict(generation or {})
    record_id = str(frozen.get("record_id") or "")
    if not record_id:
        raise QualityAssessmentContractError("Frozen generation evidence is missing its exact job record ID.")
    job = db.query(ImageGenerationJobRecord).filter_by(
        id=record_id, project_id=run.project_id, output_asset_id=asset.id,
    ).one_or_none()
    validation = dict(frozen.get("validation") or {})
    if (
        job is None
        or str(job.job_id or "") != str(frozen.get("job_id") or "")
        or str(frozen.get("output_asset_id") or "") != str(asset.id)
        or canonical_hash({"validation": validation}) != str(frozen.get("validation_result_hash") or "")
        or canonical_hash({"validation": _bounded_generation_validation(job.validation_result)}) != str(frozen.get("validation_result_hash") or "")
    ):
        raise QualityAssessmentContractError("Frozen generation validation evidence does not match its exact persisted job record.")
    return job


def _bounded_generation_validation(value: Any) -> dict[str, Any]:
    result = dict(value or {}) if isinstance(value, Mapping) else {}
    details = dict(result.get("details") or {})
    identity = dict(details.get("identity") or {})
    checks = []
    raw_checks = identity.get("checks") or {}
    if isinstance(raw_checks, Mapping):
        raw_checks = [{"feature": key, **dict(item)} if isinstance(item, Mapping) else {"feature": key, "status": item} for key, item in raw_checks.items()]
    for item in _as_mappings(raw_checks):
        feature, status = str(item.get("feature") or "").lower(), str(item.get("status") or "").lower()
        if feature and status:
            checks.append({"feature": feature, "status": status})
    return {
        "status": str(result.get("status") or "").lower(),
        "identity_status": str(identity.get("status") or "").lower(),
        "identity_checks": sorted(checks, key=lambda item: (item["feature"], item["status"])),
        "identity_metadata": dict(identity.get("observed_identity") or identity.get("identity_metadata") or {}),
        "quality_warnings": sorted({str(item).upper() for item in list(result.get("warnings") or []) if isinstance(item, str)}),
        "risk_codes": sorted({str(item).lower() for item in list(result.get("risk_codes") or []) if isinstance(item, str)}),
        "safe_crop_status": str(dict(details.get("crop") or {}).get("safe_crop_status") or "").lower(),
    }


def _image_asset_contexts(
    db: Session, *, run: AgentRun, page: DetailPageVersion, snapshot: Mapping[str, Any],
    canonical: Mapping[str, Any], source: ProductSourceSnapshotVersion,
    confirmation: SellerConfirmationVersion, master: CommerceCreativeMasterVersion,
) -> list[dict[str, Any]]:
    """Read and bind every frozen page asset to its exact persisted authority.

    Identity/manifest/storage disagreement is an evaluator input-integrity
    failure, not an ordinary image-quality observation.  The returned contexts
    intentionally contain only rows and bounded inspection metadata.
    """

    master_assets = _require_master_asset_manifest_parity(
        db, source=source, confirmation=confirmation, master=master,
    )
    manifest = dict(canonical.get("approved_asset_manifest") or {})
    manifest_assets = {
        str(item.get("asset_id") or item.get("id") or ""): dict(item)
        for item in _as_mappings(manifest.get("assets"))
    }
    uses: dict[str, list[dict[str, Any]]] = {}
    for index, section in enumerate(_frozen_sections(snapshot, canonical)):
        section_id = str(section.get("section_id") or section.get("id") or f"section:{index}")
        section_ref = _qa_typed_reference(
            {"id": section_id, "version": 1, "hash": canonical_hash(section)}, "section",
        )
        for item in _section_asset_references(section):
            uses.setdefault(str(item["asset_id"]), []).append({"used_ref": item, "section_ref": section_ref})

    contexts: list[dict[str, Any]] = []
    for asset_id, placements in sorted(uses.items()):
        manifest_item = manifest_assets.get(asset_id)
        if manifest_item is None:
            raise QualityAssessmentContractError("Frozen image asset is absent from the approved asset manifest.")
        frozen_hash = str(manifest_item.get("asset_content_hash") or manifest_item.get("hash") or "")
        if not frozen_hash:
            raise QualityAssessmentContractError("Frozen image asset is missing its approved SHA-256 identity.")
        for placement in placements:
            page_hash = str(placement["used_ref"].get("asset_content_hash") or "")
            if page_hash and page_hash != frozen_hash:
                raise QualityAssessmentContractError("Frozen page image asset hash differs from its approved manifest.")
        asset = db.query(Asset).filter_by(id=asset_id, project_id=run.project_id).one_or_none()
        if asset is None or str(asset.content_hash or "") != frozen_hash:
            raise QualityAssessmentContractError("Frozen image asset does not match the persisted project asset identity.")
        master_asset = master_assets.get(asset_id)
        if (
            (master_asset is None or str(master_asset.get("hash") or "") != frozen_hash)
            and str(asset.source_type or "").lower() not in AI_SOURCE_TYPES
        ):
            raise QualityAssessmentContractError("Frozen image asset is not permitted by the bound Commerce Creative Master.")
        frozen_evidence = _frozen_image_evidence(manifest_item, frozen_hash=frozen_hash)
        if str(dict(frozen_evidence.get("asset") or {}).get("id") or "") != asset_id:
            raise QualityAssessmentContractError("Frozen image QA evidence does not match its approved asset ID.")
        if not Path(str(asset.file_path or "")).is_file():
            raise QualityAssessmentContractError("Frozen image asset bytes are unavailable from persisted storage.")
        asset_ref = _qa_typed_reference(
            {"id": asset_id, "version": 1, "hash": frozen_hash}, "asset",
        )
        try:
            inspection = inspect_frozen_image_file(
                file_path=str(asset.file_path), declared_mime_type=str(asset.mime_type or ""),
            )
        except ProductIdentityValidationError as exc:
            inspection = {"error": str(exc)}
        if inspection.get("content_hash") and str(inspection["content_hash"]) != frozen_hash:
            raise QualityAssessmentContractError("Frozen image asset storage bytes differ from its manifest SHA-256.")
        frozen_file = dict(frozen_evidence.get("file") or {})
        if inspection.get("content_hash") and (
            int(inspection.get("width") or 0) != int(frozen_file.get("width") or 0)
            or int(inspection.get("height") or 0) != int(frozen_file.get("height") or 0)
            or str(inspection.get("image_format") or "") != str(frozen_file.get("format") or "")
        ):
            raise QualityAssessmentContractError("Frozen image storage metadata no longer matches the frozen manifest evidence.")
        metadata_ref = _qa_typed_reference(
            {
                "id": f"frozen-image-evidence:{asset.id}", "version": 1,
                "hash": str(frozen_evidence["evidence_hash"]),
            },
            "frozen_image_evidence",
        )
        job = _exact_frozen_generation_job(db, run=run, asset=asset, evidence=frozen_evidence)
        if not (
            (master_asset is not None and str(master_asset.get("hash") or "") == frozen_hash)
            or _master_permitted_generated_output(
                run=run, asset=asset, job=job, master_assets=master_assets,
            )
        ):
            raise QualityAssessmentContractError("Frozen image asset is not permitted by the bound Commerce Creative Master.")
        contexts.append({
            "asset": asset, "asset_ref": asset_ref, "placements": placements,
            "inspection": inspection, "metadata_ref": metadata_ref, "job": job,
            "frozen_evidence": frozen_evidence,
        })
    return contexts


def _image_job_signals(validation: Mapping[str, Any] | None) -> list[tuple[str, str, str]]:
    """Extract only stable LG-9 status codes, never its raw provider output."""

    if validation is None:
        return []
    result = dict(validation or {})
    signals: list[tuple[str, str, str]] = []
    status = str(result.get("identity_status") or "")
    if status == "blocked":
        signals.append(("identity_validation_blocked", "critical", "identity validation blocked"))
    elif status == "needs_review":
        signals.append(("identity_evidence_needs_review", "major", "identity evidence needs review"))
    for check in _as_mappings(result.get("identity_checks")):
        feature = str(check.get("feature") or "identity")
        check_status = str(check.get("status") or "")
        if check_status in {"blocked", "mismatch"}:
            signals.append((f"identity_{feature}_mismatch", "critical", f"{feature} identity does not match"))
        elif check_status in {"needs_review", "unavailable"}:
            signals.append((f"identity_{feature}_needs_review", "major", f"{feature} identity evidence needs review"))
    for risk in list(result.get("risk_codes") or []):
        normalized = str(risk or "").lower()
        if normalized in {"watermark", "third_party_logo", "suspicious_foreign_brand_text"}:
            signals.append((f"lg9_{normalized}", "major", f"LG-9 recorded {normalized}"))
    return signals


def evaluate_image_identity_quality_domain(db: Session, *, report_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only image/product-identity evaluation for a frozen DetailPageVersion.

    This is a domain evaluator only.  It neither persists a QA report nor
    aggregates a Quality Bar verdict, dispatches a provider, or changes page
    state.  Every image finding stays tied to a frozen section and/or asset.
    """

    report = normalize_quality_assessment_report(report_payload)
    run = _require_run(db, report)
    page = _require_target(db, report)
    _require_lineage(db, run=run, report=report)
    source = db.query(ProductSourceSnapshotVersion).filter_by(id=report["input_lineage"]["source_snapshot_ref"]["id"]).one()
    truth = db.query(ProductTruthVersion).filter_by(id=report["input_lineage"]["truth_ref"]["id"]).one()
    confirmation = db.query(SellerConfirmationVersion).filter_by(id=report["input_lineage"]["confirmation_ref"]["id"]).one()
    master = db.query(CommerceCreativeMasterVersion).filter_by(id=report["input_lineage"]["master_ref"]["id"]).one()
    snapshot, canonical = _frozen_assembly_input(page)
    _require_frozen_page_master_binding(
        page=page, snapshot=snapshot, run=run, source=source, truth=truth,
        confirmation=confirmation, master=master,
    )
    page_ref = _page_snapshot_reference(page)
    lineage_evidence = [
        _qa_row_reference(source, "ProductSourceSnapshotVersion"),
        _qa_row_reference(truth, "ProductTruthVersion"),
        _qa_row_reference(confirmation, "SellerConfirmationVersion"),
        _qa_row_reference(master, "CommerceCreativeMasterVersion"),
    ]
    findings: list[dict[str, Any]] = []
    asset_contexts = _image_asset_contexts(
        db, run=run, page=page, snapshot=snapshot, canonical=canonical,
        source=source, confirmation=confirmation, master=master,
    )
    expected_identity, source_identity_provenance_gaps, unresolved_identity_states = _expected_product_identity(
        db, run=run, source=source, truth=truth, confirmation=confirmation,
    )
    for context in asset_contexts:
        asset = context["asset"]
        asset_ref = context["asset_ref"]
        placement_refs = [item["section_ref"] for item in context["placements"]]
        targets = [page_ref, *placement_refs, asset_ref]
        evidence = [*lineage_evidence, context["metadata_ref"]]
        inspection = dict(context["inspection"])
        frozen_evidence = dict(context["frozen_evidence"])
        frozen_metadata = dict(frozen_evidence.get("metadata") or {})
        if inspection.get("error"):
            findings.append(_image_finding(
                rule_id="image.decode", code="image_decode_or_format_failure", severity="critical", target_refs=targets,
                evidence_refs=evidence, expected="decodable approved image", observed="decode failed",
                message="Frozen approved image bytes cannot be decoded using the declared image format.",
                remediation="Restore the approved image bytes or replace the frozen asset.",
            ))
            continue
        for warning in inspection.get("warnings", []):
            code = "low_resolution" if warning == "LOW_RESOLUTION" else "extreme_aspect_ratio"
            findings.append(_image_finding(
                rule_id="image.dimensions", code=code, severity="major", target_refs=targets, evidence_refs=evidence,
                expected="established LG-9 image dimensions", observed=warning,
                message="Frozen image does not meet the established deterministic image dimension guidance.",
                remediation="Use a suitable approved source image or regenerate through the existing LG-9 path.",
            ))
        warnings = {str(value).upper() for value in list(frozen_metadata.get("quality_warnings") or []) if isinstance(value, str)}
        metadata_signals = {
            "LOW_VISIBILITY": ("low_product_visibility", "major", "product visibility is insufficient"),
            "PRODUCT_CLIPPED": ("product_crop_or_clipping", "major", "product is clipped"),
            "EXCESSIVE_CROP": ("product_crop_or_clipping", "major", "product crop is excessive"),
            "SAFE_CROP_REVIEW_REQUIRED": ("product_crop_needs_review", "major", "product crop needs review"),
            "DISTORTION_MISMATCH": ("product_distortion", "critical", "product shape is distorted"),
            "VARIANT_MISMATCH": ("product_variant_mismatch", "critical", "product variant does not match source identity"),
            "COLOR_MISMATCH": ("product_color_mismatch", "major", "product color metadata does not match source identity"),
            "WATERMARK": ("visible_watermark", "major", "watermark risk is present"),
            "UNWANTED_WATERMARK": ("visible_watermark", "major", "watermark risk is present"),
            "THIRD_PARTY_LOGO": ("third_party_logo", "major", "third-party logo risk is present"),
            "FOREIGN_BRAND_CONTAMINATION": ("foreign_brand_contamination", "major", "foreign brand contamination risk is present"),
            "DUPLICATE_FILE": ("duplicate_scene_image", "minor", "duplicate scene image is recorded"),
        }
        for warning in sorted(warnings):
            signal = metadata_signals.get(warning)
            if signal is None:
                continue
            code, severity, message = signal
            findings.append(_image_finding(
                rule_id="image.persisted_metadata", code=code, severity=severity, target_refs=targets,
                evidence_refs=evidence, expected="no unresolved image identity/quality signal", observed=warning,
                message=f"Frozen asset {message}.", remediation="Review the named frozen asset and replace it only through the approved asset path.",
            ))
        if frozen_metadata.get("product_identity_preserved") is False or str(frozen_metadata.get("identity_status") or "") in {"rejected", "blocked"}:
            findings.append(_image_finding(
                rule_id="image.product_identity", code="product_identity_drift", severity="critical", target_refs=targets,
                evidence_refs=evidence, expected="source/master product identity preserved", observed=str(frozen_metadata.get("identity_status") or "not_preserved"),
                message="Frozen output asset has a recorded product-identity drift.",
                remediation="Replace it through the existing LG-9 identity review and approved manifest path.",
            ))
        elif str(frozen_metadata.get("identity_status") or "") == "needs_review":
            findings.append(_image_finding(
                rule_id="image.product_identity", code="product_identity_needs_review", severity="major", target_refs=targets,
                evidence_refs=evidence, expected="sufficient product identity evidence", observed="needs_review",
                message="Frozen asset lacks sufficient product-identity evidence and is not auto-passed.",
                remediation="Provide a reviewed identity validation result before promotion.",
            ))
        frozen_identity = dict(frozen_metadata.get("identity_metadata") or {})
        direct_identity_codes: set[str] = set()
        direct_specs = {
            "product_identity": ("product_model_identity_mismatch", "critical", "model/product identity"),
            "variant": ("product_variant_mismatch", "critical", "variant"),
            "color": ("product_color_mismatch", "major", "color"),
            "material_finish": ("product_material_finish_mismatch", "major", "material or finish"),
            "components": ("product_components_mismatch", "major", "visual components"),
        }
        for bucket, expected_value in expected_identity.items():
            observed_value = _frozen_identity_value(frozen_identity, bucket)
            code, severity, label = direct_specs[bucket]
            if observed_value is None:
                findings.append(_image_finding(
                    rule_id="image.frozen_identity_parity", code="identity_metadata_not_evaluable", severity="major",
                    target_refs=targets, evidence_refs=evidence, expected=expected_value, observed="missing_frozen_identity_metadata",
                    message=f"Frozen asset has no bounded {label} metadata for a direct product-identity comparison.",
                    remediation="Freeze reviewed visual identity metadata before promoting the asset.",
                ))
            elif observed_value != expected_value:
                direct_identity_codes.add(code)
                findings.append(_image_finding(
                    rule_id="image.frozen_identity_parity", code=code, severity=severity, target_refs=targets,
                    evidence_refs=evidence, expected=expected_value, observed=observed_value,
                    message=f"Frozen asset {label} does not match the persisted Truth/SellerConfirmation identity.",
                    remediation="Replace the asset through the approved review path; do not relabel mutable Asset metadata.",
                ))
        job = context["job"]
        job_evidence = list(evidence)
        generation = frozen_evidence.get("generation")
        if job is not None and isinstance(generation, Mapping):
            job_evidence.append(_qa_typed_reference(
                {"id": str(generation["record_id"]), "version": 1, "hash": str(generation["validation_result_hash"])},
                "lg9_image_validation",
            ))
        for code, severity, message in _image_job_signals(
            dict(generation or {}).get("validation") if isinstance(generation, Mapping) else None
        ):
            if code in direct_identity_codes:
                continue
            findings.append(_image_finding(
                rule_id="image.lg9_validation", code=code, severity=severity, target_refs=targets,
                evidence_refs=job_evidence, expected="LG-9 identity validation passed", observed=code,
                message=f"Frozen asset {message}.", remediation="Use the existing LG-9 review/replacement flow.",
            ))

    # A Truth item that looks like visual identity but lacks its immutable
    # source/observation/evidence chain cannot be used as an expected value.
    # It is also not safe to call the domain complete merely because no scalar
    # comparison was attempted.
    for bucket in sorted(source_identity_provenance_gaps):
        findings.append(_image_finding(
            rule_id="image.truth_identity_provenance",
            code="identity_source_provenance_not_evaluable",
            severity="major",
            target_refs=[page_ref],
            evidence_refs=lineage_evidence,
            expected=f"provenanced {bucket} identity observation",
            observed="missing_source_observation_or_evidence_provenance",
            message="Persisted Truth identity candidate cannot be used for direct image comparison without its immutable provenance chain.",
            remediation="Preserve the source, observation, and evidence references before promoting the asset.",
        ))

    # Unknown, unresolved-conflict, prohibited, and rejected visual identity
    # fields are not expected values.  They nevertheless make the identity
    # dimension unevaluable: passing crop/resolution must never silently mark
    # an identity-incomplete frozen page as complete.
    for bucket, states in sorted(unresolved_identity_states.items()):
        findings.append(_image_finding(
            rule_id="image.truth_identity_state",
            code="identity_state_not_evaluable",
            severity="major",
            target_refs=[page_ref],
            evidence_refs=lineage_evidence,
            expected=f"resolved {bucket} identity",
            observed="/".join(sorted(states)),
            message="Persisted Truth/SellerConfirmation leaves a visual identity field unresolved or unusable.",
            remediation="Resolve the frozen identity through the existing seller confirmation/evidence review path.",
        ))

    # TASK-12I.5/12I.6 keep OCR-derived risk observations in ProductTruth.
    # Treat them as image-quality evidence here, not a second policy decision:
    # TASK-12.3 remains the owner of the factual/rights critical policy gate.
    contexts_by_asset = {str(context["asset"].id): context for context in asset_contexts}
    truth_risk_codes = {
        "watermark": "visible_watermark",
        "third_party_logo": "third_party_logo",
        "suspicious_foreign_brand_text": "foreign_brand_contamination",
    }
    for risk in _as_mappings(dict(truth.normalization_json or {}).get("observation_risks")):
        risk_type = str(risk.get("risk_type") or "").lower()
        code = truth_risk_codes.get(risk_type)
        if code is None:
            continue
        observation = risk.get("observation_ref") if isinstance(risk.get("observation_ref"), Mapping) else None
        for source_asset_ref in _as_mappings(risk.get("source_asset_refs")):
            context = contexts_by_asset.get(str(source_asset_ref.get("id") or ""))
            if context is None:
                continue
            evidence = [*lineage_evidence, context["metadata_ref"]]
            if observation is not None:
                evidence.append(_qa_typed_reference(observation, "observation"))
            findings.append(_image_finding(
                rule_id="image.observation_risk", code=code, severity="major",
                target_refs=[page_ref, *[item["section_ref"] for item in context["placements"]], context["asset_ref"]],
                evidence_refs=evidence, expected="no unresolved image contamination risk", observed=risk_type,
                message="A frozen source observation reports an unresolved image-quality contamination risk.",
                remediation="Review the named approved asset before using it in a final page.",
            ))

    # The direct frozen Truth comparison is authoritative.  If an older LG-9
    # warning describes the same target/code, retain only the later direct
    # parity finding instead of inflating the domain with duplicate alarms.
    deduped = {
        (item["code"], tuple(sorted(_reference_identity(ref) for ref in item["target_refs"] if ref.get("type") == "asset"))): item
        for item in findings
    }
    ordered = [deduped[key] for key in sorted(deduped)]
    evidence = {(_reference_identity(ref), str(ref.get("type") or "")): ref for item in ordered for ref in item["evidence_refs"]}
    critical_count = sum(item["severity"] == "critical" for item in ordered)
    major_count = sum(item["severity"] == "major" for item in ordered)
    not_evaluable = any(
        str(item["code"]) in {
            "identity_metadata_not_evaluable",
            "identity_source_provenance_not_evaluable",
            "identity_state_not_evaluable",
        }
        for item in ordered
    )
    needs_review = not_evaluable or any("needs_review" in str(item["code"]) for item in ordered)
    domain = _domain_result({
        "domain_id": "image_identity_quality", "score": max(0, 100 - 25 * critical_count - 10 * major_count - 3 * sum(item["severity"] == "minor" for item in ordered)),
        "status": "blocked" if critical_count else ("needs_review" if needs_review else "complete"),
        "evaluator_version": IMAGE_IDENTITY_QUALITY_EVALUATOR_VERSION,
        "findings": ordered, "critical_count": critical_count,
        "warning_count": sum(item["severity"] != "critical" for item in ordered),
        "evidence_refs": [value for _, value in sorted(evidence.items())],
        "evaluated_at": f"frozen:{page_ref['hash']}", "metric_source": "automatic",
        "submetrics": [
            {"metric_id": "asset_integrity", "value": 0 if critical_count else 1, "status": "failed" if critical_count else "passed"},
            {"metric_id": "identity_consistency", "value": 0 if any("identity" in item["code"] for item in ordered) else 1, "status": "needs_review" if needs_review else "passed"},
            {"metric_id": "visibility_crop", "value": 0 if any("visibility" in item["code"] or "crop" in item["code"] for item in ordered) else 1, "status": "passed"},
            {"metric_id": "resolution", "value": 0 if any(item["code"] == "low_resolution" for item in ordered) else 1, "status": "passed"},
        ],
    }, report_payload=report_payload)
    criticals: list[dict[str, Any]] = []
    for item in domain["findings"]:
        if item["severity"] != "critical":
            continue
        violation = {
            "violation_id": f"lg12-critical:{item['finding_hash'][:32]}", "domain": item["domain"],
            "rule_id": item["rule_id"], "target_ref": item["target_refs"][-1],
            "evidence_refs": item["evidence_refs"], "reason_code": item["code"], "blocking": True,
        }
        violation["canonical_hash"] = canonical_hash(violation)
        criticals.append(violation)
    return {"domain": domain, "critical_violations": criticals}


# TASK-12.9 production assembly -------------------------------------------------
#
# TASK-12.2 deliberately stopped at the immutable report contract and each
# later evaluator deliberately returns one domain only.  The production graph
# needs one small, deterministic bridge which assembles those already-frozen
# domain results.  Keeping it here ensures it uses exactly the same target,
# lineage, profile and report validation helpers as the individual evaluators.

QUALITY_EVALUATOR_BUNDLE_VERSION = "lg12-evaluator-bundle-v1"
QUALITY_DOMAIN_WEIGHTS: dict[str, float] = {
    # LG-12's published bar is fact/policy 20, image identity 20, Korean copy
    # 15, layout+Brand Kit+scene flow 40 and channel output 5.  These are not
    # inferred runtime weights and are committed into the frozen report.
    "factual_rights_policy": 0.20,
    "image_identity_quality": 0.20,
    "korean_copy_readability": 0.15,
    "layout_typography_brand_flow": 0.40,
    "channel_preview_export_parity": 0.05,
}


def _quality_row_ref(row: Any, artifact_type: str) -> dict[str, Any]:
    return {"id": str(row.id), "version": int(row.version), "hash": str(row.canonical_hash), "type": artifact_type}


def _quality_page_ref(page: DetailPageVersion) -> dict[str, Any]:
    snapshot = dict(page.sections_json or {})
    payload = dict(snapshot)
    snapshot_hash = str(payload.pop("snapshot_hash", "") or "")
    if not snapshot_hash or canonical_hash(payload) != snapshot_hash:
        raise QualityAssessmentContractError("Quality graph requires an untampered frozen DetailPageVersion.")
    return {
        "id": str(page.id),
        "version": str(payload.get("schema_version") or ""),
        "hash": snapshot_hash,
        "type": QUALITY_REPORT_TARGET_ARTIFACT_TYPE,
    }


def _quality_lineage_rows(db: Session, *, run: AgentRun, page: DetailPageVersion) -> tuple[
    ProductSourceSnapshotVersion, ProductTruthVersion, SellerConfirmationVersion, CommerceCreativeMasterVersion,
]:
    snapshot = dict(page.sections_json or {})
    snapshot.pop("snapshot_hash", None)
    lineage = dict(snapshot.get("lg12_quality_lineage") or {})
    if lineage.get("schema_version") != "lg12-detail-page-quality-lineage-v1":
        raise QualityAssessmentContractError("Frozen DetailPageVersion is not eligible for LG-12 QA without Master lineage.")
    if str(lineage.get("creator_run_id") or "") != str(run.id):
        raise QualityAssessmentContractError("Frozen DetailPageVersion QA lineage belongs to a different run.")
    models = (
        ("source_snapshot_ref", ProductSourceSnapshotVersion),
        ("truth_ref", ProductTruthVersion),
        ("confirmation_ref", SellerConfirmationVersion),
        ("master_ref", CommerceCreativeMasterVersion),
    )
    rows: dict[str, Any] = {}
    for key, model in models:
        ref = dict(lineage.get(key) or {})
        row = db.query(model).filter_by(
            id=str(ref.get("id") or ""), workspace_id=run.workspace_id, project_id=run.project_id,
        ).one_or_none()
        if row is None or _exact_reference(row) != ref or str(row.creator_run_id) != str(run.id):
            raise QualityAssessmentContractError(f"Frozen DetailPageVersion {key} is not a persisted current-run identity.")
        validate_immutable_version(db, row)
        rows[key] = row
    source, truth, confirmation, master = (
        rows["source_snapshot_ref"], rows["truth_ref"], rows["confirmation_ref"], rows["master_ref"],
    )
    if (
        truth.source_snapshot_version_id != source.id
        or confirmation.truth_version_id != truth.id
        or master.source_snapshot_version_id != source.id
        or master.truth_version_id != truth.id
        or master.confirmation_version_id != confirmation.id
    ):
        raise QualityAssessmentContractError("Frozen DetailPageVersion QA lineage is not Source -> Truth -> Confirmation -> Master.")
    return source, truth, confirmation, master


def _ensure_quality_threshold_profile(
    db: Session, *, run: AgentRun, channels: Sequence[str],
) -> QualityThresholdProfileVersion:
    """Return the active persisted profile, creating only the specified v1 default.

    There is no mutable application default: when a project has no profile,
    the source-of-truth v1 85/70/zero-critical contract is persisted once with
    a deterministic ID.  Later profile versions remain explicit successors.
    """

    normalized_channels = sorted({str(channel) for channel in channels})
    active = (
        db.query(QualityThresholdProfileVersion)
        .filter_by(workspace_id=run.workspace_id, project_id=run.project_id, status="active")
        .order_by(QualityThresholdProfileVersion.version.desc(), QualityThresholdProfileVersion.id.asc())
        .all()
    )
    for profile in active:
        if set(normalized_channels).issubset(set(profile.applicable_channels_json or [])):
            validate_quality_threshold_profile_version(db, profile)
            return profile
    profile_id = str(uuid5(NAMESPACE_URL, f"sellform:lg12-quality-profile-v1:{run.project_id}"))
    payload = {
        "profile_id": profile_id,
        "profile_version": 1,
        "schema_version": QUALITY_THRESHOLD_PROFILE_SCHEMA_VERSION,
        "applicable_artifact_type": QUALITY_REPORT_TARGET_ARTIFACT_TYPE,
        "applicable_channels": normalized_channels,
        "overall_minimum": 85,
        "per_domain_minimum": {domain: 70 for domain in sorted(QUALITY_DOMAIN_IDS)},
        "max_critical_violations": 0,
        "status": "active",
        # This is an immutable contract epoch rather than wall-clock request
        # metadata, so replay cannot produce a different profile hash.
        "effective_from": "2026-08-18T00:00:00Z",
    }
    existing = db.query(QualityThresholdProfileVersion).filter_by(id=profile_id).one_or_none()
    if existing is not None:
        validate_quality_threshold_profile_version(db, existing)
        if set(normalized_channels).issubset(set(existing.applicable_channels_json or [])):
            return existing
        raise QualityAssessmentContractError("Persisted default quality profile does not cover this frozen channel set.")
    return create_quality_threshold_profile(
        db, workspace_id=run.workspace_id, project_id=run.project_id, payload=payload,
    )


def _quality_placeholder_domain(domain_id: str, *, report_payload: Mapping[str, Any], evaluator_version: str) -> dict[str, Any]:
    from src.schemas.lg12_quality_report import _frozen_domain_target_binding, _normalize_domain

    return _normalize_domain({
        "domain_id": domain_id, "score": 0, "status": "needs_review",
        "evaluator_version": evaluator_version, "findings": [], "critical_count": 0,
        "warning_count": 0, "evidence_refs": [],
        "evaluated_at": f"frozen:{report_payload['target_artifact']['hash']}",
        "metric_source": "automatic", "human_rubric": {"status": "not_requested"},
        **_frozen_domain_target_binding(report_payload),
    }, label=f"quality_placeholder.{domain_id}")


def _merge_channel_domain_results(
    results: Sequence[Mapping[str, Any]], *, report_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge one deterministic parity result per requested frozen channel."""

    from src.schemas.lg12_quality_report import _frozen_domain_target_binding, _normalize_domain

    domains = [dict(item["domain"]) for item in results]
    if not domains:
        raise QualityAssessmentContractError("Channel QA requires at least one frozen target channel.")
    status_rank = {"blocked": 3, "not_evaluable": 2, "needs_review": 2, "complete": 1}
    status = max((str(item["status"]) for item in domains), key=lambda value: status_rank.get(value, 99))
    findings = {str(item["finding_id"]): dict(item) for domain in domains for item in domain.get("findings") or []}
    evidence = {
        (str(item.get("type") or ""), str(item.get("id") or ""), str(item.get("version") or ""), str(item.get("hash") or "")): dict(item)
        for domain in domains for item in domain.get("evidence_refs") or []
    }
    submetrics: list[dict[str, Any]] = []
    for index, domain in enumerate(domains):
        channel = str(report_payload["target_channels"][index]) if index < len(report_payload["target_channels"]) else str(index)
        for metric in domain.get("submetrics") or []:
            submetrics.append({**dict(metric), "metric_id": f"{channel}:{metric['metric_id']}"})
    critical_count = sum(item["severity"] == "critical" for item in findings.values())
    return _normalize_domain({
        "domain_id": "channel_preview_export_parity",
        "score": min(float(item["score"]) for item in domains), "status": status,
        "evaluator_version": CHANNEL_PREVIEW_EXPORT_PARITY_EVALUATOR_VERSION,
        "findings": [findings[key] for key in sorted(findings)], "critical_count": critical_count,
        "warning_count": len(findings) - critical_count,
        "evidence_refs": [evidence[key] for key in sorted(evidence)],
        "evaluated_at": f"frozen:{report_payload['target_artifact']['hash']}:channels",
        "metric_source": "automatic", "human_rubric": {"status": "not_requested"},
        "submetrics": submetrics, **_frozen_domain_target_binding(report_payload),
    }, label="quality_channel_merge")


def build_lg12_quality_assessment_report(
    db: Session, *, run: AgentRun, detail_page_reference: Mapping[str, Any],
) -> QualityAssessmentReportVersion:
    """Evaluate one exact frozen page and persist its idempotent QA report.

    Caller supplied identifiers are never used as authority: the frozen page,
    its Master lineage and every evaluator input are loaded from persisted
    identities before any domain is evaluated.
    """

    page_id = str(detail_page_reference.get("id") or "")
    page = db.query(DetailPageVersion).filter_by(id=page_id, project_id=run.project_id).one_or_none()
    if page is None or _quality_page_ref(page) != dict(detail_page_reference):
        raise QualityAssessmentContractError("Quality graph target is not the current persisted frozen DetailPageVersion.")
    source, truth, confirmation, master = _quality_lineage_rows(db, run=run, page=page)
    channels = sorted({str(item) for item in list(master.target_channels or [])})
    if not channels:
        raise QualityAssessmentContractError("Commerce Creative Master has no frozen target channel for QA.")
    profile = _ensure_quality_threshold_profile(db, run=run, channels=channels)
    page_ref = _quality_page_ref(page)
    manifest_hash = _frozen_manifest_hash(page)
    report_id = str(uuid5(NAMESPACE_URL, f"sellform:lg12-quality:{run.id}:{page_ref['id']}:{page_ref['version']}:{page_ref['hash']}:{profile.canonical_hash}"))
    existing = db.query(QualityAssessmentReportVersion).filter_by(id=report_id).one_or_none()
    if existing is not None:
        validate_quality_assessment_report_version(db, existing)
        return existing
    source_fidelity = dict(source.source_fidelity_json or {})
    fidelity_status = str(source_fidelity.get("fidelity_status") or source_fidelity.get("status") or "unknown")
    if fidelity_status not in {"complete", "partial", "unknown", "mismatch", "unavailable"}:
        fidelity_status = "unknown"
    input_lineage = {
        "source_snapshot_ref": _exact_reference(source), "truth_ref": _exact_reference(truth),
        "confirmation_ref": _exact_reference(confirmation), "master_ref": _exact_reference(master),
    }
    from src.schemas.lg12_product_intake_golden_dataset import (
        PRODUCT_INTAKE_GOLDEN_DATASET_ID, PRODUCT_INTAKE_GOLDEN_DATASET_VERSION,
        PRODUCT_INTAKE_GOLDEN_DATASET_V2_CONTENT_HASH,
    )
    report: dict[str, Any] = {
        "report_id": report_id, "report_version": 1,
        "schema_version": "lg12-quality-assessment-report-v1",
        "evaluator_bundle_version": QUALITY_EVALUATOR_BUNDLE_VERSION,
        "target_artifact": page_ref, "approved_asset_manifest_hash": manifest_hash,
        "project_id": run.project_id, "workspace_id": run.workspace_id, "creator_run_id": run.id,
        "target_channels": channels, "created_at": f"frozen:{page_ref['hash']}",
        "input_lineage": input_lineage,
        "source_fidelity": {
            "source_kind": source.input_mode, "source_ref": dict(input_lineage["source_snapshot_ref"]),
            "fidelity_status": fidelity_status,
        },
        "dataset_ref": {"id": PRODUCT_INTAKE_GOLDEN_DATASET_ID, "version": PRODUCT_INTAKE_GOLDEN_DATASET_VERSION, "hash": PRODUCT_INTAKE_GOLDEN_DATASET_V2_CONTENT_HASH, "type": "GoldenDataset"},
        "input_mode": source.input_mode,
        "prohibited_inference_count": len(list(truth.prohibited_inference_refs_json or [])),
        "unknown_fact_count": len(list(truth.unknown_refs_json or [])),
        "clarification_count": 0,
        "overall_score": 0,
        "domain_scores": [], "critical_violations": [], "warnings": [], "findings": [],
        "threshold_profile_ref": _exact_reference(profile),
        "verdict": "not_evaluated", "routing_code": "SELLER_REVIEW", "rework_targets": [],
    }
    evaluator_versions = {
        "factual_rights_policy": FACTUAL_RIGHTS_POLICY_EVALUATOR_VERSION,
        "image_identity_quality": IMAGE_IDENTITY_QUALITY_EVALUATOR_VERSION,
        "korean_copy_readability": KOREAN_COPY_READABILITY_EVALUATOR_VERSION,
        "layout_typography_brand_flow": LAYOUT_TYPOGRAPHY_BRAND_FLOW_EVALUATOR_VERSION,
        "channel_preview_export_parity": CHANNEL_PREVIEW_EXPORT_PARITY_EVALUATOR_VERSION,
    }
    report["domain_scores"] = [
        _quality_placeholder_domain(domain, report_payload=report, evaluator_version=evaluator_versions[domain])
        for domain in sorted(QUALITY_DOMAIN_IDS)
    ]
    # Every evaluator receives the same report-binding seed.  It may only read
    # the frozen target/lineage; it cannot read a draft or mutate a page.
    evaluated = {
        "factual_rights_policy": evaluate_factual_rights_policy_domain(db, report_payload=report),
        "image_identity_quality": evaluate_image_identity_quality_domain(db, report_payload=report),
        "korean_copy_readability": evaluate_korean_copy_readability_domain(db, report_payload=report),
        "layout_typography_brand_flow": evaluate_layout_typography_brand_flow_domain(db, report_payload=report),
    }
    channel_results = [
        evaluate_channel_preview_export_parity_domain(db, report_payload=report, channel=channel)
        for channel in channels
    ]
    evaluated["channel_preview_export_parity"] = {
        "domain": _merge_channel_domain_results(channel_results, report_payload=report),
        "critical_violations": [
            violation for result in channel_results for violation in list(result.get("critical_violations") or [])
        ],
    }
    from src.schemas.lg12_quality_report import _frozen_domain_target_binding, _normalize_domain

    final_domains: list[dict[str, Any]] = []
    all_findings: dict[str, dict[str, Any]] = {}
    all_criticals: dict[str, dict[str, Any]] = {}
    for domain_id in sorted(QUALITY_DOMAIN_IDS):
        domain = dict(evaluated[domain_id]["domain"])
        domain["weight"] = QUALITY_DOMAIN_WEIGHTS[domain_id]
        # Individual evaluators intentionally hash their own bounded result.
        # The immutable report adds the published domain weight, therefore the
        # report-bound domain must receive a new canonical evaluation hash
        # rather than retaining a hash for a different semantic body.
        domain.pop("evaluation_hash", None)
        domain = _normalize_domain(
            {**domain, **_frozen_domain_target_binding(report)},
            label=f"quality_domain.{domain_id}", expected_target_binding=_frozen_domain_target_binding(report),
        )
        final_domains.append(domain)
        all_findings.update({str(item["finding_id"]): dict(item) for item in domain.get("findings") or []})
        all_criticals.update({str(item["violation_id"]): dict(item) for item in evaluated[domain_id].get("critical_violations") or []})
    report["domain_scores"] = final_domains
    report["findings"] = [all_findings[key] for key in sorted(all_findings)]
    report["critical_violations"] = [all_criticals[key] for key in sorted(all_criticals)]
    report["overall_score"] = round(sum(float(domain["score"]) * QUALITY_DOMAIN_WEIGHTS[str(domain["domain_id"])] for domain in final_domains), 2)
    report = normalize_quality_assessment_report(report)
    # The report routing is only a bounded pre-aggregation hint.  The graph
    # below consumes the persisted TASK-12.8 Quality Bar result instead.
    row = create_quality_assessment_report(db, payload=report)
    return row


def lg12_quality_report_reference(row: QualityAssessmentReportVersion) -> dict[str, Any]:
    """Return the only report identity a TASK-12.9 checkpoint may retain."""

    return {"id": str(row.id), "version": int(row.version), "hash": str(row.canonical_hash), "type": "QualityAssessmentReportVersion"}


def build_lg12_quality_rework_attempt(
    *,
    run: AgentRun,
    current_page_ref: Mapping[str, Any],
    quality_report_ref: Mapping[str, Any],
    quality_bar: Mapping[str, Any],
    master_ref: Mapping[str, Any],
    attempt_number: int,
    selected_target: Mapping[str, Any] | None = None,
    node_family: str | None = None,
    execution_run_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a bounded, canonical attempt plan from one current Quality Bar.

    This deliberately does not accept arbitrary client target IDs.  The
    targets are copied only from the verified Quality Bar projection and are
    therefore tied to its persisted report/page/run scope.
    """

    from src.services.quality_bar_service import aggregate_quality_bar

    if attempt_number not in {1, 2}:
        raise QualityAssessmentContractError("Automatic quality rework attempts are limited to one or two.")
    report_ref = dict(quality_report_ref)
    # Resolve through the report row rather than accepting a caller's copied
    # result.  The exact canonical Quality Bar result must still match.
    # ``run`` is intentionally not a DB handle, so the graph calls the DB
    # backed validator below before invoking this pure construction helper.
    if (
        str(quality_bar.get("creator_run_id") or "") != str(run.id)
        or dict(quality_bar.get("frozen_target_ref") or {}) != dict(current_page_ref)
        or dict(quality_bar.get("quality_report_ref") or {}) != report_ref
    ):
        raise QualityAssessmentContractError("Quality rework attempt does not match the current frozen Quality Bar scope.")
    routing_code = str(quality_bar.get("routing_code") or "")
    if routing_code not in {"IMAGE_REWORK", "COPY_REWORK", "VISUAL_REWORK", "PLAN_REWORK"}:
        raise QualityAssessmentContractError("Quality rework attempt requires an explicit non-PASS rework route.")
    targets = sorted(
        (dict(item) for item in list(quality_bar.get("rework_targets") or [])),
        key=canonical_hash,
    )
    if not targets:
        raise QualityAssessmentContractError("Quality rework attempt has no frozen typed target.")
    selected = dict(selected_target or targets[0])
    logical_target_ref = dict(selected.pop("logical_target_ref", {}) or {})
    # ``logical_target_ref`` is bounded checkpoint-only retry identity.  The
    # immutable Quality Bar deliberately does not hash it, so exact authority
    # membership must compare the original persisted target body only.
    if selected not in [
        {key: value for key, value in dict(item).items() if key != "logical_target_ref"}
        for item in targets
    ]:
        raise QualityAssessmentContractError("Quality rework attempt target is not present in the persisted Quality Bar.")
    target_ref = dict(selected.get("target_ref") or {})
    if not all(str(target_ref.get(key) or "") for key in ("id", "version", "hash", "type")):
        raise QualityAssessmentContractError("Quality rework attempt requires one exact typed frozen target.")
    inferred_family = {
        "asset": "scene_reassembly", "scene": "scene_reassembly",
        "copy_field": "copy_reassembly",
        "frozen_canvas_element": "layout_plan_reassembly",
        "frozen_section": "layout_plan_reassembly",
        "PagePlanVersion": "layout_plan_reassembly",
        "BrandKitVersion": "style_reassembly",
    }.get(str(target_ref.get("type") or ""), "")
    family = str(node_family or inferred_family).strip()
    if not family:
        raise QualityAssessmentContractError("Quality rework attempt requires a deterministic node family.")
    # No provider operation is invented here.  IMAGE_REWORK may later attach
    # an existing LG-9/LG-11 operation identity after cost approval.
    body = {
        "schema_version": "lg12-quality-rework-attempt-v1",
        # The Quality Bar is owned by the frozen page's source run.  LG-11 may
        # execute the resulting child fork in a different edit run; retain the
        # exact execution reference so recovery cannot mix the two graphs.
        "run_id": str(run.id),
        "execution_run_ref": dict(execution_run_ref or {"id": str(run.id), "type": "AgentRun"}),
        "master_ref": dict(master_ref),
        "previous_detail_page_ref": dict(current_page_ref),
        "triggering_quality_bar_ref": {
            "id": str(quality_bar.get("quality_bar_result_id") or ""), "version": 1,
            "hash": str(quality_bar.get("canonical_hash") or ""), "type": "QualityBarResult",
        },
        "routing_code": routing_code,
        "node_family": family,
        "attempt_number": attempt_number,
        "target_ref": target_ref,
        "logical_target_ref": logical_target_ref or target_ref,
        # Retain only the triggering target in the execution plan.  The full
        # bar remains persisted, while a rework attempt must never accidentally
        # acquire authority over unrelated sections/assets.
        "target_refs": [selected],
        "provider_operation_ref": None,
        "child_detail_page_ref": None,
    }
    if not body["triggering_quality_bar_ref"]["id"] or len(body["triggering_quality_bar_ref"]["hash"]) != 64:
        raise QualityAssessmentContractError("Quality rework attempt requires the canonical Quality Bar identity.")
    if not all(str(body["master_ref"].get(key) or "") for key in ("id", "version", "hash")):
        raise QualityAssessmentContractError("Quality rework attempt requires the frozen Commerce Creative Master reference.")
    if not all(str(dict(body["logical_target_ref"]).get(key) or "") for key in ("id", "version", "hash", "type")):
        raise QualityAssessmentContractError("Quality rework attempt requires one normalized logical target reference.")
    if set(body["execution_run_ref"]) != {"id", "type"} or body["execution_run_ref"].get("type") != "AgentRun" or not str(body["execution_run_ref"].get("id") or ""):
        raise QualityAssessmentContractError("Quality rework attempt requires the exact execution AgentRun reference.")
    plan_hash = canonical_hash(body)
    return {**body, "attempt_plan_hash": plan_hash, "canonical_hash": plan_hash}
