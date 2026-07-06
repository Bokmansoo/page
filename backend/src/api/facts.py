import datetime
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from src.config import settings
from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import ProductProject, ProductFact, FactHistory, Asset, User
from src.services.llm_router import LLMRouter
from src.services.fact_extractor import ExtractedFactCandidate, extract_fact_candidates, normalize_fact_text
from src.services.source_collector import collect_project_sources
from src.services.bulk_fact_parser import parse_bulk_fact_text

router = APIRouter(prefix="/projects/{project_id}/facts", tags=["facts"])


# Pydantic Schemas
class FactCreateSchema(BaseModel):
    fact_text: str
    source_text: Optional[str] = None
    source_asset_id: Optional[str] = None


class FactUpdateSchema(BaseModel):
    fact_text: Optional[str] = None
    source_text: Optional[str] = None
    source_asset_id: Optional[str] = None
    verification_status: Optional[Literal["unknown", "confirmed", "needs_revision"]] = None


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
    default_status: Literal["unknown", "confirmed", "needs_revision"]


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
        query = query.filter(ProductFact.verification_status == "confirmed")
    return query.all()


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
        verification_status="unknown"
    )
    db.add(fact)
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

        verification_status = "needs_revision" if candidate.risk_flags else "unknown"
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

    # Write change history before modification
    history = FactHistory(
        fact_id=fact.id,
        previous_fact_text=fact.fact_text,
        previous_source_text=fact.source_text,
        previous_source_asset_id=fact.source_asset_id,
        previous_verification_status=fact.verification_status,
        updated_by=user.id
    )
    db.add(history)

    # Apply changes
    for key, value in update_data.items():
        setattr(fact, key, value)

    # Update project updated_at timestamp as well
    project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
    if project:
        project.updated_at = datetime.datetime.utcnow()  # type: ignore

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
        )
        db.add(fact)
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
