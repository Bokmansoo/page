from __future__ import annotations

from contextlib import contextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.schemas import CopySetOutput, DetailPagePlanOutput, SalesStrategyOutput, VisualPlanOutput
from src.db.models import AgentRun, Asset, FactSnapshot, ProductProject
from src.schemas.planning_draft import PlanningDraftSchema
from src.services import langgraph_commerce_planning_service as commerce


@pytest.fixture
def auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


@pytest.fixture
def langgraph_runtime(monkeypatch):
    from src.services import langgraph_run_service
    from src.agents.langgraph_runtime import build_lg3_compiled_graph

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    # LG-3 characterization remains focused on the Commerce Planning
    # subgraph; LG-4 adds seller interrupts to the production compiled graph.
    monkeypatch.setattr(langgraph_run_service, "build_lg5_compiled_graph", build_lg3_compiled_graph)
    return saver


def _create_graph_run(client, headers, db_session) -> AgentRun:
    created = client.post("/api/agent-runs", headers=headers, json={
        "product_name": "LG3 planning pillow", "description": "Unconfirmed 999 hour claim must not enter copy",
    }).json()
    run = db_session.query(AgentRun).filter(AgentRun.id == created["id"]).one()
    # LG-2 creates the approved snapshot from seller facts. Explicit seller
    # facts make this a real evidence-board path rather than a mocked payload.
    from src.db.models import FactEvidence, ProductFact
    fact = ProductFact(project_id=run.project_id, fact_text="Rated input: DC 5V 2A", source_text="DC 5V 2A",
                       verification_status="seller_confirmed", needs_review=False, field_key="rated_input",
                       fact_category="electrical", normalized_value="DC 5V 2A", scope="product")
    # LG-3's ScenePlan must have a real seller-owned reference asset for every
    # scene; a reference-only or synthetic identifier is not sufficient.
    asset = Asset(
        project_id=run.project_id, source_type="uploaded", usage_status="seller_owned",
        filename="lg3-main.jpg", file_path="/tmp/lg3-main.jpg", mime_type="image/jpeg", file_size=10,
        asset_role="product_main", quality_status="usable", identity_status="confirmed", is_representative=True,
    )
    db_session.add_all([fact, asset])
    db_session.flush()
    db_session.add(FactEvidence(fact_id=fact.id, source_type="seller_input", original_text="DC 5V 2A"))
    db_session.commit()
    return run


def _start(client, headers, run: AgentRun):
    response = client.post(f"/api/v1/graph-runs/{run.id}/start", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_lg3_actual_graph_uses_four_planning_agents_and_writes_ui_draft(client, auth_headers, db_session, langgraph_runtime):
    run = _create_graph_run(client, auth_headers, db_session)
    started = _start(client, auth_headers, run)

    values = started["values"]
    assert started["status"] == "completed"
    assert [event["stage"] for event in values["events"]][-5:] == [
        "sales_strategy", "page_planning", "copywriting", "visual_planning", "finalize_run",
    ]
    assert set(values["commerce"]) == {"sales_strategy", "page_planning", "copywriting", "visual_planning"}
    assert "hero_title" not in repr(values["commerce"])
    assert "Rated input: DC 5V 2A" not in repr(values["commerce"])

    db_session.expire_all()
    run = db_session.query(AgentRun).filter(AgentRun.id == run.id).one()
    _, _, discovery_contract = commerce._input_contract(run, db_session)
    assert all(set(value) == {"artifact_hash", "schema_version"} for value in discovery_contract.values())
    assert "Rated input: DC 5V 2A" not in repr(discovery_contract)
    outputs = commerce.read_commerce_planning_outputs(run)
    assert SalesStrategyOutput.model_validate(outputs["sales_strategy"])
    assert DetailPagePlanOutput.model_validate(outputs["page_planning"])
    assert CopySetOutput.model_validate(outputs["copywriting"])
    assert VisualPlanOutput.model_validate(outputs["visual_planning"])
    assert "999" not in repr(outputs["copywriting"])
    assert outputs["sales_strategy"]["candidates"]
    assert outputs["sales_strategy"]["selected_candidate_id"]
    assert outputs["sales_strategy"]["selection_reason"]
    assert all(section["purpose"] and section["source_fact_ids"] for section in outputs["page_planning"]["sections"])
    assert outputs["copywriting"]["section_fact_ids"]["feature_1"]
    artifacts = run.outputs_json[commerce.COMMERCE_ARTIFACT_KEY]
    copy_metadata = artifacts["copywriting"]["metadata"]
    assert copy_metadata["copy_provenance"]
    assert all("classification" in item for item in copy_metadata["copy_provenance"].values())
    scenes = artifacts["visual_planning"]["metadata"]["scene_plan"]
    assert scenes and all({"objective", "source_fact_ids", "reference_asset_ids", "generation_mode", "requested_output"} <= set(scene) for scene in scenes)
    assert all(scene["source_fact_ids"] and scene["reference_asset_ids"] for scene in scenes)
    snapshot = db_session.query(FactSnapshot).filter(FactSnapshot.id == values["discovery"]["fact_snapshot"]["id"]).one()
    assert all(set(scene["source_fact_ids"]) <= {fact["id"] for fact in snapshot.facts_json} for scene in scenes)

    project = db_session.query(ProductProject).filter(ProductProject.id == run.project_id).one()
    draft = PlanningDraftSchema.model_validate(project.planning_draft).model_dump()
    assert draft["fact_snapshot_id"] == values["discovery"]["fact_snapshot"]["id"]
    assert draft["cards"]
    response = client.get(f"/api/v1/projects/{run.project_id}/planning-draft", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["fact_snapshot_hash"] == draft["fact_snapshot_hash"]


def test_lg3_mock_artifacts_are_reproducible_for_same_snapshot_and_prompt(client, auth_headers, db_session, langgraph_runtime):
    run = _create_graph_run(client, auth_headers, db_session)
    _start(client, auth_headers, run)
    db_session.expire_all()
    run = db_session.query(AgentRun).filter(AgentRun.id == run.id).one()
    first_hash = run.outputs_json[commerce.COMMERCE_ARTIFACT_KEY]["sales_strategy"]["metadata"]["artifact_hash"]
    delta = commerce.run_sales_strategy(run_id=run.id, project_id=run.project_id, mode="mock")
    assert delta["sales_strategy"]["artifact_hash"] == first_hash
    # Rebuild the downstream chain after an explicit Sales Strategy rerun.
    commerce.run_page_planning(run_id=run.id, project_id=run.project_id, mode="mock")
    commerce.run_copywriting(run_id=run.id, project_id=run.project_id, mode="mock")
    first_visual = commerce.run_visual_planning(run_id=run.id, project_id=run.project_id, mode="mock")
    second_visual = commerce.run_visual_planning(run_id=run.id, project_id=run.project_id, mode="mock")
    assert second_visual["visual_planning"]["artifact_hash"] == first_visual["visual_planning"]["artifact_hash"]


def test_lg3_records_invalidation_when_approved_fact_snapshot_changes(client, auth_headers, db_session, langgraph_runtime):
    run = _create_graph_run(client, auth_headers, db_session)
    _start(client, auth_headers, run)
    db_session.expire_all()
    run = db_session.query(AgentRun).filter(AgentRun.id == run.id).one()
    original = db_session.query(FactSnapshot).filter(FactSnapshot.id == run.input_snapshot["approved_fact_snapshot_id"]).one()
    replacement = FactSnapshot(project_id=run.project_id, purpose="langgraph_discovery", snapshot_hash="different-snapshot-hash", facts_json=original.facts_json)
    db_session.add(replacement)
    db_session.flush()
    run.input_snapshot = {**run.input_snapshot, "approved_fact_snapshot_id": replacement.id, "approved_fact_snapshot_hash": replacement.snapshot_hash}
    db_session.commit()
    commerce.run_sales_strategy(run_id=run.id, project_id=run.project_id, mode="mock")
    db_session.expire_all()
    run = db_session.query(AgentRun).filter(AgentRun.id == run.id).one()
    assert run.outputs_json["langgraph_commerce_invalidations"][-1]["reason"] == "approved_fact_snapshot_changed"
    artifacts = run.outputs_json[commerce.COMMERCE_ARTIFACT_KEY]
    assert set(artifacts) == {"sales_strategy"}
    project = db_session.query(ProductProject).filter(ProductProject.id == run.project_id).one()
    assert project.planning_draft["status"] == "stale"
    assert all(card["facts_stale"] for card in project.planning_draft["cards"])


def test_lg3_blocks_contextless_numbers_and_competitive_superiority_claims():
    base = {
        field: "일반 안내 문구"
        for field in CopySetOutput.model_fields
        if field not in {"schema_version", "section_fact_ids", "copy_provenance"}
    }
    facts = [{"id": "rated-input", "fact_text": "정격 입력: DC 5V 2A", "value": "DC 5V 2A", "unit": None}]
    base["feature_1_body"] = "5시간 연속 사용"
    base["hero_title"] = "경쟁사보다 뛰어난 업계 최고 제품"

    cleaned, provenance = commerce._safe_copy(base, facts)

    assert cleaned["feature_1_body"] == "판매자 확인 정보 기준으로 안내합니다."
    assert cleaned["hero_title"] == "판매자 확인 정보 기준으로 안내합니다."
    assert provenance["feature_1_body"]["classification"] == "blocked_unsupported_claim"
    assert provenance["hero_title"]["classification"] == "blocked_unsupported_claim"
