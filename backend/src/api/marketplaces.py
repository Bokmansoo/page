import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import ProductProject
from src.services.sales_package_service import SalesPackageService

router = APIRouter(tags=["Marketplaces"])


def _get_project_or_404(project_id: str, db: Session, workspace_id: str) -> ProductProject:
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/projects/{project_id}/marketplace/packages")
def prepare_marketplace_package(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    _get_project_or_404(project_id, db, workspace.id)

    sales_package = SalesPackageService.get_sales_package(project_id, db)
    readiness = sales_package.get("marketplace_readiness", {})
    if not readiness.get("ready"):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Marketplace package is missing required fields.",
                "missing_fields": readiness.get("missing_fields", []),
            },
        )

    return {
        "status": "ready",
        "package_hash": readiness["package_hash"],
        "marketplace_package": sales_package["marketplace_package"],
    }


@router.post("/projects/{project_id}/marketplace/packages/approve")
def approve_marketplace_package(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    user = auth_ctx["user"]
    project = _get_project_or_404(project_id, db, workspace.id)

    sales_package = SalesPackageService.get_sales_package(project_id, db)
    readiness = sales_package.get("marketplace_readiness", {})
    if not readiness.get("ready"):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Marketplace package is missing required fields.",
                "missing_fields": readiness.get("missing_fields", []),
            },
        )

    snapshot = project.intake_snapshot if isinstance(project.intake_snapshot, dict) else {}
    snapshot = dict(snapshot)
    snapshot["marketplace_approval"] = {
        "package_hash": readiness["package_hash"],
        "approved_by": user.id,
        "approved_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    project.intake_snapshot = snapshot
    db.add(project)
    db.commit()

    return {
        "status": "approved",
        "package_hash": readiness["package_hash"],
    }


@router.post("/projects/{project_id}/marketplaces/submit")
def submit_to_marketplace(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    _get_project_or_404(project_id, db, workspace.id)
        
    sales_package = SalesPackageService.get_sales_package(project_id, db)
    market_pkg = sales_package.get("marketplace_package", {})
    readiness = sales_package.get("marketplace_readiness", {})
    
    if not readiness.get("ready"):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Marketplace package is missing required fields.",
                "missing_fields": readiness.get("missing_fields", []),
            },
        )
    if not readiness.get("approved"):
        raise HTTPException(
            status_code=409,
            detail="Marketplace package must be approved before submit.",
        )
            
    return {
        "status": "submitted",
        "message": "마켓플레이스 등록 요청이 승인된 패키지 기준으로 준비되었습니다.",
        "package_hash": readiness["package_hash"],
        "submitted_data": market_pkg
    }
