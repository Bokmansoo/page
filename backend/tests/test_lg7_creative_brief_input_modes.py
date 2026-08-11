import io
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver, MemorySaver
from sqlalchemy import create_engine, inspect, text

from src.agents.langgraph_runtime import (
    _lg4_wait_for_seller_review, _lg7_creative_brief_compiler, build_lg7_compiled_graph,
    checkpoint_safe_input_snapshot,
)
from src.db.models import (
    AgentRun, Asset, Brand, FactSnapshot, ProductCreativeBriefVersion, ProductFact, ProductProject,
    ReferenceInputVersion, ReviewInsightVersion, User, WorkflowGateEvent, Workspace,
    WorkspaceMember,
)
from src.services.auth_service import DEV_USER_ID, DEV_WORKSPACE_ID
from src.services.creative_brief_service import (
    CreativeBriefInputError, analyze_reference, compile_creative_brief, create_creative_direction,
    create_reference_input, create_review_input, normalize_interaction_mode,
    parse_review_bytes, project_intelligence,
)
from src.services.creative_brief_llm_service import (
    CreativeBriefLLMError,
    generate_structured_creative_brief,
)
from src.services.langgraph_discovery_service import langgraph_execution_session
from src.services.prompt_intelligence_service import classify_category, compile_for_run, seed_prompt_packs
from src.services.provider_adapters import MockTextProvider

HEADERS = {"X-Mock-User-Id": DEV_USER_ID, "X-Mock-Workspace-Id": DEV_WORKSPACE_ID}


def _valid_structured_brief(*, fact_ids=None):
    fact_ids = list(fact_ids or [])
    return {
        "schema_version": "lg7r-v1",
        "target_audience": "출퇴근 고객",
        "customer_problem": ["이동 중 더위"],
        "purchase_motivation": ["휴대성"],
        "desired_mood": ["깔끔함"],
        "emphasis": ["USB 충전"],
        "forbidden_claims": ["검증되지 않은 배터리 성능"],
        "forbidden_scenes": ["의료 효능 암시"],
        "section_strategy": [
            {
                "section": "benefit",
                "target": "핵심 이익",
                "objective": "승인된 사실만 설명합니다.",
                "fact_ids": fact_ids,
                "copy_classification": "fact",
                "source": "approved_facts",
                "claim_policy": "approved_fact_required",
            },
            {
                "section": "cta",
                "target": "다음 행동",
                "objective": "안전한 행동을 안내합니다.",
                "fact_ids": [],
                "copy_classification": "creative",
                "source": "seller_direction",
                "claim_policy": "narrative_non_claim",
            },
        ],
    }


class SequenceFakeRealLLM:
    """Provider-compatible fake: exercises the real structured-output boundary without billing."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.fallback = MockTextProvider()

    def generate_json(self, request):
        if request.schema_name != "creative_brief":
            return self.fallback.generate_json(request)
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        return {"provider": "fake-real", "model": "fake-structured", "content": self.responses[index]}


def _ready_run(db, mode="quick"):
    user = User(id=DEV_USER_ID, email=f"lg7-{uuid.uuid4()}@example.com", name="LG7")
    workspace = Workspace(id=DEV_WORKSPACE_ID, name="LG7", owner_id=user.id)
    db.add_all([user, workspace]); db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    brand = Brand(workspace_id=workspace.id, name="Default", font_tone="modern")
    db.add(brand); db.flush()
    project = ProductProject(workspace_id=workspace.id, brand_id=brand.id, name="무선 선풍기",
                             raw_input_text="USB 충전 배터리", planning_mode=mode)
    db.add(project); db.flush()
    db.add(ProductFact(
        id="fact-1",
        project_id=project.id,
        fact_text="USB 충전",
        source_text="USB 충전 배터리",
        verification_status="seller_confirmed",
        extraction_source="manual_text",
        confidence=1.0,
        needs_review=False,
    ))
    db.flush()
    snapshot = FactSnapshot(project_id=project.id, purpose="generation", snapshot_hash="a" * 64,
                            facts_json=[{"id": "fact-1", "fact_text": "USB 충전", "verification_status": "confirmed"}],
                            created_by=user.id)
    db.add(snapshot); db.flush()
    run = AgentRun(workspace_id=workspace.id, project_id=project.id, mode="mock", created_by=user.id,
                   input_snapshot={"product_name": "무선 선풍기", "description": "USB 충전 배터리",
                                   "interaction_mode": mode, "approved_fact_snapshot_id": snapshot.id,
                                   "approved_fact_snapshot_hash": snapshot.snapshot_hash})
    db.add(run); db.commit()
    seed_prompt_packs(db, workspace.id, user.id)
    compile_for_run(db, run, classify_category("휴대용 USB 무선 선풍기"))
    return run, project, user, workspace


def test_review_formats_and_review_claims_never_become_facts(db_session):
    run, project, user, _ = _ready_run(db_session)
    assert parse_review_bytes("reviews.csv", b"rating,review\n5,quiet and light")[0] == "csv"
    row = create_review_input(db_session, project=project, user_id=user.id, input_format="paste",
                              text="가볍고 조용해서 만족합니다. 소음이 아쉽습니다.")
    insight = db_session.query(ReviewInsightVersion).filter_by(review_input_version_id=row.id).one()
    assert insight.fact_promotion_status == "blocked"
    assert insight.insights_json["claim_policy"] == "creative_direction_only_never_approved_fact"
    assert "positive_signals" in insight.insights_json
    assert "improvement_requests" in insight.insights_json
    assert "claim_candidates" in insight.insights_json
    assert (run.input_snapshot or {})["approved_fact_snapshot_hash"] == "a" * 64


def test_xlsx_review_parser_reads_shared_and_inline_strings():
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as package:
        package.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<si><t>평점</t></si><si><r><t>조용</t></r><r><t>하고 가벼워요</t></r></si></sst>',
        )
        package.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row>'
            '<c t="s"><v>0</v></c><c t="s"><v>1</v></c>'
            '<c t="inlineStr"><is><t>손잡이는 불편해요</t></is></c>'
            '</row></sheetData></worksheet>',
        )
    input_format, text = parse_review_bytes("reviews.xlsx", content.getvalue())
    assert input_format == "xlsx"
    assert text == "평점 | 조용하고 가벼워요 | 손잡이는 불편해요"


def test_reference_is_abstracted_and_unverified_assets_are_analysis_only(db_session):
    _, project, user, _ = _ready_run(db_session)
    row = create_reference_input(db_session, project=project, user_id=user.id, input_kind="url",
                                 source_url="https://example.com/detail", text="minimal grid source logo",
                                 rights_status="unverified")
    assert row.usage_scope == "analysis_only"
    signals = analyze_reference("minimal grid source logo")
    assert "grid" in signals["layout_signals"]
    assert "source_logo" in signals["excluded_replication"]

    selected = analyze_reference(
        "pastel grid editorial",
        {"selected_signals": ["layout"]},
    )
    assert selected["layout_signals"] == ["grid", "editorial"]
    assert selected["palette_signals"] == []
    assert selected["copy_tone_signals"] == []


def test_reference_image_and_pdf_assets_use_rights_scope_and_selected_signals(db_session):
    _, project, user, _ = _ready_run(db_session)
    image = Asset(project_id=project.id, source_type="uploaded", usage_status="seller_owned",
                  filename="reference.png", file_path="/tmp/reference.png", mime_type="image/png", file_size=10)
    pdf = Asset(project_id=project.id, source_type="uploaded", usage_status="seller_owned",
                filename="plan.pdf", file_path="/tmp/plan.pdf", mime_type="application/pdf", file_size=10)
    db_session.add_all([image, pdf]); db_session.commit()
    image_row = create_reference_input(
        db_session, project=project, user_id=user.id, input_kind="image", asset_id=image.id,
        rights_status="seller_owned", source_metadata={"selected_signals": ["palette", "layout"]},
    )
    pdf_row = create_reference_input(
        db_session, project=project, user_id=user.id, input_kind="pdf", asset_id=pdf.id,
        rights_status="unverified", source_metadata={"selected_signals": ["section_flow"]},
    )
    assert image_row.usage_scope == "final_output_eligible"
    assert pdf_row.usage_scope == "analysis_only"


def test_immutable_creative_brief_pins_all_evidence_and_is_idempotent(db_session):
    run, project, user, _ = _ready_run(db_session)
    create_review_input(db_session, project=project, user_id=user.id, input_format="txt", text="가볍고 편합니다")
    create_reference_input(db_session, project=project, user_id=user.id, input_kind="text", text="pastel editorial")
    create_creative_direction(db_session, project=project, user_id=user.id, desired_mood=["clean"],
                              target_audience="commuters", emphasis=["portable"], forbidden_scenes=["medical"])
    first = compile_creative_brief(db_session, run)
    second = compile_creative_brief(db_session, run)
    assert first.id == second.id
    assert first.approved_fact_ids == ["fact-1"]
    assert first.review_insight_version_ids and first.reference_insight_version_ids
    assert first.brief_json["constraints"]["review_claims_are_not_facts"] is True
    assert set((
        "target_audience", "customer_problem", "purchase_motivation", "desired_mood", "emphasis",
        "forbidden_claims", "forbidden_scenes", "section_strategy", "approved_fact_ids",
        "creative_directions", "review_insights", "reference_signals", "provenance",
    )).issubset(first.brief_json)
    assert first.previous_version_id is None
    assert len(first.output_hash) == 64
    assert db_session.query(ProductCreativeBriefVersion).filter_by(run_id=run.id).count() == 1


def test_changed_brief_invalidates_only_downstream_planning(db_session):
    run, project, user, _ = _ready_run(db_session)
    first = compile_creative_brief(db_session, run)
    run.outputs_json = {
        **dict(run.outputs_json or {}),
        "langgraph_commerce_planning_artifacts": {"sales_strategy": {"hash": "old"}},
        "langgraph_commerce": {"sales_strategy": {"hash": "old"}},
        "source_collection": {"hash": "preserve"},
    }
    project.planning_draft = {"status": "approved", "cards": [], "revision_history": []}
    db_session.commit()
    create_creative_direction(db_session, project=project, user_id=user.id, desired_mood=["premium"],
                              target_audience="commuters", emphasis=["portable"], forbidden_scenes=[])
    db_session.refresh(run)
    second = compile_creative_brief(db_session, run)
    db_session.refresh(run); db_session.refresh(project)
    assert first.output_hash != second.output_hash
    assert second.previous_version_id == first.id
    assert "langgraph_commerce_planning_artifacts" not in run.outputs_json
    assert run.outputs_json["source_collection"]["hash"] == "preserve"
    assert project.planning_draft["status"] == "stale"
    assert db_session.query(FactSnapshot).filter_by(project_id=project.id).count() == 1


def test_compiler_node_keeps_raw_corpora_out_of_checkpoint(db_session):
    run, project, user, workspace = _ready_run(db_session)
    create_review_input(db_session, project=project, user_id=user.id, input_format="paste", text="SECRET REVIEW BODY")
    state = {"run_id": run.id, "thread_id": run.id, "workspace_id": workspace.id,
             "project_id": project.id, "mode": "mock", "input_snapshot": run.input_snapshot}
    with langgraph_execution_session(db_session):
        delta = _lg7_creative_brief_compiler(state)
    assert delta["events"][0]["stage"] == "creative_brief_compiler"
    assert "SECRET REVIEW BODY" not in str(delta)
    assert delta["creative_brief"]["output_hash"]
    assert "creative_brief_snapshot" in checkpoint_safe_input_snapshot(delta["input_snapshot"])


def test_graph_topology_places_compiler_before_sales_strategy():
    graph = build_lg7_compiled_graph(checkpointer=MemorySaver()).get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("prompt_pack_resolver", "creative_brief_compiler") in edges
    assert ("creative_brief_compiler", "sales_strategy") in edges


def test_mode_normalization_and_api_preserve_artifacts(client, db_session):
    run, project, _, _ = _ready_run(db_session, mode="expert")
    run.outputs_json = {"preserved": {"hash": "abc"}}; db_session.commit()
    response = client.patch(f"/api/v1/agent-runs/{run.id}/interaction-mode", headers=HEADERS,
                            json={"interaction_mode": "quick"})
    assert response.status_code == 200 and response.json()["artifacts_preserved"] is True
    db_session.refresh(run)
    assert run.outputs_json["preserved"]["hash"] == "abc"
    assert normalize_interaction_mode("quality") == "expert"


def test_mode_switch_is_read_from_database_when_checkpoint_is_stale(db_session):
    run, project, _, workspace = _ready_run(db_session, mode="quick")
    state = {
        "run_id": run.id, "workspace_id": workspace.id, "project_id": project.id,
        "input_snapshot": {**run.input_snapshot, "interaction_mode": "expert"},
    }
    with langgraph_execution_session(db_session):
        delta = _lg4_wait_for_seller_review("input_review", state)
    assert delta["review"]["decision_source"] == "quick_auto"
    event = db_session.query(WorkflowGateEvent).filter_by(run_id=run.id, gate_stage="input_review").one()
    assert event.interaction_mode == "quick" and event.decision_source == "quick_auto"


def test_review_and_reference_api_are_separate(client, db_session):
    _, project, _, _ = _ready_run(db_session)
    review = client.post(f"/api/v1/projects/{project.id}/review-inputs", headers=HEADERS,
                         data={"text": "조용하고 가볍습니다"})
    reference = client.post(f"/api/v1/projects/{project.id}/reference-inputs", headers=HEADERS,
                            json={"input_kind": "url", "source_url": "https://example.com", "rights_status": "unverified"})
    assert review.status_code == 200 and review.json()["fact_promotion_status"] == "blocked"
    assert reference.status_code == 200 and reference.json()["usage_scope"] == "analysis_only"
    assert db_session.query(ReferenceInputVersion).filter_by(project_id=project.id).count() == 1


def test_fake_real_llm_accepts_valid_schema_without_repair():
    provider = SequenceFakeRealLLM([_valid_structured_brief(fact_ids=["fact-1"])])
    brief, metadata = generate_structured_creative_brief(
        provider, product_name="무선 선풍기", compiler_input={"approved_fact_ids": ["fact-1"]},
    )
    assert brief["schema_version"] == "lg7r-v1"
    assert metadata == {"attempts": 1, "repairs": 0, "provider": "fake-real", "model": "fake-structured"}
    assert len(provider.requests) == 1


def test_fake_real_llm_repairs_one_schema_error_once():
    provider = SequenceFakeRealLLM([
        {"schema_version": "lg7r-v1", "section_strategy": []},
        _valid_structured_brief(fact_ids=["fact-1"]),
    ])
    brief, metadata = generate_structured_creative_brief(
        provider, product_name="무선 선풍기", compiler_input={"approved_fact_ids": ["fact-1"]},
    )
    assert brief["section_strategy"][0]["fact_ids"] == ["fact-1"]
    assert metadata["attempts"] == 2 and metadata["repairs"] == 1
    assert "스키마 검증에 실패" in provider.requests[1].user_prompt


def test_fake_real_llm_stops_after_repair_budget_and_never_loops():
    provider = SequenceFakeRealLLM([{"bad": True}])
    with pytest.raises(CreativeBriefLLMError) as error:
        generate_structured_creative_brief(
            provider, product_name="무선 선풍기", compiler_input={}, max_repairs=1,
        )
    assert error.value.code == "CREATIVE_BRIEF_SCHEMA_REPAIR_EXHAUSTED"
    assert error.value.attempts == 2
    assert len(provider.requests) == 2

    no_repair = SequenceFakeRealLLM([{"bad": True}])
    with pytest.raises(CreativeBriefLLMError) as no_repair_error:
        generate_structured_creative_brief(
            no_repair, product_name="무선 선풍기", compiler_input={}, max_repairs=0,
        )
    assert no_repair_error.value.attempts == 1
    assert len(no_repair.requests) == 1


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        ("reviews.txt", b"", "REVIEW_FILE_EMPTY"),
        ("reviews.json", b"{}", "REVIEW_FILE_UNSUPPORTED"),
        ("reviews.txt", b"\xff\xfe\x00\x00", "REVIEW_FILE_ENCODING_INVALID"),
        ("reviews.xlsx", b"not-a-zip", "REVIEW_XLSX_CORRUPT"),
    ],
)
def test_review_file_validation_has_stable_korean_error_contract(filename, content, code):
    with pytest.raises(CreativeBriefInputError) as error:
        parse_review_bytes(filename, content)
    assert error.value.code == code
    assert error.value.message and error.value.remedy


def test_lg7r_runtime_migration_is_reentrant_and_repairs_missing_index(monkeypatch):
    from src.db import database

    migration_engine = create_engine("sqlite:///:memory:")
    with migration_engine.begin() as connection:
        connection.execute(text("CREATE TABLE assets (id VARCHAR(36) PRIMARY KEY, source_type VARCHAR(50))"))
        connection.execute(text("CREATE TABLE review_input_versions (id VARCHAR(36) PRIMARY KEY)"))

    monkeypatch.setattr(database, "engine", migration_engine)
    database.ensure_runtime_schema_compatibility()
    database.ensure_runtime_schema_compatibility()

    schema = inspect(migration_engine)
    columns = {column["name"] for column in schema.get_columns("review_input_versions")}
    indexes = {index["name"] for index in schema.get_indexes("review_input_versions")}
    assert "source_asset_id" in columns
    assert "ix_review_input_versions_source_asset_id" in indexes


def test_review_content_hash_deduplicates_paste_file_and_collected_asset(client, db_session, tmp_path):
    _, project, _, _ = _ready_run(db_session)
    review_text = "가볍고 조용해서 출퇴근에 편리합니다."
    source_path = tmp_path / "collected-reviews.txt"
    source_path.write_text(review_text, encoding="utf-8")
    asset = Asset(
        project_id=project.id, source_type="uploaded", usage_status="seller_owned",
        filename="collected-reviews.txt", file_path=str(source_path), mime_type="text/plain",
        file_size=source_path.stat().st_size, content_hash="source-hash",
    )
    db_session.add(asset); db_session.commit()

    first = client.post(
        f"/api/v1/projects/{project.id}/review-inputs", headers=HEADERS,
        data={"text": review_text, "consent_status": "confirmed"},
    )
    duplicate_file = client.post(
        f"/api/v1/projects/{project.id}/review-inputs", headers=HEADERS,
        files={"file": ("reviews.txt", review_text.encode("utf-8"), "text/plain")},
    )
    duplicate_asset = client.post(
        f"/api/v1/projects/{project.id}/review-inputs", headers=HEADERS,
        data={"source_asset_id": asset.id},
    )
    assert first.status_code == duplicate_file.status_code == duplicate_asset.status_code == 200
    assert duplicate_file.json()["deduplicated"] is True
    assert duplicate_asset.json()["deduplicated"] is True
    assert duplicate_asset.json()["id"] == first.json()["id"]
    assert db_session.query(ReviewInsightVersion).filter_by(project_id=project.id).count() == 1

    intelligence = client.get(
        f"/api/v1/projects/{project.id}/creative-intelligence", headers=HEADERS,
    )
    assert intelligence.status_code == 200
    assert any(option["id"] == asset.id for option in intelligence.json()["review_asset_options"])


def test_planning_trace_exposes_versions_facts_modes_and_stale_impact(client, db_session):
    run, project, user, _ = _ready_run(db_session, mode="quick")
    create_review_input(db_session, project=project, user_id=user.id, input_format="paste", text="조용해서 좋아요")
    create_reference_input(db_session, project=project, user_id=user.id, input_kind="text", text="minimal grid")
    create_creative_direction(
        db_session, project=project, user_id=user.id, desired_mood=["clean"],
        target_audience="commuters", emphasis=["portable"], forbidden_scenes=["medical"],
    )
    brief = compile_creative_brief(db_session, run)
    project.planning_draft = {
        "status": "stale",
        "cards": [{"id": "benefit", "scene_request": "USB 충전 설명", "source_fact_ids": ["fact-1"]}],
    }
    db_session.commit()

    response = client.get(
        f"/api/v1/projects/{project.id}/creative-intelligence?run_id={run.id}", headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    trace = response.json()["trace"]
    assert trace["generation_mode"] == "mock"
    assert trace["interaction_mode"] == "quick"
    assert {row["kind"] for row in trace["prompt_packs"] if row} == {"category", "channel"}
    assert all({"id", "version", "hash"}.issubset(row) for row in trace["prompt_packs"] if row)
    assert trace["creative_brief"] == {"id": brief.id, "version": brief.version, "hash": brief.output_hash}
    assert trace["creative_direction"]["hash"]
    assert trace["review_usage"]["used"] is True and trace["reference_usage"]["used"] is True
    assert trace["approved_facts"][0]["id"] == "fact-1"
    assert all({"section", "target", "objective", "fact_ids", "copy_classification"}.issubset(row) for row in trace["sections"])
    assert trace["stale_artifacts"][0]["impact"] == "storyboard_and_downstream"


def test_fake_llm_creative_brief_flows_through_real_interrupt_and_command_resume(
    client, db_session, monkeypatch,
):
    from src.services import langgraph_run_service
    from src.services import llm_router

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    provider = SequenceFakeRealLLM([_valid_structured_brief(fact_ids=["fact-1"])])
    monkeypatch.setattr(llm_router, "get_text_provider_by_settings", lambda: provider)

    run, project, _, _ = _ready_run(db_session, mode="expert")
    run.mode = "real"
    safe_asset = Asset(
        project_id=project.id, source_type="uploaded", usage_status="seller_owned",
        filename="product.jpg", file_path="/tmp/product.jpg", mime_type="image/jpeg", file_size=10,
        asset_role="product_main", quality_status="usable", identity_status="confirmed", is_representative=True,
    )
    db_session.add(safe_asset); db_session.flush()
    run.input_snapshot = {**run.input_snapshot, "asset_ids": [safe_asset.id]}
    db_session.commit()

    started = client.post(f"/api/v1/graph-runs/{run.id}/start", headers=HEADERS)
    assert started.status_code == 200, started.text
    state = started.json()
    assert state["current_stage"] == "input_review"

    def resume(current):
        pending = current["values"]["review"]["pending"]
        return client.post(
            f"/api/v1/graph-runs/{run.id}/resume", headers=HEADERS,
            json={
                "thread_id": current["thread_id"],
                "response": {
                    "schema_version": pending["schema_version"],
                    "review_stage": pending["review_stage"],
                    "decision": "approve",
                },
            },
        )

    evidence = resume(state)
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["current_stage"] == "evidence_review"
    planning = resume(evidence.json())
    assert planning.status_code == 200, planning.text
    planning_state = planning.json()
    assert planning_state["current_stage"] == "planning_review"
    assert planning_state["values"]["creative_brief"]["output_hash"]
    assert planning_state["values"]["commerce"]["page_planning"]
    assert len(provider.requests) == 1

    refreshed = client.get(f"/api/v1/graph-runs/{run.id}", headers=HEADERS)
    assert refreshed.status_code == 200
    assert refreshed.json()["checkpoint_id"] == planning_state["checkpoint_id"]
    assert refreshed.json()["current_stage"] == "planning_review"

    generation = resume(refreshed.json())
    assert generation.status_code == 200, generation.text
    assert generation.json()["current_stage"] == "generation_pending"
