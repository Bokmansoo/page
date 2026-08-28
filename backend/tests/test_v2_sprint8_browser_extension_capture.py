"""V2 Sprint 8 browser-extension security and durable-capture contracts."""

import base64
import io
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from src.db.models import Asset, BrowserExtensionCapture, BrowserExtensionConnection, Brand, ProductProject, SourceCapture


HEADERS = {"X-Mock-User-Id": "11111111-1111-1111-1111-111111111111", "X-Mock-Workspace-Id": "22222222-2222-2222-2222-222222222222"}


def _image_data_url(fmt="PNG", color=(120, 120, 120)):
    image = Image.new("RGB", (32, 24), color)
    output = io.BytesIO(); image.save(output, format=fmt)
    mime = "image/jpeg" if fmt == "JPEG" else f"image/{fmt.lower()}"
    return f"data:{mime};base64,{base64.b64encode(output.getvalue()).decode()}"


def _connection_token(client):
    issued = client.post("/api/v1/browser-extension/connection-codes", json={}, headers=HEADERS)
    assert issued.status_code == 200
    exchanged = client.post("/api/v1/browser-extension/connection-codes/exchange", json={"connection_code": issued.json()["connection_code"]})
    assert exchanged.status_code == 200
    return exchanged.json()["extension_token"], issued.json()["connection_code"]


def _project(db_session):
    brand = db_session.query(Brand).filter(Brand.workspace_id == HEADERS["X-Mock-Workspace-Id"]).first()
    project = ProductProject(workspace_id=HEADERS["X-Mock-Workspace-Id"], brand_id=brand.id, name="Browser capture test product", status="draft", current_step="raw_input")
    db_session.add(project); db_session.commit()
    return project


def _payload(project_id=None, adapter="1688-visible-product-v1"):
    return {
        **({"project_id": project_id} if project_id else {}),
        "url": "https://detail.1688.com/offer/996262285530.html", "page_title": "마사지 베개 YL-T02", "language": "zh-CN", "site_adapter": adapter,
        "selected_text": "YL-T02 · DC5V2A · 8W · 2000mAh", "selected_html": "<h2>제품 사양</h2><p>배터리 2000mAh</p>",
        "selected_image_urls": ["https://example.test/product.png"],
        "selected_image_blobs": [{"data_url": _image_data_url(), "filename": "product.png", "source_url": "https://example.test/product.png", "role": "selected_image"}],
        "document_order": [{"kind": "heading", "value": "제품 사양", "order": 0}, {"kind": "spec", "value": "배터리 용량 2000mAh", "order": 1}],
    }


def test_adapters_actual_files_hash_merge_and_safe_selected_html(client, db_session):
    token, _ = _connection_token(client); headers = {"X-Sellform-Extension-Token": token}; project = _project(db_session)
    preview = client.post("/api/v1/browser-extension/captures/preview", json=_payload(), headers=headers)
    assert preview.status_code == 200
    assert preview.json()["site_adapter"] == "1688-visible-product-v1"
    assert preview.json()["capture_policy"]["stored_image_bytes"] is True
    assert preview.json()["safe_selected_html"] == "<pre>제품 사양\n배터리 2000mAh</pre>"
    submitted = client.post("/api/v1/browser-extension/captures", json=_payload(project.id), headers=headers)
    assert submitted.status_code == 200
    asset = db_session.query(Asset).one()
    assert Path(asset.file_path).is_file() and asset.usage_status == "reference_only"
    source_capture = db_session.query(SourceCapture).one()
    assert source_capture.capture_metadata["site_adapter"] == "1688-visible-product-v1"
    assert source_capture.capture_metadata["selection_scope"]["stored_image_files"] == 1
    duplicate = client.post("/api/v1/browser-extension/captures", json=_payload(project.id), headers=headers)
    assert duplicate.status_code == 200 and duplicate.json()["duplicate_asset_count"] == 1
    assert db_session.query(Asset).count() == 1
    assert db_session.query(BrowserExtensionCapture).count() == 2


def test_adapter_validation_expiry_rotation_and_global_revoke(client, db_session):
    token, code = _connection_token(client); headers = {"X-Sellform-Extension-Token": token}
    assert client.post("/api/v1/browser-extension/connection-codes/exchange", json={"connection_code": code}).status_code == 401
    assert client.post("/api/v1/browser-extension/captures/preview", json=_payload(adapter="unknown-store"), headers=headers).status_code == 422
    rotated = client.post("/api/v1/browser-extension/tokens/rotate", headers=headers)
    assert rotated.status_code == 200
    assert client.post("/api/v1/browser-extension/captures/preview", json=_payload(), headers=headers).status_code == 401
    rotated_headers = {"X-Sellform-Extension-Token": rotated.json()["extension_token"]}
    connection = db_session.query(BrowserExtensionConnection).one(); connection.token_expires_at = datetime.utcnow() - timedelta(seconds=1); db_session.commit()
    assert client.post("/api/v1/browser-extension/captures/preview", json=_payload(), headers=rotated_headers).status_code == 401
    # New connection proves global revocation also invalidates another device.
    token2, _ = _connection_token(client)
    assert client.delete("/api/v1/browser-extension/connections", headers=HEADERS).status_code == 200
    assert client.post("/api/v1/browser-extension/captures/preview", json=_payload(), headers={"X-Sellform-Extension-Token": token2}).status_code == 401


def test_rejects_url_only_spoofed_oversized_and_unsafe_html(client, db_session):
    token, _ = _connection_token(client); headers = {"X-Sellform-Extension-Token": token}; project = _project(db_session)
    url_only = _payload(project.id); url_only["selected_image_blobs"] = []
    assert client.post("/api/v1/browser-extension/captures", json=url_only, headers=headers).status_code == 422
    spoofed = _payload(); spoofed["selected_image_blobs"][0]["data_url"] = _image_data_url("JPEG") .replace("data:image/jpeg", "data:image/png")
    assert client.post("/api/v1/browser-extension/captures/preview", json=spoofed, headers=headers).status_code == 422
    unsafe = _payload(); unsafe["selected_html"] = "<script>alert(1)</script><p>safe</p>"
    assert client.post("/api/v1/browser-extension/captures/preview", json=unsafe, headers=headers).status_code == 422
    too_large = _payload(); too_large["selected_image_blobs"][0]["data_url"] = "data:image/png;base64," + base64.b64encode(b"x" * (8 * 1024 * 1024 + 1)).decode()
    assert client.post("/api/v1/browser-extension/captures/preview", json=too_large, headers=headers).status_code == 422


def test_extension_declares_site_adapters_and_selected_html_transport():
    root = Path(__file__).resolve().parents[2] / "browser-extension"
    popup = (root / "popup.js").read_text(encoding="utf-8")
    manifest = (root / "manifest.json").read_text(encoding="utf-8")
    for adapter in (
        "1688-visible-product-v1",
        "taobao-visible-product-v1",
        "xiaohongshu-visible-product-v1",
        "coupang-visible-product-v1",
        "smartstore-visible-product-v1",
    ):
        assert adapter in popup
    assert "selected_html" in popup and "captureVisibleTab" in popup and "selected_image_blobs" in popup and "chooseDom" in popup
    assert "optional_host_permissions" in manifest
