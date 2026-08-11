import datetime
from typing import Any, List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from src.config import settings
from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import ProductProject, ProductFact, FactHistory, FactEvidence, FactSnapshot, Asset, User
from src.services.llm_router import LLMRouter
from src.services.fact_extractor import ExtractedFactCandidate, extract_fact_candidates, normalize_fact_text
from src.services.source_collector import collect_project_sources
from src.services.bulk_fact_parser import parse_bulk_fact_text
from src.services.commerce_policy import CONFIRMED_FACT_STATUSES, fact_status_requires_review
from src.services.fact_evidence_service import (
    approved_fact_snapshot,
    apply_conflicts,
    conflict_group_key,
    fact_board_blockers,
    fact_impact_summary,
    fact_sentence,
    mark_fact_dependents_stale,
    refresh_evidence_board,
    _history,
)

router = APIRouter(prefix="/projects/{project_id}/facts", tags=["facts"])

FactStatus = Literal[
    "extracted", "source_confirmed", "seller_confirmed", "needs_review",
    "conflicted", "rejected",
]


# Pydantic Schemas
class FactCreateSchema(BaseModel):
    fact_text: str
    source_text: Optional[str] = None
    source_asset_id: Optional[str] = None


class FactUpdateSchema(BaseModel):
    fact_text: Optional[str] = None
    source_text: Optional[str] = None
    source_asset_id: Optional[str] = None
    verification_status: Optional[FactStatus] = None
    normalized_value: Optional[str] = None
    normalized_unit: Optional[str] = None
    model_option: Optional[str] = None
    field_key: Optional[str] = None
    scope: Optional[Literal["product", "model", "option", "individual_package", "master_carton"]] = None


class EvidenceResponseSchema(BaseModel):
    id: str
    source_type: str
    source_url: Optional[str] = None
    source_asset_id: Optional[str] = None
    ocr_block_index: Optional[int] = None
    bbox: Optional[dict[str, Any]] = None
    original_text: str
    translated_text: Optional[str] = None
    confidence: Optional[float] = None
    extractor_version: Optional[str] = None
    inspection_id: Optional[str] = None
    ocr_language: Optional[str] = None
    ocr_provider: Optional[str] = None
    ocr_model: Optional[str] = None
    processed_at: Optional[datetime.datetime] = None
    model_config = ConfigDict(from_attributes=True)


class FactBoardCardSchema(BaseModel):
    id: str
    project_id: str
    fact_text: str
    source_text: Optional[str] = None
    source_asset_id: Optional[str] = None
    verification_status: str
    extraction_source: Optional[str] = None
    provider: Optional[str] = None
    model_name: Optional[str] = None
    confidence: Optional[float] = None
    needs_review: bool = True
    risk_flags: Optional[List[str]] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    field_key: Optional[str] = None
    fact_category: Optional[str] = None
    original_text: Optional[str] = None
    translated_text: Optional[str] = None
    normalized_value: Optional[str] = None
    normalized_unit: Optional[str] = None
    scope: Optional[str] = None
    model_option: Optional[str] = None
    extractor_version: Optional[str] = None
    conflict_group_key: Optional[str] = None
    evidences: List[EvidenceResponseSchema] = []
    affected_section_ids: List[str] = []
    impact: dict[str, List[str]] = {}
    model_config = ConfigDict(from_attributes=True)


class FactBoardResponseSchema(BaseModel):
    project_id: str
    cards: List[FactBoardCardSchema]
    usable_for_generation: List[str]
    blocked_fact_ids: List[str]
    blockers: List[dict[str, str]] = []


class ResolveConflictSchema(BaseModel):
    selected_fact_id: str
    note: Optional[str] = None
    risk_acknowledged: bool = False


class ConfirmFactsSchema(BaseModel):
    fact_ids: List[str]
    risk_acknowledged: bool = False
    note: Optional[str] = None


class MergeFactsSchema(BaseModel):
    target_fact_id: str
    source_fact_ids: List[str]
    note: Optional[str] = None


class AddEvidenceSchema(BaseModel):
    source_type: Literal["seller_input", "url", "asset_ocr"] = "seller_input"
    original_text: str
    translated_text: Optional[str] = None
    source_url: Optional[str] = None
    source_asset_id: Optional[str] = None
    bbox: Optional[dict[str, Any]] = None


class OcrCandidateRequestSchema(BaseModel):
    asset_ids: List[str]


class OcrCandidateAssetResultSchema(BaseModel):
    asset_id: str
    status: str
    candidate_count: int = 0
    message: str
    provider: Optional[str] = None
    model: Optional[str] = None
    retryable: bool = False
    job_id: Optional[str] = None


class OcrCandidateResponseSchema(BaseModel):
    project_id: str
    results: List[OcrCandidateAssetResultSchema]
    created_fact_ids: List[str]


class SnapshotResponseSchema(BaseModel):
    id: str
    snapshot_hash: str
    facts_json: List[dict[str, Any]]
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)


class FactResponseSchema(BaseModel):
    id: str
    project_id: str
    fact_text: str
    source_text: Optional[str]
    source_asset_id: Optional[str]
    verification_status: str
    extraction_source: Optional[str] = None
    provider: Optional[str] = None
    model_name: Optional[str] = None
    confidence: Optional[float] = None
    needs_review: bool = True
    risk_flags: Optional[List[str]] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class BulkFactInputSchema(BaseModel):
    fact_text: str
    source_text: Optional[str] = None


class BulkCreateFactsRequestSchema(BaseModel):
    items: List[BulkFactInputSchema]
    default_status: FactStatus


class BulkCreateFactsResponseSchema(BaseModel):
    created_count: int
    duplicate_count: int
    failed_count: int = 0
    created: List[FactResponseSchema]


class BulkParseFactsRequestSchema(BaseModel):
    text: str
    max_items: int = 50


class BulkParseFactItemSchema(BaseModel):
    fact_text: str
    source_text: str


class BulkParseFactsResponseSchema(BaseModel):
    candidate_count: int
    excluded_count: int
    items: List[BulkParseFactItemSchema]


class FailedSourceSchema(BaseModel):

    source: str
    reason: str
    message: str


class AutoExtractFactsResponseSchema(BaseModel):
    project_id: str
    created_count: int
    skipped_duplicates: int
    failed_sources: List[FailedSourceSchema]
    facts: List[FactResponseSchema]


class FactHistoryResponseSchema(BaseModel):
    id: str
    fact_id: str
    previous_fact_text: str
    previous_source_text: Optional[str]
    previous_source_asset_id: Optional[str]
    previous_verification_status: str
    updated_by: str
    updated_at: datetime.datetime
    event_type: str
    previous_payload: Optional[dict[str, Any]] = None
    note: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


def _build_ai_raw_text(collection) -> str:
    chunks: list[str] = []
    for source in collection.sources:
        text = (source.text or "").strip()
        if not text:
            continue
        chunks.append(f"[{source.source}]\n{text}")
    return "\n\n".join(chunks)


def _extract_ai_fact_candidates(collection) -> tuple[list[ExtractedFactCandidate] | None, list[FailedSourceSchema], str | None, str | None]:
    raw_text = _build_ai_raw_text(collection)
    if not raw_text.strip():
        return None, [
            FailedSourceSchema(
                source="ai",
                reason="empty_ai_input",
                message="AI fact extraction skipped because no source text was available.",
            )
        ], None, None

    try:
        router_res = LLMRouter().extract_facts(raw_text=raw_text)
    except Exception as exc:
        return None, [
            FailedSourceSchema(
                source="ai",
                reason="ai_adapter_failed",
                message=f"AI fact extraction failed; deterministic fallback was used instead. ({exc})",
            )
        ], None, None

    ai_failed_sources = [
        FailedSourceSchema(
            source=failed["provider"],
            reason=failed["reason"],
            message=f"{failed['provider']} extraction failed: {failed['reason']}"
        )
        for failed in router_res.failed_sources
    ]

    if router_res.provider == "deterministic":
        if ai_failed_sources:
            ai_failed_sources.append(
                FailedSourceSchema(
                    source="ai",
                    reason="ai_adapter_failed",
                    message="AI fact extraction failed; deterministic fallback was used instead."
                )
            )
        return None, ai_failed_sources, "deterministic", "local-rule-based"

    return router_res.candidates, ai_failed_sources, router_res.provider, router_res.model


# Helper function to check project ownership
def get_verified_project(project_id: str, db: Session, workspace_id: str) -> ProductProject:
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_fact_editor(auth_ctx: dict) -> None:
    if auth_ctx.get("role") not in {"owner", "admin", "member"}:
        raise HTTPException(status_code=403, detail="Fact approval requires an editor role")


def ensure_fact_can_be_confirmed(fact: ProductFact, risk_acknowledged: bool, *, allow_conflicted: bool = False) -> None:
    if not fact.evidences:
        raise HTTPException(status_code=400, detail="A fact must have at least one evidence item before confirmation")
    if fact.verification_status == "conflicted" and not allow_conflicted:
        raise HTTPException(status_code=409, detail="Conflicted facts must be resolved by selecting one candidate")
    if fact.risk_flags and not risk_acknowledged:
        raise HTTPException(status_code=409, detail="Risk acknowledgement is required before confirming this fact")


def verify_source_asset_belongs_to_project(
    source_asset_id: Optional[str],
    project_id: str,
    db: Session,
) -> None:
    if source_asset_id is None:
        return

    asset = db.query(Asset).filter(
        Asset.id == source_asset_id,
        Asset.project_id == project_id,
    ).first()
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source asset does not belong to this project",
        )


@router.get("", response_model=List[FactResponseSchema])
def list_facts(
    project_id: str,
    confirmed_only: bool = False,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_verified_project(project_id, db, workspace.id)

    query = db.query(ProductFact).filter(ProductFact.project_id == project_id)
    if confirmed_only:
        query = query.filter(ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES))
    return query.all()


def _board_card(fact: ProductFact, db: Session) -> FactBoardCardSchema:
    impact = fact_impact_summary(db, fact)
    return FactBoardCardSchema(
        **FactResponseSchema.model_validate(fact).model_dump(),
        field_key=fact.field_key,
        fact_category=fact.fact_category,
        original_text=fact.original_text,
        translated_text=fact.translated_text,
        normalized_value=fact.normalized_value,
        normalized_unit=fact.normalized_unit,
        scope=fact.scope,
        model_option=fact.model_option,
        extractor_version=fact.extractor_version,
        conflict_group_key=fact.conflict_group_key,
        evidences=[EvidenceResponseSchema.model_validate(e) for e in fact.evidences],
        affected_section_ids=impact["page_section_ids"],
        impact=impact,
    )


@router.post("/evidence-board/refresh", response_model=FactBoardResponseSchema)
def refresh_fact_evidence_board(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    project = get_verified_project(project_id, db, auth_ctx["workspace"].id)
    refresh_evidence_board(db, project, auth_ctx["user"].id)
    db.commit()
    return get_fact_evidence_board(project_id, None, None, db, auth_ctx)


@router.get("/evidence-board", response_model=FactBoardResponseSchema)
def get_fact_evidence_board(
    project_id: str,
    verification_status: Optional[FactStatus] = None,
    field_key: Optional[str] = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    get_verified_project(project_id, db, auth_ctx["workspace"].id)
    all_facts = db.query(ProductFact).filter(ProductFact.project_id == project_id).order_by(ProductFact.field_key, ProductFact.created_at).all()
    usable = [fact.id for fact in all_facts if fact.verification_status in CONFIRMED_FACT_STATUSES and not fact.needs_review and fact.evidences]
    facts = [fact for fact in all_facts if (verification_status is None or fact.verification_status == verification_status) and (field_key is None or fact.field_key == field_key)]
    blockers = fact_board_blockers(db, project_id)
    return FactBoardResponseSchema(project_id=project_id, cards=[_board_card(fact, db) for fact in facts], usable_for_generation=usable, blocked_fact_ids=[fact.id for fact in all_facts if fact.id not in usable and fact.verification_status != "rejected"], blockers=blockers)


@router.post("/evidence-board/conflicts/resolve", response_model=FactBoardCardSchema)
def resolve_fact_conflict(
    project_id: str,
    payload: ResolveConflictSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    require_fact_editor(auth_ctx)
    project = get_verified_project(project_id, db, auth_ctx["workspace"].id)
    selected = db.query(ProductFact).filter(ProductFact.id == payload.selected_fact_id, ProductFact.project_id == project_id).first()
    if not selected:
        raise HTTPException(status_code=404, detail="Selected fact card not found")
    ensure_fact_can_be_confirmed(selected, payload.risk_acknowledged, allow_conflicted=True)
    group_key = selected.conflict_group_key or f"{selected.field_key}:{selected.scope}"
    candidates = db.query(ProductFact).filter(ProductFact.project_id == project_id, ProductFact.conflict_group_key == group_key).all()
    changed: list[str] = []
    for fact in candidates:
        event_type = "risk_acknowledged" if fact.id == selected.id and fact.risk_flags and payload.risk_acknowledged else "conflict_resolved"
        _history(db, fact, auth_ctx["user"].id, event_type, payload.note)
        if fact.id == selected.id:
            fact.verification_status = "seller_confirmed"
            fact.needs_review = False
            fact.seller_confirmed_at = datetime.datetime.utcnow()
            fact.seller_confirmed_by = auth_ctx["user"].id
        else:
            fact.verification_status = "rejected"
            fact.needs_review = False
        changed.append(fact.id)
    mark_fact_dependents_stale(db, project.id, changed)
    db.commit()
    db.refresh(selected)
    return _board_card(selected, db)


@router.post("/evidence-board/confirm", response_model=FactBoardResponseSchema)
def confirm_facts(
    project_id: str,
    payload: ConfirmFactsSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    project = get_verified_project(project_id, db, auth_ctx["workspace"].id)
    require_fact_editor(auth_ctx)
    facts = db.query(ProductFact).filter(ProductFact.project_id == project_id, ProductFact.id.in_(list(dict.fromkeys(payload.fact_ids)))).all()
    if len(facts) != len(set(payload.fact_ids)):
        raise HTTPException(status_code=404, detail="One or more fact cards were not found")
    for fact in facts:
        ensure_fact_can_be_confirmed(fact, payload.risk_acknowledged)
    for fact in facts:
        event_type = "risk_acknowledged" if fact.risk_flags and payload.risk_acknowledged else "seller_confirmed"
        _history(db, fact, auth_ctx["user"].id, event_type, payload.note)
        fact.verification_status = "seller_confirmed"
        fact.needs_review = False
        fact.seller_confirmed_at = datetime.datetime.utcnow()
        fact.seller_confirmed_by = auth_ctx["user"].id
    mark_fact_dependents_stale(db, project.id, [fact.id for fact in facts])
    db.commit()
    return get_fact_evidence_board(project_id, None, None, db, auth_ctx)


@router.post("/evidence-board/merge", response_model=FactBoardCardSchema)
def merge_fact_candidates(
    project_id: str,
    payload: MergeFactsSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    project = get_verified_project(project_id, db, auth_ctx["workspace"].id)
    require_fact_editor(auth_ctx)
    target = db.query(ProductFact).filter(ProductFact.project_id == project_id, ProductFact.id == payload.target_fact_id).first()
    sources = db.query(ProductFact).filter(ProductFact.project_id == project_id, ProductFact.id.in_(payload.source_fact_ids)).all()
    if not target or len(sources) != len(set(payload.source_fact_ids)):
        raise HTTPException(status_code=404, detail="Merge candidate was not found")
    if any(source.field_key != target.field_key or source.scope != target.scope or source.model_option != target.model_option for source in sources):
        raise HTTPException(status_code=400, detail="Only candidates with the same item, scope and model can be merged")
    existing = {(item.source_type, item.source_asset_id, item.original_text) for item in target.evidences}
    for source in sources:
        if source.id == target.id:
            continue
        _history(db, source, auth_ctx["user"].id, "merged", payload.note)
        for evidence in list(source.evidences):
            key = (evidence.source_type, evidence.source_asset_id, evidence.original_text)
            if key in existing:
                db.delete(evidence)
            else:
                evidence.fact_id = target.id
                existing.add(key)
        source.verification_status = "rejected"
        source.needs_review = False
    _history(db, target, auth_ctx["user"].id, "evidence_merged", payload.note)
    target.verification_status = "needs_review"
    target.needs_review = True
    mark_fact_dependents_stale(db, project.id, [target.id, *payload.source_fact_ids])
    db.commit(); db.refresh(target)
    return _board_card(target, db)


@router.post("/evidence-board/snapshot", response_model=SnapshotResponseSchema)
def create_fact_snapshot(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    get_verified_project(project_id, db, auth_ctx["workspace"].id)
    require_fact_editor(auth_ctx)
    blockers = fact_board_blockers(db, project_id)
    if blockers:
        raise HTTPException(status_code=409, detail={"message": "Fact review must be completed before snapshot", "blockers": blockers})
    snapshot = approved_fact_snapshot(db, project_id, auth_ctx["user"].id)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.post("/ocr-candidates", response_model=OcrCandidateResponseSchema)
def create_ocr_candidates(
    project_id: str,
    payload: OcrCandidateRequestSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Turn selected reference images into review-only fact candidates."""
    require_fact_editor(auth_ctx)
    project = get_verified_project(project_id, db, auth_ctx["workspace"].id)
    if not payload.asset_ids:
        raise HTTPException(status_code=422, detail="At least one reference image is required")
    from src.services.ocr_copy_generation_service import ingest_ocr_candidates
    result = ingest_ocr_candidates(db, project, payload.asset_ids, auth_ctx["user"].id)
    db.commit()
    return OcrCandidateResponseSchema(**result)


@router.post("/evidence-board/{fact_id}/evidence", response_model=FactBoardCardSchema)
def add_fact_evidence(
    project_id: str,
    fact_id: str,
    payload: AddEvidenceSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    get_verified_project(project_id, db, auth_ctx["workspace"].id)
    require_fact_editor(auth_ctx)
    fact = db.query(ProductFact).filter(ProductFact.id == fact_id, ProductFact.project_id == project_id).first()
    if not fact:
        raise HTTPException(status_code=404, detail="Fact card not found")
    verify_source_asset_belongs_to_project(payload.source_asset_id, project_id, db)
    _history(db, fact, auth_ctx["user"].id, "evidence_added")
    db.add(FactEvidence(fact_id=fact.id, source_type=payload.source_type, source_url=payload.source_url, source_asset_id=payload.source_asset_id, bbox=payload.bbox, original_text=payload.original_text, translated_text=payload.translated_text, extractor_version="evidence-board-v2"))
    db.commit(); db.refresh(fact)
    return _board_card(fact, db)


@router.post("", response_model=FactResponseSchema, status_code=status.HTTP_201_CREATED)
def create_fact(
    project_id: str,
    payload: FactCreateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_verified_project(project_id, db, workspace.id)
    verify_source_asset_belongs_to_project(payload.source_asset_id, project_id, db)

    fact = ProductFact(
        project_id=project_id,
        fact_text=payload.fact_text,
        source_text=payload.source_text,
        source_asset_id=payload.source_asset_id,
        verification_status="extracted",
        needs_review=True,
    )
    db.add(fact)
    db.flush()
    db.add(FactEvidence(
        fact_id=fact.id,
        source_type="seller_input",
        source_asset_id=payload.source_asset_id,
        original_text=payload.source_text or payload.fact_text,
        extractor_version="manual-fact-v1",
        confidence=1.0,
    ))
    db.commit()
    db.refresh(fact)
    return fact


@router.post("/auto-extract", response_model=AutoExtractFactsResponseSchema, status_code=status.HTTP_201_CREATED)
def auto_extract_facts(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_verified_project(project_id, db, workspace.id)

    collection = collect_project_sources(project, db)
    failed_sources = [
        FailedSourceSchema(source=failed.source, reason=failed.reason, message=failed.message)
        for failed in collection.failed_sources
    ]
    ai_candidates, ai_failed_sources, provider, model = _extract_ai_fact_candidates(collection)
    failed_sources.extend(ai_failed_sources)

    if ai_candidates is not None:
        candidates = ai_candidates
    else:
        candidates = extract_fact_candidates(collection.sources)
        provider = provider or "deterministic"
        model = model or "local-rule-based"

    existing_normalized = {
        normalize_fact_text(fact.fact_text)
        for fact in db.query(ProductFact).filter(ProductFact.project_id == project_id).all()
    }

    created_facts: list[ProductFact] = []
    skipped_duplicates = 0

    for candidate in candidates:
        normalized = normalize_fact_text(candidate.fact_text)
        if normalized in existing_normalized:
            skipped_duplicates += 1
            continue

        verification_status = "needs_review" if candidate.risk_flags else "extracted"
        fact = ProductFact(
            project_id=project_id,
            fact_text=candidate.fact_text,
            source_text=candidate.source_text,
            source_asset_id=candidate.source_asset_id,
            verification_status=verification_status,
            extraction_source=candidate.extraction_source,
            provider=provider,
            model_name=model,
            confidence=candidate.confidence,
            needs_review=candidate.needs_review,
            risk_flags=candidate.risk_flags,
        )
        db.add(fact)
        db.flush()
        db.add(FactEvidence(
            fact_id=fact.id,
            source_type=candidate.extraction_source or "auto_extract",
            source_asset_id=candidate.source_asset_id,
            original_text=candidate.source_text or candidate.fact_text,
            extractor_version="auto-extract-v1",
            confidence=candidate.confidence,
        ))
        created_facts.append(fact)
        existing_normalized.add(normalized)

    project.updated_at = datetime.datetime.utcnow()  # type: ignore
    db.commit()

    for fact in created_facts:
        db.refresh(fact)

    return AutoExtractFactsResponseSchema(
        project_id=project_id,
        created_count=len(created_facts),
        skipped_duplicates=skipped_duplicates,
        failed_sources=failed_sources,
        facts=created_facts,
    )


@router.patch("/{fact_id}", response_model=FactResponseSchema)
def update_fact(
    project_id: str,
    fact_id: str,
    payload: FactUpdateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    get_verified_project(project_id, db, workspace.id)
    require_fact_editor(auth_ctx)

    fact = db.query(ProductFact).filter(
        ProductFact.id == fact_id,
        ProductFact.project_id == project_id
    ).first()
    if not fact:
        raise HTTPException(status_code=404, detail="Fact card not found")

    # Check if any change actually occurs to warrant a history log
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        return fact

    if "source_asset_id" in update_data:
        verify_source_asset_belongs_to_project(payload.source_asset_id, project_id, db)
    if update_data.get("verification_status") in {"seller_confirmed", "source_confirmed"}:
        ensure_fact_can_be_confirmed(fact, risk_acknowledged=False)

    # Write change history before modification
    history = FactHistory(
        fact_id=fact.id,
        previous_fact_text=fact.fact_text,
        previous_source_text=fact.source_text,
        previous_source_asset_id=fact.source_asset_id,
        previous_verification_status=fact.verification_status,
        updated_by=user.id,
        event_type="seller_edit",
        previous_payload={
            "field_key": fact.field_key,
            "normalized_value": fact.normalized_value,
            "normalized_unit": fact.normalized_unit,
            "scope": fact.scope,
            "model_option": fact.model_option,
        },
    )
    db.add(history)

    # Apply changes
    for key, value in update_data.items():
        setattr(fact, key, value)
    if any(key in update_data for key in {"field_key", "normalized_value", "normalized_unit", "scope", "model_option"}):
        fact.fact_text = fact_sentence(fact.field_key, fact.normalized_value, fact.normalized_unit, fact.scope)
        if fact.field_key:
            fact.conflict_group_key = conflict_group_key(fact.field_key, fact.scope or "product", fact.model_option)
        if "verification_status" not in update_data:
            fact.verification_status = "needs_review"
            fact.needs_review = True
    if "verification_status" in update_data:
        fact.needs_review = fact_status_requires_review(fact.verification_status)
        if fact.verification_status == "seller_confirmed":
            fact.seller_confirmed_at = datetime.datetime.utcnow()
            fact.seller_confirmed_by = user.id

    mark_fact_dependents_stale(db, project_id, [fact.id])

    # Update project updated_at timestamp as well
    project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
    if project:
        project.updated_at = datetime.datetime.utcnow()  # type: ignore

    apply_conflicts(db, project_id)

    db.commit()
    db.refresh(fact)
    return fact


@router.delete("/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fact(
    project_id: str,
    fact_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_verified_project(project_id, db, workspace.id)

    fact = db.query(ProductFact).filter(
        ProductFact.id == fact_id,
        ProductFact.project_id == project_id
    ).first()
    if not fact:
        raise HTTPException(status_code=404, detail="Fact card not found")

    db.delete(fact)
    db.commit()
    return


@router.get("/{fact_id}/history", response_model=List[FactHistoryResponseSchema])
def list_fact_history(
    project_id: str,
    fact_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_verified_project(project_id, db, workspace.id)

    fact = db.query(ProductFact).filter(
        ProductFact.id == fact_id,
        ProductFact.project_id == project_id
    ).first()
    if not fact:
        raise HTTPException(status_code=404, detail="Fact card not found")

    return db.query(FactHistory).filter(FactHistory.fact_id == fact_id).order_by(FactHistory.updated_at.desc()).all()


@router.post("/bulk/parse", response_model=BulkParseFactsResponseSchema)
def parse_bulk_facts(
    project_id: str,
    payload: BulkParseFactsRequestSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_verified_project(project_id, db, workspace.id)

    max_items = max(1, min(payload.max_items, 50))
    raw_text = payload.text or ""
    candidates = parse_bulk_fact_text(raw_text, max_items=max_items)
    raw_candidate_lines = [
        line.strip()
        for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if len(line.strip()) >= 3
    ]

    items = [
        BulkParseFactItemSchema(
            fact_text=fact_text,
            source_text=(
                "전체 붙여넣기 원문:\n"
                f"{raw_text.strip()}\n\n"
                "추출 후보:\n"
                f"{fact_text}"
            ),
        )
        for fact_text in candidates
    ]

    return BulkParseFactsResponseSchema(
        candidate_count=len(items),
        excluded_count=max(0, len(raw_candidate_lines) - len(items)),
        items=items,
    )


@router.post("/bulk", response_model=BulkCreateFactsResponseSchema, status_code=status.HTTP_201_CREATED)
def bulk_create_facts(
    project_id: str,
    payload: BulkCreateFactsRequestSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_verified_project(project_id, db, workspace.id)

    # 1. 1개 이상 50개 이하 제한 검증
    if not (1 <= len(payload.items) <= 50):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Items size must be between 1 and 50"
        )

    # 2. 기존 프로젝트의 normalized fact 목록 가져오기
    existing_facts = db.query(ProductFact).filter(ProductFact.project_id == project_id).all()
    existing_normalized = {normalize_fact_text(fact.fact_text) for fact in existing_facts}

    created_facts = []
    duplicate_count = 0
    failed_count = 0

    for item in payload.items:
        trimmed_fact = item.fact_text.strip() if item.fact_text else ""
        if not trimmed_fact:
            failed_count += 1
            continue

        normalized = normalize_fact_text(trimmed_fact)
        if normalized in existing_normalized:
            duplicate_count += 1
            continue

        # 3. 사실 카드 생성
        source_text = item.source_text.strip() if (item.source_text and item.source_text.strip()) else trimmed_fact

        fact = ProductFact(
            project_id=project_id,
            fact_text=trimmed_fact,
            source_text=source_text,
            verification_status=payload.default_status,
            needs_review=fact_status_requires_review(payload.default_status),
        )
        db.add(fact)
        db.flush()
        db.add(FactEvidence(
            fact_id=fact.id,
            source_type="seller_input",
            original_text=source_text,
            extractor_version="bulk-manual-v1",
            confidence=1.0,
        ))
        created_facts.append(fact)
        existing_normalized.add(normalized)

    if created_facts:
        # 프로젝트의 updated_at 업데이트
        project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
        if project:
            project.updated_at = datetime.datetime.utcnow()  # type: ignore
        db.commit()
        for fact in created_facts:
            db.refresh(fact)

    return BulkCreateFactsResponseSchema(
        created_count=len(created_facts),
        duplicate_count=duplicate_count,
        failed_count=failed_count,
        created=created_facts
    )
