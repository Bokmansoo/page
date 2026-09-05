from __future__ import annotations

from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.db.models import AgentRun, AgentRunStep, Asset, FactEvidence, ImageGenerationJobRecord, ProductFact


PUBLIC_GRAPH_VALUE_KEYS = {
    "progress", "review", "execution", "intake", "generation", "rendering", "quality", "canvas", "edit",
}


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


def test_lg4_public_graph_state_is_bounded_and_wrong_thread_is_rejected(
    client, auth_headers, db_session, lg4_runtime,
):
    run = _create_run(client, auth_headers, db_session)
    started = client.post(f"/api/v1/graph-runs/{run.id}/start", headers=auth_headers)
    assert started.status_code == 200, started.text
    state = started.json()
    assert "LG4 approval pillow" not in repr(state["values"])
    assert set(state["values"]) == PUBLIC_GRAPH_VALUE_KEYS
    assert state["values"]["review"]["pending"]["seller_guidance"] == {
        "status": "awaiting_review",
        "safe_code": None,
        "cause_ko": "입력 내용을 확인해야 합니다.",
        "action_ko": "내용을 확인한 뒤 승인하거나 수정 요청하세요.",
        "action_type": "review",
        "retryable": False,
        "review_required": True,
    }
    history = client.get(f"/api/v1/graph-runs/{run.id}/history", headers=auth_headers)
    assert history.status_code == 200
    assert "LG4 approval pillow" not in repr(history.json())
    assert all(set(item["values"]) == PUBLIC_GRAPH_VALUE_KEYS for item in history.json())

    wrong_thread = client.post(
        f"/api/v1/graph-runs/{run.id}/resume",
        headers=auth_headers,
        json={"thread_id": "another-thread", "response": {"schema_version": "lg4-v1", "review_stage": "input_review", "decision": "approve"}},
    )
    assert wrong_thread.status_code == 409


def test_lg4_public_graph_values_keep_only_frontend_refs_and_bounded_fields():
    from src.services.langgraph_run_service import _browser_checkpoint_values

    raw = "SECRET manual OCR prompt https://signed.example/path?token=private"
    digest = "a" * 64
    run = SimpleNamespace(
        status="awaiting_review",
        current_stage="seller_confirmation",
        error_log=[],
        outputs_json={"langgraph_review": {"pending": {
            "schema_version": "lg12i-v1",
            "review_stage": "seller_confirmation",
            "context": {
                "product_name": raw,
                "generation": {"cost_plan": {"cost_plan_hash": digest, "provider_payload": raw}},
                "seller_confirmation": {
                    "confirmation_required": True,
                    "resume_request_hash": digest,
                    "clarifications": [{"clarification_id": "clarification-1", "field_id": "rated_input", "question": raw}],
                },
            },
            "rejection_reason": raw,
        }}},
    )
    snapshot = SimpleNamespace(values={
        "intake": {
            "input_mode": "manual", "requested_generation_mode": "quick", "target_channels": ["smartstore"],
            "manual_source": {"body": raw},
            "creative_brief": {"brief_version": {"id": "brief-1", "version": 2, "canonical_hash": digest, "body": raw}},
        },
        "generation": {"jobs": [{
            "job_id": "job-1", "scene_id": "scene-1", "status": "approved", "output_asset_id": "asset-1",
            "estimated_cost": 0, "prompt": raw,
            "validation": {"status": "approved", "ocr_text": raw, "provider_payload": raw, "risk_codes": ["SAFE"]},
        }]},
        "rendering": {"detail_page_version": {"id": "page-1", "version": 3, "snapshot_hash": digest, "file_path": raw}},
        "quality": {"quality_bar_verdict": "PASS", "routing_code": "PROMOTE", "raw_error": raw},
        "canvas": {"canonical_page_assembly_input": {"sections": [{
            "section_id": "section-1", "body": raw,
            "canvas_elements": [{"element_id": "element-1", "kind": "image", "asset_id": "asset-1", "text": raw}],
        }]}},
        "edit": {"version_restore": {"detail_page_version_id": "page-1", "raw_prompt": raw}},
    })

    values = _browser_checkpoint_values(run, snapshot)

    assert set(values) == PUBLIC_GRAPH_VALUE_KEYS
    assert values["intake"]["input_mode"] == "manual"
    assert values["intake"]["creative_brief"]["brief_version"]["id"] == "brief-1"
    assert values["generation"]["jobs"] == [{
        "job_id": "job-1", "scene_id": "scene-1", "status": "approved", "output_asset_id": "asset-1",
        "estimated_cost": 0, "source_asset_ids": [], "validation": {"status": "approved", "risk_codes": ["SAFE"]},
    }]
    assert values["review"]["pending"]["context"]["seller_confirmation"]["clarifications"] == [{
        "clarification_id": "clarification-1", "field_id": "rated_input",
    }]
    assert values["rendering"]["detail_page_version"]["snapshot_hash"] == digest
    assert values["canvas"]["canonical_page_assembly_input"]["sections"][0]["canvas_elements"] == [{
        "element_id": "element-1", "kind": "image", "asset_id": "asset-1",
    }]
    assert raw not in json.dumps(values)
    assert "ocr_text" not in json.dumps(values)
    assert "rejection_reason" not in json.dumps(values)


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
    assert "events" not in input_wait["values"]

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
    assert evidence_wait["values"]["progress"]["stage"] == "evidence_review"

    planning_wait = _resume(client, auth_headers, evidence_wait)
    assert planning_wait.status_code == 200, planning_wait.text
    planning_wait = planning_wait.json()
    assert planning_wait["current_stage"] == "planning_review"
    assert set(planning_wait["values"]) == PUBLIC_GRAPH_VALUE_KEYS

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
    assert "events" not in payload["values"]
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
    assert "rejection_reason" not in blocked_state["values"]["review"]["pending"]
    assert "events" not in blocked_state["values"]

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
    assert execution["last_error"]["stage"] == "copywriting"
    assert execution["last_error"]["code"] == "GRAPH_EXECUTION_FAILED"
    assert execution["last_error"]["recovery_action"] == "retry_same_run"
    assert execution["last_error"]["seller_guidance"] == {
        "status": "failed",
        "safe_code": "GRAPH_EXECUTION_FAILED",
        "cause_ko": "작업을 완료하지 못했습니다.",
        "action_ko": "원인을 확인한 뒤 같은 작업을 다시 시도하세요.",
        "action_type": "retry",
        "retryable": True,
        "review_required": False,
    }

    restored = client.get(f"/api/v1/graph-runs/projects/{run.project_id}/review", headers=auth_headers)
    assert restored.status_code == 200
    assert restored.json()["run_id"] == run.id
