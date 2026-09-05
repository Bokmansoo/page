"""TASK-12.10 immutable promotion and final-export authority.

This service intentionally consumes only persisted frozen identities.  A
caller can select neither a Quality Bar verdict nor an arbitrary page/report:
the current final DetailPage, its exact immutable QA report, and the
deterministic Quality Bar are re-derived inside the service every time.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from typing import Any, Mapping

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    DetailPageVersion,
    ExportArtifact,
    ProductProject,
    QualityAssessmentReportVersion,
    QualityPromotionVersion,
)
from src.services.quality_assessment_service import (
    QualityAssessmentContractError,
    _page_snapshot_reference,
    validate_quality_assessment_report_version,
)
from src.services.quality_bar_service import QualityBarContractError, aggregate_quality_bar


QUALITY_PROMOTION_SCHEMA_VERSION = "lg12-quality-promotion-v1"
_CHANNELS = frozenset({"smartstore", "coupang"})


class QualityPromotionGateError(ValueError):
    """A final/preview/export request did not satisfy the frozen PASS gate."""


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _snapshot(version: DetailPageVersion) -> dict[str, Any]:
    value = version.sections_json
    return deepcopy(value) if isinstance(value, dict) else {}


def _has_lg12_quality_lineage(version: DetailPageVersion) -> bool:
    return isinstance(_snapshot(version).get("lg12_quality_lineage"), dict)


def _exact_ref(row: Any) -> dict[str, Any]:
    return {"id": str(row.id), "version": int(row.version), "hash": str(row.canonical_hash)}


def _current_page(db: Session, *, project_id: str) -> DetailPageVersion:
    page = (
        db.query(DetailPageVersion)
        .filter_by(project_id=project_id, is_final=True)
        .order_by(DetailPageVersion.created_at.desc(), DetailPageVersion.id.desc())
        .first()
    )
    if page is None:
        raise QualityPromotionGateError("A current frozen DetailPageVersion is required before final promotion.")
    return page


def _page_lineage(version: DetailPageVersion) -> dict[str, Any]:
    lineage = dict(_snapshot(version).get("lg12_quality_lineage") or {})
    if lineage.get("schema_version") != "lg12-detail-page-quality-lineage-v1":
        raise QualityPromotionGateError("The frozen page is missing its LG-12 quality lineage.")
    return lineage


def _require_current_quality_inputs(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    page_id: str | None = None,
    require_pass: bool = True,
) -> tuple[ProductProject, DetailPageVersion, AgentRun, QualityAssessmentReportVersion, dict[str, Any]]:
    project, current, run, report, quality_bar = _load_current_quality_lineage(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        page_id=page_id,
    )
    if str(run.current_stage) != "quality_promotion_ready" or str(run.status) != "completed":
        raise QualityPromotionGateError("Final promotion is unavailable while rework, review, or QA is still active.")
    if require_pass and (quality_bar.get("verdict") != "PASS" or quality_bar.get("routing_code") != "PASS"):
        raise QualityPromotionGateError("Final promotion and export require the current Quality Bar PASS result.")
    return project, current, run, report, quality_bar


def _load_current_quality_lineage(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    page_id: str | None = None,
) -> tuple[ProductProject, DetailPageVersion, AgentRun, QualityAssessmentReportVersion, dict[str, Any]]:
    """Load the immutable current QA lineage without treating rework as an error.

    Promotion is deliberately available only after a completed PASS, but the
    seller-facing status view must still expose a valid immutable FAIL or
    NEEDS_REVIEW result while the corresponding quality route is active.
    """
    project = db.query(ProductProject).filter_by(id=project_id, workspace_id=workspace_id).one_or_none()
    if project is None:
        raise QualityPromotionGateError("Project/workspace identity is unavailable for final promotion.")
    current = _current_page(db, project_id=project_id)
    if page_id is not None and str(page_id) != current.id:
        raise QualityPromotionGateError("A stale or non-current frozen page cannot be promoted or exported.")
    page_ref = _page_snapshot_reference(current)
    lineage = _page_lineage(current)
    run_id = str(lineage.get("creator_run_id") or "")
    run = db.query(AgentRun).filter_by(id=run_id, workspace_id=workspace_id, project_id=project_id).one_or_none()
    if run is None:
        raise QualityPromotionGateError("The frozen page creator run is not in this workspace/project.")
    report = (
        db.query(QualityAssessmentReportVersion)
        .filter_by(
            workspace_id=workspace_id,
            project_id=project_id,
            creator_run_id=run.id,
            target_detail_page_version_id=current.id,
            target_artifact_version=page_ref["version"],
            target_artifact_hash=page_ref["hash"],
        )
        .order_by(QualityAssessmentReportVersion.created_at.desc(), QualityAssessmentReportVersion.id.desc())
        .first()
    )
    if report is None:
        raise QualityPromotionGateError("The current frozen page has no immutable QA report.")
    try:
        validate_quality_assessment_report_version(db, report)
        quality_bar = aggregate_quality_bar(db, report_ref=_exact_ref(report))
    except (QualityAssessmentContractError, QualityBarContractError) as exc:
        raise QualityPromotionGateError("The persisted QA/Quality Bar lineage is invalid.") from exc
    if dict(quality_bar.get("frozen_target_ref") or {}) != page_ref:
        raise QualityPromotionGateError("Quality Bar does not bind to the current frozen page.")
    return project, current, run, report, quality_bar


def _promotion_payload(
    *, page: DetailPageVersion, run: AgentRun, report: QualityAssessmentReportVersion, quality_bar: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = _snapshot(page)
    lineage = _page_lineage(page)
    page_ref = _page_snapshot_reference(page)
    report_ref = _exact_ref(report)
    payload = {
        "promotion_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"sellform:lg12-promotion:{page.id}:{report.canonical_hash}:{quality_bar['canonical_hash']}")),
        "promotion_version": 1,
        "schema_version": QUALITY_PROMOTION_SCHEMA_VERSION,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "creator_run_id": run.id,
        "detail_page_ref": page_ref,
        "quality_report_ref": report_ref,
        "quality_bar_ref": {"id": str(quality_bar["quality_bar_result_id"]), "hash": str(quality_bar["canonical_hash"])},
        "master_ref": dict(lineage.get("master_ref") or {}),
        "page_plan_ref": dict((((snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {}).get("planning_refs") or {}).get("page_plan") or {}),
        "brand_kit_ref": dict((((snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {}).get("brand_kit_ref") or {})),
        "target_channels": sorted(set(report.target_channels_json or [])),
    }
    if not set(payload["target_channels"]).issubset(_CHANNELS) or not payload["target_channels"]:
        raise QualityPromotionGateError("Promotion target channels are invalid.")
    return payload


def promote_current_quality_page(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    actor_id: str,
    requested_page_id: str | None = None,
) -> QualityPromotionVersion:
    """Create one immutable idempotent promotion record from current PASS only."""

    _project, page, run, report, quality_bar = _require_current_quality_inputs(
        db, workspace_id=workspace_id, project_id=project_id, page_id=requested_page_id,
    )
    # The authority is a property of the current frozen PASS triple, not of
    # the HTTP caller.  Keep `created_by` as row audit metadata, but exclude it
    # from the immutable promotion identity so an authorized retry remains
    # idempotent.
    payload = _promotion_payload(page=page, run=run, report=report, quality_bar=quality_bar)
    payload_without_hash = dict(payload)
    canonical_hash = _canonical_hash(payload_without_hash)
    existing = db.query(QualityPromotionVersion).filter_by(id=payload["promotion_id"]).one_or_none()
    if existing is not None:
        if existing.canonical_hash != canonical_hash:
            raise QualityPromotionGateError("Existing promotion identity does not match the current frozen PASS authority.")
        return existing
    row = QualityPromotionVersion(
        id=payload["promotion_id"], workspace_id=workspace_id, project_id=project_id, creator_run_id=run.id,
        version=1, schema_version=QUALITY_PROMOTION_SCHEMA_VERSION,
        detail_page_version_id=page.id, detail_page_schema_version=page_ref_version(page), detail_page_hash=page_ref_hash(page),
        quality_report_id=report.id, quality_report_version=report.version, quality_report_hash=report.canonical_hash,
        quality_bar_result_id=str(quality_bar["quality_bar_result_id"]), quality_bar_hash=str(quality_bar["canonical_hash"]),
        master_ref_json=payload["master_ref"], page_plan_ref_json=payload["page_plan_ref"], brand_kit_ref_json=payload["brand_kit_ref"],
        target_channels_json=payload["target_channels"], canonical_hash=canonical_hash, created_by=actor_id,
    )
    # Two independent HTTP workers can both derive the same immutable PASS
    # authority before either commits.  The PostgreSQL unique constraint stays
    # the source of truth; a savepoint lets the losing transaction reload that
    # exact immutable row instead of surfacing a raw 23505 to the seller.
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        db.expire_all()
        existing = db.query(QualityPromotionVersion).filter_by(id=payload["promotion_id"]).one_or_none()
        if existing is not None and existing.canonical_hash == canonical_hash:
            return existing
        raise


def page_ref_version(page: DetailPageVersion) -> str:
    return str(_page_snapshot_reference(page)["version"])


def page_ref_hash(page: DetailPageVersion) -> str:
    return str(_page_snapshot_reference(page)["hash"])


def require_current_quality_export_artifact(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    file_path: str,
) -> QualityPromotionVersion | None:
    """Apply the LG-12 final-export authority to one persisted file path.

    Ordinary project assets have no ``ExportArtifact`` record and retain the
    existing workspace-scoped file contract.  When the file is referenced by
    an LG-12 frozen export, its persisted page and channel token are the only
    authority accepted by both protected export downloads and generic asset
    retrieval.
    """

    # Keep channel-token parsing in the existing frozen export contract;
    # filename/extension guesses would make HTML/ZIP protection bypassable.
    from src.services.export_service import parse_lg11_export_artifact_token

    artifacts = (
        db.query(ExportArtifact)
        .filter_by(project_id=project_id, file_path=file_path)
        .order_by(ExportArtifact.created_at.desc(), ExportArtifact.id.desc())
        .all()
    )
    protected: list[tuple[ExportArtifact, DetailPageVersion, dict[str, str]]] = []
    for artifact in artifacts:
        version = (
            db.query(DetailPageVersion)
            .filter_by(id=artifact.version_id, project_id=project_id)
            .one_or_none()
        )
        if version is None or not _has_lg12_quality_lineage(version):
            continue
        identity = parse_lg11_export_artifact_token(str(artifact.artifact_type or ""))
        if identity is None:
            raise QualityPromotionGateError("The frozen export artifact has no valid channel identity.")
        protected.append((artifact, version, identity))

    if not protected:
        return None

    # A single persisted file cannot safely represent two LG-12 page/channel
    # authorities.  Do not let ordering choose one if storage metadata was
    # accidentally or maliciously reused.
    authorities = {(version.id, identity["channel"]) for _artifact, version, identity in protected}
    if len(authorities) != 1:
        raise QualityPromotionGateError("The frozen export file has ambiguous page or channel authority.")

    _artifact, version, identity = protected[0]
    return require_current_quality_promotion(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        page_id=version.id,
        channel=identity["channel"],
    )


def require_current_quality_promotion(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    page_id: str,
    channel: str | None = None,
) -> QualityPromotionVersion | None:
    """Return the exact current LG-12 promotion authority or fail closed.

    Pages created before the LG-12 lineage contract keep their established
    LG-10/LG-11 export semantics. Once a page declares LG-12 quality lineage,
    there is no legacy fallback: every public final/export entry uses this
    gate.
    """

    requested = db.query(DetailPageVersion).filter_by(id=page_id, project_id=project_id).one_or_none()
    if requested is None:
        raise QualityPromotionGateError("Requested frozen page is unavailable.")
    if not _has_lg12_quality_lineage(requested):
        return None
    _project, page, run, report, quality_bar = _require_current_quality_inputs(
        db, workspace_id=workspace_id, project_id=project_id, page_id=page_id,
    )
    if channel is not None and channel not in _CHANNELS:
        raise QualityPromotionGateError("Unsupported channel export request.")
    if channel is not None and channel not in set(report.target_channels_json or []):
        raise QualityPromotionGateError("The current PASS report is not export-ready for this channel.")
    row = db.query(QualityPromotionVersion).filter_by(
        workspace_id=workspace_id, project_id=project_id, creator_run_id=run.id,
        detail_page_version_id=page.id, detail_page_hash=page_ref_hash(page),
        quality_report_id=report.id, quality_report_version=report.version, quality_report_hash=report.canonical_hash,
        quality_bar_hash=str(quality_bar["canonical_hash"]),
    ).one_or_none()
    if row is None:
        raise QualityPromotionGateError("The current Quality Bar PASS page has not been finally promoted.")
    if channel is not None and channel not in set(row.target_channels_json or []):
        raise QualityPromotionGateError("The final promotion does not authorize this channel.")
    return row


def quality_status_projection(db: Session, *, workspace_id: str, project_id: str) -> dict[str, Any]:
    """Bounded public summary; never expose raw evaluator/report payloads."""

    page = _current_page(db, project_id=project_id)
    if not _has_lg12_quality_lineage(page):
        return {"status": "not_available", "current_page_ref": {"id": page.id}, "promotion_status": "not_required", "export_readiness": {}}
    try:
        _project, current, run, report, bar = _load_current_quality_lineage(
            db, workspace_id=workspace_id, project_id=project_id, page_id=page.id,
        )
        promotion = db.query(QualityPromotionVersion).filter_by(
            project_id=project_id, detail_page_version_id=current.id, quality_bar_hash=str(bar["canonical_hash"]),
        ).one_or_none()
        verdict = str(bar["verdict"])
        readiness = {
            channel: bool(verdict == "PASS" and promotion and channel in set(promotion.target_channels_json or []))
            for channel in sorted(set(report.target_channels_json or []))
        }
        return {
            "status": "pass" if promotion else ("ready_to_promote" if verdict == "PASS" else "needs_attention"),
            "current_page_ref": _page_snapshot_reference(current),
            "quality_verdict": verdict,
            "score": bar.get("overall_score"),
            "promotion_status": "promoted" if promotion else ("ready" if verdict == "PASS" else "blocked"),
            "export_readiness": readiness,
            "review_required": verdict == "NEEDS_REVIEW",
            "attempt_summary": _attempt_summary(run),
        }
    except QualityPromotionGateError as exc:
        return {
            "status": "needs_attention", "current_page_ref": _page_snapshot_reference(page),
            "quality_verdict": "NEEDS_REVIEW", "promotion_status": "blocked", "export_readiness": {},
            "review_required": True, "message": str(exc), "attempt_summary": {"automatic_rework_count": 0},
        }


def _attempt_summary(run: AgentRun) -> dict[str, int]:
    """Return only the bounded rework count from persisted run projection."""

    outputs = dict(run.outputs_json or {})
    quality = dict(outputs.get("quality") or {})
    attempts = quality.get("attempt_ledger")
    return {"automatic_rework_count": len(attempts) if isinstance(attempts, list) else 0}
