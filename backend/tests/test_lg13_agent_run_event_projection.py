from __future__ import annotations

import pytest

from src.db.models import AgentRun, AgentRunEvent, Brand, ProductProject
from src.services.langgraph_run_service import AgentRunEventJournal, AgentRunGraphProjector


@pytest.mark.parametrize("mode", ["owned_product_url", "photo_only", "manual"])
def test_lg13_projects_each_intake_mode_as_reference_only_event(db_session, mode):
    brand = Brand(id=f"brand-{mode}", workspace_id=f"workspace-{mode}", name="LG13")
    project = ProductProject(id=f"project-{mode}", workspace_id=brand.workspace_id, brand_id=brand.id, name="LG13")
    run = AgentRun(
        id=f"run-{mode}", workspace_id=brand.workspace_id, project_id=project.id, created_by=f"user-{mode}",
        graph_thread_id=f"run-{mode}", mode="lg12i_intake", status="running", current_stage="intake",
        input_snapshot={"unified_product_intake": {"input_mode": mode}}, outputs_json={}, cost_approval_status="not_required",
    )
    db_session.add_all([brand, project, run])
    db_session.commit()

    source_key = {"owned_product_url": "owned_url_source", "photo_only": "photo_source", "manual": "manual_source"}[mode]
    AgentRunGraphProjector.apply_node_update(
        run,
        db_session,
        {
            "events": [{"stage": "source_snapshot_ready", "status": "completed"}],
            "intake": {source_key: {"source_snapshot": {"id": "source-id", "version": 1, "hash": "a" * 64}}},
        },
    )
    event = db_session.query(AgentRunEvent).filter_by(run_id=run.id, event_type="source_snapshot_ready").one()
    assert event.event_type == "source_snapshot_ready"
    assert event.payload_json["input_mode"] == mode
    assert event.payload_json["source_fidelity"] == {"owned_product_url": "captured", "photo_only": "ready", "manual": "seller_entered"}[mode]
    assert event.payload_json["references"] == {"source_snapshot": {"id": "source-id", "version": 1, "hash": "a" * 64}}
    assert "raw_body" not in str(event.payload_json)


def test_lg13_event_payload_rejects_unallowlisted_content():
    with pytest.raises(ValueError, match="allowlisted"):
        AgentRunEventJournal.validate_payload(
            "graph_node_updated",
            {
                "stage": "intake", "status": "running", "node_status": "completed", "input_mode": "manual", "source_fidelity": "unknown",
                "references": {}, "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
                "raw_provider_payload": {"secret": "must not persist"},
            },
        )


@pytest.mark.parametrize(
    ("event", "intake", "expected"),
    [
        ({"stage": "manual_input_adapter", "status": "running"}, {"input_hash": "a" * 64}, "intake_envelope_accepted"),
        ({"stage": "source_snapshot_ready", "status": "completed"}, {"manual_source": {"source_snapshot": {"id": "source", "version": 1, "hash": "a" * 64}}}, "source_snapshot_ready"),
        ({"stage": "seller_confirmation_required", "status": "running"}, {"product_truth": {"truth_version": {"id": "truth", "version": 1, "hash": "b" * 64}}, "seller_confirmation": {"confirmation_required": True}}, "truth_review_required"),
        ({"stage": "seller_confirmation_not_required", "status": "running"}, {"product_truth": {"truth_version": {"id": "truth", "version": 1, "hash": "b" * 64}}}, "truth_ready"),
        ({"stage": "seller_confirmation_required", "status": "running"}, {}, "seller_confirmation_pending"),
        ({"stage": "confirmation_ready", "status": "running"}, {"seller_confirmation": {"confirmation_version": {"id": "confirmation", "version": 1, "hash": "c" * 64}}}, "seller_confirmation_resolved"),
        ({"stage": "product_creative_brief", "status": "running"}, {"creative_brief": {"brief_version": {"id": "brief", "version": 1, "hash": "d" * 64}}}, "creative_brief_ready"),
        ({"stage": "master_ready", "status": "completed"}, {"commerce_creative_master": {"master_version": {"id": "master", "version": 1, "hash": "e" * 64}}}, "commerce_creative_master_ready"),
    ],
)
def test_lg13_maps_existing_lg12i_lifecycle_to_bounded_event_taxonomy(event, intake, expected):
    run = AgentRun(id="taxonomy-run", input_snapshot={"unified_product_intake": {"input_mode": "manual"}})
    event_type, payload = AgentRunEventJournal._payload_for_update(run, {"intake": intake}, event)
    assert event_type == expected
    AgentRunEventJournal.validate_payload(event_type, payload)
