from src.api.pages import create_page_snapshot
from src.db.models import Asset, ProductFact, ProductPage, PageSection
from src.services.page_finalization_service import finalize_page
from src.services.generation_provider_adapter import ProviderNotConnectedError, UnconfiguredGenerationProvider
from src.schemas.api_ready_generation import GenerationJobRequestSchema, GenerationOutputSpecSchema


def _auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def _project(client, *, product_url="https://example.test/product"):
    response = client.post(
        "/api/agent-runs",
        headers=_auth_headers(),
        json={
            "product_name": "Neck massage pillow",
            "product_url": product_url,
            "description": "경추 마사지 베개. 정격 입력 DC 5V 2A, 8W, 사용 시간 10분, 배터리 2000mAh, 크기 40 x 17 x 15cm",
            "sales_channel": "쿠팡",
            "model_options": "YL-T02, 그레이",
            "ux_auto_generate": True,
        },
    )
    assert response.status_code == 201
    return response.json()["project_id"]


def test_ux2e0_builds_provider_free_brief_scene_plan_and_snapshot(client, db_session):
    project_id = _project(client)
    safe = Asset(
        project_id=project_id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename="pillow-main.jpg",
        file_path="/tmp/pillow-main.jpg",
        mime_type="image/jpeg",
        file_size=10,
        asset_role="product_main",
        quality_status="usable",
        identity_status="confirmed",
        is_representative=True,
    )
    risky = Asset(
        project_id=project_id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename="supplier-spec.jpg",
        file_path="/tmp/supplier-spec.jpg",
        mime_type="image/jpeg",
        file_size=10,
        asset_role="feature",
        quality_status="usable",
        identity_status="confirmed",
        ocr_text="供应商 价格 199元",
    )
    usage = Asset(
        project_id=project_id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename="seller-usage.jpg",
        file_path="/tmp/seller-usage.jpg",
        mime_type="image/jpeg",
        file_size=10,
        asset_role="usage_scene",
        quality_status="usable",
        identity_status="confirmed",
    )
    facts = [
        ProductFact(project_id=project_id, fact_text="모델명 YL-T02", verification_status="seller_confirmed", needs_review=False, field_key="model_name", normalized_value="YL-T02"),
        ProductFact(project_id=project_id, fact_text="정격 입력 DC 5V 2A", verification_status="seller_confirmed", needs_review=False, field_key="rated_input", normalized_value="DC 5V 2A"),
        ProductFact(project_id=project_id, fact_text="제품 크기 40 x 17 x 15cm", verification_status="seller_confirmed", needs_review=False, field_key="product_size", normalized_value="40 x 17 x 15", normalized_unit="cm"),
        ProductFact(project_id=project_id, fact_text="배터리 용량 2000mAh", verification_status="seller_confirmed", needs_review=False, field_key="battery_capacity", normalized_value="2000", normalized_unit="mAh"),
        ProductFact(project_id=project_id, fact_text="권장 작동 시간 10분", verification_status="seller_confirmed", needs_review=False, field_key="usage_time", normalized_value="10", normalized_unit="분"),
    ]
    db_session.add_all([safe, risky, usage, *facts])
    db_session.commit()

    created = client.post(
        f"/api/v1/projects/{project_id}/generation-plan", headers=_auth_headers()
    )
    assert created.status_code == 200, created.text
    plan = created.json()
    assert plan["provider_mode"] == "api_not_connected"
    assert plan["product_brief"]["source_url_usage"] == "reference_only"
    assert {item["id"] for item in plan["product_brief"]["safe_reference_assets"]} == {safe.id, usage.id}
    assert plan["product_brief"]["model_option"] == "YL-T02"
    assert plan["product_brief"]["sales_channel"] == "쿠팡"
    assert plan["product_brief"]["options"] == ["YL-T02", "그레이"]
    assert {item["field_key"] for item in plan["product_brief"]["confirmed_facts"]} >= {
        "model_name", "rated_input", "product_size", "battery_capacity", "usage_time",
    }
    assert plan["product_brief"]["identity_criteria"]["must_preserve"]
    assert any(item["status"] == "reference_only" for item in plan["product_brief"]["source_states"])
    assert any(scene["mock_status"] == "generation_pending" for scene in plan["scenes"])
    assert any(scene["requested_output"] == "html_information" for scene in plan["scenes"])
    assert all(risky.id not in scene["reference_asset_ids"] for scene in plan["scenes"])

    hero = next(scene for scene in plan["scenes"] if scene["scene_type"] == "hero_product")
    updated = client.patch(
        f"/api/v1/projects/{project_id}/generation-plan",
        headers=_auth_headers(),
        json={
            "product_brief": {"color": "그레이", "forbidden_claims": ["치료 표현", "최고"]},
            "scenes": [{
                "id": hero["id"], "seller_approved": True, "reference_asset_ids": [safe.id],
                "source_fact_ids": [facts[0].id, facts[2].id],
                "expected_copy": {"headline": "경추 마사지 베개", "body": "모델과 크기를 확인해 주세요."},
                "seller_note": "버튼 위치와 색상은 바꾸지 마세요.",
                "regeneration_reason": "판매자 검토 후 수정",
            }],
        },
    )
    assert updated.status_code == 200, updated.text
    updated_hero = next(scene for scene in updated.json()["scenes"] if scene["id"] == hero["id"])
    assert updated_hero["seller_approved"] is True
    assert updated_hero["source_fact_ids"] == [facts[0].id, facts[2].id]
    assert updated_hero["expected_copy"]["headline"] == "경추 마사지 베개"
    assert updated_hero["seller_note"]
    assert len(updated_hero["regeneration_history"]) >= 2
    assert updated.json()["product_brief"]["color"] == "그레이"

    rejected = client.patch(
        f"/api/v1/projects/{project_id}/generation-plan",
        headers=_auth_headers(),
        json={"scenes": [{"id": hero["id"], "reference_asset_ids": [risky.id]}]},
    )
    assert rejected.status_code == 422

    project = safe.project
    page = ProductPage(project_id=project_id, theme_color="#10B981", font_family="Pretendard")
    db_session.add(page)
    db_session.flush()
    db_session.add(PageSection(
        page_id=page.id,
        section_type="hero",
        title="대표 제품",
        body_copy="확정 사실 기준 안내",
        image_asset_id=safe.id,
        sort_order=0,
        is_visible=True,
    ))
    db_session.commit()
    snapshot = create_page_snapshot(page, db_session)
    assert snapshot["ux2e0_generation_plan"]["provider_mode"] == "api_not_connected"
    assert snapshot["ux2e0_generation_plan"]["scenes"][0]["prompt_blueprint"]["negative_constraints"]
    assert snapshot["commerce_renderer"]["api_generation"]["no_fake_generated_assets"] is True
    final_version = finalize_page(db_session, project_id)
    assert final_version.sections_json["ux2e0_generation_plan"]["summary"] == plan["summary"]
    assert final_version.sections_json["commerce_renderer"]["api_generation"]["scene_fallbacks"]


def test_ux2e0_does_not_create_a_provider_job_when_api_is_not_connected(client, db_session):
    project_id = _project(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/generation-plan", headers=_auth_headers()
    )
    assert response.status_code == 200

    from src.db.models import ImageGenerationJobRecord

    assert db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == project_id
    ).count() == 0


def test_ux2e0_keeps_direct_input_when_link_is_blocked_and_provider_contract_is_typed(client, db_session):
    project_id = _project(client, product_url="https://blocked.example.test/product")
    fact = ProductFact(
        project_id=project_id, fact_text="정격 소비전력 8W", verification_status="seller_confirmed",
        needs_review=False, field_key="rated_power", normalized_value="8", normalized_unit="W",
    )
    db_session.add(fact)
    db_session.commit()

    response = client.post(f"/api/v1/projects/{project_id}/generation-plan", headers=_auth_headers())
    assert response.status_code == 200
    plan = response.json()
    assert plan["product_brief"]["seller_input"]
    assert any(item["kind"] == "link" and item["status"] == "reference_only" for item in plan["product_brief"]["source_states"])

    request = GenerationJobRequestSchema(
        request_id="ux2e0-request", project_id=project_id, plan_version=plan["version"], scene_id=plan["scenes"][0]["id"],
        product_brief=plan["product_brief"], reference_asset_ids=[], prompt_blueprint=plan["scenes"][0]["prompt_blueprint"],
        output_spec=GenerationOutputSpecSchema(kind="generated_image", width=1024, height=1024, format="png"), seller_approved=False,
    )
    try:
        UnconfiguredGenerationProvider().submit(request)
        assert False, "provider must not synthesize a generated result when unconfigured"
    except ProviderNotConnectedError:
        pass
