"""TASK-11.8 production Canvas element draft coverage."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest

from src.db.models import AgentRun, Asset, DetailPageVersion, ImageGenerationCostApprovalRecord, ImageGenerationOutboxRecord
from src.services.page_finalization_service import _lg11_canvas_default_elements
from test_lg11_canvas_section_draft import _resume, _start
from test_lg11_edit_intent_preview import _frozen_lg10_version
from test_lg11_edit_run import lg11_runtime
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers

pytestmark = pytest.mark.lg11_fake_e2e


def _element(state, element_id):
    return next(
        element
        for section in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"]
        for element in section.get("canvas_elements") or []
        if element["element_id"] == element_id
    )


def test_lg11_canvas_element_commands_are_reversible_and_commit_a_frozen_child(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__()
    source_run = _create_run(client, headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    source_snapshot = deepcopy(source.sections_json)
    started, state = _start(client, headers, source_run, source)
    state = _resume(client, headers, state, "approve").json()
    hero = next(section for section in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"] if section["section_id"] == "hero")
    asset_id, text_id = "hero:asset", "hero:text"
    assert {item["element_id"] for item in hero["canvas_elements"]} >= {asset_id, text_id, "hero:background"}

    state = _resume(client, headers, state, "apply", {"operation_id": "move-asset", "kind": "move_element", "section_id": "hero", "element_id": asset_id, "dx": 30, "dy": 12}).json()
    state = _resume(client, headers, state, "apply", {"operation_id": "resize-asset", "kind": "resize_element", "section_id": "hero", "element_id": asset_id, "width": 600, "height": 420}).json()
    state = _resume(client, headers, state, "apply", {"operation_id": "z-asset", "kind": "set_z_order", "section_id": "hero", "element_id": asset_id, "z_index": 7}).json()
    changed = _element(state, asset_id)
    assert (changed["x"], changed["y"], changed["width"], changed["height"], changed["z_index"]) == (30, 12, 600, 420, 7)

    state = _resume(client, headers, state, "apply", {"operation_id": "lock-asset", "kind": "set_lock", "section_id": "hero", "element_id": asset_id, "locked": True}).json()
    blocked = _resume(client, headers, state, "apply", {"operation_id": "blocked-move", "kind": "move_element", "section_id": "hero", "element_id": asset_id, "dx": 1, "dy": 0}).json()
    assert blocked["status"] == "awaiting_review"
    assert _element(blocked, asset_id)["x"] == 30
    state = _resume(client, headers, blocked, "apply", {"operation_id": "unlock-asset", "kind": "set_lock", "section_id": "hero", "element_id": asset_id, "locked": False}).json()
    state = _resume(client, headers, state, "apply", {"operation_id": "move-unlocked-asset", "kind": "move_element", "section_id": "hero", "element_id": asset_id, "dx": 1, "dy": 0}).json()
    assert _element(state, asset_id)["x"] == 31
    state = _resume(client, headers, state, "apply", {"operation_id": "group-hero", "kind": "group", "element_ids": [asset_id, text_id]}).json()
    group = state["values"]["canvas"]["element_groups"][0]
    assert group["child_element_ids"] == [asset_id, text_id]
    state = _resume(client, headers, state, "apply", {"operation_id": "move-group", "kind": "move_group", "section_id": "hero", "group_id": group["group_id"], "dx": 10, "dy": 5}).json()
    assert (_element(state, asset_id)["x"], _element(state, asset_id)["y"]) == (41, 17)
    assert (_element(state, text_id)["x"], _element(state, text_id)["y"]) == (10, 5)
    state = _resume(client, headers, state, "undo", {"operation_id": "undo-group-move"}).json()
    assert (_element(state, asset_id)["x"], _element(state, asset_id)["y"]) == (31, 12)
    state = _resume(client, headers, state, "redo", {"operation_id": "redo-group-move"}).json()
    state = _resume(client, headers, state, "apply", {"operation_id": "ungroup-hero", "kind": "ungroup", "section_id": "hero", "group_id": group["group_id"]}).json()
    assert not state["values"]["canvas"]["element_groups"]
    assert _element(state, asset_id)["element_id"] == asset_id and _element(state, asset_id).get("group_id") is None
    state = _resume(client, headers, state, "apply", {"operation_id": "regroup-hero", "kind": "group", "element_ids": [asset_id, text_id]}).json()
    committed_group = state["values"]["canvas"]["element_groups"][0]
    state = _resume(client, headers, state, "apply", {"operation_id": "lock-group", "kind": "set_lock", "section_id": "hero", "group_id": committed_group["group_id"], "locked": True}).json()

    run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    expected_canvas = deepcopy(state["values"]["canvas"])
    run.outputs_json, run.status = {}, "running"; db_session.commit()
    assert client.post(f"/api/v1/graph-runs/{started['run_id']}/resume", headers=headers).status_code == 409
    db_session.refresh(run)
    from src.services.langgraph_run_service import _public_canvas
    assert _public_canvas(run.outputs_json["langgraph_canvas"]) == expected_canvas

    restored = client.get(f"/api/v1/graph-runs/{started['run_id']}", headers=headers).json()
    completed = _resume(client, headers, restored, "commit").json()
    db_session.refresh(run)
    fork = run.outputs_json["langgraph_edit"]["canvas_version_fork"]
    child = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()
    frozen_asset = next(item for item in next(section for section in child.sections_json["lg10"]["canonical_page_assembly_input"]["sections"] if section["section_id"] == "hero")["canvas_elements"] if item["element_id"] == asset_id)
    assert (frozen_asset["x"], frozen_asset["y"], frozen_asset["width"], frozen_asset["height"], frozen_asset["z_index"]) == (41, 17, 600, 420, 7)
    assert child.sections_json["lg11"]["canvas_element_groups"] == state["values"]["canvas"]["element_groups"]
    assert child.sections_json["lg11"]["parent_detail_page_version_id"] == source.id
    assert f'data-canvas-element-id="{asset_id}"' in child.sections_json["lg10"]["canonical_rendering"]["html"]
    _, child_state = _start(client, headers, source_run, child)
    child_state = _resume(client, headers, child_state, "approve").json()
    assert child_state["values"]["canvas"]["element_groups"] == child.sections_json["lg11"]["canvas_element_groups"]
    db_session.refresh(source)
    assert source.sections_json == source_snapshot
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=started["run_id"]).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=started["run_id"]).count() == 0


def test_lg11_canvas_invalid_element_group_operation_is_rejected(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__()
    source_run = _create_run(client, headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    _, state = _start(client, headers, source_run, source)
    state = _resume(client, headers, state, "approve").json()
    rejected = _resume(client, headers, state, "apply", {"operation_id": "cross-section-group", "kind": "group", "element_ids": ["hero:text", "specs:text"]}).json()
    assert rejected["status"] == "awaiting_review"
    assert not rejected["values"]["canvas"]["element_groups"]


def test_lg11_canvas_element_types_duplicate_delete_and_independent_background(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__()
    source_run = _create_run(client, headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    started, state = _start(client, headers, source_run, source)
    state = _resume(client, headers, state, "approve").json()
    for kind, token in (("mask", "rounded"), ("icon", "check"), ("decorative", "divider")):
        state = _resume(client, headers, state, "apply", {
            "operation_id": f"create-{kind}", "kind": "create_element", "section_id": "hero",
            "element_kind": kind, "token": token,
        }).json()
    hero = next(item for item in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"] if item["section_id"] == "hero")
    created = {item["kind"]: item for item in hero["canvas_elements"] if item["kind"] in {"mask", "icon", "decorative"}}
    assert set(created) == {"mask", "icon", "decorative"}
    mask_id = created["mask"]["element_id"]
    state = _resume(client, headers, state, "apply", {"operation_id": "move-mask", "kind": "move_element", "section_id": "hero", "element_id": mask_id, "dx": 35, "dy": 8}).json()
    state = _resume(client, headers, state, "apply", {"operation_id": "duplicate-mask", "kind": "duplicate_element", "section_id": "hero", "element_id": mask_id}).json()
    hero = next(section for section in state["values"]["canvas"]["canonical_page_assembly_input"]["sections"] if section["section_id"] == "hero")
    duplicate = next(item for item in hero["canvas_elements"] if item["element_id"] != mask_id and item["kind"] == "mask")
    assert duplicate["element_id"] != mask_id and duplicate["kind"] == "mask"
    run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    persisted_hero = next(section for section in run.outputs_json["langgraph_canvas"]["canonical_page_assembly_input"]["sections"] if section["section_id"] == "hero")
    persisted_duplicate = next(item for item in persisted_hero["canvas_elements"] if item["element_id"] == duplicate["element_id"])
    assert persisted_duplicate["origin_element_id"] == "hero:mask"
    duplicate_before_delete = deepcopy(duplicate)
    unrelated_asset_before_delete = deepcopy(_element(state, "hero:asset"))
    state = _resume(client, headers, state, "apply", {"operation_id": "delete-mask", "kind": "delete_element", "section_id": "hero", "element_id": duplicate["element_id"]}).json()
    assert _element(state, duplicate["element_id"])["deleted"] is True
    state = _resume(client, headers, state, "undo", {"operation_id": "undo-delete-mask"}).json()
    assert _element(state, duplicate["element_id"]) == duplicate_before_delete
    assert _element(state, "hero:asset") == unrelated_asset_before_delete
    state = _resume(client, headers, state, "redo", {"operation_id": "redo-delete-mask"}).json()
    assert _element(state, duplicate["element_id"]) == {**duplicate_before_delete, "deleted": True}
    assert _element(state, "hero:asset") == unrelated_asset_before_delete
    state = _resume(client, headers, state, "apply", {"operation_id": "move-background", "kind": "move_element", "section_id": "hero", "element_id": "hero:background", "dx": 40, "dy": 0}).json()
    completed = _resume(client, headers, state, "commit").json()
    run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    fork = run.outputs_json["langgraph_edit"]["canvas_version_fork"]
    child = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()
    html = child.sections_json["lg10"]["canonical_rendering"]["html"]
    assert 'class="sf-canvas-background"' in html
    assert 'data-canvas-element-id="hero:background"' in html
    assert "position:absolute;left:40px" in html


def test_lg11_canvas_asset_replace_requires_rights_and_sha256(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__()
    source_run = _create_run(client, headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    original = db_session.query(Asset).filter_by(id=next(iter(source_run.input_snapshot["asset_ids"]))).one()
    digest = sha256(open(original.file_path, "rb").read()).hexdigest()

    def add_asset(label, usage, source_type="uploaded"):
        asset = Asset(project_id=source_run.project_id, source_type=source_type, usage_status=usage, filename=f"{label}.png", file_path=original.file_path, mime_type="image/png", file_size=1, content_hash=digest, quality_status="usable")
        db_session.add(asset); db_session.flush()
        return asset

    seller = add_asset("seller", "seller_owned")
    confirmed = add_asset("confirmed", "rights_confirmed")
    blocked = add_asset("blocked", "blocked")
    supplier = add_asset("supplier", "seller_owned", "supplier")
    reference = add_asset("reference", "reference_only")
    _, state = _start(client, headers, source_run, source)
    state = _resume(client, headers, state, "approve").json()
    state = _resume(client, headers, state, "apply", {"operation_id": "replace-seller", "kind": "replace_element", "section_id": "hero", "element_id": "hero:asset", "asset_id": seller.id, "asset_content_hash": digest}).json()
    replaced = _element(state, "hero:asset")
    assert (replaced["asset_id"], replaced["asset_content_hash"]) == (seller.id, digest)
    state = _resume(client, headers, state, "apply", {"operation_id": "replace-confirmed", "kind": "replace_element", "section_id": "hero", "element_id": "hero:asset", "asset_id": confirmed.id, "asset_content_hash": digest}).json()
    replaced = _element(state, "hero:asset")
    assert (replaced["asset_id"], replaced["asset_content_hash"]) == (confirmed.id, digest)
    for label, asset_id, content_hash in (("blocked", blocked.id, digest), ("supplier", supplier.id, digest), ("reference", reference.id, digest), ("bad-hash", seller.id, "0" * 64), ("external", "https://example.test/image.png", digest)):
        rejected = _resume(client, headers, state, "apply", {"operation_id": f"replace-{label}", "kind": "replace_element", "section_id": "hero", "element_id": "hero:asset", "asset_id": asset_id, "asset_content_hash": content_hash}).json()
        assert rejected["status"] == "awaiting_review"
        assert _element(rejected, "hero:asset")["asset_id"] == confirmed.id


def test_lg11_canvas_multi_asset_identity_and_locked_group_history(client, db_session, tmp_path, lg11_runtime):
    source_run = _create_run(client, _lg5_auth_headers.__wrapped__(), db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(id=next(iter(source_run.input_snapshot["asset_ids"]))).one()
    asset.content_hash = sha256(open(asset.file_path, "rb").read()).hexdigest(); db_session.commit()
    elements = _lg11_canvas_default_elements({"section_id": "hero", "rendering_mode": "approved_asset", "approved_assets": [{"asset_id": asset.id, "asset_content_hash": asset.content_hash}, {"asset_id": "second-asset", "asset_content_hash": "a" * 64}]})
    asset_ids = [item["element_id"] for item in elements if item["kind"] == "asset"]
    assert len(asset_ids) == 2 and len(set(asset_ids)) == 2

    headers = _lg5_auth_headers.__wrapped__(); source, _, _ = _frozen_lg10_version(db_session, source_run)
    _, state = _start(client, headers, source_run, source); state = _resume(client, headers, state, "approve").json()
    state = _resume(client, headers, state, "apply", {"operation_id": "raise-z", "kind": "set_z_order", "section_id": "hero", "element_id": "hero:asset", "z_index": 9}).json()
    state = _resume(client, headers, state, "undo", {"operation_id": "undo-z"}).json()
    assert _element(state, "hero:asset")["z_index"] == 1
    state = _resume(client, headers, state, "redo", {"operation_id": "redo-z"}).json()
    assert _element(state, "hero:asset")["z_index"] == 9
    state = _resume(client, headers, state, "apply", {"operation_id": "group", "kind": "group", "element_ids": ["hero:asset", "hero:text"]}).json()
    group = state["values"]["canvas"]["element_groups"][0]
    state = _resume(client, headers, state, "undo", {"operation_id": "undo-group"}).json()
    assert not state["values"]["canvas"]["element_groups"]
    state = _resume(client, headers, state, "redo", {"operation_id": "redo-group"}).json()
    group = state["values"]["canvas"]["element_groups"][0]
    state = _resume(client, headers, state, "apply", {"operation_id": "lock-group", "kind": "set_lock", "section_id": "hero", "group_id": group["group_id"], "locked": True}).json()
    for operation, payload in (("move-locked-group", {"kind": "move_group", "group_id": group["group_id"], "dx": 1, "dy": 1}), ("ungroup-locked-group", {"kind": "ungroup", "group_id": group["group_id"]}), ("move-locked-child", {"kind": "move_element", "element_id": "hero:text", "dx": 1, "dy": 1})):
        rejected = _resume(client, headers, state, "apply", {"operation_id": operation, "section_id": "hero", **payload}).json()
        assert rejected["status"] == "awaiting_review"
    state = _resume(client, headers, state, "undo", {"operation_id": "undo-lock"}).json()
    assert state["values"]["canvas"]["element_groups"][0]["locked"] is False
    state = _resume(client, headers, state, "redo", {"operation_id": "redo-lock"}).json()
    assert state["values"]["canvas"]["element_groups"][0]["locked"] is True
