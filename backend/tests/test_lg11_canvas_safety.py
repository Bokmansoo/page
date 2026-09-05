"""TASK-11.9 frozen Canvas channel-safety and export-gate coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm.attributes import flag_modified

from src.api.exports import parse_lg11_export_artifact_token
from src.db.models import Asset, ExportArtifact
from src.services.export_service import FrozenExportSnapshotError, build_lg10_copyable_html
from src.services.page_visual_contract import LG11CanvasSafetyError, ensure_lg11_canvas_safe, validate_lg11_canvas_safety
from test_lg10_standalone_export import _seed_lg10_version

pytestmark = pytest.mark.lg11_fake_e2e


def _snapshot(*, element=None, canvas=None, brand_geometry=None):
    element = element or {"element_id": "hero:asset", "kind": "asset", "x": 0, "y": 0, "width": 712, "height": 320, "z_index": 1, "locked": False}
    canvas = canvas or {"is_visible": True, "height_px": 480}
    brand = {"asset_id": "brand-logo", "asset_content_hash": "a" * 64}
    snapshot = {
        "schema_version": "lg10-detail-page-version-v1",
        "lg11": {"canvas_revision": 1},
        "lg10": {"canonical_rendering": {"brand_tokens": {"asset_layer": {"logo": brand}}, "sections": [
            {"section_id": "hero", "canvas": canvas, "canvas_elements": [element]},
            {"section_id": "specs", "canvas": {"is_visible": True, "height_px": 160}, "canvas_elements": []},
        ]}},
    }
    if brand_geometry is not None:
        snapshot["lg10"]["canonical_rendering"]["brand_geometry"] = {
            "page_width": 760,
            "page_height": 640,
            "placements": {"logo": {**brand_geometry, "element_id": "brand:logo"}},
        }
    return snapshot


def test_lg11_canvas_safety_uses_frozen_geometry_for_preview_and_export_gates():
    safe = _snapshot()
    preview = validate_lg11_canvas_safety(version_snapshot=safe, channel="smartstore")
    export = validate_lg11_canvas_safety(version_snapshot=safe, channel="smartstore")
    assert preview == export and preview["safe"] is True and preview["checked"] is True

    overflow = _snapshot(element={"element_id": "hero:asset", "kind": "asset", "x": 700, "y": 0, "width": 100, "height": 320, "z_index": 1, "locked": True, "group_id": "group-1"})
    result = validate_lg11_canvas_safety(version_snapshot=overflow, channel="coupang")
    assert result["safe"] is False
    assert result["issues"] == [{"code": "element_overflow", "reason": "Element exceeds the channel safe area.", "section_id": "hero", "element_id": "hero:asset"}]
    with pytest.raises(LG11CanvasSafetyError):
        ensure_lg11_canvas_safe(version_snapshot=overflow, channel="coupang")


def test_lg11_canvas_safety_handles_hidden_sections_height_and_brand_geometry():
    hidden = _snapshot(
        element={"element_id": "hero:asset", "kind": "asset", "x": 900, "y": 0, "width": 100, "height": 320, "z_index": 1, "locked": True},
        canvas={"is_visible": False, "height_px": 480},
    )
    assert validate_lg11_canvas_safety(version_snapshot=hidden)["safe"] is True
    tall = _snapshot(canvas={"is_visible": True, "height_px": 2401})
    assert validate_lg11_canvas_safety(version_snapshot=tall)["issues"][0]["code"] == "section_height_out_of_bounds"
    branded = _snapshot(brand_geometry={"x": 800, "y": 0, "width": 80, "height": 40})
    assert validate_lg11_canvas_safety(version_snapshot=branded)["issues"][0]["code"] == "brand_overflow"
    hidden_spec = _snapshot()
    hidden_spec["lg10"]["canonical_rendering"]["sections"][1]["canvas"]["is_visible"] = False
    assert validate_lg11_canvas_safety(version_snapshot=hidden_spec)["issues"][0]["code"] == "final_spec_position"


def test_lg11_canvas_unsafe_snapshot_is_blocked_by_frozen_html_export(db_session, tmp_path):
    _, _, project, version, _, _ = _seed_lg10_version(db_session, tmp_path)
    snapshot = version.sections_json
    snapshot["lg11"] = {"canvas_revision": 1}
    snapshot["lg10"]["canonical_rendering"]["sections"][0]["canvas"] = {"is_visible": True, "height_px": 160}
    snapshot["lg10"]["canonical_rendering"]["sections"][0]["canvas_elements"] = [{"element_id": "hero:asset", "kind": "asset", "x": 700, "y": 0, "width": 100, "height": 100, "z_index": 1, "locked": False}]
    with pytest.raises(FrozenExportSnapshotError):
        build_lg10_copyable_html(db=db_session, project_id=project.id, version=version)


def test_lg11_canvas_safety_validates_renderer_brand_geometry_and_visible_overlap():
    logo_overflow = _snapshot()
    logo_overflow["lg10"]["canonical_rendering"]["brand_geometry"] = {
        "page_width": 760, "page_height": 640,
        "placements": {"logo": {"element_id": "brand:logo", "x": 740, "y": 18, "width": 180, "height": 56}},
    }
    assert validate_lg11_canvas_safety(version_snapshot=logo_overflow, channel="smartstore")["issues"][0]["code"] == "brand_overflow"

    overlap = _snapshot()
    overlap["lg10"]["canonical_rendering"]["sections"][0]["canvas_elements"] = [
        {"element_id": "hero:text-custom", "kind": "text", "x": 0, "y": 0, "width": 300, "height": 100, "z_index": 1, "locked": False},
        {"element_id": "hero:asset-custom", "kind": "asset", "x": 120, "y": 20, "width": 300, "height": 120, "z_index": 2, "locked": True},
    ]
    issue = validate_lg11_canvas_safety(version_snapshot=overlap, channel="coupang")["issues"][0]
    assert issue == {
        "code": "element_overlap",
        "reason": "Visible elements overlap outside an allowed Canvas relationship.",
        "section_id": "hero",
        "element_id": "hero:text-custom",
        "conflicting_element_id": "hero:asset-custom",
    }


def test_lg11_canvas_safety_ignores_hidden_and_allows_declared_decorative_overlap():
    hidden = _snapshot()
    hidden["lg10"]["canonical_rendering"]["sections"][0]["canvas_elements"] = [
        {"element_id": "hero:text", "kind": "text", "x": 0, "y": 0, "width": 300, "height": 100, "z_index": 1, "locked": False},
        {"element_id": "hero:asset", "kind": "asset", "x": 40, "y": 0, "width": 300, "height": 120, "z_index": 2, "locked": False, "deleted": True},
    ]
    assert validate_lg11_canvas_safety(version_snapshot=hidden, channel="smartstore")["safe"] is True

    allowed = _snapshot()
    allowed["lg10"]["canonical_rendering"]["sections"][0]["canvas_elements"] = [
        {"element_id": "hero:text", "kind": "text", "x": 0, "y": 0, "width": 300, "height": 100, "z_index": 1, "locked": False},
        {"element_id": "hero:decorative", "kind": "decorative", "x": 40, "y": 0, "width": 120, "height": 80, "z_index": 2, "locked": False, "allowed_overlap_with": ["hero:text"]},
    ]
    assert validate_lg11_canvas_safety(version_snapshot=allowed, channel="coupang")["safe"] is True


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("channel_long:smartstore:png", {"artifact_type": "channel_long", "channel": "smartstore", "format": "png"}),
        ("channel_long:coupang:jpg", {"artifact_type": "channel_long", "channel": "coupang", "format": "jpg"}),
        ("channel_package:smartstore:html", {"artifact_type": "channel_package", "channel": "smartstore", "format": "html"}),
        ("channel_package:coupang:zip", {"artifact_type": "channel_package", "channel": "coupang", "format": "zip"}),
    ],
)
def test_lg11_export_artifact_parser_preserves_channel_and_format(token, expected):
    assert parse_lg11_export_artifact_token(token) == expected


def test_lg11_all_export_downloads_use_the_frozen_artifact_channel(client, db_session, tmp_path, monkeypatch):
    """Regression coverage for channel_long/channel_package download parsing.

    This exercises the production preview, export admission, standalone HTML/ZIP,
    and artifact-download routes against one frozen LG-11 version.
    """
    user, workspace, project, version, _, _ = _seed_lg10_version(db_session, tmp_path)
    from src.api.auth import get_current_user_and_workspace
    from src.services import export_service

    version.sections_json["lg11"] = {"canvas_revision": 1}
    flag_modified(version, "sections_json")
    db_session.commit()
    client.app.dependency_overrides[get_current_user_and_workspace] = lambda: {
        "user": user, "workspace": workspace, "role": "owner",
    }

    # Keep this an API admission test: page export must validate the frozen
    # channel but must not launch a headless render here.
    monkeypatch.setattr("src.api.exports.run_export_task", lambda *_args, **_kwargs: None)
    original_bundle = export_service.build_lg10_standalone_export_bundle
    monkeypatch.setattr(
        "src.api.exports.build_lg10_standalone_export_bundle",
        lambda **kwargs: original_bundle(**kwargs, output_dir=str(tmp_path / "standalone")),
    )

    def add_artifact(token: str, filename: str, mime_type: str) -> Asset:
        path = Path(tmp_path) / filename
        path.write_bytes(b"frozen-export-artifact")
        asset = Asset(
            id=f"artifact-{filename}", project_id=project.id,
            source_type="exported_image", usage_status="blocked",
            filename=filename, file_path=str(path), mime_type=mime_type,
            file_size=path.stat().st_size,
        )
        db_session.add(asset)
        db_session.flush()
        db_session.add(ExportArtifact(
            project_id=project.id, version_id=version.id,
            artifact_type=token, file_path=str(path),
        ))
        db_session.commit()
        return asset

    artifacts = [
        (add_artifact("channel_long:smartstore:png", "safe.png", "image/png"), "smartstore"),
        (add_artifact("channel_long:coupang:jpg", "safe.jpg", "image/jpeg"), "coupang"),
        (add_artifact("channel_package:smartstore:html", "safe.html", "text/html"), "smartstore"),
        (add_artifact("channel_package:coupang:zip", "safe.zip", "application/zip"), "coupang"),
    ]

    for channel in ("smartstore", "coupang"):
        preview = client.get(
            f"/api/v1/projects/{project.id}/page/final",
            params={"version_id": version.id, "channel": channel},
        )
        assert preview.status_code == 200
        export = client.post(
            f"/api/v1/projects/{project.id}/page/export",
            json={"final_version_id": version.id, "preset_name": channel, "output_format": "png"},
        )
        assert export.status_code == 202

    for artifact, _channel in artifacts:
        response = client.get(f"/api/v1/projects/{project.id}/page/export/download/{artifact.id}")
        assert response.status_code == 200

    # Copyable HTML and standalone ZIP use the same parser contract through
    # their channel-suffixed frozen artifact identities.
    standalone = client.post(
        f"/api/v1/projects/{project.id}/page/export/standalone",
        json={"final_version_id": version.id, "channel": "smartstore"},
    )
    assert standalone.status_code == 200
    assert "data:image/png;base64," in standalone.json()["copyable_html"]
    assert client.get(standalone.json()["html_download_url"]).status_code == 200
    assert client.get(standalone.json()["zip_download_url"]).status_code == 200

    invalid = add_artifact("channel_long:png:smartstore", "invalid.png", "image/png")
    invalid_response = client.get(f"/api/v1/projects/{project.id}/page/export/download/{invalid.id}")
    assert invalid_response.status_code == 409
    assert invalid_response.json()["detail"]["canvas_safety"] == {
        "schema_version": "lg11-canvas-safety-v1",
        "checked": True,
        "safe": False,
        "channel": None,
        "issues": [{
            "code": "invalid_export_artifact_channel",
            "reason": "The frozen export artifact token does not contain a valid channel and format.",
            "section_id": None,
            "element_id": None,
        }],
    }

    # All output/download paths must expose the same structured safety issue
    # for their own immutable channel identity.
    version.sections_json["lg10"]["canonical_rendering"]["sections"][0]["canvas"] = {
        "is_visible": True,
        "height_px": 160,
    }
    version.sections_json["lg10"]["canonical_rendering"]["sections"][0]["canvas_elements"] = [{
        "element_id": "hero:asset", "kind": "asset", "x": 700, "y": 0,
        "width": 100, "height": 100, "z_index": 1, "locked": False,
    }]
    flag_modified(version, "sections_json")
    db_session.commit()

    preview = client.get(
        f"/api/v1/projects/{project.id}/page/final",
        params={"version_id": version.id, "channel": "smartstore"},
    )
    assert preview.status_code == 409
    expected_issue = preview.json()["detail"]["canvas_safety"]["issues"]
    assert expected_issue == [{
        "code": "element_overflow", "reason": "Element exceeds the channel safe area.",
        "section_id": "hero", "element_id": "hero:asset",
    }]

    for artifact, channel in artifacts:
        response = client.get(f"/api/v1/projects/{project.id}/page/export/download/{artifact.id}")
        detail = response.json()["detail"]
        assert response.status_code == 409
        safety = detail["canvas_safety"]
        assert safety["schema_version"] == "lg11-canvas-safety-v1"
        assert safety["checked"] is True and safety["safe"] is False
        assert safety["channel"] == channel
        assert safety["issues"] == expected_issue

    unsafe_standalone = client.post(
        f"/api/v1/projects/{project.id}/page/export/standalone",
        json={"final_version_id": version.id, "channel": "smartstore"},
    )
    assert unsafe_standalone.status_code == 409
    assert unsafe_standalone.json()["detail"]["canvas_safety"] == {
        **preview.json()["detail"]["canvas_safety"],
        "channel": "smartstore",
    }
