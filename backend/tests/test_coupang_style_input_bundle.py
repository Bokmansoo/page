from unittest.mock import patch

from src.db.models import AgentRun, Asset, ProductFact, ProductProject
from src.services.agent_run_service import AgentRunService


AUTH_HEADERS = {
    "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
}


def _asset(project_id: str, asset_id: str) -> Asset:
    return Asset(
        id=asset_id,
        project_id=project_id,
        source_type="uploaded",
        filename=f"{asset_id}.jpg",
        file_path=f"{asset_id}.jpg",
        mime_type="image/jpeg",
        file_size=100,
        quality_status="usable",
        quality_warnings=[],
    )


def test_input_bundle_preserves_explicit_product_fields_and_numeric_units(client, db_session):
    response = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={
            "product_name": "미니 마사지건",
            "category": "Living",
            "description": "무게 260g, 사용 시간 10분, 배터리 800mAh",
            "feature_details": "3단 진동",
            "components": "본체, 충전 케이블",
            "cautions": "사용 전 설명서를 확인해 주세요.",
            "price": "39,900원",
            "shipping": "무료배송",
        },
    )

    assert response.status_code == 201
    project_id = response.json()["project_id"]
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).one()
    run = db_session.query(AgentRun).filter(AgentRun.id == response.json()["id"]).one()
    facts = db_session.query(ProductFact).filter(ProductFact.project_id == project_id).all()

    assert project.category == "Living"
    assert project.category_confirmed is True
    assert project.intake_snapshot["input_bundle"]["components"] == "본체, 충전 케이블"
    assert run.input_snapshot["feature_details"] == "3단 진동"
    assert run.input_snapshot["cautions"] == "사용 전 설명서를 확인해 주세요."
    assert {fact.source_text for fact in facts} >= {"260g", "10분", "800mAh"}


def test_input_bundle_summary_keeps_numeric_values_and_units(client):
    description = "상품 상세 설명\n무게 260g, 사용 시간 10분, 배터리 용량 800mAh"
    response = client.post(
        "/api/agent-runs/structure-intake",
        headers=AUTH_HEADERS,
        json={
            "product_name": "미니 마사지건",
            "description": description,
            "asset_ids": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["description"]["value"] == description


def test_input_bundle_persists_image_order_and_the_runner_keeps_it(client, db_session):
    created = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={"product_name": "사진 묶음 상품", "description": "판매자가 확인한 핵심 기능 1개"},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    project_id = created.json()["project_id"]
    images = [_asset(project_id, f"bundle-image-{index}") for index in range(5)]
    db_session.add_all(images)
    db_session.commit()

    selected_order = [images[3].id, images[0].id, images[4].id, images[1].id, images[2].id]
    saved = client.patch(
        f"/api/agent-runs/{run_id}/input-assets",
        headers=AUTH_HEADERS,
        json={"asset_ids": selected_order},
    )

    assert saved.status_code == 200
    assert saved.json()["product_input"]["asset_ids"] == selected_order
    run = db_session.query(AgentRun).filter(AgentRun.id == run_id).one()
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).one()
    assert run.input_snapshot["asset_ids"] == selected_order
    assert project.intake_snapshot["input_bundle"]["asset_ids"] == selected_order
    assert AgentRunService._ensure_input_asset_ids(run, db_session) == selected_order


def test_input_bundle_rejects_assets_from_another_project(client, db_session):
    first = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={"product_name": "첫 번째 상품"},
    ).json()
    second = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={"product_name": "두 번째 상품"},
    ).json()
    foreign_asset = _asset(second["project_id"], "foreign-image")
    db_session.add(foreign_asset)
    db_session.commit()

    response = client.patch(
        f"/api/agent-runs/{first['id']}/input-assets",
        headers=AUTH_HEADERS,
        json={"asset_ids": [foreign_asset.id]},
    )

    assert response.status_code == 422


def test_url_collection_failure_is_preserved_as_direct_upload_guidance(client, db_session):
    with patch(
        "src.api.agent_runs.collect_url_evidence",
        side_effect=RuntimeError("403 Forbidden"),
    ):
        response = client.post(
            "/api/agent-runs",
            headers=AUTH_HEADERS,
            json={
                "product_name": "직접 업로드 안내 상품",
                "product_url": "https://example.com/restricted-product",
            },
        )

    assert response.status_code == 201
    warnings = response.json()["collection_warnings"]
    assert len(warnings) == 1
    assert "403 Forbidden" in warnings[0]

    run = db_session.query(AgentRun).filter(AgentRun.id == response.json()["id"]).one()
    assert run.input_snapshot["source_collection_warnings"] == warnings
