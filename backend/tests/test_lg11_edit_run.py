"""LG-11.2 production edit-run, checkpoint, and frozen-version lineage tests."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.db.models import AgentRun, DetailPageVersion, ProductProject
from test_lg11_edit_intent_preview import _frozen_lg10_version
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers

pytestmark = pytest.mark.lg11_fake_e2e


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


@pytest.fixture
def lg11_runtime(monkeypatch):
    """Use the production LG-11 compiled graph with an explicit test saver."""

    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _edit_request() -> dict[str, object]:
    return {
        "scope": "copy",
        "target_ids": ["hero"],
        "operation": "rewrite",
        "instruction": "Rewrite the hero title clearly.",
        "preserve_constraints": {"retain_approved_assets": True},
    }


def _start_edit_run(client, headers, run, version):
    response = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-runs",
        headers=headers,
        json=_edit_request(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_lg11_edit_run_uses_final_frozen_version_and_keeps_preview_read_only(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, source_run)
    before_count = db_session.query(AgentRun).count()

    preview = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/versions/{version.id}/edit-intents/preview",
        headers=auth_headers,
        json=_edit_request(),
    )
    assert preview.status_code == 200, preview.text
    assert db_session.query(AgentRun).count() == before_count

    payload = _start_edit_run(client, auth_headers, source_run, version)
    assert db_session.query(AgentRun).count() == before_count + 1
    assert payload["source_detail_page_version_id"] == version.id
    assert payload["parent_detail_page_version_id"] == version.id
    assert payload["state"]["status"] == "awaiting_review"
    persisted = db_session.query(AgentRun).filter_by(id=payload["run_id"]).one()
    edit = persisted.outputs_json["langgraph_edit"]
    assert edit["base_version"] == {
        "id": version.id,
        "snapshot_hash": version.sections_json["snapshot_hash"],
    }
    assert edit["lineage"] == {
        "edit_run_id": payload["run_id"],
        "source_detail_page_version_id": version.id,
        "parent_detail_page_version_id": version.id,
    }
    assert edit["intent_id"] == payload["intent_id"]
    assert edit["impact_preview"] == preview.json()["impact_preview"]

    db_session.refresh(persisted)
    assert persisted.mode == "lg11_edit"
    assert persisted.outputs_json["langgraph_edit"] == edit
    assert persisted.outputs_json["langgraph_review"]["pending"]["review_stage"] == "edit_confirmation"
    assert "lg11_edit_intent" not in edit


def test_lg11_edit_run_public_resume_rebuild_restores_lineage_and_confirmation_then_resumes(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, source_run)
    started = _start_edit_run(client, auth_headers, source_run, version)
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    expected_edit = deepcopy(edit_run.outputs_json["langgraph_edit"])

    # Simulate a crash after checkpoint commit but before SQL projection.
    outputs = dict(edit_run.outputs_json or {})
    outputs.pop("langgraph_edit", None)
    outputs.pop("langgraph_review", None)
    edit_run.outputs_json = outputs
    edit_run.status = "running"
    db_session.add(edit_run)
    db_session.commit()

    # This is the public resume entrypoint, not a private projector call. It
    # first rebuilds the checkpoint projection, then correctly requires the
    # recovered seller-confirmation payload.
    recovered = client.post(f"/api/v1/graph-runs/{edit_run.id}/resume", headers=auth_headers)
    assert recovered.status_code == 409, recovered.text
    db_session.refresh(edit_run)
    assert edit_run.outputs_json["langgraph_edit"] == expected_edit
    assert edit_run.outputs_json["langgraph_review"]["pending"]["review_stage"] == "edit_confirmation"

    resumed = client.post(
        f"/api/v1/graph-runs/{edit_run.id}/resume",
        headers=auth_headers,
        json={
            "thread_id": edit_run.id,
            "response": {
                "schema_version": "lg11-v1",
                "review_stage": "edit_confirmation",
                "decision": "approve",
            },
        },
    )
    assert resumed.status_code == 200, resumed.text
    state = resumed.json()
    assert state["status"] == "completed"
    db_session.refresh(edit_run)
    persisted_edit = edit_run.outputs_json["langgraph_edit"]
    assert persisted_edit["confirmation"] == {"status": "confirmed", "decision": "approve"}
    assert persisted_edit["lineage"] == expected_edit["lineage"]
    assert persisted_edit["base_version"] == expected_edit["base_version"]
    assert persisted_edit["next_action"] == "task_11_3_edit_execution"

    # A browser retry after a completed confirmation is a read: no new step,
    # checkpoint lineage, or edit run is created.
    db_session.refresh(edit_run)
    step_count = len(edit_run.steps)
    retried = client.post(
        f"/api/v1/graph-runs/{edit_run.id}/resume",
        headers=auth_headers,
        json={
            "thread_id": edit_run.id,
            "response": {
                "schema_version": "lg11-v1",
                "review_stage": "edit_confirmation",
                "decision": "approve",
            },
        },
    )
    assert retried.status_code == 200, retried.text
    db_session.refresh(edit_run)
    assert len(edit_run.steps) == step_count
    assert edit_run.outputs_json["langgraph_edit"]["lineage"] == expected_edit["lineage"]


def test_lg11_running_run_with_current_projection_is_a_public_noop(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, source_run)
    started = _start_edit_run(client, auth_headers, source_run, version)
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    expected_outputs = deepcopy(edit_run.outputs_json)
    step_count = len(edit_run.steps)

    # A living execution lease with a current projection must not replay
    # checkpoint history merely because a retry observes `running`.
    edit_run.status = "running"
    db_session.add(edit_run)
    db_session.commit()
    response = client.post(f"/api/v1/graph-runs/{edit_run.id}/resume", headers=auth_headers)
    assert response.status_code == 200, response.text
    db_session.refresh(edit_run)
    assert edit_run.status == "running"
    assert edit_run.outputs_json == expected_outputs
    assert len(edit_run.steps) == step_count


def test_lg11_rejected_confirmation_is_not_an_edit_execution_candidate(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, source_run)
    started = _start_edit_run(client, auth_headers, source_run, version)
    response = client.post(
        f"/api/v1/graph-runs/{started['run_id']}/resume",
        headers=auth_headers,
        json={
            "thread_id": started["run_id"],
            "response": {
                "schema_version": "lg11-v1",
                "review_stage": "edit_confirmation",
                "decision": "reject",
            },
        },
    )
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["status"] == "completed"
    assert state["current_stage"] == "edit_rejected"
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    db_session.refresh(edit_run)
    persisted_edit = edit_run.outputs_json["langgraph_edit"]
    assert persisted_edit["confirmation"] == {"status": "rejected", "decision": "reject"}
    assert persisted_edit["next_action"] == "none"


def test_lg11_edit_run_rejects_non_final_and_cross_project_versions(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, source_run)
    non_final = DetailPageVersion(
        project_id=source_run.project_id,
        name="Non-final frozen fixture",
        style_key="balanced_sale",
        sections_json=deepcopy(version.sections_json),
        is_final=False,
    )
    source_project = db_session.query(ProductProject).filter_by(id=source_run.project_id).one()
    other_project = ProductProject(
        workspace_id=source_project.workspace_id,
        brand_id=source_project.brand_id,
        name="LG-11 ownership guard project",
    )
    db_session.add(non_final)
    db_session.add(other_project)
    db_session.commit()

    non_final_response = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/versions/{non_final.id}/edit-runs",
        headers=auth_headers,
        json=_edit_request(),
    )
    assert non_final_response.status_code == 422
    assert "final frozen DetailPageVersion" in non_final_response.json()["detail"]

    cross_project_response = client.post(
        f"/api/v1/projects/{other_project.id}/page/versions/{version.id}/edit-runs",
        headers=auth_headers,
        json=_edit_request(),
    )
    assert cross_project_response.status_code == 422


def test_lg11_edit_route_is_absent_from_existing_lg5_through_lg10_graphs():
    from langgraph.checkpoint.memory import InMemorySaver
    from src.agents.langgraph_runtime import (
        build_lg5_compiled_graph,
        build_lg6_compiled_graph,
        build_lg7_compiled_graph,
        build_lg8_compiled_graph,
        build_lg10_compiled_graph,
    )

    for builder in (
        build_lg5_compiled_graph,
        build_lg6_compiled_graph,
        build_lg7_compiled_graph,
        build_lg8_compiled_graph,
        build_lg10_compiled_graph,
    ):
        graph = builder(checkpointer=InMemorySaver())
        assert "prepare_edit_run" not in graph.get_graph().nodes
        assert "edit_confirmation" not in graph.get_graph().nodes
