from __future__ import annotations

from contextlib import contextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.nodes.input_router.schema import AgentOutputSchema as InputRouterOutput
from src.agents.nodes.reference_analysis.schema import AgentOutputSchema as ReferenceAnalysisOutput
from src.agents.nodes.source_collection.schema import AgentOutputSchema as SourceCollectionOutput
from src.agents.schemas import ProductUnderstandingOutput
from src.db.models import AgentRun, AgentRunStep, Asset, FactEvidence, ProductFact, SourceCapture
from src.services import langgraph_discovery_service as discovery_service


@pytest.fixture
def auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


@pytest.fixture
def lg2_runtime(monkeypatch):
    """Use the actual LG-2 nodes/domain services with only the saver replaced."""

    from src.services import langgraph_run_service
    from src.agents.langgraph_runtime import build_lg2_compiled_graph

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    # Characterize LG-2 independently; LG-4 adds human-review interrupts to
    # the production rollout graph.
    monkeypatch.setattr(langgraph_run_service, "build_lg5_compiled_graph", build_lg2_compiled_graph)
    return saver


def _create_run(client, auth_headers, db_session, *, with_url: bool = False) -> AgentRun:
    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "경추 마사지 베개", "description": "판매자 제공 제품 설명"},
    ).json()
    run = db_session.query(AgentRun).filter(AgentRun.id == created["id"]).one()
    asset = Asset(
        project_id=run.project_id,
        source_type="self_shot",
        usage_status="seller_owned",
        filename="seller-neck-pillow.jpg",
        file_path="/uploads/seller-neck-pillow.jpg",
        mime_type="image/jpeg",
        file_size=1,
        asset_role="product_main",
        identity_status="confirmed",
        quality_status="usable",
        classification_version=2,
        is_representative=True,
    )
    db_session.add(asset)
    db_session.flush()
    run.input_snapshot = {**run.input_snapshot, "asset_ids": [asset.id]}
    if with_url:
        url = "https://example.test/supplier"
        run.input_snapshot = {**run.input_snapshot, "product_url": url}
        db_session.add(SourceCapture(
            project_id=run.project_id,
            url=url,
            platform="example",
            source_role="reference",
            collection_status="failed",
            failure_code="blocked_or_forbidden",
            error_message="blocked",
        ))
    fact = ProductFact(
        project_id=run.project_id,
        fact_text="정격 입력: DC 5V 2A",
        source_text="DC 5V 2A",
        verification_status="seller_confirmed",
        needs_review=False,
        field_key="rated_input",
        fact_category="electrical",
        normalized_value="DC 5V 2A",
        scope="product",
    )
    db_session.add(fact)
    db_session.flush()
    db_session.add(FactEvidence(
        fact_id=fact.id,
        source_type="seller_input",
        original_text="DC 5V 2A",
    ))
    db_session.commit()
    db_session.refresh(run)
    return run


def _start_graph(client, auth_headers, run: AgentRun, db_session=None):
    response = client.post(f"/api/v1/graph-runs/{run.id}/start", headers=auth_headers)
    if response.status_code != 200 and db_session is not None:
        db_session.expire_all()
        failed = db_session.query(AgentRun).filter(AgentRun.id == run.id).one()
        pytest.fail(f"{response.text}; graph error: {failed.error_log}")
    assert response.status_code == 200, response.text
    return response.json()


def test_lg2_actual_domain_path_registers_nodes_preserves_schemas_and_keeps_facts_out_of_state(
    client, auth_headers, db_session, lg2_runtime,
):
    run = _create_run(client, auth_headers, db_session, with_url=False)
    started = _start_graph(client, auth_headers, run, db_session)

    values = started["values"]
    assert values["discovery"]["reference_analysis"]["skipped"] is True
    assert values["discovery"]["reference_analysis"]["skip_reason"] == "no_reference_url"
    assert values["discovery"]["fact_snapshot"]["id"]
    assert "정격 입력: DC 5V 2A" not in repr(values)
    assert "evidence" not in repr(values).lower()

    db_session.refresh(run)
    artifacts = run.outputs_json["langgraph_discovery_artifacts"]
    input_output = InputRouterOutput.model_validate(artifacts["input_router"]["output"]).model_dump()
    source_output = SourceCollectionOutput.model_validate(artifacts["source_collection"]["output"]).model_dump()
    product_output = ProductUnderstandingOutput.model_validate(artifacts["product_understanding"]["output"]).model_dump()
    reference_output = ReferenceAnalysisOutput.model_validate(artifacts["reference_analysis"]["output"]).model_dump()
    assert all(artifacts[stage]["metadata"]["prompt_hash"] for stage in artifacts)
    assert input_output["input_type"] == "mixed"
    assert source_output["uploaded_images"][0]["source_type"] == "self_shot"
    assert product_output["verified_facts"] == ["정격 입력: DC 5V 2A"]
    assert reference_output["skipped"] is True
    assert {step.stage for step in db_session.query(AgentRunStep).filter(AgentRunStep.run_id == run.id)} >= {
        "input_router", "source_collection", "product_understanding", "reference_analysis"
    }


def test_lg2_failed_link_continues_with_upload_and_runs_reference_node(
    client, auth_headers, db_session, lg2_runtime,
):
    run = _create_run(client, auth_headers, db_session, with_url=True)
    started = _start_graph(client, auth_headers, run, db_session)

    discovery = started["values"]["discovery"]
    assert discovery["source_collection"]["routing_decision"] == "continue_with_direct_uploads"
    # URL presence chooses the Reference Analysis edge. The node then records
    # the capture failure honestly instead of pretending it analysed content.
    assert discovery["reference_analysis"]["skipped"] is True
    assert discovery["reference_analysis"]["skip_reason"] == "collection_failed"
    assert "product_understanding" in [event["stage"] for event in started["values"]["events"]]


def test_lg2_real_provider_uses_existing_prompt_and_same_schema_contract(monkeypatch):
    calls = []

    class FakeProvider:
        def generate_json(self, request):
            calls.append(request)
            return {
                "provider": "fake",
                "model": "fake-model",
                "content": {
                    "product_type": "마사지 베개",
                    "target_customer": "검토 고객",
                    "verified_facts": ["근거 없는 내용"],
                    "assumptions": [],
                    "verification_required": [],
                    "forbidden_claims": [],
                    "buyer_problem": "불편함",
                    "risk_notes": [],
                },
                "token_usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "cost": 0,
            }

    monkeypatch.setattr("src.services.llm_router.get_text_provider_by_settings", lambda: FakeProvider())
    facts = [{"id": "fact-1", "fact_text": "정격 입력: DC 5V 2A"}]
    mock_output, _ = discovery_service._product_output(
        mode="mock", input_snapshot={"product_name": "마사지 베개"}, facts=facts,
    )
    real_output, metadata = discovery_service._product_output(
        mode="real", input_snapshot={"product_name": "마사지 베개"}, facts=facts,
    )

    assert calls and "상품 이해 에이전트" in calls[0].system_prompt
    assert ProductUnderstandingOutput.model_validate(mock_output).model_dump().keys() == ProductUnderstandingOutput.model_validate(real_output).model_dump().keys()
    assert real_output["verified_facts"] == ["정격 입력: DC 5V 2A"]
    assert metadata["provider"] == "fake"


def test_lg2_product_brief_adapter_reads_same_evidence_board_contract(
    client, auth_headers, db_session, lg2_runtime,
):
    run = _create_run(client, auth_headers, db_session, with_url=False)
    _start_graph(client, auth_headers, run, db_session)
    db_session.refresh(run)

    compatible = discovery_service.compatible_product_brief(run, db_session)
    brief = compatible["product_brief"]
    assert any(item["text"] == "정격 입력: DC 5V 2A" for item in brief["confirmed_facts"])
    assert brief["safe_reference_assets"][0]["id"]
    assert compatible["discovery_outputs"]["product_understanding"]["verified_facts"] == ["정격 입력: DC 5V 2A"]
