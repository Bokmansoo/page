"""TASK-12I.5 photo-only observation adapter contracts."""

from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager

import pytest

from src.db.models import (
    Asset,
    CommerceCreativeMasterVersion,
    ImageGenerationCostApprovalRecord,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ProductCreativeBriefVersion,
    ProductSourceSnapshotVersion,
)
from src.services.image_asset_inspector import inspect_asset
from src.services.brand_kit_service import create_kit, create_version
from src.services.product_intake_version_service import (
    PHOTO_ONLY_SOURCE_CANDIDATES_SCHEMA_VERSION,
    PhotoOnlyIntakeContractError,
    canonical_unified_intake_input_hash,
    adapt_photo_only_input_to_source_snapshot,
)
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _headers


pytestmark = pytest.mark.lg12i_fake_e2e


@pytest.fixture
def auth_headers():
    return _headers.__wrapped__()


@pytest.fixture
def lg12i_runtime(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _asset_ref(db_session, asset: Asset, *, rights_status: str = "seller_owned") -> dict[str, object]:
    inspection = inspect_asset(asset, db_session)
    assert inspection.content_hash is not None
    return {
        "id": asset.id,
        "kind": "asset_ref",
        "version": 1,
        "hash": inspection.content_hash,
        "rights_status": rights_status,
    }


def _envelope(run, refs, *, mode: str = "quick"):
    value = {
        "schema_version": "lg12i-unified-product-intake-v1",
        "project_id": run.project_id,
        "run_identity": {"run_id": run.id, "thread_id": run.id},
        "input_mode": "photo_only",
        "source_payload_refs": refs,
        "requested_generation_mode": mode,
        "target_channels": ["coupang", "smartstore"],
        "actor_workspace_identity": {
            "actor_id": "00000000-0000-0000-0000-000000000001",
            "workspace_id": run.workspace_id,
        },
        "created_at": "2026-08-18T00:00:00Z",
    }
    value["input_hash"] = canonical_unified_intake_input_hash(value)
    return value


def test_photo_only_creates_source_observations_not_facts_and_reuses_same_snapshot(
    client, auth_headers, db_session, tmp_path
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(project_id=run.project_id, asset_role="product_main").one()
    asset.ocr_text = "FAN-PRO visible label"
    db_session.commit()
    envelope = _envelope(run, [_asset_ref(db_session, asset)])

    before_jobs = db_session.query(ImageGenerationJobRecord).count()
    result = adapt_photo_only_input_to_source_snapshot(db_session, run=run, envelope=envelope)
    retry = adapt_photo_only_input_to_source_snapshot(db_session, run=run, envelope=envelope)

    assert result["schema_version"] == PHOTO_ONLY_SOURCE_CANDIDATES_SCHEMA_VERSION
    assert result["source_snapshot"] == retry["source_snapshot"]
    assert result["observations"]
    assert all(item["approval_status"] == "not_approved" for item in result["observations"])
    assert all(item["observation_type"] in {"ocr_text", "visible_visual"} for item in result["observations"])
    assert "raw_body" not in repr(result)
    assert "FAN-PRO visible label" in repr(result)  # bounded visible OCR observation, not a raw OCR document.
    assert {item["field_id"] for item in result["unknown_candidates"]} >= {"exact_weight", "battery_capacity"}
    assert result["rights"]["confirmation_state"] == "seller_owned"
    assert result["rights"]["final_use_status"] == "not_approved"
    assert db_session.query(ImageGenerationJobRecord).count() == before_jobs
    assert db_session.query(ImageGenerationOutboxRecord).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).count() == 0


def test_photo_only_accepts_one_or_two_assets_and_fails_closed_for_bad_refs(
    client, auth_headers, db_session, tmp_path
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    assets = db_session.query(Asset).filter_by(project_id=run.project_id).order_by(Asset.id).all()
    refs = [_asset_ref(db_session, asset) for asset in assets]
    two = adapt_photo_only_input_to_source_snapshot(db_session, run=run, envelope=_envelope(run, refs))
    assert len(two["source_asset_refs"]) == 2

    for invalid in (
        [],
        [*refs, deepcopy(refs[0])],
        [{**refs[0], "hash": "0" * 64}],
        [{**refs[0], "rights_status": "reference_only"}],
    ):
        with pytest.raises((PhotoOnlyIntakeContractError, ValueError)):
            adapt_photo_only_input_to_source_snapshot(db_session, run=run, envelope=_envelope(run, invalid))


def test_photo_only_unconfirmed_and_asset_changes_are_source_observations_not_final_use(
    client, auth_headers, db_session, tmp_path
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(project_id=run.project_id, asset_role="product_main").one()
    unconfirmed = _envelope(run, [_asset_ref(db_session, asset, rights_status="unconfirmed")], mode="expert")
    original = adapt_photo_only_input_to_source_snapshot(db_session, run=run, envelope=unconfirmed)
    assert original["rights"]["confirmation_state"] == "unconfirmed"
    assert original["rights"]["final_use_status"] == "not_approved"

    original_bytes = open(asset.file_path, "rb").read()
    with open(asset.file_path, "wb") as image_file:
        image_file.write(original_bytes + b"\x00photo-revision")
    changed = _envelope(run, [_asset_ref(db_session, asset, rights_status="unconfirmed")], mode="expert")
    changed_result = adapt_photo_only_input_to_source_snapshot(db_session, run=run, envelope=changed)
    assert changed_result["source_snapshot"] != original["source_snapshot"]
    assert db_session.query(ProductSourceSnapshotVersion).filter_by(id=original["source_snapshot"]["id"]).one().canonical_hash == original["source_snapshot"]["hash"]


def test_photo_observation_dedupes_identical_assets_and_preserves_conflicts(monkeypatch, client, auth_headers, db_session, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    assets = db_session.query(Asset).filter_by(project_id=run.project_id).order_by(Asset.id).all()

    def same_observation(asset, *, source_asset_ref):
        from src.services.product_intake_version_service import _normalized_photo_observation
        return [
            _normalized_photo_observation(
                observation_type="visible_visual", normalized_field="visible_color", observed_value="black",
                confidence=0.9, source_asset_ref=source_asset_ref, region={"x": 0, "y": 0, "width": 1, "height": 1},
                extractor_type="VLM", extractor_version="fake-v1",
            )
        ], [], {"ocr": {"state": "ready", "status": "fake"}, "vlm": {"state": "ready", "status": "fake"}}

    monkeypatch.setattr("src.services.product_intake_version_service._photo_observations_for_asset", same_observation)
    same = adapt_photo_only_input_to_source_snapshot(
        db_session, run=run, envelope=_envelope(run, [_asset_ref(db_session, asset) for asset in assets])
    )
    assert len(same["observations"]) == 1
    assert len(same["observations"][0]["source_asset_refs"]) == 2
    assert same["conflict_candidates"] == []

    def conflicting_observation(asset, *, source_asset_ref):
        from src.services.product_intake_version_service import _normalized_photo_observation
        return [
            _normalized_photo_observation(
                observation_type="visible_visual", normalized_field="visible_color",
                observed_value="black" if asset.id == assets[0].id else "navy", confidence=0.9,
                source_asset_ref=source_asset_ref, region={"x": 0, "y": 0, "width": 1, "height": 1},
                extractor_type="VLM", extractor_version="fake-v2",
            )
        ], [], {"ocr": {"state": "ready", "status": "fake"}, "vlm": {"state": "ready", "status": "fake"}}

    monkeypatch.setattr("src.services.product_intake_version_service._photo_observations_for_asset", conflicting_observation)
    conflict = adapt_photo_only_input_to_source_snapshot(
        db_session, run=run, envelope=_envelope(run, [_asset_ref(db_session, asset) for asset in assets], mode="expert")
    )
    assert len(conflict["conflict_candidates"]) == 1
    candidate = conflict["conflict_candidates"][0]
    assert candidate["approval_status"] == "not_approved"
    assert {item["observed_value"] for item in candidate["observations"]} == {"black", "navy"}


def test_photo_only_unsafe_ocr_is_not_preserved_as_raw_markup(client, auth_headers, db_session, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(project_id=run.project_id, asset_role="product_main").one()
    asset.ocr_text = "<script>alert('not source data')</script>"
    db_session.commit()
    result = adapt_photo_only_input_to_source_snapshot(
        db_session, run=run, envelope=_envelope(run, [_asset_ref(db_session, asset)])
    )
    assert "<script>" not in repr(result)
    assert "raw_ocr" not in result


def test_photo_only_observation_failure_is_a_recoverable_graph_state(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(project_id=source_run.project_id, asset_role="product_main").one()
    asset.asset_role = "unknown"
    db_session.commit()
    monkeypatch.setattr(
        "src.services.product_intake_version_service.extract_ocr_blocks",
        lambda _asset: ([], "ocr_engine_not_configured"),
    )
    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json={
            "input_mode": "photo_only", "source_payload_refs": [_asset_ref(db_session, asset)],
            "requested_generation_mode": "quick", "target_channels": ["smartstore"],
        },
    )
    assert response.status_code == 201, response.text
    state = response.json()
    assert state["current_stage"] == "photo_observation_recovery"
    assert state["values"]["intake"]["photo_observation"]["observation_status"] == "recovery"
    assert state["values"]["intake"]["photo_observation"]["failure_reason"] == "ocr_engine_not_configured"
    assert state["values"]["intake"]["next_action"] == "task_12i_manual_or_owned_url_fallback"


def test_photo_only_rejected_prohibited_inferences_handoff_to_planning(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(project_id=source_run.project_id, asset_role="product_main").one()
    monkeypatch.setattr(
        "src.services.product_intake_version_service.extract_ocr_blocks",
        lambda _asset: ([], "ocr_no_text_detected"),
    )
    kit = create_kit(db_session, source_run.workspace_id, source_run.created_by, "Photo handoff test kit")
    create_version(
        db_session, source_run.workspace_id, source_run.created_by, kit.id,
        {"color_tokens": {"accent": "#0f766e"}, "typography": {"body_font": "system-ui"}},
        scope="project", project_id=source_run.project_id, activate=True,
    )
    db_session.commit()
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    response = client.post(
        endpoint,
        headers=auth_headers,
        json={
            "input_mode": "photo_only", "source_payload_refs": [_asset_ref(db_session, asset)],
            "requested_generation_mode": "quick", "target_channels": ["smartstore"],
        },
    )
    assert response.status_code == 201, response.text
    state = response.json()
    run_id = state["run_id"]
    before = (
        db_session.query(ProductCreativeBriefVersion).filter_by(run_id=run_id).count(),
        db_session.query(CommerceCreativeMasterVersion).filter_by(creator_run_id=run_id).count(),
    )
    for _ in range(5):
        if state["current_stage"] != "seller_confirmation":
            break
        plan = state["values"]["intake"]["seller_confirmation"]
        state = client.post(
            f"/api/v1/graph-runs/{run_id}/resume",
            headers=auth_headers,
            json={
                "thread_id": state["thread_id"],
                "response": {
                    "schema_version": "lg12i-v1", "review_stage": "seller_confirmation",
                    "decision": "submit", "confirmation_request_hash": plan["resume_request_hash"],
                    "confirmation_answers": [
                        {"clarification_id": item["clarification_id"], "decision": "reject"}
                        for item in plan["clarifications"]
                    ],
                },
            },
        )
        assert state.status_code == 200, state.text
        state = state.json()
    assert state["current_stage"] == "planning_review"
    assert state["status"] == "awaiting_review"
    assert db_session.query(ProductCreativeBriefVersion).filter_by(run_id=run_id).count() == before[0] + 1
    assert db_session.query(CommerceCreativeMasterVersion).filter_by(creator_run_id=run_id).count() == before[1] + 2


@pytest.mark.parametrize(
    ("ocr_status", "expected_observation_status", "expected_stage", "role"),
    [
        ("ocr_engine_not_configured", "partial_observation_ready", "seller_confirmation", "product_main"),
        ("ocr_image_not_available", "recovery", "photo_observation_recovery", "unknown"),
        ("ocr_no_text_detected", "ready", "seller_confirmation", "unknown"),
    ],
)
def test_photo_only_ocr_structured_statuses_use_explicit_graph_contract(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch,
    ocr_status, expected_observation_status, expected_stage, role,
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(project_id=source_run.project_id, asset_role="product_main").one()
    asset.asset_role = role
    db_session.commit()
    monkeypatch.setattr(
        "src.services.product_intake_version_service.extract_ocr_blocks",
        lambda _asset: ([], ocr_status),
    )
    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json={
            "input_mode": "photo_only", "source_payload_refs": [_asset_ref(db_session, asset)],
            "requested_generation_mode": "quick", "target_channels": ["smartstore"],
        },
    )
    assert response.status_code == 201, response.text
    state = response.json()
    assert state["current_stage"] == expected_stage
    if expected_observation_status == "recovery":
        observation = state["values"]["intake"]["photo_observation"]
        assert observation["failure_reason"] == ocr_status
        assert observation["photo_observation_artifact_ref"] is not None
    else:
        source = state["values"]["intake"]["photo_observation"]
        assert source["observation_status"] == expected_observation_status
        assert state["values"]["intake"]["product_truth"]["truth_version"]["id"]


def test_photo_only_ocr_exception_is_recoverable_and_preserves_observation_artifact(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(project_id=source_run.project_id, asset_role="product_main").one()
    asset.asset_role = "unknown"
    db_session.commit()
    monkeypatch.setattr(
        "src.services.product_intake_version_service.extract_ocr_blocks",
        lambda _asset: (_ for _ in ()).throw(RuntimeError("engine boom")),
    )
    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json={
            "input_mode": "photo_only", "source_payload_refs": [_asset_ref(db_session, asset)],
            "requested_generation_mode": "expert", "target_channels": ["coupang"],
        },
    )
    assert response.status_code == 201, response.text
    observation = response.json()["values"]["intake"]["photo_observation"]
    assert observation["failure_reason"] == "ocr_failed"
    assert observation["photo_observation_artifact_ref"] is not None
    persisted_run = db_session.query(type(source_run)).filter_by(id=response.json()["run_id"]).one()
    expected = deepcopy(response.json()["values"]["intake"])
    persisted_run.outputs_json = {
        key: value for key, value in persisted_run.outputs_json.items() if key != "langgraph_intake"
    }
    persisted_run.status = "running"
    db_session.commit()
    resumed = client.post(f"/api/v1/graph-runs/{persisted_run.id}/resume", headers=auth_headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["values"]["intake"] == expected


def test_photo_only_unknown_provenance_and_ocr_risk_observations_are_bounded(
    client, auth_headers, db_session, tmp_path, monkeypatch
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(project_id=run.project_id, asset_role="product_main").one()
    monkeypatch.setattr(
        "src.services.product_intake_version_service.extract_ocr_blocks",
        lambda _asset: ([{"text": "BRAND SALE QR 29,900원", "bbox": {"x": 1, "y": 2}, "confidence": 90}], "source_ocr"),
    )
    result = adapt_photo_only_input_to_source_snapshot(
        db_session, run=run, envelope=_envelope(run, [_asset_ref(db_session, asset)])
    )
    candidate = result["unknown_candidates"][0]
    assert candidate["state"] in {"unknown", "prohibited_inference"}
    assert candidate["source_asset_refs"] and candidate["extractor_identities"]
    assert candidate["provenance_hash"]
    assert {item["risk_type"] for item in result["risk_signals"]} >= {"qr_code", "price_or_promotion", "suspicious_foreign_brand_text"}
    assert all(item["approval_status"] == "not_approved" for item in result["risk_signals"])


@pytest.mark.parametrize("source_type, usage_status, declared_rights, allowed", [
    ("uploaded", "seller_owned", "seller_owned", True),
    ("uploaded", "seller_owned", "unconfirmed", True),
    ("self_shot", "seller_owned", "rights_confirmed", True),
    ("supplier", "seller_owned", "seller_owned", False),
    ("supplier", "seller_owned", "unconfirmed", False),
    ("url-imported", "seller_owned", "seller_owned", False),
    ("uploaded", "blocked", "seller_owned", False),
])
def test_photo_only_picker_and_adapter_share_source_provenance_rights_gate(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, source_type, usage_status, declared_rights, allowed
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter_by(project_id=run.project_id, asset_role="product_main").one()
    asset.source_type = source_type
    asset.usage_status = usage_status
    db_session.commit()
    ref = _asset_ref(db_session, asset, rights_status=declared_rights)
    response = client.post(
        f"/api/v1/graph-runs/projects/{run.project_id}/unified-intake",
        headers=auth_headers,
        json={"input_mode": "photo_only", "source_payload_refs": [ref], "requested_generation_mode": "quick", "target_channels": ["smartstore"]},
    )
    if allowed:
        assert response.status_code == 201, response.text
        result = adapt_photo_only_input_to_source_snapshot(db_session, run=run, envelope=_envelope(run, [ref]))
        assert result["rights"]["final_use_status"] == "not_approved"
    else:
        assert response.status_code == 422, response.text
        with pytest.raises(PhotoOnlyIntakeContractError):
            adapt_photo_only_input_to_source_snapshot(db_session, run=run, envelope=_envelope(run, [ref]))
