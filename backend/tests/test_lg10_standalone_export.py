from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm.attributes import flag_modified

from src.db.models import Asset, Brand, DetailPageVersion, ExportArtifact, ProductProject, User, Workspace
from src.services.export_service import (
    _LG10_COPYABLE_HTML_ARTIFACT,
    _LG10_STANDALONE_PACKAGE_ARTIFACT,
    build_lg10_standalone_export_bundle,
    sanitize_copyable_html,
    FrozenExportSnapshotError,
)


def _png(path: Path, color: tuple[int, int, int]) -> bytes:
    Image.new("RGB", (8, 8), color=color).save(path, format="PNG")
    return path.read_bytes()


def _seed_lg10_version(db_session, tmp_path):
    user = User(id="lg10-export-user", email="lg10-export@example.com", name="LG10 Export")
    workspace = Workspace(id="lg10-export-workspace", name="LG10 Export Workspace", owner_id=user.id)
    brand = Brand(id="lg10-export-brand", workspace_id=workspace.id, name="LG10 Export Brand")
    project = ProductProject(
        id="lg10-export-project", workspace_id=workspace.id, brand_id=brand.id,
        name="LG10 standalone export",
    )
    db_session.add_all([user, workspace, brand, project])
    db_session.flush()
    first_path = tmp_path / "approved-one.png"
    second_path = tmp_path / "approved-two.png"
    first_bytes = _png(first_path, (20, 80, 160))
    second_bytes = _png(second_path, (180, 90, 30))
    first = Asset(
        id="lg10-approved-one", project_id=project.id, source_type="ai_generated", usage_status="ai_generated",
        filename=first_path.name, file_path=str(first_path), mime_type="image/png", file_size=len(first_bytes),
        content_hash=hashlib.sha256(first_bytes).hexdigest(), quality_status="usable",
    )
    second = Asset(
        id="lg10-approved-two", project_id=project.id, source_type="uploaded", usage_status="seller_owned",
        filename=second_path.name, file_path=str(second_path), mime_type="image/png", file_size=len(second_bytes),
        content_hash=hashlib.sha256(second_bytes).hexdigest(), quality_status="usable",
    )
    db_session.add_all([first, second])
    db_session.flush()
    manifest = {
        "run_id": "lg10-run", "project_id": project.id,
        "assets": [
            {"scene_id": "hero", "asset_id": first.id, "asset_content_hash": first.content_hash},
            {"scene_id": "detail", "asset_id": second.id, "asset_content_hash": second.content_hash},
        ],
    }
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    rendering = {
        "html": (
            '<main class="sf-page"><script>window.bad()</script>'
            f'<section class="sf-section" onclick="bad()" data-section-id="hero">'
            f'<figure class="sf-asset-layer" data-asset-id="{first.id}" data-asset-content-hash="{first.content_hash}"></figure>'
            '<div class="sf-text-layer"><h2>한국어 고정 카피</h2><p>승인된 자산만 사용합니다.</p></div></section>'
            '<img src="https://expired.example/signature"><a href="javascript:bad()">bad</a></main>'
        ),
        "css": ".sf-page{max-width:760px}.sf-section{padding:24px}",
        "brand_tokens": {"typography": {"body_font": "system-ui, sans-serif"}},
        "sections": [{
            "section_id": "hero", "component_id": "media_with_copy", "layout_token": "image_text",
            "asset_layer": [{"asset_id": first.id, "asset_content_hash": first.content_hash}],
            "text_layer": [{"field": "title", "text": "한국어 고정 카피"}],
        }],
    }
    version = DetailPageVersion(
        id="lg10-export-version", project_id=project.id, name="LG10 frozen", style_key="balanced_sale", is_final=True,
        sections_json={
            "schema_version": "lg10-detail-page-version-v1",
            "lg10": {
                "canonical_page_assembly_input": {"approved_asset_manifest": manifest},
                "canonical_rendering": rendering,
            },
        },
    )
    db_session.add(version)
    db_session.commit()
    return user, workspace, project, version, first, second


def test_lg10_standalone_bundle_is_local_sanitized_and_manifest_bound(db_session, tmp_path):
    _, _, project, version, first, second = _seed_lg10_version(db_session, tmp_path)

    result = build_lg10_standalone_export_bundle(
        db=db_session, project_id=project.id, version=version, output_dir=str(tmp_path / "exports"),
    )

    copyable_html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "<script" not in copyable_html
    assert "onclick=" not in copyable_html
    assert "https://expired.example" not in copyable_html
    assert "javascript:" not in copyable_html
    assert "한국어 고정 카피" in copyable_html
    assert f"assets/{first.id}.png" in copyable_html
    assert second.id not in copyable_html

    with zipfile.ZipFile(result["zip_path"]) as archive:
        names = set(archive.namelist())
        assert {"index.html", "copyable.html", "styles.css", "approved-asset-manifest.json", "font-manifest.json", "README.txt"} <= names
        assert f"assets/{first.id}.png" in names
        assert f"assets/{second.id}.png" in names
        index = archive.read("index.html").decode("utf-8")
        assert 'href="styles.css"' in index
        assert "/api/" not in index
        assert "https://" not in index
        manifest = json.loads(archive.read("approved-asset-manifest.json"))
        assert manifest["detail_page_version_id"] == version.id
        assert manifest["approved_asset_manifest"] == version.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]
        assert {item["asset_id"] for item in manifest["bundled_assets"]} == {first.id, second.id}


def test_lg10_standalone_zip_renders_locally_without_network_requests(db_session, tmp_path):
    """The packaged page must remain useful when opened outside Sellform."""
    _, _, project, version, first, _ = _seed_lg10_version(db_session, tmp_path)
    result = build_lg10_standalone_export_bundle(
        db=db_session, project_id=project.id, version=version, output_dir=str(tmp_path / "exports"),
    )
    extracted = tmp_path / "standalone"
    with zipfile.ZipFile(result["zip_path"]) as archive:
        archive.extractall(extracted)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        requested_urls: list[str] = []
        page.on("request", lambda request: requested_urls.append(request.url))
        page.goto((extracted / "index.html").as_uri(), wait_until="networkidle")

        assert page.locator(".sf-page").evaluate("element => getComputedStyle(element).maxWidth") == "760px"
        image = page.locator(f'img[src="assets/{first.id}.png"]')
        assert image.count() == 1
        assert image.evaluate("element => element.complete && element.naturalWidth > 0") is True
        assert requested_urls
        assert all(url.startswith("file://") for url in requested_urls)
        browser.close()


def test_lg10_standalone_export_uses_static_fallback_for_unsupported_component(db_session, tmp_path):
    _, _, project, version, _, _ = _seed_lg10_version(db_session, tmp_path)
    version.sections_json["lg10"]["canonical_rendering"]["sections"][0]["component_id"] = "freeform_canvas"
    flag_modified(version, "sections_json")
    db_session.commit()

    result = build_lg10_standalone_export_bundle(
        db=db_session, project_id=project.id, version=version, output_dir=str(tmp_path / "exports"),
    )

    assert "Unsupported channel component was replaced with the fixed static fallback." in result["warnings"]
    assert 'data-static-fallback="unsupported_channel_component"' in Path(result["html_path"]).read_text(encoding="utf-8")


def test_lg10_standalone_export_rejects_non_final_or_changed_manifest_assets(db_session, tmp_path):
    _, _, project, version, first, second = _seed_lg10_version(db_session, tmp_path)
    second.usage_status = "reference_only"
    db_session.commit()
    with pytest.raises(FrozenExportSnapshotError, match="Approved asset bytes"):
        build_lg10_standalone_export_bundle(
            db=db_session, project_id=project.id, version=version, output_dir=str(tmp_path / "exports"),
        )

    second.usage_status = "seller_owned"
    Path(first.file_path).write_bytes(b"replaced-under-the-same-id")
    db_session.commit()
    with pytest.raises(FrozenExportSnapshotError, match="Approved asset bytes"):
        build_lg10_standalone_export_bundle(
            db=db_session, project_id=project.id, version=version, output_dir=str(tmp_path / "exports-two"),
        )


def test_sanitize_copyable_html_removes_executable_markup_and_risky_urls():
    clean, warnings = sanitize_copyable_html(
        '<main><script>alert(1)</script><p onclick="bad()">안전 카피</p><img src="https://signed.example/a"></main>'
    )
    assert "script" not in clean
    assert "onclick" not in clean
    assert "signed.example" not in clean
    assert "안전 카피" in clean
    assert warnings


def test_lg10_standalone_export_api_reuses_the_same_frozen_version_history(
    client, db_session, tmp_path, monkeypatch
):
    user, workspace, project, version, _, _ = _seed_lg10_version(db_session, tmp_path)
    from src.api.auth import get_current_user_and_workspace
    from src.services import export_service

    original_build = export_service.build_lg10_standalone_export_bundle
    monkeypatch.setattr(
        "src.api.exports.build_lg10_standalone_export_bundle",
        lambda **kwargs: original_build(**kwargs, output_dir=str(tmp_path / "exports")),
    )
    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": user, "workspace": workspace, "role": "owner",
    }

    first = client.post(
        f"/api/v1/projects/{project.id}/page/export/standalone",
        json={"final_version_id": version.id},
    )
    second = client.post(
        f"/api/v1/projects/{project.id}/page/export/standalone",
        json={"final_version_id": version.id},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["detail_page_version_id"] == second.json()["detail_page_version_id"] == version.id
    assert first.json()["html_download_url"] == second.json()["html_download_url"]
    assert first.json()["zip_download_url"] == second.json()["zip_download_url"]
    assert {
        artifact.artifact_type
        for artifact in db_session.query(ExportArtifact).filter_by(project_id=project.id, version_id=version.id).all()
    } == {_LG10_COPYABLE_HTML_ARTIFACT, _LG10_STANDALONE_PACKAGE_ARTIFACT}

    history = client.get("/api/v1/page/exports")
    assert history.status_code == 200
    standalone_history = [item for item in history.json()["items"] if item["format"] == "lg10_standalone"]
    assert len(standalone_history) == 2
    assert {item["version_id"] for item in standalone_history} == {version.id}
    assert {item["approved_asset_manifest_hash"] for item in standalone_history} == {
        version.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]["manifest_hash"]
    }
    assert {item["package_download_url"] for item in standalone_history} == {first.json()["zip_download_url"]}
