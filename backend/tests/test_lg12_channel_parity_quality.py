from __future__ import annotations

import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from src.db.models import ExportArtifact, ImageGenerationCostApprovalRecord, ImageGenerationJobRecord, ImageGenerationOutboxRecord
from src.schemas.lg12_quality_report import QualityAssessmentContractError
from src.services.export_service import write_lg12_frozen_export_parity_evidence
from src.services.channel_export_service import get_channel_preset, image_sha256
from src.services.page_finalization_service import resolve_lg10_brand_renderer_tokens
from src.services.prompt_intelligence_service import canonical_hash
from src.services.quality_assessment_service import (
    CHANNEL_PREVIEW_EXPORT_PARITY_EVALUATOR_VERSION,
    evaluate_channel_preview_export_parity_domain,
)
from src.services.renderer import render_lg10_canonical_page_html
from test_lg12_image_identity_quality import _setup as _image_setup
from test_lg12_quality_report_contract import _report_payload
from test_lg12i_version_contract import auth_headers as _headers


@pytest.fixture
def auth_headers():
    return _headers.__wrapped__()


def _artifact_file(tmp_path: Path, *, token: str) -> Path:
    suffix = token.rsplit(":", 1)[-1]
    path = tmp_path / (token.replace(":", "-") + (".zip" if token.startswith("channel_package") or token.startswith("lg10_standalone") else ".html" if suffix == "html" else f".{suffix}"))
    if token.startswith("channel_long"):
        image = Image.new("RGB", (860, 640), "white")
        image.save(path, "JPEG" if suffix in {"jpg", "jpeg"} else "PNG")
    elif path.suffix == ".zip":
        if token.startswith("channel_package"):
            _, channel, output_format = token.split(":")
            preset = get_channel_preset(channel)
            normalized_format = "jpg" if output_format in {"jpg", "jpeg"} else "png"
            image_path = tmp_path / f"{token.replace(':', '-')}-master.{normalized_format}"
            image = Image.new("RGB", (preset.width, 640), "white")
            image.save(image_path, "JPEG" if normalized_format == "jpg" else "PNG")
            payload = image_path.read_bytes()
            manifest = {
                "preset": {
                    "key": preset.key, "version": preset.version, "width": preset.width,
                    "max_segment_height": preset.max_segment_height, "default_format": preset.default_format,
                },
                "format": normalized_format, "master": image_path.name,
                "master_sha256": image_sha256(str(image_path)),
                "parts": [{"filename": f"part.{normalized_format}", "top": 0, "bottom": 640}],
            }
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(image_path.name, payload)
                archive.writestr(f"part.{normalized_format}", payload)
                archive.writestr("manifest.json", json.dumps(manifest))
        else:
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("manifest.json", "{}")
    else:
        path.write_text("<main data-detail-page-document='true'></main>", encoding="utf-8")
    return path


def _setup(db, client, headers, tmp_path):
    """Use a fully frozen approved-image page, not a layout-only fixture."""

    run, master, page, _manifest_hash, profile, asset = _image_setup(db, client, headers, tmp_path)
    prior = deepcopy(dict(page.sections_json or {})); prior.pop("snapshot_hash", None)
    prior_canonical = dict(dict(prior["lg10"])["canonical_page_assembly_input"])
    manifest = deepcopy(dict(prior_canonical["approved_asset_manifest"]))
    manifest_body = deepcopy(manifest); manifest_body.pop("manifest_hash", None)
    manifest["manifest_hash"] = canonical_hash(manifest_body)
    asset_ref = {"asset_id": asset.id, "asset_content_hash": asset.content_hash, "rights_status": "seller_owned"}
    sections = [
        {
            "section_id": "hero", "copy_ref": {"fields": ["hero_title", "hero_body"]},
            "approved_assets": [asset_ref], "rendering_mode": "approved_asset",
            "canvas": {"is_visible": True, "height_px": 500},
            "canvas_elements": [
                {"element_id": "hero:background", "kind": "background", "x": 0, "y": 0, "width": 760, "height": 500, "z_index": 0, "locked": True},
                {"element_id": "hero:text", "kind": "text", "x": 24, "y": 42, "width": 280, "height": 120, "z_index": 2, "locked": False},
                {"element_id": "hero:asset", "kind": "asset", "asset_id": asset.id, "asset_content_hash": asset.content_hash, "x": 380, "y": 42, "width": 320, "height": 320, "z_index": 1, "locked": False},
            ],
        },
        {
            "section_id": "specs", "copy_ref": {"fields": ["specs_title", "specs_body"]},
            "canvas": {"is_visible": True, "height_px": 500},
            "canvas_elements": [
                {"element_id": "specs:background", "kind": "background", "x": 0, "y": 0, "width": 760, "height": 500, "z_index": 0, "locked": True},
                {"element_id": "specs:text", "kind": "text", "x": 24, "y": 42, "width": 600, "height": 120, "z_index": 2, "locked": False},
            ],
        },
    ]
    canonical = {
        "design_direction": "balanced_sale",
        "planning_refs": {"copy": dict(master.copy_artifact_ref_json), "page_plan": dict(master.page_plan_artifact_ref_json)},
        "brand_kit_ref": {"brand_kit_version_id": master.brand_kit_version_id, "brand_kit_hash": master.brand_kit_hash},
        "image_generation_contract": {"required_scene_count": 1, "completion_basis": "approved_required_scenes"},
        "approved_asset_manifest": manifest, "page_asset_manifest": deepcopy(manifest), "sections": sections,
    }
    assembly = {"sections": [
        {"section_id": "hero", "sort_order": 0, "component_id": "media_with_copy", "layout_token": "image_text", "design_direction": "balanced_sale", "renderer_token": "balanced_sale_v1"},
        {"section_id": "specs", "sort_order": 1, "component_id": "information_only", "layout_token": "spec_table", "design_direction": "balanced_sale", "renderer_token": "balanced_sale_v1"},
    ]}
    brand_tokens = resolve_lg10_brand_renderer_tokens(run=run, brand_kit_ref=canonical["brand_kit_ref"], db=db)
    rendering = render_lg10_canonical_page_html(
        canonical_page_assembly_input=canonical, page_assembly=assembly,
        copy_set={"hero_title": "frozen hero", "hero_body": "frozen body", "specs_title": "frozen specs", "specs_body": "frozen details"},
        brand_tokens=brand_tokens,
    )
    rendering["render_hash"] = canonical_hash(rendering)
    body = {
        "schema_version": "lg10-detail-page-version-v1", "lg10": {"canonical_page_assembly_input": canonical, "canonical_rendering": rendering},
        "lg11": {"schema_version": "lg11-canvas-v1"}, "lg12_quality_lineage": dict(prior["lg12_quality_lineage"]),
        "commerce_renderer": {"sections": sections}, "sections": sections,
    }
    page.sections_json = {**body, "snapshot_hash": canonical_hash(body)}
    db.flush(); db.commit()
    manifest_hash = str(manifest["manifest_hash"])
    return run, master, page, manifest_hash, profile


def _add_artifact(db, *, run, page, tmp_path: Path, token: str, channel: str, evidence: bool = True) -> ExportArtifact:
    artifact = ExportArtifact(
        project_id=run.project_id, version_id=page.id, artifact_type=token,
        file_path=str(_artifact_file(tmp_path, token=token)),
    )
    db.add(artifact); db.flush()
    if evidence:
        write_lg12_frozen_export_parity_evidence(version=page, artifact=artifact, channel=channel)
    return artifact


def _evaluate(db, run, master, page, manifest_hash, profile, *, channel: str, artifacts=None):
    kwargs = {}
    if artifacts is not None:
        kwargs["export_artifact_ids"] = [artifact.id for artifact in artifacts]
    return evaluate_channel_preview_export_parity_domain(
        db,
        report_payload=_report_payload(
            run, page, manifest_hash, master, profile,
            report_id=f"channel-quality-report-{page.id}-{channel}",
        ),
        channel=channel,
        **kwargs,
    )


def _rewrite_sidecar(artifact: ExportArtifact, mutate) -> None:
    sidecar = Path(f"{artifact.file_path}.lg12-parity.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    mutate(payload)
    body = dict(payload); body.pop("evidence_hash", None)
    payload["evidence_hash"] = canonical_hash(body)
    sidecar.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    "channel,token",
    [("smartstore", "channel_long:smartstore:png"), ("coupang", "channel_long:coupang:jpg")],
)
def test_channel_preview_and_frozen_export_are_deterministic_for_each_production_channel(
    client, db_session, auth_headers, tmp_path, channel, token,
):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    artifact = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token=token, channel=channel)
    before = (
        db_session.query(ImageGenerationJobRecord).count(), db_session.query(ImageGenerationOutboxRecord).count(),
        db_session.query(ImageGenerationCostApprovalRecord).count(),
    )
    first = _evaluate(db_session, run, master, page, manifest_hash, profile, channel=channel, artifacts=[artifact])
    assert first == _evaluate(db_session, run, master, page, manifest_hash, profile, channel=channel, artifacts=[artifact])
    assert first["domain"]["status"] == "complete"
    assert first["domain"]["evaluator_version"] == CHANNEL_PREVIEW_EXPORT_PARITY_EVALUATOR_VERSION
    assert not first["critical_violations"]
    assert before == (
        db_session.query(ImageGenerationJobRecord).count(), db_session.query(ImageGenerationOutboxRecord).count(),
        db_session.query(ImageGenerationCostApprovalRecord).count(),
    )


def test_png_jpg_html_zip_and_package_artifacts_share_one_frozen_preview_identity(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    artifacts = [
        _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:png", channel="smartstore"),
        _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_package:smartstore:zip", channel="smartstore"),
        _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="lg10_copyable_html:smartstore", channel="smartstore"),
        _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="lg10_standalone_package:smartstore", channel="smartstore"),
    ]
    result = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=artifacts)
    assert result["domain"]["status"] == "complete"
    assert {item["metric_id"] for item in result["domain"]["submetrics"]} == {
        "channel_binding", "preview_identity", "export_identity", "preview_export_parity", "channel_contract",
    }


def test_unknown_or_cross_channel_artifact_is_a_structured_critical_finding(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    cross = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:coupang:jpg", channel="coupang")
    malformed = ExportArtifact(project_id=run.project_id, version_id=page.id, artifact_type="channel_long:png:smartstore", file_path=str(_artifact_file(tmp_path, token="channel_long:smartstore:png")))
    db_session.add(malformed); db_session.flush()
    result = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[cross, malformed])
    codes = {item["code"] for item in result["domain"]["findings"]}
    assert {"cross_channel_export_artifact", "malformed_export_artifact_token"} <= codes
    assert result["domain"]["critical_count"] == 2
    with pytest.raises(QualityAssessmentContractError):
        _evaluate(db_session, run, master, page, manifest_hash, profile, channel="unknown", artifacts=[cross])


def test_default_discovery_is_channel_scoped_but_explicit_cross_channel_injection_is_critical(
    client, db_session, auth_headers, tmp_path,
):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    smartstore = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:png", channel="smartstore")
    coupang = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:coupang:jpg", channel="coupang")

    smartstore_default = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore")
    coupang_default = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="coupang")
    assert smartstore_default["domain"]["status"] == "complete"
    assert coupang_default["domain"]["status"] == "complete"
    assert "cross_channel_export_artifact" not in {item["code"] for item in smartstore_default["domain"]["findings"]}
    assert "cross_channel_export_artifact" not in {item["code"] for item in coupang_default["domain"]["findings"]}

    assert _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[smartstore])["domain"]["status"] == "complete"
    injected = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[coupang])
    mixed = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[smartstore, coupang])
    assert "cross_channel_export_artifact" in {item["code"] for item in injected["domain"]["findings"]}
    assert "cross_channel_export_artifact" in {item["code"] for item in mixed["domain"]["findings"]}


def test_missing_evidence_is_needs_review_but_hash_tamper_is_fail_closed(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    missing = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:png", channel="smartstore", evidence=False)
    result = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[missing])
    assert result["domain"]["status"] == "needs_review"
    assert "missing_frozen_export_evidence" in {item["code"] for item in result["domain"]["findings"]}

    artifact = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:jpg", channel="smartstore")
    sidecar = Path(f"{artifact.file_path}.lg12-parity.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8")); payload["manifest_hash"] = "f" * 64
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(QualityAssessmentContractError, match="parity evidence"):
        _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.__setitem__("layout_evidence_hash", None),
        lambda payload: payload.__setitem__("layout_evidence_hash", ""),
        lambda payload: payload.pop("page_plan_ref"),
        lambda payload: payload["page_plan_ref"].__setitem__("id", ""),
        lambda payload: payload["page_plan_ref"].update({"version": "", "hash": ""}),
        lambda payload: payload.pop("brand_kit_ref"),
        lambda payload: payload["brand_kit_ref"].update({"id": "", "version": "", "hash": ""}),
    ],
)
def test_missing_mandatory_export_evidence_is_needs_review_not_complete(
    client, db_session, auth_headers, tmp_path, mutate,
):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    artifact = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:png", channel="smartstore")
    _rewrite_sidecar(artifact, mutate)
    result = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])
    assert result["domain"]["status"] == "needs_review"
    assert all(item["status"] != "passed" for item in result["domain"]["submetrics"] if item["metric_id"] in {"preview_identity", "export_identity", "preview_export_parity"})


def test_missing_preview_layout_or_master_ref_is_needs_review_and_persisted_ref_substitution_is_fail_closed(
    client, db_session, auth_headers, tmp_path, monkeypatch,
):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    artifact = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:png", channel="smartstore")
    from src.services import quality_assessment_service as service

    original = service.frozen_preview_parity_evidence
    for field, value in (("layout_evidence_hash", None), ("page_plan_ref", {"id": "", "version": "", "hash": "", "type": "PagePlanVersion"}), ("brand_kit_ref", {"id": "", "version": "", "hash": "", "type": "BrandKitVersion"})):
        monkeypatch.setattr(service, "frozen_preview_parity_evidence", lambda *args, _field=field, _value=value, **kwargs: {**original(*args, **kwargs), _field: _value})
        result = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])
        assert result["domain"]["status"] == "needs_review"
    monkeypatch.setattr(service, "frozen_preview_parity_evidence", original)

    empty_plan = {"id": "", "version": "", "hash": "", "type": "PagePlanVersion"}
    empty_brand = {"id": "", "version": "", "hash": "", "type": "BrandKitVersion"}
    _rewrite_sidecar(artifact, lambda payload: payload.update({"page_plan_ref": empty_plan, "brand_kit_ref": empty_brand}))
    monkeypatch.setattr(service, "frozen_preview_parity_evidence", lambda *args, **kwargs: {**original(*args, **kwargs), "page_plan_ref": empty_plan, "brand_kit_ref": empty_brand})
    assert _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])["domain"]["status"] == "needs_review"
    monkeypatch.setattr(service, "frozen_preview_parity_evidence", original)
    write_lg12_frozen_export_parity_evidence(version=page, artifact=artifact, channel="smartstore")

    def fake_plan(*args, **kwargs):
        payload = original(*args, **kwargs)
        payload["page_plan_ref"] = {"id": "fake-plan", "version": 1, "hash": "a" * 64, "type": "PagePlanVersion"}
        return payload

    monkeypatch.setattr(service, "frozen_preview_parity_evidence", fake_plan)
    with pytest.raises(QualityAssessmentContractError, match="PagePlan reference"):
        _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])


def test_valid_hash_recomputed_parity_substitution_is_critical_and_file_tamper_fails_closed(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    artifact = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:png", channel="smartstore")
    sidecar = Path(f"{artifact.file_path}.lg12-parity.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8")); payload["asset_refs"] = []
    body = dict(payload); body.pop("evidence_hash")
    payload["evidence_hash"] = canonical_hash(body)
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    result = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])
    assert "preview_export_asset_refs_mismatch" in {item["code"] for item in result["domain"]["findings"]}

    Path(artifact.file_path).write_bytes(b"tampered")
    with pytest.raises(QualityAssessmentContractError, match="bytes"):
        _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda payload: payload["page_ref"].__setitem__("id", "other-frozen-page"), "preview_export_page_ref_mismatch"),
        (lambda payload: payload["sections"].pop(), "preview_export_sections_mismatch"),
        (lambda payload: payload["sections"][0].__setitem__("height_px", 999), "preview_export_sections_mismatch"),
        (lambda payload: payload["element_refs"][0].__setitem__("element_hash", "a" * 64), "preview_export_element_refs_mismatch"),
        (lambda payload: payload["copy_refs"][0].__setitem__("text_hash", "f" * 64), "preview_export_copy_refs_mismatch"),
        (lambda payload: payload["renderer_ref"].__setitem__("hash", "e" * 64), "preview_export_renderer_ref_mismatch"),
        (lambda payload: payload["page_plan_ref"].__setitem__("hash", "d" * 64), "preview_export_page_plan_ref_mismatch"),
        (lambda payload: payload["brand_kit_ref"].__setitem__("hash", "c" * 64), "preview_export_brand_kit_ref_mismatch"),
        (lambda payload: payload["preset"].__setitem__("key", "coupang"), "preview_export_preset_mismatch"),
        (lambda payload: payload.__setitem__("transform_version", "untrusted-transform-v1"), "unauthorized_channel_transform"),
    ],
)
def test_rehashed_preview_export_identity_substitution_is_structured_critical(
    client, db_session, auth_headers, tmp_path, mutate, expected_code,
):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    artifact = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:png", channel="smartstore")
    sidecar = Path(f"{artifact.file_path}.lg12-parity.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    mutate(payload)
    body = dict(payload); body.pop("evidence_hash", None)
    payload["evidence_hash"] = canonical_hash(body)
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    if expected_code in {"preview_export_page_plan_ref_mismatch", "preview_export_brand_kit_ref_mismatch"}:
        with pytest.raises(QualityAssessmentContractError, match="persisted Master"):
            _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])
        return
    result = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])
    assert expected_code in {item["code"] for item in result["domain"]["findings"]}
    assert result["domain"]["critical_count"] >= 1


def test_arbitrary_raw_export_body_is_rejected_even_when_sidecar_hash_is_recomputed(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    artifact = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:png", channel="smartstore")
    sidecar = Path(f"{artifact.file_path}.lg12-parity.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8")); payload["unrelated"] = {"raw_export_body": "<main>copied</main>"}
    body = dict(payload); body.pop("evidence_hash", None)
    payload["evidence_hash"] = canonical_hash(body)
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(QualityAssessmentContractError, match="unsupported"):
        _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])


def test_lg11_unsafe_canvas_is_a_structured_channel_critical_with_element_identity(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    artifact = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_long:smartstore:png", channel="smartstore")
    snapshot = deepcopy(dict(page.sections_json)); snapshot.pop("snapshot_hash", None)
    rendering = snapshot["lg10"]["canonical_rendering"]
    rendering["sections"][0]["canvas_elements"][2]["width"] = 800
    rendering["render_hash"] = canonical_hash({key: value for key, value in rendering.items() if key != "render_hash"})
    page.sections_json = {**snapshot, "snapshot_hash": canonical_hash(snapshot)}
    db_session.flush()
    result = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])
    finding = next(item for item in result["domain"]["findings"] if item["code"] == "unsafe_channel_element_overflow")
    assert {item["type"] for item in finding["target_refs"]} >= {"DetailPageVersion", "section", "element"}
    assert finding["severity"] == "critical"


@pytest.mark.parametrize(
    ("manifest_format", "part_format", "expect_complete"),
    [
        ("png", "png", True),
        ("jpg", "png", False),
        ("png", "jpg", False),
    ],
)
def test_channel_package_manifest_and_member_formats_must_match_the_preset(
    client, db_session, auth_headers, tmp_path, manifest_format, part_format, expect_complete,
):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    artifact = _add_artifact(db_session, run=run, page=page, tmp_path=tmp_path, token="channel_package:smartstore:zip", channel="smartstore")
    package_path = Path(artifact.file_path)
    with zipfile.ZipFile(package_path) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        master_payload = archive.read(manifest["master"])
    manifest["format"] = manifest_format
    if part_format == "jpg":
        replacement = tmp_path / "mixed-part.jpg"
        Image.new("RGB", (860, 640), "white").save(replacement, "JPEG")
        part_payload = replacement.read_bytes()
        manifest["parts"][0]["filename"] = replacement.name
    else:
        part_payload = master_payload
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr(manifest["master"], master_payload)
        archive.writestr(manifest["parts"][0]["filename"], part_payload)
        archive.writestr("manifest.json", json.dumps(manifest))
    _rewrite_sidecar(artifact, lambda payload: payload.__setitem__("file_sha256", image_sha256(str(package_path))))
    result = _evaluate(db_session, run, master, page, manifest_hash, profile, channel="smartstore", artifacts=[artifact])
    if expect_complete:
        assert result["domain"]["status"] == "complete"
    else:
        finding = next(item for item in result["domain"]["findings"] if item["code"] == "channel_package_contract_mismatch")
        assert finding["severity"] == "critical"
