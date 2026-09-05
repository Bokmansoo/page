from src.agents.mock_outputs import build_mock_copy_set, build_mock_page_assembly
from src.db.models import DetailPageVersion, FactEvidence, ProductFact, ProductPage
from src.services.page_readiness_service import inspect_page_readiness


def _auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def test_mock_copy_does_not_claim_unverified_assurances():
    copy = build_mock_copy_set("Neck massager", "USB-C charging product")
    rendered = " ".join(str(value).lower() for value in copy.values())

    for forbidden in ("certification", "warranty", "after-sales", "treatment"):
        assert forbidden not in rendered


def test_mock_page_contains_usage_section_and_never_uses_fake_asset_ids():
    page = build_mock_page_assembly(
        "Neck massager",
        uploaded_assets=[
            {"id": "supplier-1", "filename": "supplier.png", "source_type": "url-extracted"},
            {"id": "owned-1", "filename": "owned.png", "source_type": "uploaded"},
        ],
    )
    sections = page["sections"]

    assert any(section["visual_role"] == "usage_guide" for section in sections)
    assert {"feature_1", "feature_2", "feature_3"}.issubset(
        {section["section_type"] for section in sections}
    )
    assert all(not str(section.get("image_id") or "").startswith("mock-") for section in sections)
    assert "supplier-1" not in {section.get("image_id") for section in sections}
    assert "owned-1" in {section.get("image_id") for section in sections}


def test_ux2_mock_run_is_export_ready_without_scene_images(client, db_session):
    created = client.post(
        "/api/agent-runs",
        headers=_auth_headers(),
        json={"product_name": "Neck massager", "ux_auto_generate": True},
    ).json()
    response = client.post(
        f"/api/agent-runs/{created['id']}/run-mock", headers=_auth_headers()
    )
    assert response.status_code == 200

    db_session.expire_all()
    page = db_session.query(ProductPage).filter(
        ProductPage.project_id == created["project_id"]
    ).one()
    readiness = inspect_page_readiness(page, db_session)

    assert readiness.ready is True, [issue.code for issue in readiness.blockers]
    visible = sorted((section for section in page.sections if section.is_visible), key=lambda item: item.sort_order)
    assert visible[-1].section_type == "product_information"
    assert all(
        section.visual_kind == "html_graphic" or section.image_asset_id
        for section in visible
    )


def test_ux2_mock_run_builds_three_grounded_feature_cards_and_final_specs(client, db_session):
    created = client.post(
        "/api/agent-runs",
        headers=_auth_headers(),
        json={
            "product_name": "Neck massager",
            "ux_auto_generate": True,
        },
    ).json()
    for index, (field_key, value, unit) in enumerate(
        [("battery_capacity", "2000", "mAh"), ("rated_power", "8", "W"), ("usage_time", "10", "min")]
    ):
        fact = ProductFact(
            project_id=created["project_id"],
            fact_text=f"{field_key} {value}{unit}",
            source_text=f"{value}{unit}",
            verification_status="seller_confirmed",
            extraction_source="seller_input",
            field_key=field_key,
            normalized_value=value,
            normalized_unit=unit,
            needs_review=False,
        )
        db_session.add(fact)
        db_session.flush()
        db_session.add(FactEvidence(fact_id=fact.id, source_type="seller_input", original_text=f"{value}{unit}"))
    db_session.commit()
    response = client.post(
        f"/api/agent-runs/{created['id']}/run-mock", headers=_auth_headers()
    )
    assert response.status_code == 200

    db_session.expire_all()
    page = db_session.query(ProductPage).filter(
        ProductPage.project_id == created["project_id"]
    ).one()
    by_type = {section.section_type: section for section in page.sections}
    for section_type in ("feature_1", "feature_2", "feature_3"):
        payload = by_type[section_type].visual_payload
        assert payload["layout_variant"] == "benefit_cards"
        assert payload["cards"][0]["verification_status"] == "confirmed"
    assert by_type["product_information"].visual_payload["layout_variant"] == "spec_table"
    assert by_type["feature_1"].title == "배터리 용량"
    assert by_type["feature_1"].associated_fact_ids
    assert by_type["product_information"].title == "제품 사양·주의사항·필수 고지"
    assert by_type["product_information"].visual_payload["table_rows"][0]["label"] == "배터리 용량"
    assert set(by_type["usage_guide"].associated_fact_ids or []) == {
        fact.id for fact in db_session.query(ProductFact).filter(ProductFact.project_id == created["project_id"], ProductFact.field_key.in_(["rated_power", "usage_time"])).all()
    }

    original = db_session.query(DetailPageVersion).filter(
        DetailPageVersion.project_id == created["project_id"],
        DetailPageVersion.name == "AI 생성 상세페이지",
    ).one()
    restored = client.post(
        f"/api/v1/projects/{created['project_id']}/page/versions/{original.id}/restore",
        headers=_auth_headers(),
    )
    assert restored.status_code == 200
    db_session.expire_all()
    restored_page = db_session.query(ProductPage).filter(ProductPage.project_id == created["project_id"]).one()
    assert next(section for section in restored_page.sections if section.section_type == "feature_1").associated_fact_ids


def test_unsupported_copy_requires_then_records_reconfirmation(client, db_session):
    created = client.post(
        "/api/agent-runs", headers=_auth_headers(),
        json={"product_name": "마사지기", "ux_auto_generate": True},
    ).json()
    assert client.post(f"/api/agent-runs/{created['id']}/run-mock", headers=_auth_headers()).status_code == 200
    page = db_session.query(ProductPage).filter(ProductPage.project_id == created["project_id"]).one()
    sections = [
        {
            "id": section.id,
            "title": "통증 완화 마사지기" if section.section_type == "hero" else section.title,
            "body_copy": section.body_copy,
            "image_asset_id": section.image_asset_id,
            "visual_kind": section.visual_kind,
            "visual_payload": section.visual_payload,
            "sort_order": section.sort_order,
            "is_visible": section.is_visible,
        }
        for section in page.sections
    ]
    payload = {"theme_color": page.theme_color, "font_family": page.font_family, "sections": sections}
    blocked = client.patch(f"/api/v1/projects/{created['project_id']}/page", headers=_auth_headers(), json=payload)
    assert blocked.status_code == 422
    allowed = client.patch(
        f"/api/v1/projects/{created['project_id']}/page", headers=_auth_headers(),
        json={**payload, "confirm_unsupported_claims": True},
    )
    assert allowed.status_code == 200
    db_session.expire_all()
    hero = next(section for section in page.sections if section.section_type == "hero")
    assert hero.visual_payload["unsupported_claim_review"]["claims"] == ["통증 완화"]


def test_components_and_model_option_become_grounded_facts(client, db_session):
    created = client.post(
        "/api/agent-runs", headers=_auth_headers(),
        json={
            "product_name": "경추 마사지 베개",
            "model_options": "YL-T02",
            "components": "마사지 베개 본체, 충전 케이블, 사용 설명서",
            "description": "정격 입력 DC 5V 2A, 정격 소비전력 8W",
            "ux_auto_generate": True,
        },
    ).json()
    assert client.post(f"/api/agent-runs/{created['id']}/run-mock", headers=_auth_headers()).status_code == 200
    db_session.expire_all()
    page = db_session.query(ProductPage).filter(ProductPage.project_id == created["project_id"]).one()
    details = next(section for section in page.sections if section.section_type == "details_components")
    assert details.title == "구성품 확인"
    assert details.associated_fact_ids
    linked = db_session.query(ProductFact).filter(ProductFact.id.in_(details.associated_fact_ids)).all()
    assert linked[0].field_key == "components"
    assert "충전 케이블" in details.body_copy
