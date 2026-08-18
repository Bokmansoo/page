"""TASK-11.5 production LG-11 fact evidence-review and stale-state tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.db.models import AgentRun, DetailPageVersion, ImageGenerationCostApprovalRecord, ImageGenerationOutboxRecord
from src.services.page_finalization_service import _canonical_hash, build_page_assembly_structure
from src.services.renderer import render_lg10_canonical_page_html
from test_lg11_edit_intent_preview import _frozen_lg10_version
from test_lg11_edit_run import lg11_runtime
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers

pytestmark = pytest.mark.lg11_fake_e2e


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


def _fact_edit_request(fact_id: str) -> dict[str, object]:
    return {
        "scope": "fact",
        "target_ids": [fact_id],
        "operation": "replace",
        "instruction": "Update the confirmed input specification after evidence review.",
        "preserve_constraints": {"retain_unaffected_approved_assets": True},
    }


def _make_specs_unrelated(version: DetailPageVersion) -> None:
    """Keep the fixture's specs section outside the target fact dependency."""

    snapshot = deepcopy(version.sections_json)
    canonical = snapshot["lg10"]["canonical_page_assembly_input"]
    specs = next(section for section in canonical["sections"] if section["section_id"] == "specs")
    specs["copy_ref"]["fact_ids"] = []
    specs["copy_ref"]["evidence_ids_by_fact"] = {}
    canonical_payload = deepcopy(canonical)
    canonical_payload.pop("input_hash", None)
    canonical["input_hash"] = _canonical_hash(canonical_payload)
    assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical)
    old_rendering = snapshot["lg10"]["canonical_rendering"]
    copy_set = {
        "hero_title": "Frozen hero title",
        "hero_subtitle": "Frozen fact-backed summary",
        "details_body": "Unrelated static details",
    }
    rendering_payload = {
        **render_lg10_canonical_page_html(
            canonical_page_assembly_input=canonical,
            page_assembly=assembly,
            copy_set=copy_set,
            brand_tokens=deepcopy(old_rendering["brand_tokens"]),
        ),
        "canonical_input_ref": {
            "schema_version": "lg10-canonical-page-assembly-input-v1",
            "input_hash": canonical["input_hash"],
        },
        "page_assembly_ref": {
            "schema_version": "lg10-page-assembly-v1",
            "assembly_hash": assembly["assembly_hash"],
        },
    }
    snapshot["lg10"]["page_assembly"] = assembly
    snapshot["lg10"]["canonical_rendering"] = {
        **rendering_payload,
        "render_hash": _canonical_hash(rendering_payload),
    }
    snapshot.pop("snapshot_hash", None)
    version.sections_json = {**snapshot, "snapshot_hash": _canonical_hash(snapshot)}


def _resume(client, headers, state, decision: str):
    pending = state["values"]["review"]["pending"]
    return client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume",
        headers=headers,
        json={
            "thread_id": state["thread_id"],
            "response": {
                "schema_version": pending["schema_version"],
                "review_stage": pending["review_stage"],
                "decision": decision,
            },
        },
    )


def _start(client, headers, run, version, fact_id):
    response = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-runs",
        headers=headers,
        json=_fact_edit_request(fact_id),
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["run_id"]
    return run_id, client.get(f"/api/v1/graph-runs/{run_id}", headers=headers).json()


def test_lg11_fact_change_requires_evidence_review_then_records_only_frozen_dependents(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    version, fact, _ = _frozen_lg10_version(db_session, source_run)
    _make_specs_unrelated(version)
    db_session.commit()
    source_snapshot = deepcopy(version.sections_json)
    before_versions = db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count()

    run_id, confirmation = _start(client, auth_headers, source_run, version, fact.id)
    evidence_wait = _resume(client, auth_headers, confirmation, "approve")
    assert evidence_wait.status_code == 200, evidence_wait.text
    evidence_state = evidence_wait.json()
    assert evidence_state["current_stage"] == "evidence_review"
    pending = evidence_state["values"]["review"]["pending"]
    assert pending["context"]["fact_evidence"][0]["fact_id"] == fact.id
    assert pending["context"]["affected_section_ids"] == ["hero"]
    assert pending["context"]["affected_scene_ids"] == ["hero-scene"]

    approved = _resume(client, auth_headers, evidence_state, "approve")
    assert approved.status_code == 200, approved.text
    completed = approved.json()
    assert completed["status"] == "completed"
    assert completed["current_stage"] == "fact_selective_stale"
    stale = completed["values"]["edit"]["selective_stale"]
    assert stale["status"] == "stale"
    assert stale["fact_evidence"][0]["fact_id"] == fact.id
    assert stale["affected"]["section_ids"] == ["hero"]
    assert stale["affected"]["scene_ids"] == ["hero-scene"]
    assert stale["retained"]["section_ids"] == ["specs"]
    assert stale["retained"]["scene_ids"] == []
    assert stale["execution"] == {
        "provider_calls": 0, "outbox_records": 0, "cost_approvals": 0, "next_action": "none",
    }
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run_id).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run_id).count() == 0
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == before_versions
    db_session.refresh(version)
    assert version.sections_json == source_snapshot

    edit_run = db_session.query(AgentRun).filter_by(id=run_id).one()
    assert edit_run.outputs_json["langgraph_edit"]["selective_stale"] == stale

    duplicate = _resume(client, auth_headers, evidence_state, "approve")
    assert duplicate.status_code == 200
    db_session.refresh(edit_run)
    assert edit_run.outputs_json["langgraph_edit"]["selective_stale"] == stale
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == before_versions


def test_lg11_fact_evidence_reject_keeps_frozen_version_and_rebuilds_pending_review(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    version, fact, _ = _frozen_lg10_version(db_session, source_run)
    source_snapshot = deepcopy(version.sections_json)
    run_id, confirmation = _start(client, auth_headers, source_run, version, fact.id)
    evidence_state = _resume(client, auth_headers, confirmation, "approve").json()
    assert evidence_state["current_stage"] == "evidence_review"

    edit_run = db_session.query(AgentRun).filter_by(id=run_id).one()
    edit_run.outputs_json = {}
    edit_run.status = "running"
    db_session.commit()
    recovered = client.post(f"/api/v1/graph-runs/{run_id}/resume", headers=auth_headers)
    assert recovered.status_code == 409, recovered.text
    db_session.refresh(edit_run)
    assert edit_run.outputs_json["langgraph_review"]["pending"]["review_stage"] == "evidence_review"
    assert edit_run.outputs_json["langgraph_edit"]["lineage"]["source_detail_page_version_id"] == version.id

    restored = client.get(f"/api/v1/graph-runs/{run_id}", headers=auth_headers).json()
    rejected = _resume(client, auth_headers, restored, "reject")
    assert rejected.status_code == 200, rejected.text
    result = rejected.json()
    assert result["status"] == "completed"
    assert result["current_stage"] == "fact_evidence_rejected"
    assert result["values"]["edit"]["selective_stale"] == {
        "status": "not_applied", "reason": "evidence_review_rejected",
    }
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run_id).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run_id).count() == 0
    db_session.refresh(version)
    assert version.sections_json == source_snapshot
