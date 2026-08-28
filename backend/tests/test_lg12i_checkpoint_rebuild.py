"""TASK-12I.9 checkpoint-authoritative LG-12I projection recovery."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy

import pytest

from src.db.models import (
    AgentRun,
    CommerceCreativeMasterVersion,
    ProductCreativeBriefVersion,
    ProductSourceSnapshotVersion,
    ProductTruthVersion,
    SellerConfirmationVersion,
)
from src.services.product_intake_version_service import create_manual_input_artifact
from src.services.brand_kit_service import create_kit, create_version
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _headers


pytestmark = pytest.mark.lg12i_fake_e2e


@pytest.fixture
def auth_headers():
    return _headers.__wrapped__()


@pytest.fixture
def lg12i_runtime(monkeypatch):
    """Exercise the production compiled graph with a deterministic saver."""

    from langgraph.checkpoint.memory import InMemorySaver
    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _metadata() -> dict:
    # Deliberately leaves three bounded clarification observations so the test
    # covers an interrupt checkpoint, including deterministic question order.
    return {
        "manual_payload_schema_version": "lg12i-manual-input-artifact-v1",
        "seller_entered_fields": [
            {
                "field_id": "product_identity",
                "classification": "fact_candidate",
                "label": "product",
                "value": "fan",
            },
        ],
        "unknown_fact_field_ids": ["certification", "warranty"],
        "conflict_fact_candidates": [
            {
                "field_id": "material",
                "label": "material",
                "observations": [{"value": "steel"}, {"value": "aluminum"}],
            },
        ],
        "rights_confirmation_state": "unconfirmed",
    }


def _start_pending_manual_run(client, headers, db_session, tmp_path) -> tuple[dict, AgentRun]:
    source_run = _create_run(client, headers, db_session, tmp_path)
    artifact = create_manual_input_artifact(
        db_session,
        workspace_id=source_run.workspace_id,
        project_id=source_run.project_id,
        created_by=source_run.created_by,
        raw_body="bounded source body never enters a checkpoint",
        source_metadata=_metadata(),
    )
    db_session.commit()
    db_session.refresh(artifact)
    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=headers,
        json={
            "input_mode": "manual",
            "source_payload_refs": [{
                "id": artifact.id,
                "kind": "manual_payload_artifact",
                "version": artifact.version,
                "hash": artifact.content_hash,
            }],
            "requested_generation_mode": "quick",
            "target_channels": ["smartstore", "coupang"],
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "awaiting_review"
    return payload, db_session.query(AgentRun).filter_by(id=payload["run_id"]).one()


def _immutable_counts(db_session) -> tuple[int, int, int, int, int]:
    return (
        db_session.query(ProductSourceSnapshotVersion).count(),
        db_session.query(ProductTruthVersion).count(),
        db_session.query(SellerConfirmationVersion).count(),
        db_session.query(ProductCreativeBriefVersion).count(),
        db_session.query(CommerceCreativeMasterVersion).count(),
    )


def _make_projection_ahead_of_checkpoint(db_session, run: AgentRun) -> None:
    """Simulate a SQL-only future stage; checkpoint must win on recovery."""

    run.outputs_json = {
        "langgraph_intake": {
            "input_mode": "manual",
            "next_action": "sql_only_future_stage",
            "commerce_creative_master": {"master_version": {"id": "not-durable"}},
        },
        "langgraph_runtime": {"last_stage": "master_ready"},
    }
    run.current_stage = "master_ready"
    run.status = "completed"
    run.graph_checkpoint_id = "sql-only-projection"
    db_session.add(run)
    db_session.commit()


def test_public_get_rebuilds_checkpoint_newer_or_projection_ahead_without_recreating_versions(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    state, run = _start_pending_manual_run(client, auth_headers, db_session, tmp_path)
    expected_intake = deepcopy(state["values"]["intake"])
    expected_questions = [
        (item["clarification_id"], item["clarification_hash"])
        for item in expected_intake["seller_confirmation"]["clarifications"]
    ]
    immutable_counts = _immutable_counts(db_session)
    _make_projection_ahead_of_checkpoint(db_session, run)

    # GET is a public recovery entrypoint; it must never accept the SQL-only
    # master state as a way to advance the graph.
    recovered = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert recovered.status_code == 200, recovered.text
    body = recovered.json()
    assert body["status"] == "awaiting_review"
    assert body["current_stage"] == "seller_confirmation"
    assert body["values"]["intake"] == expected_intake
    assert [
        (item["clarification_id"], item["clarification_hash"])
        for item in body["values"]["intake"]["seller_confirmation"]["clarifications"]
    ] == expected_questions
    assert "raw_body" not in str(body["values"])
    assert _immutable_counts(db_session) == immutable_counts


def test_public_start_and_history_recover_the_same_pending_checkpoint_once(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    state, run = _start_pending_manual_run(client, auth_headers, db_session, tmp_path)
    expected_intake = deepcopy(state["values"]["intake"])
    _make_projection_ahead_of_checkpoint(db_session, run)

    started = client.post(f"/api/v1/graph-runs/{run.id}/start", headers=auth_headers)
    assert started.status_code == 200, started.text
    assert started.json()["values"]["intake"] == expected_intake
    assert started.json()["status"] == "awaiting_review"

    # A second public read is a no-op: same checkpoint and projection identity,
    # no fresh clarification/cycle/version is manufactured by history rebuild.
    before = _immutable_counts(db_session)
    history = client.get(f"/api/v1/graph-runs/{run.id}/history", headers=auth_headers)
    assert history.status_code == 200, history.text
    assert history.json()[0]["values"]["intake"]["seller_confirmation"]["confirmation_cycle"] == 1
    assert _immutable_counts(db_session) == before


def test_recovery_is_scoped_to_the_requested_workspace_and_run(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    _state, run = _start_pending_manual_run(client, auth_headers, db_session, tmp_path)
    _make_projection_ahead_of_checkpoint(db_session, run)

    denied = client.get(
        f"/api/v1/graph-runs/{run.id}",
        headers={**auth_headers, "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000099"},
    )
    assert denied.status_code == 404
    db_session.refresh(run)
    # The foreign lookup cannot cause a rebuild/write in the owner run.
    assert run.current_stage == "master_ready"
    assert run.status == "completed"


def test_public_recovery_resume_restores_a_failed_projection_without_advancing_business_nodes(
    client, auth_headers, db_session, tmp_path, lg12i_runtime,
):
    state, run = _start_pending_manual_run(client, auth_headers, db_session, tmp_path)
    expected_questions = [
        (item["clarification_id"], item["clarification_hash"], item["priority"])
        for item in state["values"]["intake"]["seller_confirmation"]["clarifications"]
    ]
    before = _immutable_counts(db_session)
    # Simulate the exact prior failure shape: SQL says failed while the durable
    # checkpoint still holds the seller-confirmation interrupt.
    run.outputs_json = {
        key: value for key, value in (run.outputs_json or {}).items()
        if key not in {"langgraph_intake", "langgraph_review"}
    }
    run.status = "failed"
    run.current_stage = "seller_confirmation"
    db_session.add(run)
    db_session.commit()

    missing_response = client.post(
        f"/api/v1/graph-runs/{run.id}/resume",
        headers=auth_headers,
        json={"thread_id": run.id, "mode": "respond"},
    )
    assert missing_response.status_code == 422
    ambiguous_recovery = client.post(
        f"/api/v1/graph-runs/{run.id}/resume",
        headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover", "response": {"review_stage": "seller_confirmation"}},
    )
    assert ambiguous_recovery.status_code == 422

    recovered = client.post(
        f"/api/v1/graph-runs/{run.id}/resume",
        headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert recovered.status_code == 200, recovered.text
    body = recovered.json()
    assert body["status"] == "awaiting_review"
    assert body["current_stage"] == "seller_confirmation"
    assert body["values"]["intake"]["seller_confirmation"]["confirmation_cycle"] == 1
    assert [
        (item["clarification_id"], item["clarification_hash"], item["priority"])
        for item in body["values"]["intake"]["seller_confirmation"]["clarifications"]
    ] == expected_questions
    assert _immutable_counts(db_session) == before

    replay = client.post(
        f"/api/v1/graph-runs/{run.id}/resume",
        headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["values"]["intake"] == body["values"]["intake"]
    assert _immutable_counts(db_session) == before

    denied = client.post(
        f"/api/v1/graph-runs/{run.id}/resume",
        headers={**auth_headers, "X-Mock-User-Id": "00000000-0000-0000-0000-000000000099"},
        json={"thread_id": run.id, "mode": "recover"},
    )
    # The existing workspace-membership/authentication layer rejects the
    # foreign actor before the resume service is reached.
    assert denied.status_code == 403
    assert _immutable_counts(db_session) == before


def test_public_brand_kit_continuation_reuses_the_same_frozen_intake_lineage(
    client, auth_headers, db_session, tmp_path, lg12i_runtime,
):
    """A later project prerequisite advances only Brief -> Master on this thread."""

    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = create_manual_input_artifact(
        db_session,
        workspace_id=source_run.workspace_id,
        project_id=source_run.project_id,
        created_by=source_run.created_by,
        raw_body="rights-only source stays outside the checkpoint",
        source_metadata={
            "manual_payload_schema_version": "lg12i-manual-input-artifact-v1",
            "seller_entered_fields": [{
                "field_id": "product_identity", "classification": "fact_candidate",
                "label": "product", "value": "fan",
            }],
            "unknown_fact_field_ids": [], "conflict_fact_candidates": [],
            "rights_confirmation_state": "unconfirmed",
        },
    )
    db_session.commit(); db_session.refresh(artifact)
    started = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json={
            "input_mode": "manual",
            "source_payload_refs": [{
                "id": artifact.id, "kind": "manual_payload_artifact",
                "version": artifact.version, "hash": artifact.content_hash,
            }],
            "requested_generation_mode": "quick", "target_channels": ["smartstore"],
        },
    )
    assert started.status_code == 201, started.text
    state = started.json()
    run = db_session.query(AgentRun).filter_by(id=state["run_id"]).one()
    plan = state["values"]["intake"]["seller_confirmation"]
    assert len(plan["clarifications"]) == 1
    answers = [{"clarification_id": plan["clarifications"][0]["clarification_id"], "decision": "confirm"}]
    response = {
        "thread_id": state["thread_id"],
        "response": {
            "schema_version": "lg12i-v1", "review_stage": "seller_confirmation", "decision": "submit",
            "confirmation_request_hash": plan["resume_request_hash"], "confirmation_answers": answers,
        },
    }
    blocked = client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers, json=response)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["current_stage"] == "creative_brief_blocked"
    source_truth_confirmation = _immutable_counts(db_session)[:3]

    kit = create_kit(db_session, run.workspace_id, run.created_by, "LG12I continuation test kit")
    create_version(
        db_session, run.workspace_id, run.created_by, kit.id,
        {"color_tokens": {"accent": "#0f766e"}, "typography": {"body_font": "system-ui"}},
        scope="project", project_id=run.project_id, activate=True,
    )
    continued = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": state["thread_id"], "mode": "continue"},
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["current_stage"] == "planning_review"
    assert _immutable_counts(db_session)[:3] == source_truth_confirmation
    assert _immutable_counts(db_session)[3:] == (1, 2)

    # A completed continuation is read/idempotent; the original confirmation
    # replay also remains a no-op after Master has been frozen.
    again = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": state["thread_id"], "mode": "continue"},
    )
    assert again.status_code == 200, again.text
    replay = client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers, json=response)
    assert replay.status_code == 200, replay.text
    assert _immutable_counts(db_session) == (*source_truth_confirmation, 1, 2)
