import datetime
import os
import threading
from collections import defaultdict, deque
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.config import settings
from src.db.database import get_db
from src.db.models import ProductProject, ProductPage, Asset, FigmaPluginExportTicket
from src.services.figma_plugin_ticket_service import (
    FigmaPluginTicketService,
    _digest,
    TicketExpired,
    TicketAlreadyRedeemed,
    TicketNotFound,
    TicketConfigurationError,
)
from src.services.figma_plugin_package_service import (
    FigmaPluginPackageService,
    PackageTooLarge
)

router = APIRouter(tags=["Figma Plugin"])
FAILED_ATTEMPT_WINDOW = datetime.timedelta(minutes=5)
FAILED_ATTEMPT_LIMIT = 10
_failed_redeem_attempts: dict[str, deque[datetime.datetime]] = defaultdict(deque)
_failed_redeem_lock = threading.Lock()


class RedeemTicketRequest(BaseModel):
    code: str


def _redeem_client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _check_redeem_rate_limit(client_key: str, now: datetime.datetime) -> None:
    cutoff = now - FAILED_ATTEMPT_WINDOW
    with _failed_redeem_lock:
        attempts = _failed_redeem_attempts[client_key]
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= FAILED_ATTEMPT_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Too many invalid Figma plugin codes. Try again in five minutes.",
            )


def _record_failed_redeem(client_key: str, now: datetime.datetime) -> None:
    with _failed_redeem_lock:
        _failed_redeem_attempts[client_key].append(now)


def _clear_failed_redeems(client_key: str) -> None:
    with _failed_redeem_lock:
        _failed_redeem_attempts.pop(client_key, None)


def build_plugin_snapshot(project: ProductProject, page: ProductPage, db: Session):
    from src.services.figma_design_payload_builder import build_figma_design_payload
    payload = build_figma_design_payload(project, page, db)

    # Convert cuts image_url to asset_ref
    asset_map = {}
    cuts = payload.get("cuts", [])
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()

    for idx, cut in enumerate(cuts):
        if cut.get("image_url"):
            filename = cut["image_url"].split("/uploads/")[-1]
            matched_asset = next(
                (a for a in assets if a.filename == filename or os.path.basename(a.file_path) == filename),
                None
            )
            if matched_asset:
                asset_ref = f"asset_{idx}"
                asset_map[asset_ref] = matched_asset.id
                cut["image_url"] = asset_ref

    return payload, asset_map


def require_canonical_plugin_payload(payload: dict) -> None:
    cuts = payload.get("cuts")
    if not isinstance(cuts, list) or len(cuts) == 0:
        raise HTTPException(
            status_code=409,
            detail="Figma plugin export requires a valid page draft with at least 1 section.",
        )


@router.post("/projects/{project_id}/page/figma-plugin/tickets")
def issue_ticket(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    user = auth_ctx["user"]

    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(
            status_code=409,
            detail="Page draft not found for this project. Please generate a page draft first."
        )

    payload, asset_map = build_plugin_snapshot(project, page, db)
    require_canonical_plugin_payload(payload)
    try:
        ticket = FigmaPluginTicketService(db).issue(project, user.id, payload, asset_map)
    except TicketConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "ticket_id": ticket.id,
        "code": ticket.code,
        "expires_at": ticket.expires_at.isoformat() + "Z",
        "status": ticket.status,
    }


@router.post("/figma-plugin/import")
def redeem_ticket(
    body: RedeemTicketRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    now = datetime.datetime.utcnow()
    client_key = _redeem_client_key(request)
    _check_redeem_rate_limit(client_key, now)
    try:
        result = FigmaPluginTicketService(db).redeem(body.code)
        _clear_failed_redeems(client_key)
        return {
            "ticket_id": result.ticket_id,
            "schema_version": result.payload.get("schema_version", "1.0"),
            "payload": result.payload,
            "embedded_assets": [],
            "asset_map": result.asset_map,
            "asset_session_token": result.asset_session_token,
            "asset_session_expires_at": result.asset_session_expires_at.isoformat() + "Z",
        }
    except TicketNotFound as e:
        _record_failed_redeem(client_key, now)
        raise HTTPException(status_code=404, detail=str(e))
    except TicketAlreadyRedeemed as e:
        _record_failed_redeem(client_key, now)
        raise HTTPException(status_code=409, detail=str(e))
    except TicketExpired as e:
        _record_failed_redeem(client_key, now)
        raise HTTPException(status_code=410, detail=str(e))
    except TicketConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/figma-plugin/assets/{asset_ref}")
def get_plugin_asset(
    asset_ref: str,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    session_token = authorization.split("Bearer ")[1].strip()
    session_token_hash = _digest(session_token, settings.SELLFORM_FIGMA_PLUGIN_TICKET_SECRET)

    now = datetime.datetime.utcnow()
    ticket = db.query(FigmaPluginExportTicket).filter(
        FigmaPluginExportTicket.session_token_hash == session_token_hash,
        FigmaPluginExportTicket.session_expires_at >= now
    ).first()

    if not ticket:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    asset_map = ticket.asset_map_json or {}
    asset_id = asset_map.get(asset_ref)
    if not asset_id:
        raise HTTPException(status_code=404, detail="Asset reference not found in session")

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset or not os.path.exists(asset.file_path):
        raise HTTPException(status_code=404, detail="Asset file not found")

    return FileResponse(asset.file_path, media_type=asset.mime_type)


@router.get("/projects/{project_id}/page/figma-plugin/package.json")
def download_package(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]

    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(
            status_code=409,
            detail="Page draft not found for this project. Please generate a page draft first."
        )

    payload, asset_map = build_plugin_snapshot(project, page, db)
    require_canonical_plugin_payload(payload)

    try:
        package = FigmaPluginPackageService(db).build_package(payload, asset_map)
        return package
    except PackageTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))


@router.options("/figma-plugin/assets/{asset_ref}")
def options_plugin_asset():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400"
        }
    )


@router.options("/figma-plugin/import")
def options_redeem_ticket():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400"
        }
    )
