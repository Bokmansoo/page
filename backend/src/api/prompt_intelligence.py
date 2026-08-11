from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace, require_roles
from src.db.database import get_db
from src.db.models import PromptPack, PromptPackVersion
from src.services.prompt_intelligence_service import (
    classify_category, create_proposal, evaluate_classifier, seed_prompt_packs,
    transition_pack_version,
)

router = APIRouter(prefix="/prompt-intelligence", tags=["prompt-intelligence"])


class ProposalRequest(BaseModel):
    pack_type: Literal["category", "channel"]
    pack_key: str = Field(min_length=1, max_length=100)
    content: dict[str, Any] | None = None


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    explicit_category: str | None = None


def _version_view(version: PromptPackVersion, pack: PromptPack) -> dict[str, Any]:
    return {
        "id": version.id, "pack_id": pack.id, "pack_type": pack.pack_type,
        "pack_key": pack.pack_key, "locale": pack.locale, "version": version.version,
        "status": version.status, "content_hash": version.content_hash,
        "evaluation_score": version.evaluation_score,
        "evaluation_dataset_version": version.evaluation_dataset_version,
        "actors": {"created_by": version.created_by, "validated_by": version.validated_by,
                   "approved_by": version.approved_by, "activated_by": version.activated_by},
        "created_at": version.created_at, "activated_at": version.activated_at,
    }


@router.get("/packs")
def list_packs(db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    workspace = auth_ctx["workspace"]
    rows = db.query(PromptPackVersion, PromptPack).join(PromptPack).filter(
        PromptPack.workspace_id == workspace.id).order_by(
        PromptPack.pack_type, PromptPack.pack_key, PromptPackVersion.version.desc()).all()
    return [_version_view(version, pack) for version, pack in rows]


@router.post("/packs/seed")
def seed_packs(db: Session = Depends(get_db), auth_ctx: dict = Depends(require_roles(["owner", "admin"]))):
    versions = seed_prompt_packs(db, auth_ctx["workspace"].id, auth_ctx["user"].id)
    return {"seeded": len(versions), "active_version_ids": [item.id for item in versions]}


@router.post("/packs/propose")
def propose_pack(payload: ProposalRequest, db: Session = Depends(get_db),
                 auth_ctx: dict = Depends(require_roles(["owner", "admin"]))):
    try:
        version = create_proposal(db, auth_ctx["workspace"].id, auth_ctx["user"].id,
                                  payload.pack_type, payload.pack_key, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pack = db.query(PromptPack).filter_by(id=version.pack_id).one()
    return _version_view(version, pack)


def _transition(version_id: str, target: str, db: Session, auth_ctx: dict):
    try:
        version = transition_pack_version(db, auth_ctx["workspace"].id, auth_ctx["user"].id,
                                          version_id, target)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    pack = db.query(PromptPack).filter_by(id=version.pack_id).one()
    return _version_view(version, pack)


@router.post("/versions/{version_id}/validate")
def validate_version(version_id: str, db: Session = Depends(get_db),
                     auth_ctx: dict = Depends(require_roles(["owner", "admin"]))):
    return _transition(version_id, "validation_pending", db, auth_ctx)


@router.post("/versions/{version_id}/approve")
def approve_version(version_id: str, db: Session = Depends(get_db),
                    auth_ctx: dict = Depends(require_roles(["owner", "admin"]))):
    return _transition(version_id, "approved", db, auth_ctx)


@router.post("/versions/{version_id}/activate")
def activate_version(version_id: str, db: Session = Depends(get_db),
                     auth_ctx: dict = Depends(require_roles(["owner", "admin"]))):
    return _transition(version_id, "active", db, auth_ctx)


@router.post("/versions/{version_id}/deprecate")
def deprecate_version(version_id: str, db: Session = Depends(get_db),
                      auth_ctx: dict = Depends(require_roles(["owner", "admin"]))):
    return _transition(version_id, "deprecated", db, auth_ctx)


@router.post("/evaluate")
def evaluate(db: Session = Depends(get_db), auth_ctx: dict = Depends(require_roles(["owner", "admin"]))):
    report = evaluate_classifier(db, auth_ctx["workspace"].id, auth_ctx["user"].id)
    return {"id": report.id, "dataset_version": report.dataset_version,
            "classifier_version": report.classifier_version, "accuracy": report.accuracy,
            "safe_fallback_rate": report.safe_fallback_rate, "input_hash": report.input_hash,
            "output_hash": report.output_hash, "report": report.report_json}


@router.post("/classify")
def classify(payload: ClassifyRequest, auth_ctx: dict = Depends(get_current_user_and_workspace)):
    return classify_category(payload.text, payload.explicit_category)

