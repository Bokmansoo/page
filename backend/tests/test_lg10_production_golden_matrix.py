"""Zero-cost production LG-10 golden matrix over the durable fake provider."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import zipfile
from unittest.mock import patch

import pytest
from PIL import Image

from src.db.models import AgentRun, Asset, DetailPageVersion, ImageGenerationJobRecord, ProductProject
from src.services.export_service import build_lg10_standalone_export_bundle
from test_lg5_image_generation_subgraph import (
    _cost_hash,
    _create_run,
    _resume,
    _to_generation_pending,
    auth_headers as _lg5_auth_headers,
    lg5_runtime as _lg5_runtime,
)


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


@pytest.fixture
def lg5_runtime(monkeypatch):
    return _lg5_runtime.__wrapped__(monkeypatch)


def _fake_export_capture(tmp_path, captured):
    def capture(**kwargs):
        output_format = str(kwargs["output_format"])
        extension = "jpg" if output_format in {"jpg", "jpeg"} else "png"
        image_path = tmp_path / f"golden-{kwargs['version_id']}.{extension}"
        Image.new("RGB", (24, 24), color=(32, 96, 160)).save(
            image_path, format="JPEG" if extension == "jpg" else "PNG"
        )
        zip_path = tmp_path / f"golden-{kwargs['version_id']}-{extension}.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr(f"01-section.{extension}", image_path.read_bytes())
        captured[output_format] = dict(kwargs)
        return {
            "long_vertical_image": str(image_path),
            "section_images_zip": str(zip_path),
            "section_heights": [24],
        }

    return capture


def _planning_review(client, auth_headers, run_id):
    state = client.post(f"/api/v1/graph-runs/{run_id}/start", headers=auth_headers).json()
    state = _resume(client, auth_headers, state, "approve").json()
    state = _resume(client, auth_headers, state, "approve").json()
    assert state["current_stage"] == "planning_review"
    return state


def _configure_no_generation_plan(db_session, run, *, information_only: bool) -> None:
    project = db_session.query(ProductProject).filter_by(id=run.project_id).one()
    draft = deepcopy(project.planning_draft or {})
    cards = [dict(card) for card in draft.get("cards") or []]
    assert cards
    for card in cards:
        card["image_requirement"] = "seller_upload_required"
    draft["cards"] = cards
    project.planning_draft = draft

    outputs = deepcopy(run.outputs_json or {})
    artifacts = deepcopy(outputs["langgraph_commerce_planning_artifacts"])
    visual_artifact = deepcopy(artifacts["visual_planning"])
    visual_output = deepcopy(visual_artifact["output"])
    scenes = [dict(scene) for scene in visual_output.get("scene_plan") or []]
    assert scenes
    for index, scene in enumerate(scenes):
        use_original = not information_only and index == 0
        scene["generation_mode"] = "safe_existing_photo" if use_original else "html_information_fallback"
        scene["rendering_strategy"] = "safe_existing_photo" if use_original else "html_information_fallback"
        scene["mock_status"] = "asset_ready" if use_original else "information_fallback"
    visual_output["scene_plan"] = scenes
    metadata = {
        key: value
        for key, value in dict(visual_artifact.get("metadata") or {}).items()
        if key != "artifact_hash"
    }
    visual_artifact["output"] = visual_output
    visual_artifact["metadata"] = {
        **metadata,
        "artifact_hash": hashlib.sha256(
            json.dumps(
                {"stage": "visual_planning", "output": visual_output, "metadata": metadata},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest(),
    }
    artifacts["visual_planning"] = visual_artifact
    outputs["langgraph_commerce_planning_artifacts"] = artifacts
    run.outputs_json = outputs
    db_session.add_all([project, run])
    db_session.commit()


@pytest.mark.parametrize("information_only", (True, False), ids=("information-only", "seller-owned-fallback"))
def test_lg10_production_completes_without_required_image_jobs(
    client, auth_headers, db_session, lg5_runtime, tmp_path, information_only
):
    """The LG-10 graph completes without provider work when images are optional or seller-owned."""

    run = _create_run(client, auth_headers, db_session, tmp_path)
    planning_review = _planning_review(client, auth_headers, run.id)
    run = db_session.query(AgentRun).filter_by(id=run.id).one()
    _configure_no_generation_plan(db_session, run, information_only=information_only)

    resumed = _resume(client, auth_headers, planning_review, "approve")
    assert resumed.status_code == 200, resumed.text
    state = resumed.json()
    assert state["status"] == "awaiting_review"
    assert state["values"]["review"]["pending"]["review_stage"] == "quality_review"
    assert state["values"]["quality"]["quality_bar_verdict"] == "NEEDS_REVIEW"
    assert state["values"]["quality"]["seller_review_required"] is True
    generation = state["values"]["generation"]
    assert generation["image_generation_required"] is False
    assert generation["required_scene_count"] == 0
    assert generation["all_required_scenes_approved"] is True
    assert generation.get("jobs", []) == []
    # Canonical assembly inputs are persisted on the immutable page version,
    # not exposed through the bounded seller-facing generation projection.
    assert "completion_basis" not in generation
    assert "canonical_page_assembly_input" not in generation
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == 0

    version_id = state["values"]["rendering"]["detail_page_version"]["id"]
    version = db_session.query(DetailPageVersion).filter_by(id=version_id, project_id=run.project_id).one()
    snapshot = version.sections_json
    canonical_input = snapshot["lg10"]["canonical_page_assembly_input"]
    assert canonical_input["approved_asset_manifest"] is None
    assert canonical_input["image_generation_contract"] == {
        "required_scene_count": 0,
        "completion_basis": "no_required_image_scenes",
    }
    assembly = snapshot["lg10"]["page_assembly"]
    rendering = snapshot["lg10"]["canonical_rendering"]
    assert assembly["page_asset_manifest_ref"] == {
        "manifest_hash": canonical_input["page_asset_manifest"]["manifest_hash"]
    }

    rendered_assets = {
        (asset["asset_id"], asset["asset_content_hash"])
        for section in rendering["sections"]
        for asset in section["asset_layer"]
    }
    manifest_assets = {
        (asset["asset_id"], asset["asset_content_hash"])
        for asset in canonical_input["page_asset_manifest"]["assets"]
    }
    assert rendered_assets == manifest_assets
    if information_only:
        assert not manifest_assets
        assert all(section["component_id"] == "information_only" for section in rendering["sections"])
    else:
        assert manifest_assets
        assert any(section["selection_basis"] == "seller_owned_fallback" for section in assembly["sections"])
        allowed_assets = {
            asset.id
            for asset in db_session.query(Asset).filter_by(project_id=run.project_id).all()
            if asset.usage_status == "seller_owned"
        }
        assert {asset_id for asset_id, _ in manifest_assets} <= allowed_assets

    bundle = build_lg10_standalone_export_bundle(
        db=db_session,
        project_id=run.project_id,
        version=version,
        output_dir=str(tmp_path / f"standalone-{information_only}"),
    )
    with zipfile.ZipFile(bundle["zip_path"]) as archive:
        bundled = json.loads(archive.read("approved-asset-manifest.json"))
        assert bundled["detail_page_version_id"] == version_id
        assert bundled["approved_asset_manifest"] == canonical_input["page_asset_manifest"]
        bundled_images = {name for name in archive.namelist() if name.startswith("assets/")}
    assert bool(bundled_images) is (not information_only)


def test_lg10_no_generation_path_rejects_ineligible_fallback_assets(
    client, auth_headers, db_session, lg5_runtime, tmp_path
):
    """Blocked/reference-only assets cannot make a required visual section complete."""

    from src.services.page_finalization_service import (
        PageAssemblyInputError,
        build_canonical_page_assembly_input,
        build_page_assembly_structure,
    )

    run = _create_run(client, auth_headers, db_session, tmp_path)
    _planning_review(client, auth_headers, run.id)
    run = db_session.query(AgentRun).filter_by(id=run.id).one()
    _configure_no_generation_plan(db_session, run, information_only=False)
    for index, asset in enumerate(db_session.query(Asset).filter_by(project_id=run.project_id).all()):
        asset.usage_status = "blocked" if index == 0 else "reference_only"
    db_session.commit()

    canonical_input = build_canonical_page_assembly_input(
        run=run,
        approved_asset_manifest=None,
        db=db_session,
    )
    assert canonical_input["page_asset_manifest"]["assets"] == []
    assert all(not section["seller_owned_fallback_assets"] for section in canonical_input["sections"])
    with pytest.raises(PageAssemblyInputError, match="incomplete required image scene"):
        build_page_assembly_structure(canonical_page_assembly_input=canonical_input)
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == 0


@pytest.mark.lg10_fake_e2e
@pytest.mark.parametrize("direction", ("safe_information", "image_centric", "balanced_sale"))
def test_lg10_fake_provider_production_golden_matrix(
    client, auth_headers, db_session, lg5_runtime, testing_session_local, tmp_path, direction
):
    """One approved fake scene reaches the frozen LG-10 outputs for every direction."""
    from src.db.database import SessionLocal
    from src.services.image_generation_worker import run_image_worker_batch

    run = _create_run(client, auth_headers, db_session, tmp_path)
    run.input_snapshot = {
        **run.input_snapshot,
        "product_name": "휴대용 제품",
        "design_direction": direction,
    }
    db_session.commit()

    # Make the golden scenario explicitly require provider work; the shared
    # helper otherwise permits the no-image path to advance directly to QA.
    generation_pending = _to_generation_pending(
        client, auth_headers, run.id, db_session, minimum_generation_scenes=2
    )
    provider_wait = _resume(
        client,
        auth_headers,
        generation_pending,
        "approve",
        cost_plan_hash=_cost_hash(generation_pending),
    )
    assert provider_wait.status_code == 200, provider_wait.text
    assert provider_wait.json()["current_stage"] == "provider_wait"

    worker_db = SessionLocal()
    try:
        worker_results = run_image_worker_batch(worker_db, owner=f"lg10-golden-{direction}", batch_size=100)
    finally:
        worker_db.close()
    assert worker_results
    db_session.expire_all()
    assert all(
        job.actual_cost == 0
        for job in db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
    )

    state = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers).json()
    while state["status"] == "awaiting_review" and state["values"]["review"]["pending"]["review_stage"] == "image_review":
        target = next(
            job for job in state["values"]["generation"]["jobs"] if job["status"] == "needs_review"
        )
        response = _resume(client, auth_headers, state, "approve", job_id=target["job_id"])
        assert response.status_code == 200, response.text
        state = response.json()
    assert state["status"] == "awaiting_review"
    assert state["values"]["review"]["pending"]["review_stage"] == "quality_review"
    assert state["values"]["quality"]["quality_bar_verdict"] == "NEEDS_REVIEW"

    generation = state["values"]["generation"]
    version_ref = state["values"]["rendering"]["detail_page_version"]
    version = db_session.query(DetailPageVersion).filter_by(id=version_ref["id"], project_id=run.project_id).one()
    snapshot = deepcopy(version.sections_json)
    canonical_input = snapshot["lg10"]["canonical_page_assembly_input"]
    manifest = canonical_input["approved_asset_manifest"]
    assembly = snapshot["lg10"]["page_assembly"]
    rendering = snapshot["lg10"]["canonical_rendering"]
    assert all(job["status"] == "approved" for job in generation["jobs"])
    assert all(re.fullmatch(r"[0-9a-f]{64}", asset["asset_content_hash"]) for asset in manifest["assets"])
    assert assembly["design_direction"] == rendering["design_direction"] == direction
    assert assembly["approved_asset_manifest_ref"] == {"manifest_hash": manifest["manifest_hash"]}
    assert re.search(r"[가-힣]", rendering["html"])
    assert all(section["component_id"] in {"media_with_copy", "information_only"} for section in rendering["sections"])
    page_rule = re.search(r"\.sf-page\s*\{(?P<declarations>[^}]*)\}", rendering["css"])
    assert page_rule, "The deterministic renderer must emit the .sf-page selector."
    assert re.search(r"max-width\s*:\s*760px(?:;|$)", page_rule["declarations"])
    assert re.search(r"position\s*:\s*relative(?:;|$)", page_rule["declarations"])
    assert re.fullmatch(r"[0-9a-f]{64}", rendering["render_hash"])
    assert rendering["canonical_input_ref"]["input_hash"] == canonical_input["input_hash"]
    assert rendering["page_assembly_ref"]["assembly_hash"] == assembly["assembly_hash"]

    version_id = version.id
    assert version.is_final is True
    assert snapshot["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"] == manifest
    assert snapshot["lg10"]["page_assembly"] == assembly
    assert snapshot["lg10"]["canonical_rendering"] == {
        key: value for key, value in rendering.items() if key != "detail_page_version"
    }

    preview = client.get(
        f"/api/v1/projects/{run.project_id}/page/final?version_id={version_id}", headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["sections_json"] == snapshot

    captured: dict[str, dict] = {}
    with patch("src.api.exports.SessionLocal", testing_session_local), patch(
        "src.services.export_service.capture_next_render_export",
        side_effect=_fake_export_capture(tmp_path, captured),
    ):
        for output_format in ("png", "jpg"):
            started = client.post(
                f"/api/v1/projects/{run.project_id}/page/export",
                headers=auth_headers,
                json={
                    "preset_name": "coupang",
                    "output_format": output_format,
                    "export_target": "local_download",
                    "final_version_id": version_id,
                },
            )
            assert started.status_code == 202, started.text
            completed = client.get(
                f"/api/v1/projects/{run.project_id}/page/export/jobs/{started.json()['id']}", headers=auth_headers
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["status"] == "completed"
    assert set(captured) == {"png", "jpg"}
    assert all(item["version_id"] == version_id for item in captured.values())

    bundle = build_lg10_standalone_export_bundle(
        db=db_session, project_id=run.project_id, version=version, output_dir=str(tmp_path / "standalone")
    )
    with zipfile.ZipFile(bundle["zip_path"]) as archive:
        bundled_manifest = json.loads(archive.read("approved-asset-manifest.json"))
    assert bundled_manifest["detail_page_version_id"] == version_id
    assert bundled_manifest["approved_asset_manifest"] == manifest
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id, status="approved").count() == len(
        generation["jobs"]
    )
