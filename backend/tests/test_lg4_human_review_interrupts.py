from __future__ import annotations

from contextlib import contextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.db.models import AgentRun, AgentRunStep, Asset, FactEvidence, ImageGenerationJobRecord, ProductFact


@pytest.fixture
def auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


@pytest.fixture
def lg4_runtime(monkeypatch):
    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _create_run(client, headers, db_session) -> AgentRun:
    created = client.post("/api/agent-runs", headers=headers, json={
        "product_name": "LG4 approval pillow",
        "description": "Rated input: DC 5V 2A. Size: 40 x 17 x 15cm.",
    })
    assert created.status_code == 201, created.text
    run = db_session.query(AgentRun).filter(AgentRun.id == created.json()["id"]).one()
    fact = ProductFact(
        project_id=run.project_id,
        fact_text="Rated input: DC 5V 2A",
        source_text="DC 5V 2A",
        verification_status="seller_confirmed",
        needs_review=False,
        field_key="rated_input",
        fact_category="electrical",
        normalized_value="DC 5V 2A",
        scope="product",
    )
    asset = Asset(
        project_id=run.project_id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename="lg4-main.jpg",
        file_path="/tmp/lg4-main.jpg",
        mime_type="image/jpeg",
        file_size=10,
        asset_role="product_main",
        quality_status="usable",
        identity_status="confirmed",
        is_representative=True,
    )
    db_session.add_all([fact, asset])
    db_session.flush()
    db_session.add(FactEvidence(fact_id=fact.id, source_type="seller_input", original_text="DC 5V 2A"))
    run.input_snapshot = {**run.input_snapshot, "asset_ids": [asset.id]}
    db_session.commit()
    return run


def _resume(client, headers, state, *, decision="approve"):
    pending = state["values"]["review"]["pending"]
    generation = (pending.get("context") or {}).get("generation") or {}
    cost_plan_hash = (generation.get("cost_plan") or {}).get("cost_plan_hash", "")
    return client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume",
        headers=headers,
        json={
            "thread_id": state["thread_id"],
            "response": {
                "schema_version": pending["schema_version"],
                "review_stage": pending["review_stage"],
                "decision": decision,
                "cost_plan_hash": cost_plan_hash,
            },
        },
    )


def test_lg4_pauses_before_each_approval_boundary_and_never_dispatches_generation(
    client, auth_headers, db_session, lg4_runtime
):
    run = _create_run(client, auth_headers, db_session)

    started = client.post(f"/api/v1/graph-runs/{run.id}/start", headers=auth_headers)
    assert started.status_code == 200, started.text
    input_wait = started.json()
    assert input_wait["status"] == "awaiting_review"
    assert input_wait["current_stage"] == "input_review"
    assert input_wait["values"]["review"]["pending"]["schema_version"] == "lg4-v1"
    assert input_wait["values"]["review"]["pending"]["review_stage"] == "input_review"
    assert "input_router" not in [event["stage"] for event in input_wait["values"]["events"]]

    restored = client.get(f"/api/v1/graph-runs/projects/{run.project_id}/review", headers=auth_headers)
    assert restored.status_code == 200
    assert restored.json()["run_id"] == run.id

    wrong_thread = client.post(
        f"/api/v1/graph-runs/{run.id}/resume",
        headers=auth_headers,
        json={"thread_id": "another-thread", "response": {"schema_version": "lg4-v1", "review_stage": "input_review", "decision": "approve"}},
    )
    assert wrong_thread.status_code == 409

    evidence_wait = _resume(client, auth_headers, input_wait)
    assert evidence_wait.status_code == 200, evidence_wait.text
    evidence_wait = evidence_wait.json()
    assert evidence_wait["current_stage"] == "evidence_review"
    stages = [event["stage"] for event in evidence_wait["values"]["events"]]
    assert stages[-4:] == ["input_review", "input_router", "source_collection", "product_understanding"] or stages[-5:] == ["input_review", "input_router", "source_collection", "product_understanding", "reference_analysis"]

    planning_wait = _resume(client, auth_headers, evidence_wait)
    assert planning_wait.status_code == 200, planning_wait.text
    planning_wait = planning_wait.json()
    assert planning_wait["current_stage"] == "planning_review"
    assert set(planning_wait["values"]["commerce"]) == {
        "sales_strategy",
        "page_planning",
        "copywriting",
        "visual_planning",
        # LG-8 compiles provider-safe visual prompts before this approval
        # boundary, so the planning artifact now includes this fifth stage.
        "visual_prompt_compiler",
    }

    generation_wait = _resume(client, auth_headers, planning_wait)
    assert generation_wait.status_code == 200, generation_wait.text
    generation_wait = generation_wait.json()
    assert generation_wait["status"] == "awaiting_review"
    assert generation_wait["current_stage"] == "generation_pending"
    # LG-5 keeps this safe no-provider/cost checkpoint but adds the explicit
    # seller approval that enters the image-generation subgraph.
    assert generation_wait["values"]["review"]["pending"]["allowed_decisions"] == ["approve", "defer"]
    assert db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.project_id == run.project_id).count() == 0

    # Repeated defer resumes the exact same thread and keeps one operational
    # waiting step; it cannot create a provider job or duplicate approval row.
    deferred = _resume(client, auth_headers, generation_wait, decision="defer")
    assert deferred.status_code == 200, deferred.text
    assert deferred.json()["current_stage"] == "generation_pending"
    assert db_session.query(AgentRunStep).filter(
        AgentRunStep.run_id == run.id,
        AgentRunStep.stage == "generation_pending",
    ).count() == 1
    assert db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.project_id == run.project_id).count() == 0


def test_lg4_rejection_reinterrupts_without_advancing_or_duplicate_steps(client, auth_headers, db_session, lg4_runtime):
    run = _create_run(client, auth_headers, db_session)
    initial = client.post(f"/api/v1/graph-runs/{run.id}/start", headers=auth_headers).json()
    rejected = _resume(client, auth_headers, initial, decision="reject")
    assert rejected.status_code == 200, rejected.text
    payload = rejected.json()
    assert payload["current_stage"] == "input_review"
    assert payload["status"] == "awaiting_review"
    assert "input_router" not in [event["stage"] for event in payload["values"]["events"]]
    assert db_session.query(AgentRunStep).filter(
        AgentRunStep.run_id == run.id,
        AgentRunStep.stage == "input_review",
    ).count() == 1


def test_lg4_requires_a_versioned_response_for_review_resume(client, auth_headers, db_session, lg4_runtime):
    run = _create_run(client, auth_headers, db_session)
    client.post(f"/api/v1/graph-runs/{run.id}/start", headers=auth_headers)
    missing = client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers)
    assert missing.status_code == 409
    assert "versioned review response" in missing.json()["detail"]


def test_lg4_evidence_approval_stays_interrupted_until_a_safe_asset_exists(
    client, auth_headers, db_session, lg4_runtime
):
    run = _create_run(client, auth_headers, db_session)
    asset = db_session.query(Asset).filter(Asset.id == run.input_snapshot["asset_ids"][0]).one()
    asset.source_type = "sourced"
    asset.usage_status = "reference_only"
    db_session.commit()

    input_wait = client.post(f"/api/v1/graph-runs/{run.id}/start", headers=auth_headers).json()
    evidence_wait = _resume(client, auth_headers, input_wait).json()
    blocked = _resume(client, auth_headers, evidence_wait)

    assert blocked.status_code == 200, blocked.text
    blocked_state = blocked.json()
    assert blocked_state["status"] == "awaiting_review"
    assert blocked_state["current_stage"] == "evidence_review"
    assert "권리 보유 사진" in blocked_state["values"]["review"]["pending"]["rejection_reason"]
    assert "sales_strategy" not in [event["stage"] for event in blocked_state["values"]["events"]]

    asset.source_type = "uploaded"
    asset.usage_status = "seller_owned"
    asset.quality_status = "usable"
    asset.quality_warnings = []
    db_session.commit()

    recovered = _resume(client, auth_headers, blocked_state)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["current_stage"] == "planning_review", recovered.json()


def test_lg4_failed_state_exposes_an_actionable_recovery_contract(
    client, auth_headers, db_session, lg4_runtime
):
    run = _create_run(client, auth_headers, db_session)
    client.post(f"/api/v1/graph-runs/{run.id}/start", headers=auth_headers)
    db_session.refresh(run)
    run.status = "failed"
    run.current_stage = "copywriting"
    run.error_log = [{
        "stage": "copywriting",
        "message": "LG-3 Visual Planning requires at least one safe seller-owned reference asset.",
        "source": "langgraph",
        "recoverable": True,
    }]
    run.outputs_json = {**(run.outputs_json or {}), "langgraph_review": {"pending": None}}
    db_session.commit()

    response = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    execution = response.json()["values"]["execution"]
    assert execution["recoverable"] is True
    assert execution["last_error"]["stage"] == "visual_planning"
    assert execution["last_error"]["code"] == "SAFE_REFERENCE_ASSET_REQUIRED"
    assert execution["last_error"]["recovery_action"] == "upload_safe_reference_asset_and_retry"

    restored = client.get(f"/api/v1/graph-runs/projects/{run.project_id}/review", headers=auth_headers)
    assert restored.status_code == 200
    assert restored.json()["run_id"] == run.id
