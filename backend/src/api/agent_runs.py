import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import AgentRun, Brand, ProductProject


router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


# Pydantic Schemas
class ProductInputSchema(BaseModel):
    product_name: str
    description: Optional[str] = None
    product_url: Optional[str] = None
    asset_ids: List[str] = []
    reference_urls: List[str] = []


class AgentRunCreateRequest(BaseModel):
    product_name: str
    description: Optional[str] = None
    product_url: Optional[str] = None
    asset_ids: List[str] = []
    reference_urls: List[str] = []


class AgentRunResponseSchema(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    mode: str
    current_stage: str
    product_input: ProductInputSchema


@router.post("", response_model=AgentRunResponseSchema, status_code=201)
def create_agent_run(
    req: AgentRunCreateRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]

    # 1. Fetch or create a default Brand for project creation
    brand = db.query(Brand).filter(Brand.workspace_id == workspace.id).first()
    if not brand:
        brand = Brand(
            workspace_id=workspace.id,
            name="Default Brand",
            font_tone="modern",
        )
        db.add(brand)
        db.commit()
        db.refresh(brand)

    # 2. Create ProductProject
    project = ProductProject(
        workspace_id=workspace.id,
        brand_id=brand.id,
        name=req.product_name,
        raw_input_text=req.description,
        raw_input_url=req.product_url,
        status="draft",
        current_step="raw_input",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # 3. Create AgentRun
    run_id = str(uuid.uuid4())
    run = AgentRun(
        id=run_id,
        workspace_id=workspace.id,
        project_id=project.id,
        mode="mock",
        status="created",
        current_stage="intake",
        input_snapshot={
            "product_name": req.product_name,
            "description": req.description,
            "product_url": req.product_url,
            "asset_ids": req.asset_ids,
            "reference_urls": req.reference_urls,
        },
        outputs_json={},
        cost_approval_status="not_required",
        created_by=user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    return AgentRunResponseSchema(
        id=run.id,
        project_id=project.id,
        workspace_id=workspace.id,
        mode=run.mode,
        current_stage=run.current_stage,
        product_input=ProductInputSchema(
            product_name=req.product_name,
            description=req.description,
            product_url=req.product_url,
            asset_ids=req.asset_ids,
            reference_urls=req.reference_urls,
        ),
    )
