"""Permission-safe browser extension capture endpoints (V2 Sprint 8).

This is an intake bridge for material a seller explicitly selected in the
current browser tab.  It never acts as a scraper and it never receives site
cookies, credentials, order information, or browser session data.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import io
import os
import re
import secrets
import uuid
from html import escape
from html.parser import HTMLParser
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, status
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.config import settings
from src.db.database import get_db
from src.db.models import (
    Asset,
    AuditLog,
    BrowserExtensionCapture,
    BrowserExtensionConnection,
    ProductProject,
    SourceCapture,
)


router = APIRouter(prefix="/browser-extension", tags=["browser-extension"])

CODE_TTL_MINUTES = 10
TOKEN_TTL_HOURS = 12
MAX_SELECTED_TEXT = 20_000
MAX_SELECTED_HTML = 30_000
MAX_IMAGES = 20
MAX_DOCUMENT_ORDER = 30
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_IMAGE_BYTES = 24 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
SUPPORTED_IMAGE_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
SUPPORTED_ADAPTERS = {
    "generic-visible-selection-v1",
    "generic-manual-selection-v1",
    "1688-visible-product-v1",
    "taobao-visible-product-v1",
    "xiaohongshu-visible-product-v1",
    "coupang-visible-product-v1",
    "smartstore-visible-product-v1",
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


def _connection_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part = lambda: "".join(secrets.choice(alphabet) for _ in range(5))
    return f"SFC-{part()}-{part()}"


def _token() -> str:
    return f"sfext_{secrets.token_urlsafe(32)}"


def _domain(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="Capture URL must be a valid http(s) page URL.")
    return parsed.hostname or parsed.netloc


def _safe_image_urls(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values[:MAX_IMAGES]:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail="Selected image URLs must be http(s) URLs.")
        normalized = value.strip()
        if normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    ("browser_auth", r"(?i)(cookie|set-cookie|authorization\s*:|bearer\s+[a-z0-9._-]{8,}|session(?:id|_id)?)"),
    ("password", r"(?i)(password\s*[:=]|비밀번호\s*[:=])"),
    ("payment_card", r"\b(?:\d[ -]*?){13,19}\b"),
    ("korean_phone", r"\b01[0-9][- ]?\d{3,4}[- ]?\d{4}\b"),
    ("email", r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ("order_member", r"(?i)(주문번호|주문 내역|회원 정보|배송지|recipient|order\s*(?:id|number))"),
]


def _sensitive_findings(*texts: str | None) -> list[str]:
    joined = "\n".join(value for value in texts if value)
    return [label for label, pattern in SENSITIVE_PATTERNS if re.search(pattern, joined)]


class _SafeSelectionHTML(HTMLParser):
    """Permit simple selected text markup and reject executable/page-control HTML."""

    allowed = {"p", "br", "ul", "ol", "li", "strong", "b", "em", "i", "span", "div", "table", "tbody", "tr", "td", "th", "h1", "h2", "h3"}
    forbidden = {"script", "style", "iframe", "object", "embed", "form", "input", "button", "textarea", "link", "meta", "svg", "math"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.unsafe = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.forbidden or tag not in self.allowed:
            self.unsafe = True
            return
        for key, value in attrs:
            if key.lower().startswith("on") or (value and re.search(r"(?i)(javascript:|data:text/html|vbscript:)", value)):
                self.unsafe = True
        if tag == "br":
            self.parts.append("\n")
        elif tag in {"p", "li", "tr", "h1", "h2", "h3", "div"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def _sanitize_selected_html(value: str | None) -> tuple[str | None, str]:
    if not value:
        return None, ""
    parser = _SafeSelectionHTML()
    try:
        parser.feed(value)
        parser.close()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Selected HTML could not be safely parsed.") from exc
    text = parser.text()
    if parser.unsafe:
        raise HTTPException(status_code=422, detail="Selected HTML contains unsafe or unsupported page controls.")
    # Persist a deliberately inert representation.  It retains the seller's
    # selected text but can never execute when later displayed in a review UI.
    return (f"<pre>{escape(text)}</pre>" if text else None), text


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionCodeRequest(StrictModel):
    extension_name: str = Field(default="Sellform Product Capture", max_length=100)
    extension_version: str = Field(default="0.2.0", max_length=50)


class ExchangeCodeRequest(StrictModel):
    connection_code: str = Field(min_length=8, max_length=50)
    extension_name: str = Field(default="Sellform Product Capture", max_length=100)
    extension_version: str = Field(default="0.2.0", max_length=50)


class SelectedDocumentItem(StrictModel):
    kind: Literal["text", "image", "heading", "spec"]
    value: str = Field(min_length=1, max_length=3000)
    order: int = Field(ge=0, le=999)


class CapturedImageBlob(StrictModel):
    """A browser-selected image/screenshot sent as an actual byte payload."""

    data_url: str = Field(min_length=32, max_length=12_000_000)
    filename: str = Field(default="browser-capture.png", min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2000)
    role: Literal["selected_image", "screenshot"] = "selected_image"


class ExtensionCapturePayload(StrictModel):
    url: str = Field(min_length=8, max_length=1000)
    page_title: str | None = Field(default=None, max_length=1000)
    language: str | None = Field(default=None, max_length=20)
    site_adapter: str = Field(default="generic-visible-selection-v1", max_length=100)
    selected_text: str | None = Field(default=None, max_length=MAX_SELECTED_TEXT)
    selected_html: str | None = Field(default=None, max_length=MAX_SELECTED_HTML)
    selected_image_urls: list[str] = Field(default_factory=list, max_length=MAX_IMAGES)
    selected_image_blobs: list[CapturedImageBlob] = Field(default_factory=list, max_length=MAX_IMAGES)
    screenshot: CapturedImageBlob | None = None
    document_order: list[SelectedDocumentItem] = Field(default_factory=list, max_length=MAX_DOCUMENT_ORDER)
    captured_at: dt.datetime | None = None

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("site_adapter")
    @classmethod
    def supported_adapter(cls, value: str) -> str:
        if value not in SUPPORTED_ADAPTERS:
            raise ValueError("Unknown site adapter. Use an approved adapter or generic visible selection.")
        return value


class SubmitCaptureRequest(ExtensionCapturePayload):
    project_id: str = Field(min_length=1, max_length=36)


def _decode_image_blob(blob: CapturedImageBlob) -> dict[str, Any]:
    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)", blob.data_url, flags=re.S)
    if not match:
        raise HTTPException(status_code=422, detail="Only base64 JPEG, PNG, or WebP image data URLs are accepted.")
    declared_mime, encoded = match.groups()
    try:
        content = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Image data is not valid base64.") from exc
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail=f"Each captured image must be between 1 byte and {MAX_IMAGE_BYTES // 1024 // 1024}MB.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            actual_format = (image.format or "").upper()
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Declared image MIME type does not match a valid image file.") from exc
    actual_mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(actual_format)
    if actual_mime is None or actual_mime != declared_mime:
        raise HTTPException(status_code=422, detail="Declared image MIME type does not match the actual image file.")
    if not width or not height or width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(status_code=422, detail="Image dimensions are invalid or too large.")
    if blob.source_url:
        _safe_image_urls([blob.source_url])
    return {
        "content": content,
        "mime_type": actual_mime,
        "extension": SUPPORTED_IMAGE_MIME[actual_mime],
        "width": width,
        "height": height,
        "content_hash": hashlib.sha256(content).hexdigest(),
        "filename": re.sub(r"[^A-Za-z0-9._-]", "_", blob.filename).strip("._") or f"capture.{SUPPORTED_IMAGE_MIME[actual_mime]}",
        "source_url": blob.source_url,
        "role": blob.role,
    }


def _decoded_blobs(payload: ExtensionCapturePayload) -> list[dict[str, Any]]:
    blobs = list(payload.selected_image_blobs)
    if payload.screenshot:
        if payload.screenshot.role != "screenshot":
            raise HTTPException(status_code=422, detail="The screenshot field must use role=screenshot.")
        blobs.append(payload.screenshot)
    if len(blobs) > MAX_IMAGES + 1:
        raise HTTPException(status_code=422, detail="Too many captured image files.")
    decoded = [_decode_image_blob(blob) for blob in blobs]
    if sum(len(item["content"]) for item in decoded) > MAX_CAPTURE_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="Combined captured image files exceed the 24MB limit.")
    return decoded


def _connection_from_token(
    x_sellform_extension_token: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> BrowserExtensionConnection:
    if not x_sellform_extension_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Extension token is required.")
    connection = db.query(BrowserExtensionConnection).filter(
        BrowserExtensionConnection.token_hash == _hash(x_sellform_extension_token)
    ).first()
    if not connection or connection.token_revoked_at or not connection.token_expires_at or connection.token_expires_at <= _now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Extension token is invalid, revoked, or expired.")
    connection.last_used_at = _now()
    db.commit()
    return connection


def _preview(payload: ExtensionCapturePayload) -> dict[str, Any]:
    domain = _domain(payload.url)
    images = _safe_image_urls(payload.selected_image_urls)
    safe_html, html_text = _sanitize_selected_html(payload.selected_html)
    findings = _sensitive_findings(payload.selected_text, html_text, payload.page_title, *(item.value for item in payload.document_order))
    if findings:
        raise HTTPException(
            status_code=422,
            detail={"code": "sensitive_capture_blocked", "message": "Sensitive/member/payment/authentication data cannot be transferred.", "findings": findings},
        )
    decoded = _decoded_blobs(payload)
    return {
        "url": payload.url,
        "domain": domain,
        "page_title": payload.page_title,
        "language": payload.language,
        "site_adapter": payload.site_adapter,
        "selected_text": payload.selected_text or "",
        "selected_text_length": len(payload.selected_text or ""),
        "safe_selected_html": safe_html,
        "selected_images": images,
        "captured_files": [{key: item[key] for key in ("filename", "mime_type", "width", "height", "content_hash", "source_url", "role")} for item in decoded],
        "document_order": [item.model_dump() for item in payload.document_order],
        "sensitive_findings": [],
        "capture_policy": {"user_selected_only": True, "reference_only": True, "cookies_or_auth_tokens_collected": False, "bypass_attempted": False, "stored_image_bytes": True},
        "_decoded_files": decoded,
    }


def _store_capture_asset(project: ProductProject, item: dict[str, Any], db: Session) -> tuple[Asset, bool]:
    existing = db.query(Asset).filter(
        Asset.project_id == project.id,
        Asset.content_hash == item["content_hash"],
    ).first()
    if existing:
        return existing, True
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(settings.UPLOAD_DIR, f"browser-extension-{item['content_hash'][:16]}-{uuid.uuid4().hex[:8]}.{item['extension']}")
    with open(file_path, "wb") as output:
        output.write(item["content"])
    asset = Asset(
        project_id=project.id,
        source_type="sourced",
        usage_status="reference_only",
        filename=item["filename"],
        file_path=file_path,
        mime_type=item["mime_type"],
        file_size=len(item["content"]),
        asset_role="spec_reference" if item["role"] == "screenshot" else "unidentifiable_reference",
        role_source="browser_extension",
        quality_status="warning",
        identity_status="needs_review",
        width=item["width"],
        height=item["height"],
        image_format=item["extension"].upper(),
        quality_warnings=["BROWSER_CAPTURE_REFERENCE_ONLY"],
        content_hash=item["content_hash"],
        safe_crop_status="needs_review",
    )
    db.add(asset)
    db.flush()
    return asset, False


@router.post("/connection-codes")
def issue_connection_code(payload: ConnectionCodeRequest, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    code = _connection_code()
    connection = BrowserExtensionConnection(
        workspace_id=auth_ctx["workspace"].id, user_id=auth_ctx["user"].id,
        code_hash=_hash(code), code_expires_at=_now() + dt.timedelta(minutes=CODE_TTL_MINUTES),
        extension_name=payload.extension_name, extension_version=payload.extension_version,
    )
    db.add(connection); db.flush()
    db.add(AuditLog(workspace_id=auth_ctx["workspace"].id, user_id=auth_ctx["user"].id, action="browser_extension_connection_code_issued", entity_type="browser_extension_connection", entity_id=connection.id, payload={"extension_name": payload.extension_name, "expires_in_minutes": CODE_TTL_MINUTES}))
    db.commit()
    return {"connection_id": connection.id, "connection_code": code, "expires_at": connection.code_expires_at, "permissions": ["activeTab", "scripting", "storage", "current-tab screenshot", "selected-image-origin (on demand)"], "policy": "Only user-selected visible product material may be sent. Cookies, login tokens, orders and member data are blocked."}


@router.post("/connection-codes/exchange")
def exchange_connection_code(payload: ExchangeCodeRequest, db: Session = Depends(get_db)):
    connection = db.query(BrowserExtensionConnection).filter(BrowserExtensionConnection.code_hash == _hash(payload.connection_code.strip().upper())).first()
    if not connection or connection.code_used_at or connection.code_expires_at <= _now():
        raise HTTPException(status_code=401, detail="Connection code is invalid, already used, or expired.")
    token = _token()
    connection.code_used_at = _now(); connection.token_hash = _hash(token); connection.token_expires_at = _now() + dt.timedelta(hours=TOKEN_TTL_HOURS)
    connection.extension_name = payload.extension_name; connection.extension_version = payload.extension_version
    db.add(AuditLog(workspace_id=connection.workspace_id, user_id=connection.user_id, action="browser_extension_connected", entity_type="browser_extension_connection", entity_id=connection.id, payload={"extension_name": payload.extension_name, "extension_version": payload.extension_version}))
    db.commit()
    return {"extension_token": token, "expires_at": connection.token_expires_at, "workspace_id": connection.workspace_id, "capture_policy": "User-triggered current-tab capture only; no access-control bypass or browser credential collection."}


@router.post("/tokens/rotate")
def rotate_extension_token(connection: BrowserExtensionConnection = Depends(_connection_from_token), db: Session = Depends(get_db)):
    token = _token()
    connection.token_hash = _hash(token); connection.token_rotated_at = _now(); connection.token_expires_at = _now() + dt.timedelta(hours=TOKEN_TTL_HOURS)
    db.add(AuditLog(workspace_id=connection.workspace_id, user_id=connection.user_id, action="browser_extension_token_rotated", entity_type="browser_extension_connection", entity_id=connection.id, payload={"expires_in_hours": TOKEN_TTL_HOURS}))
    db.commit()
    return {"extension_token": token, "expires_at": connection.token_expires_at}


@router.get("/projects")
def list_extension_projects(connection: BrowserExtensionConnection = Depends(_connection_from_token), db: Session = Depends(get_db)):
    projects = db.query(ProductProject).filter(ProductProject.workspace_id == connection.workspace_id).order_by(ProductProject.updated_at.desc()).limit(50).all()
    return {"projects": [{"id": project.id, "name": project.name, "status": project.status} for project in projects]}


@router.post("/captures/preview")
def preview_capture(payload: ExtensionCapturePayload, connection: BrowserExtensionConnection = Depends(_connection_from_token)):
    preview = _preview(payload); preview.pop("_decoded_files", None); preview["connection_id"] = connection.id
    return preview


@router.post("/captures")
def submit_capture(payload: SubmitCaptureRequest, connection: BrowserExtensionConnection = Depends(_connection_from_token), db: Session = Depends(get_db)):
    project = db.query(ProductProject).filter(ProductProject.id == payload.project_id, ProductProject.workspace_id == connection.workspace_id).first()
    if not project:
        raise HTTPException(status_code=403, detail="Target project is unavailable in this extension workspace.")
    preview = _preview(payload)
    decoded = preview.pop("_decoded_files")
    # A selected remote image URL alone is not a durable capture.  The new
    # extension sends image bytes or a seller-triggered screenshot instead.
    if preview["selected_images"] and not decoded:
        raise HTTPException(status_code=422, detail="Selected image URLs must include their captured image bytes or a user-triggered screenshot.")
    stored_assets: list[dict[str, Any]] = []
    duplicate_count = 0
    for item in decoded:
        asset, duplicate = _store_capture_asset(project, item, db)
        duplicate_count += int(duplicate)
        stored_assets.append({"asset_id": asset.id, "content_hash": item["content_hash"], "source_url": item["source_url"], "role": item["role"], "mime_type": item["mime_type"], "file_size": len(item["content"]), "duplicate": duplicate})
    scope = {"selected_document_items": len(preview["document_order"]), "selected_image_urls": len(preview["selected_images"]), "stored_image_files": len(stored_assets), "screenshot_included": any(item["role"] == "screenshot" for item in stored_assets), "explicit_user_selection": True}
    source_capture = SourceCapture(project_id=project.id, url=payload.url, platform=preview["domain"], source_role="browser_extension", collection_status="collected", collected_image_count=len(stored_assets), collected_spec_count=sum(1 for item in preview["document_order"] if item["kind"] in {"spec", "text"}), capture_metadata={"extension_version": connection.extension_version, "site_adapter": payload.site_adapter, "selection_scope": scope, "source": "current-tab-user-selection"})
    db.add(source_capture); db.flush()
    capture = BrowserExtensionCapture(connection_id=connection.id, workspace_id=connection.workspace_id, user_id=connection.user_id, project_id=project.id, source_capture_id=source_capture.id, url=payload.url, domain=preview["domain"], page_title=payload.page_title, language=payload.language, site_adapter=payload.site_adapter, extension_version=connection.extension_version, selected_text=payload.selected_text, selected_html=preview["safe_selected_html"], selected_images=stored_assets, selected_asset_ids=[item["asset_id"] for item in stored_assets], selection_scope=scope, document_order=preview["document_order"], sensitive_findings=[], transfer_status="submitted", captured_at=payload.captured_at or _now(), submitted_at=_now())
    db.add(capture); db.flush()
    snapshot = dict(project.intake_snapshot or {}); captures = list(snapshot.get("browser_extension_captures") or [])
    captures.append({"capture_id": capture.id, "url": payload.url, "title": payload.page_title, "selected_text": (payload.selected_text or "")[:4000], "selected_asset_ids": capture.selected_asset_ids, "selected_images": stored_assets, "source_role": "browser_extension", "usage_status": "reference_only", "captured_at": (payload.captured_at or _now()).isoformat()})
    snapshot["browser_extension_captures"] = captures[-20:]; project.intake_snapshot = snapshot
    if not project.raw_input_url: project.raw_input_url = payload.url
    db.add(AuditLog(workspace_id=connection.workspace_id, user_id=connection.user_id, action="browser_extension_capture_submitted", entity_type="browser_extension_capture", entity_id=capture.id, payload={"project_id": project.id, "domain": preview["domain"], "stored_asset_count": len(stored_assets), "duplicate_asset_count": duplicate_count, "reference_only": True, "site_adapter": payload.site_adapter}))
    db.commit()
    return {"capture_id": capture.id, "source_capture_id": source_capture.id, "project_id": project.id, "transfer_status": "submitted", "usage_status": "reference_only", "stored_asset_ids": capture.selected_asset_ids, "duplicate_asset_count": duplicate_count, "message": "Selected product material was safely stored as reference files. Review facts/images before final use."}


@router.get("/connections")
def list_connections(db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    rows = db.query(BrowserExtensionConnection).filter(BrowserExtensionConnection.workspace_id == auth_ctx["workspace"].id, BrowserExtensionConnection.user_id == auth_ctx["user"].id).order_by(BrowserExtensionConnection.created_at.desc()).all()
    return {"connections": [{"id": row.id, "extension_name": row.extension_name, "extension_version": row.extension_version, "created_at": row.created_at, "last_used_at": row.last_used_at, "expires_at": row.token_expires_at, "rotated_at": row.token_rotated_at, "revoked": bool(row.token_revoked_at), "pending_code": row.code_used_at is None and row.code_expires_at > _now()} for row in rows]}


@router.delete("/connections/{connection_id}")
def revoke_connection(connection_id: str, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    connection = db.query(BrowserExtensionConnection).filter(BrowserExtensionConnection.id == connection_id, BrowserExtensionConnection.workspace_id == auth_ctx["workspace"].id, BrowserExtensionConnection.user_id == auth_ctx["user"].id).first()
    if not connection: raise HTTPException(status_code=404, detail="Extension connection not found.")
    connection.token_revoked_at = _now()
    db.add(AuditLog(workspace_id=auth_ctx["workspace"].id, user_id=auth_ctx["user"].id, action="browser_extension_connection_revoked", entity_type="browser_extension_connection", entity_id=connection.id, payload={}))
    db.commit()
    return {"id": connection.id, "revoked": True}


@router.delete("/connections")
def revoke_all_connections(db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    rows = db.query(BrowserExtensionConnection).filter(BrowserExtensionConnection.workspace_id == auth_ctx["workspace"].id, BrowserExtensionConnection.user_id == auth_ctx["user"].id, BrowserExtensionConnection.token_revoked_at.is_(None)).all()
    for row in rows: row.token_revoked_at = _now()
    db.add(AuditLog(workspace_id=auth_ctx["workspace"].id, user_id=auth_ctx["user"].id, action="browser_extension_all_connections_revoked", entity_type="browser_extension_connection", entity_id=auth_ctx["workspace"].id, payload={"count": len(rows)}))
    db.commit()
    return {"revoked_count": len(rows)}
