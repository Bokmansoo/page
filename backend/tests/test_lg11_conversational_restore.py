"""TASK-11.10 selected-context guards and immutable frozen-version restore."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.db.models import AgentRun, DetailPageVersion, ImageGenerationCostApprovalRecord, ImageGenerationOutboxRecord
from src.services.page_finalization_service import _lg11_canvas_default_elements
from test_lg11_edit_intent_preview import _canonical_hash, _frozen_lg10_version
from test_lg11_edit_run import lg11_runtime
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers


pytestmark = pytest.mark.lg11_fake_e2e


def _resume(client, headers, state, decision, canvas_operation=None):
    pending = state["values"]["review"]["pending"]
    return client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume",
        headers=headers,
        json={"thread_id": state["thread_id"], "response": {
            "schema_version": pending["schema_version"],
            "review_stage": pending["review_stage"],
            "decision": decision,
            "canvas_operation": canvas_operation or {},
        }},
    )


def test_lg11_conversational_input_is_pinned_to_frozen_selection_and_rejects_markup(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__()
    run = _create_run(client, headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, run)
    canonical = version.sections_json["lg10"]["canonical_page_assembly_input"]
    for section in canonical["sections"]:
        section["canvas_elements"] = _lg11_canvas_default_elements(section)
    snapshot = deepcopy(version.sections_json); snapshot.pop("snapshot_hash", None)
    version.sections_json = {**snapshot, "snapshot_hash": _canonical_hash(snapshot)}
    db_session.commit()

    payload = {
        "scope": "page", "target_ids": [version.id], "operation": "canvas_draft",
        "instruction": "선택한 이미지를 오른쪽으로 이동해줘",
        "selected_section_id": "hero", "selected_element_id": "hero:asset",
    }
    preview = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-intents/preview",
        headers=headers, json=payload,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["edit_intent"]["preserve_constraints"]["selected_context"] == {
        "section_id": "hero", "element_id": "hero:asset",
    }

    started = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-runs",
        headers=headers, json=payload,
    )
    state = client.get(f"/api/v1/graph-runs/{started.json()['run_id']}", headers=headers).json()
    canvas = _resume(client, headers, state, "approve").json()
    moved = _resume(client, headers, canvas, "apply", {
        "operation_id": "selected-move", "kind": "move_element", "section_id": "hero",
        "element_id": "hero:asset", "dx": 10, "dy": 0,
    }).json()
    element = next(item for section in moved["values"]["canvas"]["canonical_page_assembly_input"]["sections"] for item in section.get("canvas_elements") or [] if item["element_id"] == "hero:asset")
    assert element["x"] == 10
    blocked = _resume(client, headers, moved, "apply", {
        "operation_id": "other-element", "kind": "move_element", "section_id": "hero",
        "element_id": "hero:text", "dx": 10, "dy": 0,
    }).json()
    assert "selected frozen element" in blocked["values"]["edit"]["canvas_last_error"]

    unsafe = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-intents/preview",
        headers=headers, json={**payload, "instruction": "<script>alert(1)</script>"},
    )
    assert unsafe.status_code == 422
    external = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-intents/preview",
        headers=headers, json={**payload, "instruction": "https://unsafe.example/image.png를 사용해 주세요"},
    )
    assert external.status_code == 422


def test_lg11_selected_section_copy_edit_pins_only_the_frozen_section(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__()
    run = _create_run(client, headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, run)
    response = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-intents/preview",
        headers=headers,
        json={
            "scope": "copy", "target_ids": ["hero"], "operation": "rewrite",
            "instruction": "선택한 제목 문구만 더 간결하게 다듬어 주세요",
            "copy_changes": {"hero": {"hero_title": "간결한 제품 소개"}},
            "selected_section_id": "hero",
        },
    )
    assert response.status_code == 200, response.text
    intent = response.json()["edit_intent"]
    assert intent["target_ids"] == ["hero"]
    assert intent["preserve_constraints"]["selected_context"] == {"section_id": "hero", "element_id": None}


def test_lg11_restore_reactivates_only_the_existing_frozen_version_without_provider_work(client, db_session, tmp_path, lg11_runtime):
    headers = _lg5_auth_headers.__wrapped__()
    source_run = _create_run(client, headers, db_session, tmp_path)
    historical, _, _ = _frozen_lg10_version(db_session, source_run)
    historical.sections_json["lg11"] = {
        "schema_version": "lg11-canvas-fork-v1",
        "parent_detail_page_version_id": historical.id,
    }
    frozen_snapshot = deepcopy(historical.sections_json); frozen_snapshot.pop("snapshot_hash", None)
    historical.sections_json = {**frozen_snapshot, "snapshot_hash": _canonical_hash(frozen_snapshot)}
    historical.is_final = False
    current = DetailPageVersion(
        id="lg11-current-final", project_id=source_run.project_id, name="current",
        style_key=historical.style_key, is_final=True, sections_json=deepcopy(historical.sections_json),
    )
    db_session.add(current); db_session.commit()
    before = deepcopy(historical.sections_json)

    listed = client.get(f"/api/v1/projects/{source_run.project_id}/page/versions", headers=headers)
    assert listed.status_code == 200, listed.text
    listed_by_id = {item["id"]: item for item in listed.json()}
    assert listed_by_id[historical.id]["lg11_frozen"] is True
    assert listed_by_id[current.id]["lg11_frozen"] is True

    response = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/versions/{historical.id}/edit-runs",
        headers=headers,
        json={
            "scope": "page", "target_ids": [historical.id], "operation": "restore",
            "instruction": "이 frozen 버전으로 복원해줘",
        },
    )
    assert response.status_code == 201, response.text
    state = client.get(f"/api/v1/graph-runs/{response.json()['run_id']}", headers=headers).json()
    restored = _resume(client, headers, state, "approve")
    assert restored.status_code == 200, restored.text
    values = restored.json()["values"]
    assert values["edit"]["version_restore"]["detail_page_version_id"] == historical.id
    assert values["edit"]["version_restore"]["snapshot_hash"] == before["snapshot_hash"]
    db_session.refresh(historical); db_session.refresh(current)
    assert historical.is_final is True and current.is_final is False
    assert historical.sections_json == before
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == 2
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(project_id=source_run.project_id).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(project_id=source_run.project_id).count() == 0

    # Every read/export endpoint resolves the reactivated frozen snapshot, not
    # the previously-current mutable page or a newly forked version.
    preview = client.get(
        f"/api/v1/projects/{source_run.project_id}/page/final?channel=smartstore",
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["id"] == historical.id
    standalone = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/export/standalone",
        headers=headers,
        json={"final_version_id": historical.id, "channel": "smartstore"},
    )
    assert standalone.status_code == 200, standalone.text
    export = standalone.json()
    assert export["detail_page_version_id"] == historical.id
    assert historical.id in export["copyable_html"]
    assert client.get(export["html_download_url"], headers=headers).status_code == 200
    assert client.get(export["zip_download_url"], headers=headers).status_code == 200

    # A restart must rebuild the same immutable restore reference from the
    # production checkpoint rather than deriving a new version or mutable page.
    edit_run = db_session.query(AgentRun).filter_by(id=response.json()["run_id"]).one()
    expected_restore = deepcopy(edit_run.outputs_json["langgraph_edit"]["version_restore"])
    edit_run.outputs_json = {}
    edit_run.status = "running"
    db_session.commit()
    rebuilt = client.post(f"/api/v1/graph-runs/{edit_run.id}/resume", headers=headers)
    assert rebuilt.status_code == 200, rebuilt.text
    db_session.refresh(edit_run)
    assert edit_run.outputs_json["langgraph_edit"]["version_restore"] == expected_restore
    assert edit_run.outputs_json["langgraph_edit"]["version_restore"]["detail_page_version_id"] == historical.id
