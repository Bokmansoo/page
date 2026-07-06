import json

import pytest
from src.agents.schemas import ProductUnderstandingOutput, SalesStrategyOutput
from src.agents.graph import AgentGraph
from src.agents.state import AgentRunMode, AgentRunState, ProductInput
from src.agents.mock_outputs import (
    build_mock_copy_set,
    build_mock_page_plan,
    build_mock_product_understanding,
    build_mock_qa_report,
    build_mock_sales_strategy,
    build_mock_visual_plan,
)
from src.services.provider_adapters import MockTextProvider


@pytest.fixture
def auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def test_product_understanding_schema_requires_facts():
    output = ProductUnderstandingOutput(
        product_type="유아 자전거",
        target_customer="첫 자전거를 찾는 부모",
        buyer_problem="안전한 첫 자전거 선택이 어렵다",
        verified_facts=["보조 바퀴 포함"],
        assumptions=["실내외 사용 가능"],
        risk_notes=[],
    )
    assert output.verified_facts == ["보조 바퀴 포함"]


def test_sales_strategy_schema_has_recommended_direction():
    output = SalesStrategyOutput(
        recommended_direction="문제 해결형",
        alternatives=["감성형", "스펙 강조형"],
        main_claim="처음 타는 순간부터 안정적인 자전거",
        support_claims=["보조 바퀴", "낮은 안장"],
        reason="초보 사용자의 구매 불안을 직접 해결한다",
    )
    assert output.recommended_direction == "문제 해결형"


def test_real_text_graph_blocks_image_generation_when_cost_is_not_approved(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "SELLFORM_IMAGE_COST_APPROVAL_REQUIRED", True)
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "real")
    graph = AgentGraph.real_text(text_provider=MockTextProvider())
    state = AgentRunState(
        project_id="p1",
        mode=AgentRunMode.REAL,
        product_input=ProductInput(product_name="유아 자전거"),
    )
    completed = graph.run_text_generation(state)
    assert "product_understanding" in completed.outputs
    assert "sales_strategy" in completed.outputs
    assert "copy_set" in completed.outputs
    assert completed.outputs["image_generation"]["images"] == []
    assert "generated_assets" not in completed.outputs

    assert "page_assembly" in completed.outputs
    sections = completed.outputs["page_assembly"]["sections"]
    assert len(sections) > 0
    assert sections[0]["title"]


def test_run_real_api_endpoint(client, auth_headers, monkeypatch):
    from src.config import settings
    from src.db.models import PageSection, ProductPage
    from src.services import llm_router

    monkeypatch.setattr(settings, "SELLFORM_GENERATION_MODE", "real")
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "mock")
    monkeypatch.setattr(
        llm_router,
        "get_text_provider_by_settings",
        lambda: MockTextProvider(),
    )

    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "유아 자전거", "description": "안전 바퀴 장착"},
    ).json()

    response = client.post(f"/api/agent-runs/{created['id']}/run", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["current_stage"] == "review_editor"
    assert data["mode"] == "real"
    assert "product_understanding" in data["outputs"]
    assert "copy_set" in data["outputs"]
    assert "page_assembly" in data["outputs"]

    progress = client.get(
        f"/api/agent-runs/{created['id']}/status",
        headers=auth_headers,
    )
    assert progress.status_code == 200
    progress_data = progress.json()
    assert progress_data["status"] == "completed"
    assert progress_data["current_stage"] == "review_editor"
    assert progress_data["completed_stages"] == [
        "input_router",
        "source_collection",
        "product_understanding",
        "reference_analysis",
        "sales_strategy",
        "page_planning",
        "copywriting",
        "visual_planning",
        "image_generation",
        "page_assembly",
        "qa_review",
    ]


def test_run_real_api_materializes_page_for_result_view(client, auth_headers, db_session, monkeypatch):
    from src.config import settings
    from src.db.models import PageSection, ProductPage
    from src.services import llm_router

    monkeypatch.setattr(settings, "SELLFORM_GENERATION_MODE", "real")
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "mock")
    monkeypatch.setattr(
        llm_router,
        "get_text_provider_by_settings",
        lambda: MockTextProvider(),
    )

    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "삼탠바이미", "description": "이동식 스마트 모니터"},
    ).json()

    response = client.post(f"/api/agent-runs/{created['id']}/run", headers=auth_headers)
    assert response.status_code == 200

    page = db_session.query(ProductPage).filter(ProductPage.project_id == created["project_id"]).first()
    assert page is not None

    sections = (
        db_session.query(PageSection)
        .filter(PageSection.page_id == page.id)
        .order_by(PageSection.sort_order.asc())
        .all()
    )
    assert len(sections) > 0
    assert sections[0].title
    assert sections[0].body_copy is not None

    page_response = client.get(f"/api/v1/projects/{created['project_id']}/page", headers=auth_headers)
    assert page_response.status_code == 200
    visual_sections = [
        section
        for section in page_response.json()["sections"]
        if section["section_type"] != "product_information"
    ]
    assert visual_sections
    assert all(section["image_candidates"] for section in visual_sections)


def test_materialized_page_prefers_generated_visual_slot_over_legacy_image_id(
    client,
    auth_headers,
    db_session,
):
    from src.db.models import AgentRun, Asset, PageSection, ProductPage
    from src.services.agent_run_service import AgentRunService

    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "삼탠바이미"},
    ).json()
    uploaded = Asset(
        project_id=created["project_id"],
        source_type="uploaded",
        filename="samtanbyme.png",
        file_path="/uploads/samtanbyme.png",
        mime_type="image/png",
        file_size=1024,
    )
    generated = Asset(
        project_id=created["project_id"],
        source_type="real-generated",
        filename="ai_generated/hero.png",
        file_path="/uploads/ai_generated/hero.png",
        mime_type="image/png",
        file_size=2048,
    )
    db_session.add_all([uploaded, generated])
    db_session.flush()

    run = db_session.query(AgentRun).filter(AgentRun.id == created["id"]).one()
    run.outputs_json = {
        "page_assembly": {
            "sections": [
                {
                    "id": "sec-1",
                    "section_type": "hero",
                    "title": "거실 어디서나 편하게",
                    "body_copy": "이동식 스마트 모니터",
                    "image_id": uploaded.id,
                    "visual_slot": {
                        "asset_id": generated.id,
                        "source_type": "real-generated",
                        "status": "completed",
                    },
                }
            ]
        }
    }

    AgentRunService._materialize_page_from_outputs(run, db_session)
    db_session.flush()

    page = db_session.query(ProductPage).filter_by(project_id=created["project_id"]).one()
    section = db_session.query(PageSection).filter_by(page_id=page.id).one()
    assert section.image_asset_id == generated.id


def test_materialized_page_does_not_repeat_upload_for_failed_generated_slots(
    client,
    auth_headers,
    db_session,
):
    from src.db.models import AgentRun, Asset, DetailPageVersion, PageSection, ProductPage
    from src.services.agent_run_service import AgentRunService

    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "삼탠바이미", "description": "거실용 이동형 스마트 모니터"},
    ).json()

    asset = Asset(
        project_id=created["project_id"],
        source_type="uploaded",
        filename="samtanbyme.png",
        file_path="/uploads/samtanbyme.png",
        mime_type="image/png",
        file_size=1024,
    )
    db_session.add(asset)
    db_session.flush()

    run = db_session.query(AgentRun).filter(AgentRun.id == created["id"]).first()
    run.input_snapshot = {**run.input_snapshot, "asset_ids": [asset.id]}
    run.outputs_json = {
        "page_assembly": {
            "sections": [
                {
                    "id": "hero",
                    "section_type": "hero",
                    "title": "거실 속 삼탠바이미",
                    "body_copy": "원하는 곳에서 편하게 시청하세요.",
                    "visual_slot": {"status": "generation_failed", "asset_id": None},
                },
                {
                    "id": "comparison",
                    "section_type": "comparison",
                    "title": "공간을 옮길 때마다",
                    "body_copy": "고정형 화면의 불편을 줄입니다.",
                    "visual_slot": {"status": "generation_failed", "asset_id": None},
                },
            ]
        }
    }
    db_session.add(run)
    db_session.flush()

    AgentRunService._materialize_page_from_outputs(run, db_session)
    db_session.flush()

    page = db_session.query(ProductPage).filter(ProductPage.project_id == created["project_id"]).first()
    sections = (
        db_session.query(PageSection)
        .filter(PageSection.page_id == page.id)
        .order_by(PageSection.sort_order.asc())
        .all()
    )
    assert [section.image_asset_id for section in sections] == [None, None]
    assert (
        db_session.query(DetailPageVersion)
        .filter(DetailPageVersion.project_id == created["project_id"])
        .count()
        == 1
    )


def test_run_real_api_materializes_uploaded_image_into_page_sections(client, auth_headers, db_session, monkeypatch):
    from src.config import settings
    from src.db.models import AgentRun, Asset, PageSection, ProductPage
    from src.services import llm_router

    monkeypatch.setattr(settings, "SELLFORM_GENERATION_MODE", "real")
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "mock")
    monkeypatch.setattr(
        llm_router,
        "get_text_provider_by_settings",
        lambda: MockTextProvider(),
    )

    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "삼탠바이미", "description": "이동형 스마트 모니터"},
    ).json()

    asset = Asset(
        project_id=created["project_id"],
        source_type="uploaded",
        filename="samtanbyme.png",
        file_path="/uploads/samtanbyme.png",
        mime_type="image/png",
        file_size=1024,
    )
    db_session.add(asset)
    db_session.flush()

    run = db_session.query(AgentRun).filter(AgentRun.id == created["id"]).first()
    run.input_snapshot["asset_ids"] = [asset.id]
    db_session.add(run)
    db_session.commit()

    response = client.post(f"/api/agent-runs/{created['id']}/run", headers=auth_headers)
    assert response.status_code == 200

    page = db_session.query(ProductPage).filter(ProductPage.project_id == created["project_id"]).first()
    sections = (
        db_session.query(PageSection)
        .filter(PageSection.page_id == page.id)
        .order_by(PageSection.sort_order.asc())
        .all()
    )
    assert sections[0].image_asset_id == asset.id


def test_run_real_api_backfills_project_image_asset_ids_before_execution(client, auth_headers, db_session, monkeypatch):
    from src.config import settings
    from src.db.models import AgentRun, Asset
    from src.services import llm_router

    monkeypatch.setattr(settings, "SELLFORM_GENERATION_MODE", "real")
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "mock")
    monkeypatch.setattr(
        llm_router,
        "get_text_provider_by_settings",
        lambda: MockTextProvider(),
    )

    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "삼탠바이미", "description": "이동형 스마트 모니터"},
    ).json()

    asset = Asset(
        project_id=created["project_id"],
        source_type="uploaded",
        filename="samtanbyme.png",
        file_path="/uploads/samtanbyme.png",
        mime_type="image/png",
        file_size=1024,
    )
    db_session.add(asset)
    db_session.commit()

    response = client.post(f"/api/agent-runs/{created['id']}/run", headers=auth_headers)
    assert response.status_code == 200

    run = db_session.query(AgentRun).filter(AgentRun.id == created["id"]).first()
    assert run.input_snapshot["asset_ids"] == [asset.id]
    jobs = response.json()["outputs"]["visual_planning"]["image_jobs"]
    assert all(job["reference_asset_ids"] == [asset.id] for job in jobs)


def test_real_text_graph_keeps_product_context_and_reviews_final_assembly():
    requests = []

    class RecordingProvider:
        def generate_json(self, req):
            requests.append(req)
            builders = {
                "product_understanding": build_mock_product_understanding,
                "sales_strategy": build_mock_sales_strategy,
                "page_plan": build_mock_page_plan,
                "copy_set": build_mock_copy_set,
                "visual_plan": build_mock_visual_plan,
                "qa_report": build_mock_qa_report,
            }
            content = builders[req.schema_name](req.product_name or "상품")
            if req.schema_name == "copy_set":
                content.update(
                    {
                        "feature_2_title": "손잡이 구조를 확인하세요",
                        "feature_2_body": "등록된 상품 정보를 기준으로 안내합니다.",
                        "guarantee_title": "구매 전 상품 정보를 확인하세요",
                        "guarantee_body": "판매자가 등록한 교환 및 배송 정보를 확인하세요.",
                    }
                )
            return {
                "provider": "recording",
                "model": "recording-model",
                "content": content,
                "token_usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "cost": 0,
            }

    graph = AgentGraph.real_text(text_provider=RecordingProvider())
    state = AgentRunState(
        project_id="p-context",
        mode=AgentRunMode.REAL,
        product_input=ProductInput(
            product_name="스테인리스 프라이팬",
            description="인덕션 사용 가능",
        ),
    )

    completed = graph.run_text_generation(state)
    copy_request = next(req for req in requests if req.schema_name == "copy_set")
    qa_request = next(req for req in requests if req.schema_name == "qa_report")

    assert "스테인리스 프라이팬" in copy_request.user_prompt
    assert "카피라이팅 에이전트" in copy_request.system_prompt
    assert "상세페이지 문구" in copy_request.system_prompt
    assert "verified_facts" in copy_request.user_prompt
    assert "page_assembly" in qa_request.user_prompt
    assert "KC" not in json.dumps(completed.outputs["page_assembly"], ensure_ascii=False)
    assert completed.provider_trace
