"""TASK-12I.3 production LangGraph manual source-snapshot contracts."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.db.models import (
    AgentRun,
    ImageGenerationCostApprovalRecord,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ProductSourceSnapshotVersion,
)
from src.services.product_intake_version_service import (
    MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION,
    ManualIntakeContractError,
    adapt_manual_input_to_source_snapshot,
    create_manual_input_artifact,
    normalize_manual_input_metadata,
)
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers


pytestmark = pytest.mark.lg12i_fake_e2e

_ACTOR_ID = "00000000-0000-0000-0000-000000000001"
_WORKSPACE_ID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


@pytest.fixture
def lg12i_runtime(monkeypatch):
    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _metadata(
    *,
    fields: list[dict[str, object]] | None = None,
    rights: str = "unconfirmed",
    unknown_ids: list[str] | None = None,
    conflicts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "manual_payload_schema_version": MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION,
        "seller_entered_fields": fields or [
            {
                "field_id": "battery_capacity",
                "classification": "fact_candidate",
                "label": "배터리 용량",
                "value": "3200mAh",
                "unit": "mAh",
            },
            {
                "field_id": "visual_tone",
                "classification": "creative_direction",
                "label": "연출 톤",
                "value": "차분하고 프리미엄",
            },
        ],
        "unknown_fact_field_ids": unknown_ids if unknown_ids is not None else ["certification"],
        "rights_confirmation_state": rights,
    }
    if conflicts is not None:
        metadata["conflict_fact_candidates"] = conflicts
    return metadata


def _manual_ref(artifact) -> list[dict[str, object]]:
    return [{
        "id": artifact.id,
        "kind": "manual_payload_artifact",
        "version": artifact.version,
        "hash": artifact.content_hash,
    }]


def _payload(artifact, *, generation: str = "quick", channels: list[str] | None = None) -> dict[str, object]:
    return {
        "input_mode": "manual",
        "source_payload_refs": _manual_ref(artifact),
        "requested_generation_mode": generation,
        "target_channels": channels or ["smartstore", "coupang"],
    }


def _create_artifact(db_session, source_run, *, raw_body: str = "판매자 직접 입력 원문", metadata=None):
    artifact = create_manual_input_artifact(
        db_session,
        workspace_id=_WORKSPACE_ID,
        project_id=source_run.project_id,
        created_by=_ACTOR_ID,
        raw_body=raw_body,
        source_metadata=metadata or _metadata(),
    )
    db_session.commit()
    db_session.refresh(artifact)
    return artifact


def test_manual_reference_input_entry_point_creates_adapter_eligible_artifact(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    created = client.post(
        f"/api/v1/projects/{source_run.project_id}/reference-inputs",
        headers=auth_headers,
        json={
            "input_kind": "text",
            "text": "판매자 직접 입력용 원문",
            "source_metadata": _metadata(),
        },
    )
    assert created.status_code == 200, created.text
    artifact_ref = {
        "id": created.json()["id"],
        "kind": "manual_payload_artifact",
        "version": created.json()["version"],
        "hash": created.json()["content_hash"],
    }
    routed = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json={
            "input_mode": "manual",
            "source_payload_refs": [artifact_ref],
            "requested_generation_mode": "quick",
            "target_channels": ["smartstore"],
        },
    )
    assert routed.status_code == 201, routed.text
    assert routed.json()["values"]["intake"]["manual_source"]["manual_artifact_ref"]["id"] == artifact_ref["id"]


def test_manual_adapter_creates_structured_source_snapshot_without_raw_graph_body(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = _create_artifact(db_session, source_run)
    before = {
        "jobs": db_session.query(ImageGenerationJobRecord).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).count(),
    }

    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json=_payload(artifact, generation="expert"),
    )
    assert response.status_code == 201, response.text
    state = response.json()
    assert state["current_stage"] == "seller_confirmation"
    intake = state["values"]["intake"]
    assert intake["requested_generation_mode"] == "expert"
    assert intake["target_channels"] == ["coupang", "smartstore"]
    assert intake["next_action"] == "seller_confirmation"
    assert intake["product_truth"]["truth_version"]["id"]
    manual = intake["manual_source"]
    assert manual["manual_artifact_ref"]["id"] == artifact.id
    assert manual["rights"] == {
        "confirmation_state": "unconfirmed",
        "final_use_status": "not_approved",
    }
    assert manual["fact_count"] == 1
    assert manual["creative_direction_count"] == 1
    assert "판매자 직접 입력 원문" not in repr(intake)
    snapshot = db_session.query(ProductSourceSnapshotVersion).filter_by(
        id=manual["source_snapshot"]["id"]
    ).one()
    assert snapshot.input_mode == "manual"
    assert {
        key: snapshot.source_refs_json[0][key] for key in ("id", "version", "hash")
    } == manual["manual_artifact_ref"]
    assert snapshot.provenance_json["source"] == "seller_entered"
    assert snapshot.source_fidelity_json["fact_candidate_count"] == 1
    assert db_session.query(ImageGenerationJobRecord).count() == before["jobs"]
    assert db_session.query(ImageGenerationOutboxRecord).count() == before["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).count() == before["cost"]


def test_manual_empty_and_missing_optional_facts_are_preserved_as_unknown_candidates(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = _create_artifact(
        db_session,
        source_run,
        metadata=_metadata(
            fields=[
                {
                    "field_id": "material",
                    "classification": "fact_candidate",
                    "label": "소재",
                    "value": "",
                },
                {
                    "field_id": "visual_tone",
                    "classification": "creative_direction",
                    "label": "연출 톤",
                    "value": "정갈한",
                },
            ],
            unknown_ids=["certification"],
        ),
    )
    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json=_payload(artifact),
    )
    assert response.status_code == 201, response.text
    manual = response.json()["values"]["intake"]["manual_source"]
    assert manual["fact_count"] == 0
    assert manual["creative_direction_count"] == 1
    assert manual["unknown_count"] == 2
    snapshot = db_session.query(ProductSourceSnapshotVersion).filter_by(
        id=manual["source_snapshot"]["id"]
    ).one()
    assert snapshot.rights_json["confirmation_state"] == "unconfirmed"
    assert snapshot.rights_json["final_use_status"] == "not_approved"
    assert snapshot.source_fidelity_json["unknown_fact_field_ids"] == ["certification", "material"]


def test_manual_conflict_observations_are_preserved_without_fact_promotion(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    conflict_metadata = _metadata(
        unknown_ids=[],
        conflicts=[{
            "field_id": "material",
            "label": "소재",
            "observations": [{"value": "stainless"}, {"value": "aluminum"}],
        }],
    )
    artifact = _create_artifact(db_session, source_run, metadata=conflict_metadata)
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    first = client.post(endpoint, headers=auth_headers, json=_payload(artifact, generation="expert"))
    repeated = client.post(endpoint, headers=auth_headers, json=_payload(artifact, generation="expert"))
    assert first.status_code == repeated.status_code == 201
    manual = first.json()["values"]["intake"]["manual_source"]
    assert repeated.json()["values"]["intake"]["manual_source"]["source_snapshot"] == manual["source_snapshot"]
    assert manual["fact_count"] == 1
    assert manual["conflict_count"] == 1

    changed = _create_artifact(
        db_session,
        source_run,
        metadata=_metadata(
            unknown_ids=[],
            conflicts=[{
                "field_id": "material",
                "label": "소재",
                "observations": [{"value": "stainless"}, {"value": "titanium"}],
            }],
        ),
    )
    changed_response = client.post(endpoint, headers=auth_headers, json=_payload(changed, generation="expert"))
    assert changed_response.status_code == 201, changed_response.text
    assert (
        changed_response.json()["values"]["intake"]["manual_source"]["source_snapshot"]["id"]
        != manual["source_snapshot"]["id"]
    )


def test_manual_adapter_is_idempotent_for_same_artifact_and_changes_identity_for_changed_content(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    first_artifact = _create_artifact(db_session, source_run, raw_body="첫 번째 판매자 입력")
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    first = client.post(endpoint, headers=auth_headers, json=_payload(first_artifact, generation="quick"))
    retry = client.post(endpoint, headers=auth_headers, json=_payload(first_artifact, generation="quick"))
    expert = client.post(endpoint, headers=auth_headers, json=_payload(first_artifact, generation="expert"))
    assert first.status_code == retry.status_code == expert.status_code == 201
    assert retry.json()["run_id"] == first.json()["run_id"]
    assert expert.json()["run_id"] != first.json()["run_id"]
    first_snapshot = first.json()["values"]["intake"]["manual_source"]["source_snapshot"]
    assert expert.json()["values"]["intake"]["manual_source"]["source_snapshot"] == first_snapshot

    changed_artifact = _create_artifact(db_session, source_run, raw_body="변경된 판매자 입력")
    changed = client.post(endpoint, headers=auth_headers, json=_payload(changed_artifact))
    assert changed.status_code == 201, changed.text
    assert changed.json()["values"]["intake"]["manual_source"]["source_snapshot"]["id"] != first_snapshot["id"]
    assert db_session.query(ProductSourceSnapshotVersion).filter_by(project_id=source_run.project_id).count() == 2


def test_manual_metadata_prevents_fact_creative_overlap_and_executable_payloads(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    overlap = _metadata(fields=[
        {"field_id": "model", "classification": "fact_candidate", "label": "모델", "value": "A1"},
        {"field_id": "model", "classification": "creative_direction", "label": "모델", "value": "감성"},
    ])
    with pytest.raises(ManualIntakeContractError):
        normalize_manual_input_metadata(overlap)
    same_category_duplicate = _metadata(fields=[
        {"field_id": "model", "classification": "fact_candidate", "label": "모델", "value": "A1"},
        {"field_id": "model", "classification": "fact_candidate", "label": "모델", "value": "A2"},
    ])
    with pytest.raises(ManualIntakeContractError):
        normalize_manual_input_metadata(same_category_duplicate)
    unknown_state = _metadata(fields=[
        {
            "field_id": "model",
            "classification": "fact_candidate",
            "label": "모델",
            "value": "A1",
            "observation_state": "approved",
        },
    ])
    with pytest.raises(ManualIntakeContractError):
        normalize_manual_input_metadata(unknown_state)
    unsafe = _metadata(fields=[
        {"field_id": "model", "classification": "fact_candidate", "label": "모델", "value": "<script>alert(1)</script>"},
    ])
    with pytest.raises(ManualIntakeContractError):
        _create_artifact(db_session, source_run, metadata=unsafe)
    with pytest.raises(ManualIntakeContractError):
        _create_artifact(db_session, source_run, raw_body="<script>alert(1)</script>")

    artifact = _create_artifact(db_session, source_run)
    raw_state_attempt = _payload(artifact)
    raw_state_attempt["source_payload_refs"] = [{**_manual_ref(artifact)[0], "raw_html": "<script>x</script>"}]
    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json=raw_state_attempt,
    )
    assert response.status_code == 422, response.text


def test_manual_adapter_rejects_tampered_artifact_reference_and_preserves_immutable_snapshot(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = _create_artifact(db_session, source_run)
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    mismatched = _payload(artifact)
    mismatched["source_payload_refs"] = [{**_manual_ref(artifact)[0], "hash": "0" * 64}]
    response = client.post(endpoint, headers=auth_headers, json=mismatched)
    # The reference-only envelope can be syntactically valid, but its durable
    # artifact identity is verified by the production LangGraph adapter before
    # any snapshot is created.  A failed run is still a hard fail-closed gate.
    assert response.status_code == 500, response.text
    assert db_session.query(ProductSourceSnapshotVersion).filter_by(project_id=source_run.project_id).count() == 0

    valid = client.post(endpoint, headers=auth_headers, json=_payload(artifact))
    assert valid.status_code == 201, valid.text
    source_ref = valid.json()["values"]["intake"]["manual_source"]["source_snapshot"]
    snapshot = db_session.query(ProductSourceSnapshotVersion).filter_by(id=source_ref["id"]).one()
    with pytest.raises(Exception):
        snapshot.source_fidelity_json = {"tampered": True}
        db_session.commit()
    db_session.rollback()
    snapshot = db_session.query(ProductSourceSnapshotVersion).filter_by(id=source_ref["id"]).one()
    assert snapshot.canonical_hash == source_ref["hash"]


def test_manual_adapter_projection_rebuild_restores_identity_without_url_photo_or_provider_work(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = _create_artifact(db_session, source_run)
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    state = client.post(endpoint, headers=auth_headers, json=_payload(artifact)).json()
    run = db_session.query(AgentRun).filter_by(id=state["run_id"]).one()
    expected = deepcopy(run.outputs_json["langgraph_intake"])
    run.outputs_json = {key: value for key, value in run.outputs_json.items() if key != "langgraph_intake"}
    run.status = "running"
    db_session.add(run)
    db_session.commit()
    recovered = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert recovered.status_code == 200, recovered.text
    db_session.refresh(run)
    assert run.outputs_json["langgraph_intake"] == expected
    assert recovered.json()["values"]["intake"] == state["values"]["intake"]
