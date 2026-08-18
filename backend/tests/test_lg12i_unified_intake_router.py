"""LG-12I.2 reference-only unified intake router contracts."""

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
)
from src.services.product_intake_version_service import (
    UNIFIED_PRODUCT_INTAKE_SCHEMA_VERSION,
    UnifiedProductIntakeContractError,
    canonical_unified_intake_input_hash,
    validate_unified_product_intake_envelope,
)
from src.services.prompt_intelligence_service import canonical_hash
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers


pytestmark = pytest.mark.lg12i_fake_e2e


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


def _hash(label: str) -> str:
    return canonical_hash({"fixture": label})


def _source_refs(mode: str) -> list[dict[str, object]]:
    if mode == "owned_product_url":
        return [{"id": "capture-owned-url", "kind": "url_capture_request", "version": 1, "hash": _hash("url")}]
    if mode == "photo_only":
        return [{
            "id": "asset-seller-photo", "kind": "asset_ref", "version": 1,
            "hash": _hash("photo"), "rights_status": "seller_owned",
        }]
    return [{"id": "manual-input-artifact", "kind": "manual_payload_artifact", "version": 1, "hash": _hash("manual")}]


def _payload(
    mode: str, *, generation: str = "quick", source_payload_refs: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "input_mode": mode,
        "source_payload_refs": source_payload_refs if source_payload_refs is not None else _source_refs(mode),
        "requested_generation_mode": generation,
        "target_channels": ["smartstore", "coupang"],
    }


def _envelope(mode: str, *, refs: list[dict[str, object]] | None = None, channels: list[str] | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": UNIFIED_PRODUCT_INTAKE_SCHEMA_VERSION,
        "project_id": "project-1",
        "run_identity": {"run_id": "run-1", "thread_id": "run-1"},
        "input_mode": mode,
        "source_payload_refs": refs if refs is not None else _source_refs(mode),
        "requested_generation_mode": "expert",
        "target_channels": channels if channels is not None else ["smartstore", "coupang"],
        "actor_workspace_identity": {"actor_id": "actor-1", "workspace_id": "workspace-1"},
        "created_at": "2026-08-18T00:00:00Z",
    }
    value["input_hash"] = canonical_unified_intake_input_hash(value)
    return value


def _project_asset_ref(db_session, project_id: str) -> list[dict[str, object]]:
    from src.db.models import Asset

    asset = db_session.query(Asset).filter_by(project_id=project_id, usage_status="seller_owned").first()
    assert asset is not None
    return [{
        "id": asset.id,
        "kind": "asset_ref",
        "version": 1,
        "hash": _hash(f"asset-ref:{asset.id}"),
        "rights_status": "seller_owned",
    }]


def test_lg12i_envelopes_are_deterministic_and_reference_only():
    for mode in ("owned_product_url", "photo_only", "manual"):
        envelope = _envelope(mode)
        assert validate_unified_product_intake_envelope(envelope)["input_mode"] == mode
        assert canonical_unified_intake_input_hash(envelope) == envelope["input_hash"]

    ordered = _envelope("photo_only", refs=[
        {"id": "asset-b", "kind": "asset_ref", "version": 1, "hash": _hash("b"), "rights_status": "seller_owned"},
        {"id": "asset-a", "kind": "asset_ref", "version": 1, "hash": _hash("a"), "rights_status": "rights_confirmed"},
    ])
    reversed_refs = deepcopy(ordered)
    reversed_refs["source_payload_refs"] = list(reversed(ordered["source_payload_refs"]))
    reversed_refs["input_hash"] = canonical_unified_intake_input_hash(reversed_refs)
    assert ordered["input_hash"] == reversed_refs["input_hash"]

    smartstore_only = _envelope("manual", channels=["smartstore"])
    coupang_only = _envelope("manual", channels=["coupang"])
    both_reversed = _envelope("manual", channels=["coupang", "smartstore"])
    assert smartstore_only["input_hash"] != coupang_only["input_hash"]
    assert _envelope("manual")["input_hash"] == both_reversed["input_hash"]
    assert validate_unified_product_intake_envelope(both_reversed)["target_channels"] == ["coupang", "smartstore"]
    for channels in (["smartstore"], ["coupang"], ["smartstore", "coupang"]):
        assert validate_unified_product_intake_envelope(_envelope("manual", channels=channels))["target_channels"] == sorted(channels)

    unsafe = _envelope("photo_only")
    unsafe["source_payload_refs"] = [{
        "id": "asset-unsafe", "kind": "asset_ref", "version": 1, "hash": _hash("unsafe"),
        "rights_status": "seller_owned", "raw_image_bytes": "x" * 5000,
    }]
    unsafe["input_hash"] = canonical_unified_intake_input_hash(unsafe)
    with pytest.raises(UnifiedProductIntakeContractError):
        validate_unified_product_intake_envelope(unsafe)


def test_lg12i_production_router_uses_one_path_for_every_input_mode(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    legacy_calls: list[str] = []

    def legacy_call(*_args, **_kwargs):
        legacy_calls.append("called")
        raise AssertionError("Legacy input router must not be called by LG-12I.")

    monkeypatch.setattr("src.agents.nodes.input_router.agent.InputRouterAgent.run_delta", legacy_call)
    before_outbox = db_session.query(ImageGenerationOutboxRecord).count()
    before_cost = db_session.query(ImageGenerationCostApprovalRecord).count()
    before_jobs = db_session.query(ImageGenerationJobRecord).count()

    routed = []
    for mode in ("owned_product_url", "photo_only", "manual"):
        refs = _project_asset_ref(db_session, source_run.project_id) if mode == "photo_only" else None
        response = client.post(
            f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
            headers=auth_headers,
            json=_payload(
                mode,
                generation="expert" if mode == "manual" else "quick",
                source_payload_refs=refs,
            ),
        )
        assert response.status_code == 201, response.text
        state = response.json()
        assert state["status"] == "completed"
        assert state["current_stage"] == "intake_adapter_pending"
        intake = state["values"]["intake"]
        assert intake["input_mode"] == mode
        assert intake["next_action"] == "task_12i_adapter_not_implemented"
        assert intake["requested_generation_mode"] == ("expert" if mode == "manual" else "quick")
        assert intake["target_channels"] == ["coupang", "smartstore"]
        assert intake["run_identity"]["run_id"] == state["run_id"]
        routed.append(intake)

    assert len({item["next_action"] for item in routed}) == 1
    assert legacy_calls == []
    assert db_session.query(ImageGenerationJobRecord).count() == before_jobs
    assert db_session.query(ImageGenerationOutboxRecord).count() == before_outbox
    assert db_session.query(ImageGenerationCostApprovalRecord).count() == before_cost


def test_lg12i_rejects_unknown_or_incomplete_modes_before_router(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    invalid_cases = [
        {**_payload("manual"), "input_mode": "supplier_url"},
        {**_payload("owned_product_url"), "source_payload_refs": []},
        {**_payload("photo_only"), "source_payload_refs": [{
            "id": "reference-only", "kind": "asset_ref", "version": 1,
            "hash": _hash("reference"), "rights_status": "reference_only",
        }]},
        {**_payload("manual"), "source_payload_refs": [{
            "id": "unsafe-html", "kind": "manual_payload_artifact", "version": 1,
            "hash": _hash("html"), "raw_html": "<main>" + ("x" * 5000),
        }]},
        {**_payload("manual"), "source_payload_refs": [
            *_source_refs("manual"), *_source_refs("owned_product_url"),
        ]},
        {**_payload("manual"), "raw_html": "<main>" + ("x" * 5000)},
        {**_payload("manual"), "target_channels": []},
        {**_payload("manual"), "target_channels": ["smartstore", "smartstore"]},
        {**_payload("manual"), "target_channels": ["unknown-channel"]},
        {**_payload("manual"), "target_channels": ["smartstore", "unknown-channel"]},
    ]
    for payload in invalid_cases:
        response = client.post(endpoint, headers=auth_headers, json=payload)
        assert response.status_code == 422, response.text


def test_lg12i_photo_only_reuses_project_scoped_asset_picker_contract(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    reference = _project_asset_ref(db_session, source_run.project_id)
    permitted = client.post(
        endpoint,
        headers=auth_headers,
        json=_payload("photo_only", source_payload_refs=reference),
    )
    assert permitted.status_code == 201, permitted.text

    from src.db.models import Asset

    asset = db_session.query(Asset).filter_by(id=reference[0]["id"]).one()
    asset.usage_status = "blocked"
    db_session.add(asset)
    db_session.commit()
    blocked = client.post(
        endpoint,
        headers=auth_headers,
        json={
            **_payload("photo_only", source_payload_refs=reference),
            # A distinct channel set avoids intentionally reusing the completed
            # idempotent run while exercising the asset picker gate.
            "target_channels": ["coupang"],
        },
    )
    assert blocked.status_code == 422, blocked.text


def test_lg12i_idempotency_and_rebuild_restore_envelope_projection(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    payload = _payload(
        "photo_only", source_payload_refs=_project_asset_ref(db_session, source_run.project_id)
    )
    first = client.post(endpoint, headers=auth_headers, json=payload)
    assert first.status_code == 201, first.text
    retry = client.post(endpoint, headers=auth_headers, json=payload)
    assert retry.status_code == 201, retry.text
    assert retry.json()["run_id"] == first.json()["run_id"]

    reversed_channels = client.post(
        endpoint,
        headers=auth_headers,
        json={**payload, "target_channels": ["coupang", "smartstore"]},
    )
    assert reversed_channels.status_code == 201, reversed_channels.text
    assert reversed_channels.json()["run_id"] == first.json()["run_id"]

    expert = client.post(
        endpoint,
        headers=auth_headers,
        json={**payload, "requested_generation_mode": "expert"},
    )
    smartstore = client.post(
        endpoint,
        headers=auth_headers,
        json={**payload, "target_channels": ["smartstore"]},
    )
    coupang = client.post(
        endpoint,
        headers=auth_headers,
        json={**payload, "target_channels": ["coupang"]},
    )
    for response in (expert, smartstore, coupang):
        assert response.status_code == 201, response.text
        assert response.json()["run_id"] != first.json()["run_id"]
    assert smartstore.json()["run_id"] != coupang.json()["run_id"]

    run = db_session.query(AgentRun).filter_by(id=first.json()["run_id"]).one()
    expected = deepcopy(run.outputs_json["langgraph_intake"])
    run.outputs_json = {key: value for key, value in run.outputs_json.items() if key != "langgraph_intake"}
    run.status = "running"
    db_session.add(run)
    db_session.commit()

    recovered = client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers)
    assert recovered.status_code == 200, recovered.text
    db_session.refresh(run)
    assert run.status == "completed"
    assert run.outputs_json["langgraph_intake"] == expected
    assert recovered.json()["values"]["intake"] == expected
