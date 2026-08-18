"""TASK-11.7 production LG-11 section canvas draft tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from src.db.models import AgentRun, DetailPageVersion, ImageGenerationCostApprovalRecord, ImageGenerationOutboxRecord
from src.services.export_service import build_lg10_copyable_html, build_lg10_standalone_export_bundle
from test_lg11_edit_intent_preview import _frozen_lg10_version
from test_lg11_edit_run import lg11_runtime
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers

pytestmark = pytest.mark.lg11_fake_e2e


def _request(version_id: str):
    return {"scope": "page", "target_ids": [version_id], "operation": "canvas_draft", "instruction": "Reorder sections in the Canvas draft only.", "preserve_constraints": {"retain_approved_assets": True}}


def _resume(client, headers, state, decision, operation=None):
    pending = state["values"]["review"]["pending"]
    return client.post(f"/api/v1/graph-runs/{state['run_id']}/resume", headers=headers, json={"thread_id": state["thread_id"], "response": {"schema_version": pending["schema_version"], "review_stage": pending["review_stage"], "decision": decision, "canvas_operation": operation or {}}})


def _start(client, headers, run, version):
    response = client.post(f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-runs", headers=headers, json=_request(version.id))
    assert response.status_code == 201, response.text
    state = client.get(f"/api/v1/graph-runs/{response.json()['run_id']}", headers=headers).json()
    return response.json(), state


def test_lg11_canvas_draft_is_reversible_and_commits_only_one_immutable_child(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__(); source_run = _create_run(client, headers, db_session, tmp_path)
    source, _, asset_id = _frozen_lg10_version(db_session, source_run); source_snapshot = deepcopy(source.sections_json)
    started, state = _start(client, headers, source_run, source)
    state = _resume(client, headers, state, "approve").json()
    assert state["status"] == "awaiting_review" and state["values"]["review"]["pending"]["review_stage"] == "canvas_edit"
    before = db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count()
    original = [item["section_id"] for item in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"]]
    invalid = _resume(client, headers, state, "apply", {"operation_id": "move-spec", "kind": "reorder", "section_id": original[1], "position": 0}).json()
    assert invalid["values"]["edit"]["canvas_last_error"]
    state = _resume(client, headers, invalid, "apply", {"operation_id": "add-leading", "kind": "add", "position": 0}).json()
    added_leading = state["values"]["canvas"]["canonical_page_assembly_input"]["sections"][0]["section_id"]
    state = _resume(client, headers, state, "apply", {"operation_id": "move-added", "kind": "reorder", "section_id": added_leading, "position": 1}).json()
    moved = [item["section_id"] for item in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"]]
    assert moved[-1] == original[1]
    state = _resume(client, headers, state, "undo", {"operation_id": "undo-1"}).json()
    assert [item["section_id"] for item in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"]] == [added_leading, *original]
    state = _resume(client, headers, state, "redo", {"operation_id": "redo-1"}).json()
    assert [item["section_id"] for item in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"]] == moved
    state = _resume(client, headers, state, "apply", {"operation_id": "add", "kind": "add", "position": 1}).json()
    added = state["values"]["canvas"]["canonical_page_assembly_input"]["sections"][1]["section_id"]
    state = _resume(client, headers, state, "apply", {"operation_id": "height", "kind": "set_height", "section_id": added, "height_px": 320}).json()
    state = _resume(client, headers, state, "apply", {"operation_id": "hide", "kind": "set_visibility", "section_id": added, "is_visible": False}).json()
    state = _resume(client, headers, state, "apply", {"operation_id": "remove-added", "kind": "remove", "section_id": added}).json()
    assert [item["section_id"] for item in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"]] == moved
    state = _resume(client, headers, state, "apply", {"operation_id": "duplicate", "kind": "duplicate", "section_id": moved[0], "position": 1}).json()
    assert len(state["values"]["canvas"]["canonical_page_assembly_input"]["sections"]) == len(moved) + 1
    state = _resume(client, headers, state, "undo", {"operation_id": "undo-duplicate"}).json()
    assert [item["section_id"] for item in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"]] == moved
    rejected = _resume(client, headers, state, "apply", {"operation_id": "remove-source", "kind": "remove", "section_id": original[0]}).json()
    assert rejected["status"] == "awaiting_review"
    assert rejected["values"]["edit"]["canvas_last_error"]
    completed = _resume(client, headers, rejected, "commit").json()
    assert completed["status"] == "completed"
    fork = completed["values"]["edit"]["canvas_version_fork"]
    child = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()
    assert child.sections_json["lg11"]["parent_detail_page_version_id"] == source.id
    assert [item["section_id"] for item in child.sections_json["lg10"]["canonical_page_assembly_input"]["sections"]] == moved
    assert asset_id in {
        asset["asset_id"]
        for section in child.sections_json["lg10"]["canonical_page_assembly_input"]["sections"]
        for asset in section.get("approved_assets") or []
    }
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == before + 1
    db_session.refresh(source); assert source.sections_json == source_snapshot
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=started["run_id"]).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=started["run_id"]).count() == 0


def test_lg11_canvas_restart_rebuild_restores_draft_and_commit_lineage(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__(); source_run = _create_run(client, headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run); started, state = _start(client, headers, source_run, source)
    state = _resume(client, headers, state, "approve").json(); sections = state["values"]["canvas"]["canonical_page_assembly_input"]["sections"]
    state = _resume(client, headers, state, "apply", {"operation_id": "add", "kind": "add", "position": 0}).json()
    changed = _resume(client, headers, state, "apply", {"operation_id": "move", "kind": "reorder", "section_id": state["values"]["canvas"]["canonical_page_assembly_input"]["sections"][0]["section_id"], "position": 1}).json()
    expected = deepcopy(changed["values"]["canvas"])
    run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one(); run.outputs_json = {}; run.status = "running"; db_session.commit()
    restored = client.post(f"/api/v1/graph-runs/{started['run_id']}/resume", headers=headers)
    assert restored.status_code == 409, restored.text
    db_session.refresh(run); assert run.outputs_json["langgraph_canvas"] == expected
    state = client.get(f"/api/v1/graph-runs/{started['run_id']}", headers=headers).json()
    done = _resume(client, headers, state, "commit").json(); fork = done["values"]["edit"]["canvas_version_fork"]
    assert db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one().sections_json == fork["snapshot"]


def test_lg11_canvas_visibility_and_height_are_frozen_for_all_lg10_outputs(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__()
    source_run = _create_run(client, headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    source_snapshot = deepcopy(source.sections_json)
    started, state = _start(client, headers, source_run, source)
    state = _resume(client, headers, state, "approve").json()

    state = _resume(client, headers, state, "apply", {
        "operation_id": "add-canvas-output-section", "kind": "add", "position": 1,
    }).json()
    section_id = state["values"]["canvas"]["canonical_page_assembly_input"]["sections"][1]["section_id"]
    state = _resume(client, headers, state, "apply", {
        "operation_id": "set-canvas-output-height", "kind": "set_height", "section_id": section_id, "height_px": 360,
    }).json()
    state = _resume(client, headers, state, "apply", {
        "operation_id": "hide-canvas-output-section", "kind": "set_visibility", "section_id": section_id, "is_visible": False,
    }).json()
    state = _resume(client, headers, state, "undo", {"operation_id": "undo-hide-canvas-output-section"}).json()
    restored_canvas = next(item for item in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"] if item["section_id"] == section_id)["canvas"]
    assert restored_canvas == {"is_visible": True, "height_px": 360, "origin": "canvas_added"}
    state = _resume(client, headers, state, "redo", {"operation_id": "redo-hide-canvas-output-section"}).json()
    completed = _resume(client, headers, state, "commit").json()
    child = db_session.query(DetailPageVersion).filter_by(
        id=completed["values"]["edit"]["canvas_version_fork"]["detail_page_version_id"]
    ).one()

    frozen_canvas = next(item for item in child.sections_json["lg10"]["canonical_page_assembly_input"]["sections"] if item["section_id"] == section_id)["canvas"]
    preview_section = next(item for item in child.sections_json["commerce_renderer"]["sections"] if item["id"] == section_id)
    assert frozen_canvas == {"is_visible": False, "height_px": 360, "origin": "canvas_added"}
    assert preview_section["is_visible"] is False
    assert preview_section["height_px"] == 360
    assert preview_section["visual_payload"]["canvas_height_px"] == 360
    assert preview_section["visual_payload"]["canvas_is_visible"] is False

    rendering = child.sections_json["lg10"]["canonical_rendering"]
    assert f'data-section-id="{section_id}"' not in rendering["html"]
    copyable = build_lg10_copyable_html(db=db_session, project_id=source_run.project_id, version=child)
    assert f'data-section-id="{section_id}"' not in copyable["html"]
    bundle = build_lg10_standalone_export_bundle(
        db=db_session, project_id=source_run.project_id, version=child, output_dir=str(tmp_path / "canvas-standalone"),
    )
    assert f'data-section-id="{section_id}"' not in Path(bundle["html_path"]).read_text(encoding="utf-8")
    assert f'data-section-id="{section_id}"' not in (Path(bundle["html_path"]).parent / "index.html").read_text(encoding="utf-8")
    db_session.refresh(source)
    assert source.sections_json == source_snapshot
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=started["run_id"]).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=started["run_id"]).count() == 0
