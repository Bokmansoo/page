import pytest
from unittest.mock import patch

from src.db.models import AgentRun, AgentRunStep
from src.services.url_evidence_collector import URLEvidence


@pytest.fixture
def auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def test_create_agent_run_from_product_name(client, auth_headers):
    response = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "유아 자전거", "description": "보조 바퀴가 있는 첫 자전거"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["current_stage"] == "intake"
    assert data["mode"] == "mock"
    assert data["product_input"]["product_name"] == "유아 자전거"


def test_create_agent_run_preserves_confirmed_structured_intake(
    client,
    auth_headers,
    db_session,
):
    response = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={
            "product_name": "수정된 상품명",
            "description": "사용자가 확인한 설명",
            "selling_points": ["LED 조명", "보조 바퀴 탈착"],
            "price": "39,900원",
            "shipping": "무료배송",
            "desired_mood": ["안전한", "감성적인"],
        },
    )

    assert response.status_code == 201
    run = db_session.query(AgentRun).filter(AgentRun.id == response.json()["id"]).one()
    assert run.input_snapshot["product_name"] == "수정된 상품명"
    assert run.input_snapshot["selling_points"] == ["LED 조명", "보조 바퀴 탈착"]
    assert run.input_snapshot["price"] == "39,900원"
    assert run.input_snapshot["shipping"] == "무료배송"
    assert run.input_snapshot["desired_mood"] == ["안전한", "감성적인"]


def test_create_agent_run_collects_product_and_reference_url_evidence(
    client,
    auth_headers,
    db_session,
):
    def fake_collect(url, **_kwargs):
        return URLEvidence(
            url=url,
            title="수집된 상품",
            image_urls=[f"{url}/hero.jpg"],
            specs=[{"label": "무게", "value": "6kg"}],
            text_blocks=["보조 바퀴 탈착 가능"],
            ocr_text_blocks=["권장 연령 3~6세"],
        )

    with patch("src.api.agent_runs.collect_url_evidence", side_effect=fake_collect):
        response = client.post(
            "/api/agent-runs",
            headers=auth_headers,
            json={
                "product_name": "",
                "product_url": "https://shop.example.com/product",
                "reference_urls": ["https://reference.example.com/detail"],
            },
        )

    assert response.status_code == 201
    run = db_session.query(AgentRun).filter(AgentRun.id == response.json()["id"]).one()
    assert run.input_snapshot["product_name"] == "수집된 상품"
    assert len(run.input_snapshot["url_images"]) == 2
    assert {"label": "무게", "value": "6kg"} in run.input_snapshot["url_specs"]
    assert "권장 연령 3~6세" in run.input_snapshot["reference_text_blocks"]


def test_run_mock_generation_returns_page_assembly(client, auth_headers):
    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "유아 자전거"},
    ).json()
    response = client.post(f"/api/agent-runs/{created['id']}/run-mock", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["current_stage"] == "review_editor"
    assert data["outputs"]["page_assembly"]["sections"]


def test_run_mock_rejects_other_workspace_agent_run(client, auth_headers):
    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "kids bike"},
    ).json()

    other_workspace_headers = {
        **auth_headers,
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000099",
    }
    response = client.post(f"/api/agent-runs/{created['id']}/run-mock", headers=other_workspace_headers)

    assert response.status_code == 404


def test_agent_run_status_returns_persisted_stage_progress(
    client,
    auth_headers,
    db_session,
):
    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "kids bike"},
    ).json()
    run = db_session.query(AgentRun).filter(AgentRun.id == created["id"]).one()
    run.status = "running"
    run.current_stage = "sales_strategy"
    db_session.add_all(
        [
            AgentRunStep(
                run_id=run.id,
                stage="product_understanding",
                status="completed",
            ),
            AgentRunStep(
                run_id=run.id,
                stage="sales_strategy",
                status="running",
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/api/agent-runs/{run.id}/status",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": run.id,
        "status": "running",
        "current_stage": "sales_strategy",
        "completed_stages": ["product_understanding"],
        "failed_stage": None,
        "error_message": None,
        "steps": [
            {
                "stage": "product_understanding",
                "status": "completed",
                "started_at": None,
                "completed_at": None,
                "error_message": None,
            },
            {
                "stage": "sales_strategy",
                "status": "running",
                "started_at": None,
                "completed_at": None,
                "error_message": None,
            },
        ],
    }
