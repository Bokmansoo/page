import base64
from unittest.mock import patch

import pytest

from src.api.agent_runs import _collection_failure_code
from src.db.models import AgentRun, Asset, PageSection, ProductFact, ProductPage, ProductProject, SourceCapture
from src.services.url_evidence_collector import URLEvidence
from src.services.seller_fact_ingestion_service import (
    display_seller_spec,
    extract_confirmed_seller_specs,
    relink_legacy_seller_specs,
)


AUTH_HEADERS = {
    "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
}

ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Jv5QAAAAASUVORK5CYII="
)


def _image_asset(project_id: str, asset_id: str, source_type: str = "self_shot") -> Asset:
    return Asset(
        id=asset_id,
        project_id=project_id,
        source_type=source_type,
        usage_status="reference_only" if source_type == "sourced" else "seller_owned",
        filename=f"{asset_id}.jpg",
        file_path=f"/tmp/{asset_id}.jpg",
        mime_type="image/jpeg",
        file_size=100,
        quality_status="usable",
        quality_warnings=[],
    )


def test_three_input_paths_share_the_immutable_intake_contract(client, db_session):
    direct = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={
            "product_name": "자체 촬영 상품",
            "description": "무게 260g",
            "sales_channel": "스마트스토어",
            "model_options": "그레이",
        },
    )
    assert direct.status_code == 201

    with patch(
        "src.api.agent_runs.collect_url_evidence",
        return_value=URLEvidence(
            url="https://detail.1688.com/offer/123.html",
            title="해외 소싱 마사지 베개",
            image_urls=["https://images.example.com/main.jpg"],
            specs=[{"label": "배터리", "value": "2000mAh"}],
        ),
    ):
        overseas = client.post(
            "/api/agent-runs",
            headers=AUTH_HEADERS,
            json={"product_url": "https://detail.1688.com/offer/123.html", "description": "2000mAh"},
        )
    assert overseas.status_code == 201

    with patch("src.api.agent_runs.collect_url_evidence", side_effect=RuntimeError("403 Forbidden")):
        domestic = client.post(
            "/api/agent-runs",
            headers=AUTH_HEADERS,
            json={"product_name": "국내 소싱 상품", "product_url": "https://www.coupang.com/vp/products/1", "description": "사용 시간 10분"},
        )
    assert domestic.status_code == 201

    for response in (direct, overseas, domestic):
        project = db_session.query(ProductProject).filter(ProductProject.id == response.json()["project_id"]).one()
        bundle = project.intake_snapshot["input_bundle"]
        assert {"product_name", "asset_ids", "asset_records", "source_captures"} <= set(bundle)
        assert project.intake_snapshot.get("input_bundle_locked") is None

    overseas_project_id = overseas.json()["project_id"]
    overseas_asset = db_session.query(Asset).filter(Asset.project_id == overseas_project_id).one()
    assert overseas_asset.source_type == "url-extracted"
    assert overseas_asset.usage_status == "reference_only"
    failed_capture = db_session.query(SourceCapture).filter(SourceCapture.project_id == domestic.json()["project_id"]).one()
    assert (failed_capture.collection_status, failed_capture.failure_code) == ("access_limited", "http_403")
    assert domestic.json()["input_guidance"]


def test_intake_bundle_preserves_five_image_order_rights_and_numeric_units(client, db_session):
    created = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={
            "product_name": "YL-T02 마사지 베개",
            "description": "무게 260g, 사용 시간 10분, 배터리 800mAh, 온도 42°C",
            "model_options": "YL-T01 / YL-T02, 그레이",
        },
    )
    assert created.status_code == 201
    run_id, project_id = created.json()["id"], created.json()["project_id"]
    assets = [
        _image_asset(project_id, "direct-main", "self_shot"),
        _image_asset(project_id, "licensed-detail", "uploaded"),
        _image_asset(project_id, "supplier-reference", "sourced"),
        _image_asset(project_id, "direct-usage", "self_shot"),
        _image_asset(project_id, "licensed-spec", "uploaded"),
    ]
    db_session.add_all(assets)
    db_session.commit()
    order = ["direct-usage", "supplier-reference", "direct-main", "licensed-spec", "licensed-detail"]

    saved = client.patch(f"/api/agent-runs/{run_id}/input-assets", headers=AUTH_HEADERS, json={"asset_ids": order})
    assert saved.status_code == 200
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).one()
    bundle = project.intake_snapshot["input_bundle"]
    assert bundle["asset_ids"] == order
    assert [item["order"] for item in bundle["asset_records"]] == [1, 2, 3, 4, 5]
    db_session.expire_all()
    persisted_assets = db_session.query(Asset).filter(Asset.project_id == project_id).all()
    assert {asset.id: asset.intake_order for asset in persisted_assets} == {
        asset_id: index for index, asset_id in enumerate(order, start=1)
    }
    assert bundle["asset_records"][1]["usage_status"] == "reference_only"
    assert project.intake_snapshot["input_bundle_locked"] is True
    assert client.patch(f"/api/agent-runs/{run_id}/input-assets", headers=AUTH_HEADERS, json={"asset_ids": order}).status_code == 409

    facts = db_session.query(ProductFact).filter(ProductFact.project_id == project_id).all()
    assert {fact.source_text for fact in facts} >= {"260g", "10분", "800mAh", "42°C"}
    assert {fact.verification_status for fact in facts} == {"seller_confirmed"}


def test_intake_assets_reject_cross_workspace_and_more_than_twenty(client, db_session):
    created = client.post("/api/agent-runs", headers=AUTH_HEADERS, json={"product_name": "소유권 확인 상품"}).json()
    foreign = client.post(
        "/api/agent-runs",
        headers={**AUTH_HEADERS, "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000099"},
        json={"product_name": "다른 워크스페이스 상품"},
    ).json()
    foreign_asset = _image_asset(foreign["project_id"], "foreign-workspace-image")
    db_session.add(foreign_asset)
    db_session.commit()

    rejected = client.patch(
        f"/api/agent-runs/{created['id']}/input-assets",
        headers=AUTH_HEADERS,
        json={"asset_ids": [foreign_asset.id]},
    )
    assert rejected.status_code == 422
    too_many = client.patch(
        f"/api/agent-runs/{created['id']}/input-assets",
        headers=AUTH_HEADERS,
        json={"asset_ids": [f"image-{index}" for index in range(21)]},
    )
    assert too_many.status_code == 422


def test_input_bundle_finalization_enforces_minimum_seller_input(client, db_session):
    created = client.post("/api/agent-runs", headers=AUTH_HEADERS, json={"product_name": "최소 입력 확인"}).json()
    image = _image_asset(created["project_id"], "minimum-input-image")
    db_session.add(image)
    db_session.commit()

    missing_fact = client.patch(
        f"/api/agent-runs/{created['id']}/input-assets",
        headers=AUTH_HEADERS,
        json={"asset_ids": [image.id]},
    )
    assert missing_fact.status_code == 422
    assert "seller-confirmed" in missing_fact.json()["detail"]

    missing_image_run = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={"product_name": "대표 사진 누락", "description": "무게 260g"},
    ).json()
    missing_image = client.patch(
        f"/api/agent-runs/{missing_image_run['id']}/input-assets",
        headers=AUTH_HEADERS,
        json={"asset_ids": []},
    )
    assert missing_image.status_code == 422
    assert "representative product image" in missing_image.json()["detail"]


def test_source_capture_endpoint_is_workspace_scoped(client):
    with patch("src.api.agent_runs.collect_url_evidence", side_effect=RuntimeError("403 Forbidden")):
        created = client.post("/api/agent-runs", headers=AUTH_HEADERS, json={"product_name": "수집 상태 상품", "product_url": "https://example.com/product", "description": "10분"})
    project_id = created.json()["project_id"]
    captures = client.get(f"/api/v1/projects/{project_id}/source-captures", headers=AUTH_HEADERS)
    assert captures.status_code == 200
    assert captures.json()[0]["platform"] == "example.com"
    assert captures.json()[0]["attempted_at"]
    hidden = client.get(
        f"/api/v1/projects/{project_id}/source-captures",
        headers={**AUTH_HEADERS, "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000099"},
    )
    assert hidden.status_code == 404


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("403 Forbidden", "http_403"),
        ("Login required", "login_required"),
        ("CAPTCHA verify you are human", "captcha_required"),
        ("Dynamic page requires JavaScript", "dynamic_page"),
    ],
)
def test_expected_access_limits_have_stable_failure_codes(message, expected):
    assert _collection_failure_code(RuntimeError(message)) == expected


def test_upload_endpoint_persists_seller_rights_choice(client):
    created = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={"product_name": "권리 선택 상품", "description": "정격 출력 8W"},
    ).json()

    supplier = client.post(
        "/api/v1/files/upload",
        headers=AUTH_HEADERS,
        data={"project_id": created["project_id"], "source_type": "sourced"},
        files={"file": ("supplier.png", ONE_PIXEL_PNG, "image/png")},
    )
    owned = client.post(
        "/api/v1/files/upload",
        headers=AUTH_HEADERS,
        data={"project_id": created["project_id"], "source_type": "self_shot"},
        files={"file": ("owned.png", ONE_PIXEL_PNG, "image/png")},
    )

    assert supplier.status_code == 201
    assert supplier.json()["usage_status"] == "reference_only"
    assert owned.status_code == 201
    assert owned.json()["usage_status"] == "seller_owned"

    invalid = client.post(
        "/api/v1/files/upload",
        headers=AUTH_HEADERS,
        data={"project_id": created["project_id"], "source_type": "ai_generated"},
        files={"file": ("spoofed.png", ONE_PIXEL_PNG, "image/png")},
    )
    assert invalid.status_code == 422


def test_upload_endpoint_defaults_to_reference_only_until_seller_selects_rights(client):
    created = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={"product_name": "기본 권리 상태 상품", "description": "정격 출력 8W"},
    ).json()

    response = client.post(
        "/api/v1/files/upload",
        headers=AUTH_HEADERS,
        data={"project_id": created["project_id"]},
        files={"file": ("supplier-capture.png", ONE_PIXEL_PNG, "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["source_type"] == "sourced"
    assert response.json()["usage_status"] == "reference_only"


def test_empty_marketplace_shell_is_saved_as_access_limited(client, db_session):
    with patch(
        "src.api.agent_runs.collect_url_evidence",
        return_value=URLEvidence(
            url="https://detail.1688.com/offer/empty.html",
            title="로그인 페이지",
        ),
    ):
        created = client.post(
            "/api/agent-runs",
            headers=AUTH_HEADERS,
            json={
                "product_name": "수집 제한 확인 상품",
                "product_url": "https://detail.1688.com/offer/empty.html",
                "description": "사용 시간 10분",
            },
        )

    assert created.status_code == 201
    capture = db_session.query(SourceCapture).filter(
        SourceCapture.project_id == created.json()["project_id"]
    ).one()
    assert capture.collection_status == "access_limited"
    assert capture.failure_code == "no_extractable_evidence"
    assert created.json()["collection_warnings"]


def test_repeated_url_images_are_merged_without_duplicate_assets(client, db_session):
    repeated_image = "https://cdn.example.com/yl-t02-main.jpg"

    def fake_collect(url, **_kwargs):
        return URLEvidence(url=url, title="YL-T02", image_urls=[repeated_image])

    with patch("src.api.agent_runs.collect_url_evidence", side_effect=fake_collect):
        created = client.post(
            "/api/agent-runs",
            headers=AUTH_HEADERS,
            json={
                "product_name": "중복 URL 이미지 확인",
                "product_url": "https://detail.1688.com/offer/123.html",
                "reference_urls": ["https://supplier.example.com/same-product"],
                "description": "정격 출력 8W",
            },
        )

    assert created.status_code == 201
    assets = db_session.query(Asset).filter(Asset.project_id == created.json()["project_id"]).all()
    assert len(assets) == 1
    assert created.json()["product_input"]["asset_ids"] == [assets[0].id]
    assert db_session.query(SourceCapture).filter(SourceCapture.project_id == created.json()["project_id"]).count() == 2


def test_seller_spec_parser_preserves_electrical_labels_and_full_dimensions():
    specs = extract_confirmed_seller_specs(
        ["DC5V2A, 8W, 50/60Hz, 2000mAh, 10분, 42℃, 40*17*15cm"]
    )
    texts = {fact_text: source_text for fact_text, source_text in specs}

    assert any("정격 입력" in text and value == "DC 5V 2A" for text, value in texts.items())
    assert any("정격 소비전력" in text and value == "8W" for text, value in texts.items())
    assert any("제품 크기" in text and value == "40 × 17 × 15cm" for text, value in texts.items())

    display = display_seller_spec("판매자 제공 사양: 제품 크기는 40 × 17 × 15cm입니다.", "40×17×15cm", "seller_confirmed")
    assert display.label == "제품 크기"
    assert display.value == "40 × 17 × 15cm"
    assert display.provenance_label == "판매자 제공 정보"


def test_relink_legacy_seller_specs_prefers_full_dimensions_for_existing_pages(client, db_session):
    created = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={"product_name": "규격 보정 테스트", "description": "테스트"},
    )
    assert created.status_code == 201
    project_id = created.json()["project_id"]
    legacy = ProductFact(
        project_id=project_id,
        fact_text="이 상품의 크기는 15cm입니다.",
        source_text="15cm",
        verification_status="seller_confirmed",
        extraction_source="seller_input",
    )
    richer = ProductFact(
        project_id=project_id,
        fact_text="판매자 제공 사양: 제품 크기는 40 × 17 × 15cm입니다.",
        source_text="40 × 17 × 15cm",
        verification_status="seller_confirmed",
        extraction_source="seller_input",
    )
    page = ProductPage(project_id=project_id)
    db_session.add_all([legacy, richer, page])
    db_session.flush()
    section = PageSection(
        page_id=page.id,
        section_type="specifications",
        title="사양",
        associated_fact_ids=[legacy.id],
    )
    db_session.add(section)
    db_session.commit()

    assert relink_legacy_seller_specs(db_session, project_id) == 1
    db_session.commit()
    db_session.refresh(section)
    assert section.associated_fact_ids == [richer.id]
