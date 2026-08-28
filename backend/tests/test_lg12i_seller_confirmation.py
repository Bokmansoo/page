"""TASK-12I.7 bounded seller-confirmation production contracts."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import uuid

import pytest

from src.db.models import AgentRun, ProductSourceSnapshotVersion, ProductTruthVersion, SellerConfirmationVersion
from src.services.product_intake_version_service import (
    SellerConfirmationContractError,
    _validate_confirmation_answer,
    adapt_manual_input_to_source_snapshot,
    apply_seller_confirmation_cycle,
    build_seller_confirmation_plan,
    canonical_unified_intake_input_hash,
    create_manual_input_artifact,
    create_product_source_snapshot_version,
    normalize_product_truth_from_source_snapshot,
    seller_confirmation_answer_bundle_hash,
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


def _metadata(*, forbidden_source: bool = False) -> dict:
    return {
        "manual_payload_schema_version": "lg12i-manual-input-artifact-v1",
        "seller_entered_fields": [
            {"field_id": "product_identity", "classification": "fact_candidate", "label": "product", "value": "fan"},
            {"field_id": "battery_capacity", "classification": "fact_candidate", "label": "battery", "value": "3200", "unit": "mAh"},
        ],
        "unknown_fact_field_ids": ["certification", "warranty", "material"],
        "conflict_fact_candidates": ([{
            "field_id": "capacity_label", "label": "capacity", "observations": [
                {"value": "large"}, {"value": "compact"},
            ],
        }] if not forbidden_source else []),
        "rights_confirmation_state": "unconfirmed",
    }


def _truth(db, client, auth_headers, tmp_path, *, forbidden_source: bool = False):
    run = _create_run(client, auth_headers, db, tmp_path)
    artifact = create_manual_input_artifact(
        db,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        created_by=run.created_by,
        raw_body="bounded seller-entered source",
        source_metadata=_metadata(forbidden_source=forbidden_source),
    )
    db.commit(); db.refresh(artifact)
    artifact_ref = {
        "id": artifact.id, "kind": "manual_payload_artifact", "version": artifact.version,
        "hash": artifact.content_hash, "schema_version": "lg12i-manual-input-artifact-v1",
    }
    if forbidden_source:
        frozen_artifact_ref = {
            key: artifact_ref[key]
            for key in ("id", "version", "hash", "schema_version")
        }
        frozen_artifact_ref["artifact_key"] = "manual_product_input"
        source_row = create_product_source_snapshot_version(
            db,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            creator_run_id=run.id,
            created_by=run.created_by,
            input_mode="manual",
            source_refs=[frozen_artifact_ref],
            provenance={"source_type": "supplier", "manual_artifact_ref": frozen_artifact_ref},
            rights={"confirmation_state": "unconfirmed", "source_type": "supplier", "final_use_status": "not_approved"},
            source_fidelity={"source_kind": "manual"},
        )
        db.commit(); db.refresh(source_row)
        source = {"source_snapshot": {"id": source_row.id, "version": source_row.version, "hash": source_row.canonical_hash}}
    else:
        envelope = {
            "schema_version": "lg12i-unified-product-intake-v1",
            "project_id": run.project_id,
            "run_identity": {"run_id": run.id, "thread_id": run.id},
            "input_mode": "manual",
            "source_payload_refs": [artifact_ref],
            "requested_generation_mode": "quick",
            "target_channels": ["smartstore"],
            "actor_workspace_identity": {"actor_id": run.created_by, "workspace_id": run.workspace_id},
            "input_hash": "",
            "created_at": "2026-08-19T00:00:00Z",
        }
        envelope["input_hash"] = canonical_unified_intake_input_hash(envelope)
        source = adapt_manual_input_to_source_snapshot(db, run=run, envelope=envelope)
    truth = normalize_product_truth_from_source_snapshot(
        db,
        run=run,
        source_reference={"id": source["source_snapshot"]["id"], "version": source["source_snapshot"]["version"], "hash": source["source_snapshot"]["hash"]},
    )
    return run, truth


def test_confirmation_plan_is_bounded_priority_ordered_and_hashes_questions(db_session, client, auth_headers, tmp_path):
    run, truth = _truth(db_session, client, auth_headers, tmp_path)
    plan = build_seller_confirmation_plan(db_session, run=run, truth_reference=truth["truth_version"])

    assert len(plan["clarifications"]) == 3
    assert len(plan["unresolved_queue"]) >= 1
    assert [item["priority"] for item in plan["clarifications"]] == [2, 3, 4]
    assert all(item["clarification_id"] and item["clarification_hash"] for item in plan["clarifications"])
    assert all(item["truth_item_ref"]["hash"] for item in plan["clarifications"])
    assert len(plan["resume_request_hash"]) == 64


def test_source_backed_truth_with_no_blockers_skips_confirmation(db_session, client, auth_headers, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    metadata = {
        "manual_payload_schema_version": "lg12i-manual-input-artifact-v1",
        "seller_entered_fields": [{
            "field_id": "product_identity", "classification": "fact_candidate",
            "label": "product", "value": "fan",
        }],
        "unknown_fact_field_ids": [],
        "conflict_fact_candidates": [],
        "rights_confirmation_state": "confirmed",
    }
    artifact = create_manual_input_artifact(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        created_by=run.created_by, raw_body="bounded seller source", source_metadata=metadata,
    )
    db_session.commit(); db_session.refresh(artifact)
    envelope = {
        "schema_version": "lg12i-unified-product-intake-v1", "project_id": run.project_id,
        "run_identity": {"run_id": run.id, "thread_id": run.id}, "input_mode": "manual",
        "source_payload_refs": [{"id": artifact.id, "kind": "manual_payload_artifact", "version": artifact.version, "hash": artifact.content_hash}],
        "requested_generation_mode": "quick", "target_channels": ["smartstore"],
        "actor_workspace_identity": {"actor_id": run.created_by, "workspace_id": run.workspace_id},
        "input_hash": "", "created_at": "2026-08-19T00:00:00Z",
    }
    envelope["input_hash"] = canonical_unified_intake_input_hash(envelope)
    source = adapt_manual_input_to_source_snapshot(db_session, run=run, envelope=envelope)
    truth = normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=source["source_snapshot"])
    plan = build_seller_confirmation_plan(db_session, run=run, truth_reference=truth["truth_version"])

    assert plan["confirmation_required"] is False
    assert plan["clarifications"] == []


def test_confirmation_cycle_persists_answers_without_promoting_prohibited_or_duplicate_rows(db_session, client, auth_headers, tmp_path):
    run, truth = _truth(db_session, client, auth_headers, tmp_path)
    plan = build_seller_confirmation_plan(db_session, run=run, truth_reference=truth["truth_version"])
    rights, conflict, unknown = plan["clarifications"]
    assert rights["type"] == "rights"
    assert conflict["type"] == "fact_conflict"
    first = apply_seller_confirmation_cycle(
        db_session,
        run=run,
        plan=plan,
        actor_id=run.created_by,
        answers=[
            {"clarification_id": conflict["clarification_id"], "decision": "confirm", "selected_observation_id": conflict["allowed_options"][0]["observation_id"]},
            {"clarification_id": rights["clarification_id"], "decision": "confirm"},
            {"clarification_id": unknown["clarification_id"], "decision": "unknown"},
        ],
    )
    second = apply_seller_confirmation_cycle(
        db_session,
        run=run,
        plan=plan,
        actor_id=run.created_by,
        answers=[
            {"clarification_id": conflict["clarification_id"], "decision": "confirm", "selected_observation_id": conflict["allowed_options"][0]["observation_id"]},
            {"clarification_id": rights["clarification_id"], "decision": "confirm"},
            {"clarification_id": unknown["clarification_id"], "decision": "unknown"},
        ],
    )

    assert first["confirmation_version"] == second["confirmation_version"]
    confirmation = db_session.query(SellerConfirmationVersion).filter_by(id=first["confirmation_version"]["id"]).one()
    assert confirmation.confirmation_cycle == 1
    assert confirmation.rights_confirmations_json[0]["status"] == "rights_confirmed"
    assert db_session.query(SellerConfirmationVersion).filter_by(creator_run_id=run.id).count() == 1


def test_seller_confirmed_values_pin_unknown_and_conflict_provenance(db_session, client, auth_headers, tmp_path):
    """A confirmation is self-sufficient; it never relies on answers_json for value provenance."""

    run, truth = _truth(db_session, client, auth_headers, tmp_path)
    plan = build_seller_confirmation_plan(db_session, run=run, truth_reference=truth["truth_version"])
    rights, conflict, unknown = plan["clarifications"]
    result = apply_seller_confirmation_cycle(
        db_session,
        run=run,
        plan=plan,
        actor_id=run.created_by,
        answers=[
            {"clarification_id": rights["clarification_id"], "decision": "confirm"},
            {
                "clarification_id": conflict["clarification_id"],
                "decision": "confirm", "answer_value": "550", "unit": "ml",
            },
            {
                "clarification_id": unknown["clarification_id"],
                "decision": "confirm", "answer_value": "600", "unit": "mAh",
            },
        ],
    )
    confirmation = db_session.query(SellerConfirmationVersion).filter_by(
        id=result["confirmation_version"]["id"]
    ).one()
    refs = {item["field_id"]: item for item in confirmation.confirmed_fact_refs_json}

    conflict_ref = refs["capacity_label"]
    assert conflict_ref["normalized_value"] == "550"
    assert conflict_ref["unit"] == "ml"
    assert conflict_ref["source_kind"] == "seller_confirmation"
    assert conflict_ref["selected_observation_ref"] is None
    assert len(conflict_ref["conflicting_observation_refs"]) == 2
    assert conflict_ref["seller_actor_id"] == run.created_by
    assert conflict_ref["confirmation_cycle"] == 1

    unknown_ref = refs["certification"]
    assert unknown_ref["normalized_value"] == "600"
    assert unknown_ref["unit"] == "mAh"
    assert unknown_ref["source_kind"] == "seller_confirmation"
    for item in (conflict_ref, unknown_ref):
        assert item["decision_status"] == "confirmed"
        assert item["confirmed_fact_id"].startswith("seller-confirmed-fact:")
        assert item["provenance_hash"]
        assert item["clarification_ref"]["hash"]
        assert item["answer_ref"]["hash"]
        assert item["original_truth_item_ref"]["hash"]
        assert item["source_refs"] or item["evidence_refs"]


def test_selected_conflict_observation_pins_selected_value_and_changes_confirmation_hash(
    db_session, client, auth_headers, tmp_path
):
    run_one, truth_one = _truth(db_session, client, auth_headers, tmp_path)
    plan_one = build_seller_confirmation_plan(db_session, run=run_one, truth_reference=truth_one["truth_version"])
    rights_one, conflict_one, unknown_one = plan_one["clarifications"]
    selected = conflict_one["allowed_options"][1]
    first = apply_seller_confirmation_cycle(
        db_session,
        run=run_one,
        plan=plan_one,
        actor_id=run_one.created_by,
        answers=[
            {"clarification_id": rights_one["clarification_id"], "decision": "confirm"},
            {
                "clarification_id": conflict_one["clarification_id"],
                "decision": "confirm", "selected_observation_id": selected["observation_id"],
            },
            {"clarification_id": unknown_one["clarification_id"], "decision": "unknown"},
        ],
    )
    first_row = db_session.query(SellerConfirmationVersion).filter_by(
        id=first["confirmation_version"]["id"]
    ).one()
    selected_ref = next(item for item in first_row.confirmed_fact_refs_json if item["field_id"] == "capacity_label")
    assert selected_ref["source_kind"] == "selected_observation"
    assert selected_ref["normalized_value"] == selected["value"]
    assert selected_ref["selected_observation_ref"]["hash"] == selected["observation_ref"]["hash"]

    # The same frozen Truth with a changed seller value must yield a different
    # immutable confirmation hash rather than mutating the original row.
    run_one.status = "completed"
    db_session.add(run_one)
    db_session.commit()
    run_two, truth_two = _truth(db_session, client, auth_headers, tmp_path)
    plan_two = build_seller_confirmation_plan(db_session, run=run_two, truth_reference=truth_two["truth_version"])
    rights_two, conflict_two, unknown_two = plan_two["clarifications"]
    second = apply_seller_confirmation_cycle(
        db_session,
        run=run_two,
        plan=plan_two,
        actor_id=run_two.created_by,
        answers=[
            {"clarification_id": rights_two["clarification_id"], "decision": "confirm"},
            {
                "clarification_id": conflict_two["clarification_id"],
                "decision": "confirm", "answer_value": "550", "unit": "ml",
            },
            {"clarification_id": unknown_two["clarification_id"], "decision": "unknown"},
        ],
    )
    assert first["confirmation_version"]["hash"] != second["confirmation_version"]["hash"]


def test_confirmation_successors_require_exact_latest_parent_and_actor(db_session, client, auth_headers, tmp_path):
    run, truth = _truth(db_session, client, auth_headers, tmp_path)
    cycle_one = build_seller_confirmation_plan(db_session, run=run, truth_reference=truth["truth_version"])
    rights, conflict, unknown = cycle_one["clarifications"]
    first = apply_seller_confirmation_cycle(
        db_session,
        run=run,
        plan=cycle_one,
        actor_id=run.created_by,
        answers=[
            {"clarification_id": rights["clarification_id"], "decision": "confirm"},
            {"clarification_id": conflict["clarification_id"], "decision": "skip"},
            {"clarification_id": unknown["clarification_id"], "decision": "confirm", "answer_value": "seller value"},
        ],
    )
    cycle_two = {
        "schema_version": cycle_one["schema_version"],
        "truth_version": cycle_one["truth_version"],
        "run_identity": cycle_one["run_identity"],
        "confirmation_cycle": 2,
        "confirmation_required": True,
        "clarifications": first["clarifications"],
        "unresolved_queue": first["unresolved_queue"],
        "parent_confirmation_version": first["confirmation_version"],
    }
    with pytest.raises(SellerConfirmationContractError, match="Only the actor"):
        apply_seller_confirmation_cycle(
            db_session, run=run, plan=cycle_two, actor_id="00000000-0000-0000-0000-000000000099", answers=[]
        )

    invalid_parent = deepcopy(cycle_two)
    invalid_parent["parent_confirmation_version"]["hash"] = "0" * 64
    with pytest.raises(SellerConfirmationContractError, match="exact latest parent"):
        apply_seller_confirmation_cycle(
            db_session, run=run, plan=invalid_parent, actor_id=run.created_by, answers=[]
        )

    second = apply_seller_confirmation_cycle(
        db_session, run=run, plan=cycle_two, actor_id=run.created_by, answers=[]
    )
    first_row = db_session.query(SellerConfirmationVersion).filter_by(id=first["confirmation_version"]["id"]).one()
    second_row = db_session.query(SellerConfirmationVersion).filter_by(id=second["confirmation_version"]["id"]).one()
    assert second_row.confirmation_cycle == 2
    assert (second_row.parent_version_id, second_row.parent_version, second_row.parent_version_hash) == (
        first_row.id, first_row.version, first_row.canonical_hash
    )
    assert second_row.confirmed_fact_refs_json == first_row.confirmed_fact_refs_json
    assert second_row.rights_confirmations_json == first_row.rights_confirmations_json

    stale = deepcopy(cycle_two)
    stale["confirmation_cycle"] = 3
    with pytest.raises(SellerConfirmationContractError, match="latest parent"):
        apply_seller_confirmation_cycle(db_session, run=run, plan=stale, actor_id=run.created_by, answers=[])


def test_confirmation_rejects_truth_created_by_a_different_run_in_same_project(
    db_session, client, auth_headers, tmp_path,
):
    run_one, truth_one = _truth(db_session, client, auth_headers, tmp_path)
    run_two_id = str(uuid.uuid4())
    run_two = AgentRun(
        id=run_two_id,
        workspace_id=run_one.workspace_id,
        project_id=run_one.project_id,
        mode="lg12i_intake",
        status="awaiting_review",
        current_stage="seller_confirmation",
        input_snapshot=dict(run_one.input_snapshot or {}),
        outputs_json={},
        cost_approval_status="not_required",
        graph_thread_id=run_two_id,
        created_by=run_one.created_by,
    )
    db_session.add(run_two)
    db_session.flush()
    first_truth = db_session.query(ProductTruthVersion).filter_by(
        id=truth_one["truth_version"]["id"]
    ).one()
    first_source = db_session.query(ProductSourceSnapshotVersion).filter_by(
        id=first_truth.source_snapshot_version_id
    ).one()
    second_source = create_product_source_snapshot_version(
        db_session,
        workspace_id=run_two.workspace_id,
        project_id=run_two.project_id,
        creator_run_id=run_two.id,
        created_by=run_two.created_by,
        input_mode=first_source.input_mode,
        source_refs=list(first_source.source_refs_json),
        provenance=dict(first_source.provenance_json),
        rights=dict(first_source.rights_json),
        source_fidelity=dict(first_source.source_fidelity_json),
    )
    db_session.commit(); db_session.refresh(second_source)
    truth_two = normalize_product_truth_from_source_snapshot(
        db_session,
        run=run_two,
        source_reference={"id": second_source.id, "version": second_source.version, "hash": second_source.canonical_hash},
    )
    other_plan = build_seller_confirmation_plan(
        db_session, run=run_two, truth_reference=truth_two["truth_version"],
    )
    injected = deepcopy(other_plan)
    injected["run_identity"] = {"run_id": run_one.id, "thread_id": run_one.graph_thread_id or run_one.id}

    with pytest.raises(SellerConfirmationContractError, match="intake run/thread"):
        apply_seller_confirmation_cycle(
            db_session, run=run_one, plan=injected, actor_id=run_one.created_by, answers=[],
        )
    assert db_session.query(SellerConfirmationVersion).filter_by(creator_run_id=run_one.id).count() == 0


def test_prohibited_claim_cannot_be_confirmed_and_forbidden_provenance_cannot_be_attested_owned(db_session, client, auth_headers, tmp_path):
    prohibited_question = {
        "clarification_id": "clarification:prohibited-price-advantage",
        "clarification_hash": "a" * 64,
        "type": "high_risk_claim",
        "allowed_options": [],
    }
    with pytest.raises(SellerConfirmationContractError, match="cannot be approved"):
        _validate_confirmation_answer(
            {"clarification_id": prohibited_question["clarification_id"], "decision": "confirm"},
            prohibited_question,
        )

    run, truth = _truth(db_session, client, auth_headers, tmp_path, forbidden_source=True)
    plan = build_seller_confirmation_plan(db_session, run=run, truth_reference=truth["truth_version"])
    rights = next(question for question in plan["clarifications"] if question["type"] == "rights")
    # A valid cycle records the explicit provenance block rather than allowing
    # an attestation to recategorize a supplier source as seller-owned.
    result = apply_seller_confirmation_cycle(
        db_session, run=run, plan=plan, actor_id=run.created_by,
        answers=[{"clarification_id": rights["clarification_id"], "decision": "confirm"}],
    )
    confirmation = db_session.query(SellerConfirmationVersion).filter_by(id=result["confirmation_version"]["id"]).one()
    assert confirmation.rights_confirmations_json[0]["status"] == "provenance_blocked"
    assert confirmation.rights_confirmations_json[0]["final_use_status"] == "not_approved"


def test_confirmation_answer_requirements_follow_the_frozen_clarification_type(
    db_session, client, auth_headers, tmp_path,
):
    run, truth = _truth(db_session, client, auth_headers, tmp_path)
    plan = build_seller_confirmation_plan(db_session, run=run, truth_reference=truth["truth_version"])
    rights, conflict, unknown = plan["clarifications"]

    assert _validate_confirmation_answer(
        {"clarification_id": rights["clarification_id"], "decision": "confirm"}, rights,
    )["selected_observation_id"] is None
    assert _validate_confirmation_answer(
        {"clarification_id": rights["clarification_id"], "decision": "reject"}, rights,
    )["decision"] == "reject"
    # Empty optional IDs from a resume serializer normalize to omission.
    assert _validate_confirmation_answer(
        {"clarification_id": rights["clarification_id"], "decision": "confirm", "selected_observation_id": ""},
        rights,
    )["selected_observation_id"] is None
    with pytest.raises(SellerConfirmationContractError, match="does not allow an observation"):
        _validate_confirmation_answer(
            {"clarification_id": rights["clarification_id"], "decision": "confirm", "selected_observation_id": "injected"},
            rights,
        )

    assert _validate_confirmation_answer(
        {
            "clarification_id": conflict["clarification_id"], "decision": "confirm",
            "selected_observation_id": conflict["allowed_options"][0]["observation_id"],
        },
        conflict,
    )["selected_observation_id"] == conflict["allowed_options"][0]["observation_id"]
    with pytest.raises(SellerConfirmationContractError, match="requires an observation selection"):
        _validate_confirmation_answer(
            {"clarification_id": conflict["clarification_id"], "decision": "confirm"}, conflict,
        )
    with pytest.raises(SellerConfirmationContractError, match="not part of the pending"):
        _validate_confirmation_answer(
            {"clarification_id": conflict["clarification_id"], "decision": "confirm", "selected_observation_id": "other-truth"},
            conflict,
        )
    assert _validate_confirmation_answer(
        {"clarification_id": conflict["clarification_id"], "decision": "confirm", "answer_value": "550", "unit": "ml"},
        conflict,
    )["selected_observation_id"] is None
    assert _validate_confirmation_answer(
        {"clarification_id": unknown["clarification_id"], "decision": "confirm", "answer_value": "600", "unit": "mAh"},
        unknown,
    )["answer_value"] == "600"
    generic = {
        "clarification_id": "clarification:generic", "clarification_hash": "b" * 64,
        "type": "fact_candidate", "allowed_answer_type": "confirm_or_reject", "allowed_options": [],
    }
    assert _validate_confirmation_answer(
        {"clarification_id": generic["clarification_id"], "decision": "confirm"}, generic,
    )["selected_observation_id"] is None


def test_public_resume_returns_structured_review_error_for_malformed_confirmation_answer(
    db_session, client, auth_headers, tmp_path, lg12i_runtime,
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = create_manual_input_artifact(
        db_session,
        workspace_id=source_run.workspace_id,
        project_id=source_run.project_id,
        created_by=source_run.created_by,
        raw_body="bounded seller source",
        source_metadata=_metadata(),
    )
    db_session.commit(); db_session.refresh(artifact)
    started = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json={
            "input_mode": "manual",
            "source_payload_refs": [{
                "id": artifact.id, "kind": "manual_payload_artifact", "version": artifact.version, "hash": artifact.content_hash,
            }],
            "requested_generation_mode": "quick", "target_channels": ["smartstore"],
        },
    )
    state = started.json()
    plan = state["values"]["intake"]["seller_confirmation"]
    conflict = next(item for item in plan["clarifications"] if item["type"] == "fact_conflict")
    response = client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume",
        headers=auth_headers,
        json={
            "thread_id": state["thread_id"],
            "response": {
                "schema_version": "lg12i-v1", "review_stage": "seller_confirmation", "decision": "submit",
                "confirmation_request_hash": plan["resume_request_hash"],
                "confirmation_answers": [{"clarification_id": conflict["clarification_id"], "decision": "confirm"}],
            },
        },
    )
    assert response.status_code == 409
    assert "requires an observation selection" in response.json()["detail"]
    assert db_session.query(SellerConfirmationVersion).filter_by(creator_run_id=state["run_id"]).count() == 0


def test_public_langgraph_resume_persists_one_bounded_confirmation_cycle(
    db_session, client, auth_headers, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = create_manual_input_artifact(
        db_session,
        workspace_id=source_run.workspace_id,
        project_id=source_run.project_id,
        created_by=source_run.created_by,
        raw_body="bounded seller source",
        source_metadata=_metadata(),
    )
    db_session.commit(); db_session.refresh(artifact)
    started = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json={
            "input_mode": "manual",
            "source_payload_refs": [{
                "id": artifact.id, "kind": "manual_payload_artifact", "version": artifact.version, "hash": artifact.content_hash,
            }],
            "requested_generation_mode": "quick",
            "target_channels": ["smartstore"],
        },
    )
    assert started.status_code == 201, started.text
    state = started.json()
    assert state["current_stage"] == "seller_confirmation"
    confirmation_plan = state["values"]["intake"]["seller_confirmation"]
    questions = confirmation_plan["clarifications"]
    answers = []
    for question in questions:
        answer = {"clarification_id": question["clarification_id"], "decision": "unknown"}
        if question["type"] == "rights":
            answer["decision"] = "confirm"
        elif question["type"] in {"fact_conflict", "identity_conflict"}:
            answer = {
                "clarification_id": question["clarification_id"], "decision": "confirm",
                "selected_observation_id": question["allowed_options"][0]["observation_id"],
            }
        answers.append(answer)
    first_resume_payload = {
        "thread_id": state["run_id"],
        "response": {
            "schema_version": "lg12i-v1", "review_stage": "seller_confirmation",
            "decision": "submit", "confirmation_request_hash": confirmation_plan["resume_request_hash"],
            "confirmation_answers": answers,
        },
    }
    resumed = client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume",
        headers=auth_headers,
        json=first_resume_payload,
    )
    assert resumed.status_code == 200, resumed.text
    assert db_session.query(SellerConfirmationVersion).filter_by(creator_run_id=state["run_id"]).count() == 1
    assert resumed.json()["values"]["intake"]["seller_confirmation"]["confirmation_cycle"] == 2

    # The original browser request may arrive again after the graph has moved
    # to cycle 2.  It must return the durable state without applying cycle 2.
    replayed = client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume", headers=auth_headers, json=first_resume_payload,
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["values"]["intake"]["seller_confirmation"]["confirmation_cycle"] == 2
    assert db_session.query(SellerConfirmationVersion).filter_by(creator_run_id=state["run_id"]).count() == 1

    changed = deepcopy(first_resume_payload)
    changed["response"]["confirmation_answers"] = list(reversed(answers))
    if changed["response"]["confirmation_answers"]:
        changed["response"]["confirmation_answers"][0] = {
            **changed["response"]["confirmation_answers"][0], "decision": "reject",
        }
    changed_response = client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume", headers=auth_headers, json=changed,
    )
    assert changed_response.status_code == 409

    # Simulate a process stop after the second interrupt checkpoint but before
    # the durable SQL projection is written.  The public resume endpoint is
    # the recovery entrypoint and must restore the exact pending cycle.
    persisted = db_session.query(AgentRun).filter_by(id=state["run_id"]).one()
    expected_intake = deepcopy(resumed.json()["values"]["intake"])
    persisted.outputs_json = {
        key: value for key, value in persisted.outputs_json.items()
        if key not in {"langgraph_intake", "langgraph_review"}
    }
    persisted.status = "running"
    db_session.add(persisted)
    db_session.commit()

    recovered = client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume", headers=auth_headers, json=first_resume_payload,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "awaiting_review"
    assert recovered.json()["values"]["intake"] == expected_intake
    assert recovered.json()["values"]["intake"]["seller_confirmation"]["confirmation_cycle"] == 2


def test_public_terminal_rights_confirmation_replays_when_optional_fields_are_omitted(
    db_session, client, auth_headers, tmp_path, lg12i_runtime,
):
    """Browser omission and checkpoint empty-string serialization share one replay ID."""

    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = create_manual_input_artifact(
        db_session,
        workspace_id=source_run.workspace_id,
        project_id=source_run.project_id,
        created_by=source_run.created_by,
        raw_body="rights-only seller source",
        source_metadata={
            "manual_payload_schema_version": "lg12i-manual-input-artifact-v1",
            "seller_entered_fields": [{
                "field_id": "product_identity", "classification": "fact_candidate",
                "label": "product", "value": "fan",
            }],
            "unknown_fact_field_ids": [],
            "conflict_fact_candidates": [],
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
            "requested_generation_mode": "quick",
            "target_channels": ["smartstore"],
        },
    )
    assert started.status_code == 201, started.text
    state = started.json()
    plan = state["values"]["intake"]["seller_confirmation"]
    rights = plan["clarifications"]
    assert len(rights) == 1 and rights[0]["type"] == "rights"
    payload = {
        "thread_id": state["run_id"],
        "response": {
            "schema_version": "lg12i-v1", "review_stage": "seller_confirmation",
            "decision": "submit", "confirmation_request_hash": plan["resume_request_hash"],
            # Deliberately omit optional answer_value/unit/selected_observation_id,
            # exactly as the production UI does for a rights decision.
            "confirmation_answers": [{
                "clarification_id": rights[0]["clarification_id"], "decision": "confirm",
            }],
        },
    }
    first = client.post(f"/api/v1/graph-runs/{state['run_id']}/resume", headers=auth_headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "completed"
    assert db_session.query(SellerConfirmationVersion).filter_by(creator_run_id=state["run_id"]).count() == 1

    replay = client.post(f"/api/v1/graph-runs/{state['run_id']}/resume", headers=auth_headers, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["current_stage"] == first.json()["current_stage"]
    assert db_session.query(SellerConfirmationVersion).filter_by(creator_run_id=state["run_id"]).count() == 1

    answer = payload["response"]["confirmation_answers"]
    assert seller_confirmation_answer_bundle_hash(decision="submit", answers=answer) == (
        seller_confirmation_answer_bundle_hash(
            decision="submit",
            answers=[{**answer[0], "answer_value": "", "unit": "", "selected_observation_id": ""}],
        )
    )
