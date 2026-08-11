from src.db.models import Asset, AssetInspectionRecord, DetailPageVersion, ProductPage
from src.services.commerce_content_quality_service import _similar_copy, auto_placement_risk_codes, export_slug, inspect_content_quality, normalize_product_name
from src.services.rule_based_copy_service import build_rule_based_copy


def _headers():
    return {"X-Mock-User-Id": "00000000-0000-0000-0000-000000000001", "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002"}


def _page(client, db_session):
    created = client.post("/api/agent-runs", headers=_headers(), json={"product_name": "경추 마사지 베개", "ux_auto_generate": True}).json()
    assert client.post(f"/api/agent-runs/{created['id']}/run-mock", headers=_headers()).status_code == 200
    return created["project_id"], db_session.query(ProductPage).filter_by(project_id=created["project_id"]).one()


def test_ux2d_normalizes_pasted_specification_name():
    name, warnings = normalize_product_name("색상: 그레이 정격 입력: DC 5V 2A 배터리 용량: 2000mAh")
    assert name == "상세페이지"
    assert "product_name_looks_like_specification" in warnings
    assert len(export_slug("x" * 300)) <= 60
    fallback_name, fallback_warnings = normalize_product_name("", "12345678-project")
    assert fallback_name == "상세페이지-12345678"
    assert "product_name_fallback_used" in fallback_warnings
    one_spec_name, one_spec_warnings = normalize_product_name("정격 입력: DC 5V 2A", "12345678")
    assert one_spec_name == "상세페이지-12345678"
    assert "product_name_looks_like_specification" in one_spec_warnings


def test_short_fact_inside_full_spec_table_is_not_duplicate_copy():
    short_fact = "배터리 용량 2000mah"
    full_specs = "정격 입력 dc 5v 2a 배터리 용량 2000mah 제품 크기 40 17 15cm 정격 소비전력 8w"
    assert _similar_copy(short_fact, short_fact) is True
    assert _similar_copy(short_fact, full_specs) is False


def test_ux2d_quality_endpoint_reports_duplicate_and_foreign_text_then_acknowledges(client, db_session):
    project_id, page = _page(client, db_session)
    asset = Asset(project_id=project_id, source_type="uploaded", usage_status="seller_owned", filename="main.jpg", file_path="/tmp/main.jpg", mime_type="image/jpeg", file_size=1, asset_role="product_main", identity_status="confirmed", ocr_text="产品参数")
    db_session.add(asset); db_session.flush()
    hero = next(s for s in page.sections if s.section_type == "hero")
    pain = next(s for s in page.sections if s.section_type == "pain_point")
    hero.image_asset_id = asset.id; pain.image_asset_id = asset.id
    hero.title = pain.title = "구매 전 제품 정보 확인"
    db_session.commit()

    response = client.get(f"/api/v1/projects/{project_id}/page/content-quality", headers=_headers())
    assert response.status_code == 200
    codes = {item["code"] for item in response.json()["reviews"]}
    assert {"placeholder_copy", "duplicate_title", "duplicate_asset", "foreign_text_exposed"}.issubset(codes)

    acknowledged = client.post(f"/api/v1/projects/{project_id}/page/content-quality/acknowledge", headers=_headers(), json={"section_id": pain.id, "code": "foreign_text_exposed", "asset_id": asset.id})
    assert acknowledged.status_code == 200
    assert "foreign_text_exposed" not in {item["code"] for item in acknowledged.json()["reviews"] if item["section_id"] == pain.id}
    latest = db_session.query(DetailPageVersion).filter_by(project_id=project_id).order_by(DetailPageVersion.created_at.desc()).first()
    assert latest and latest.name == "판매용 품질 확인"
    acknowledgement = (pain.visual_payload or {}).get("ux2d_quality_acknowledgements", [])[0]
    assert acknowledgement["acknowledged_by"]
    assert acknowledgement["acknowledged_at"]
    assert latest.sections_json["ux2d_content_quality"]["product_name"] == "경추 마사지 베개"


def test_ux2d_detects_duplicate_hash_body_and_ocr_commercial_risks(client, db_session):
    project_id, page = _page(client, db_session)
    first = Asset(project_id=project_id, source_type="uploaded", usage_status="seller_owned", filename="factory-qr.jpg", file_path="/tmp/first.jpg", mime_type="image/jpeg", file_size=1, asset_role="product_main", identity_status="confirmed", content_hash="same-file", ocr_text="공장 문의 010-1234-5678 ¥88 QR")
    copy = Asset(project_id=project_id, source_type="uploaded", usage_status="seller_owned", filename="copy.jpg", file_path="/tmp/copy.jpg", mime_type="image/jpeg", file_size=1, asset_role="feature", identity_status="confirmed", content_hash="same-file")
    db_session.add_all([first, copy]); db_session.flush()
    hero = next(s for s in page.sections if s.section_type == "hero")
    feature = next(s for s in page.sections if s.section_type == "feature_1")
    hero.image_asset_id = first.id; feature.image_asset_id = copy.id
    hero.body_copy = feature.body_copy = "판매자가 확인한 제품 정보를 구매 전에 확인해 주세요."
    db_session.commit()

    report = inspect_content_quality(page, db_session)
    codes = {item["code"] for item in report["reviews"]}
    assert {"duplicate_asset_group", "duplicate_copy", "phone_number_exposed", "price_exposed", "qr_code_review", "supplier_text_exposed"}.issubset(codes)
    assert feature.id in report["section_copy_quality_codes"]


def test_ux2d1_auto_placement_checks_every_risk_code_and_latest_inspection_ocr(client, db_session):
    project_id, _ = _page(client, db_session)
    cases = {
        "foreign_text_exposed": "产品参数",
        "phone_number_exposed": "문의 010-1234-5678",
        "price_exposed": "₩39,900",
        "qr_code_review": "QR CODE",
        "market_or_competitor_text": "1688 상품",
        "supplier_text_exposed": "공장 직영",
    }
    for index, (expected_code, text) in enumerate(cases.items()):
        asset = Asset(
            id=f"risk-{index}", project_id=project_id, source_type="uploaded",
            usage_status="seller_owned", filename=f"risk-{index}.jpg",
            file_path=f"/tmp/risk-{index}.jpg", mime_type="image/jpeg", file_size=1,
            ocr_text=text,
        )
        db_session.add(asset)
        db_session.flush()
        assert expected_code in auto_placement_risk_codes(asset, db_session)

    inspection_only = Asset(
        id="inspection-risk", project_id=project_id, source_type="uploaded",
        usage_status="seller_owned", filename="inspection-risk.jpg",
        file_path="/tmp/inspection-risk.jpg", mime_type="image/jpeg", file_size=1,
    )
    db_session.add(inspection_only)
    db_session.flush()
    db_session.add(AssetInspectionRecord(
        project_id=project_id, asset_id=inspection_only.id, analysis_version=1,
        status="completed", ocr_blocks=[{"text": "旧记录"}],
    ))
    db_session.add(AssetInspectionRecord(
        project_id=project_id, asset_id=inspection_only.id, analysis_version=2,
        status="completed", ocr_blocks=[{"text": "最新 供应商"}],
    ))
    db_session.flush()
    assert "supplier_text_exposed" in auto_placement_risk_codes(inspection_only, db_session)


def test_ux2d1_upscaled_lineage_keeps_original_ocr_risk_and_counts_images_once(client, db_session):
    project_id, page = _page(client, db_session)
    source = Asset(
        id="source-risk", project_id=project_id, source_type="uploaded", usage_status="seller_owned",
        filename="source.jpg", file_path="/tmp/source.jpg", mime_type="image/jpeg", file_size=1,
        ocr_text="产品参数 공장 문의 010-1234-5678 ₩39,900 QR",
    )
    enhanced = Asset(
        id="enhanced-risk", project_id=project_id, source_type="local_upscaled", usage_status="seller_owned",
        filename="source-고화질보정.png", file_path="/tmp/enhanced.png", mime_type="image/png", file_size=1,
        source_asset_id=source.id,
    )
    db_session.add_all([source, enhanced])
    db_session.flush()
    hero = next(section for section in page.sections if section.section_type == "hero")
    hero.image_asset_id = enhanced.id
    hero.visual_kind = "image"
    hero.visual_payload = {
        "ux2d_quality_acknowledgements": [
            {"code": code, "asset_id": enhanced.id}
            for code in auto_placement_risk_codes(enhanced, db_session)
        ]
    }
    db_session.commit()

    report = inspect_content_quality(page, db_session)
    assert report["seller_confirmed_usage"] is True
    assert report["seller_confirmed_usage_count"] == 1
    assert not any(
        issue["code"] in {
            "foreign_text_exposed", "phone_number_exposed", "price_exposed",
            "qr_code_review", "supplier_text_exposed",
        }
        for issue in report["reviews"]
    )


def test_ux2d_rule_copy_keeps_each_feature_question_distinct():
    copy = build_rule_based_copy(
        "경추 마사지 베개",
        facts=[
            {"id": "battery", "field_key": "battery_capacity", "value": "2000", "unit": "mAh"},
            {"id": "input", "field_key": "rated_input", "value": "DC 5V 2A"},
            {"id": "time", "field_key": "single_operation_time", "value": "10", "unit": "분"},
        ],
    )
    titles = [copy["hero_title"], copy["painpoint_title"], copy["feature_1_title"], copy["feature_2_title"], copy["feature_3_title"]]
    assert len(set(titles)) == len(titles)
    assert "구매 전 제품 정보 확인" not in " ".join(str(value) for value in copy.values())
