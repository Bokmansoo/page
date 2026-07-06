import pytest
from unittest.mock import patch, MagicMock
import httpx
from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import Asset, ProductProject
from src.services.ai_adapter import AIResponse, ExtractedFactSchema, ExtractionResultSchema



@pytest.fixture
def setup_project(client):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    payload = {
        "name": "Fact Test Product",
        "brand_id": DEFAULT_BRAND_ID,
        "raw_input_text": "Spec: Width 100cm, Height 50cm, Depth 20cm."
    }
    res = client.post("/api/v1/projects", json=payload, headers=headers)
    assert res.status_code == 201
    return res.json()["id"]


def test_create_and_list_facts(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # 1. Create a fact
    payload = {
        "fact_text": "???곹뭹??媛濡?湲몄씠??100cm?낅땲??",
        "source_text": "Width 100cm"
    }
    res = client.post(f"/api/v1/projects/{project_id}/facts", json=payload, headers=headers)
    assert res.status_code == 201
    fact = res.json()
    assert fact["fact_text"] == "???곹뭹??媛濡?湲몄씠??100cm?낅땲??"
    assert fact["source_text"] == "Width 100cm"
    assert fact["verification_status"] == "unknown"
    fact_id = fact["id"]

    # 2. List facts
    list_res = client.get(f"/api/v1/projects/{project_id}/facts", headers=headers)
    assert list_res.status_code == 200
    facts_list = list_res.json()
    assert len(facts_list) == 1
    assert facts_list[0]["id"] == fact_id


def test_update_fact_and_verify_history(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # 1. Create a fact
    payload = {
        "fact_text": "???곹뭹???몃줈 湲몄씠??50cm?낅땲??",
        "source_text": "Height 50cm"
    }
    res = client.post(f"/api/v1/projects/{project_id}/facts", json=payload, headers=headers)
    assert res.status_code == 201
    fact_id = res.json()["id"]

    # 2. Update fact text and status
    update_payload = {
        "fact_text": "???곹뭹???ㅼ젣 ?믪씠??50cm?대ŉ 源딆씠??20cm?낅땲??",
        "verification_status": "confirmed"
    }
    update_res = client.patch(f"/api/v1/projects/{project_id}/facts/{fact_id}", json=update_payload, headers=headers)
    assert update_res.status_code == 200
    updated_fact = update_res.json()
    assert updated_fact["fact_text"] == "???곹뭹???ㅼ젣 ?믪씠??50cm?대ŉ 源딆씠??20cm?낅땲??"
    assert updated_fact["verification_status"] == "confirmed"

    # 3. Check history log
    history_res = client.get(f"/api/v1/projects/{project_id}/facts/{fact_id}/history", headers=headers)
    assert history_res.status_code == 200
    history = history_res.json()
    assert len(history) == 1
    assert history[0]["previous_fact_text"] == "???곹뭹???몃줈 湲몄씠??50cm?낅땲??"
    assert history[0]["previous_verification_status"] == "unknown"
    assert history[0]["updated_by"] == "user-1"


def test_fact_confirmed_filter(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # 1. Create one confirmed fact
    res1 = client.post(f"/api/v1/projects/{project_id}/facts", json={
        "fact_text": "媛二??쒗듃 ?뚯옱?낅땲??",
        "source_text": "Leather"
    }, headers=headers)
    assert res1.status_code == 201
    fact1_id = res1.json()["id"]

    # Mark as confirmed
    client.patch(f"/api/v1/projects/{project_id}/facts/{fact1_id}", json={"verification_status": "confirmed"}, headers=headers)

    # 2. Create one unknown fact
    res2 = client.post(f"/api/v1/projects/{project_id}/facts", json={
        "fact_text": "?먯궛吏???쒓뎅?낅땲??",
        "source_text": "Made in Korea"
    }, headers=headers)
    assert res2.status_code == 201

    # 3. Get all facts
    all_res = client.get(f"/api/v1/projects/{project_id}/facts", headers=headers)
    assert len(all_res.json()) == 2

    # 4. Get only confirmed facts
    confirmed_res = client.get(f"/api/v1/projects/{project_id}/facts?confirmed_only=true", headers=headers)
    assert confirmed_res.status_code == 200
    confirmed_list = confirmed_res.json()
    assert len(confirmed_list) == 1
    assert confirmed_list[0]["id"] == fact1_id


def test_delete_fact(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # 1. Create a fact
    res = client.post(f"/api/v1/projects/{project_id}/facts", json={
        "fact_text": "???곹뭹??源딆씠??20cm?낅땲??"
    }, headers=headers)
    assert res.status_code == 201
    fact_id = res.json()["id"]

    # 2. Delete the fact
    del_res = client.delete(f"/api/v1/projects/{project_id}/facts/{fact_id}", headers=headers)
    assert del_res.status_code == 204

    # 3. List facts (should be empty)
    list_res = client.get(f"/api/v1/projects/{project_id}/facts", headers=headers)
    assert len(list_res.json()) == 0


def test_reject_invalid_verification_status(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    res = client.post(f"/api/v1/projects/{project_id}/facts", json={
        "fact_text": "?곹뭹 ?됱긽? 釉붾옓?낅땲??"
    }, headers=headers)
    assert res.status_code == 201
    fact_id = res.json()["id"]

    update_res = client.patch(
        f"/api/v1/projects/{project_id}/facts/{fact_id}",
        json={"verification_status": "approved"},
        headers=headers,
    )

    assert update_res.status_code == 422


def test_fact_source_asset_must_belong_to_same_project(client, db_session, setup_project):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    project_id = setup_project

    other_project_res = client.post("/api/v1/projects", json={
        "name": "Other Product",
        "brand_id": DEFAULT_BRAND_ID,
        "raw_input_text": "Other source"
    }, headers=headers)
    assert other_project_res.status_code == 201
    other_project_id = other_project_res.json()["id"]

    other_asset = Asset(
        project_id=other_project_id,
        source_type="sourced",
        filename="other-product.jpg",
        file_path="uploads/other-product.jpg",
        mime_type="image/jpeg",
        file_size=1234,
    )
    db_session.add(other_asset)
    db_session.commit()
    db_session.refresh(other_asset)

    create_res = client.post(f"/api/v1/projects/{project_id}/facts", json={
        "fact_text": "?곹뭹 ?대?吏???ㅻⅨ ?꾨줈?앺듃 ?먯궛??洹쇨굅濡??쇱쓣 ???놁뒿?덈떎.",
        "source_asset_id": other_asset.id,
    }, headers=headers)

    assert create_res.status_code == 400
    assert create_res.json()["detail"] == "Source asset does not belong to this project"


def test_auto_extract_creates_reviewable_fact_candidates_from_manual_text(client):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    payload = {
        "name": "Portable Cooling Fan",
        "brand_id": DEFAULT_BRAND_ID,
        "raw_input_text": (
            "USB-C charging supported. 3 wind speeds. Foldable stand. "
            "Battery capacity 4000mAh. Weight 180g. Color white."
        )
    }
    project_res = client.post("/api/v1/projects", json=payload, headers=headers)
    assert project_res.status_code == 201
    project_id = project_res.json()["id"]

    res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)

    assert res.status_code == 201
    body = res.json()
    assert body["project_id"] == project_id
    assert body["created_count"] >= 5
    assert body["skipped_duplicates"] == 0
    assert body["failed_sources"] == []
    assert len(body["facts"]) == body["created_count"]
    assert all(fact["verification_status"] in {"unknown", "needs_revision"} for fact in body["facts"])
    assert all(fact["needs_review"] is True for fact in body["facts"])
    assert {fact["extraction_source"] for fact in body["facts"]} == {"manual_text"}


def test_auto_extract_skips_duplicate_candidates(client):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    project_res = client.post("/api/v1/projects", json={
        "name": "Duplicate Fact Product",
        "brand_id": DEFAULT_BRAND_ID,
        "raw_input_text": "USB-C charging supported. 3 wind speeds. Foldable stand. Battery capacity 4000mAh. Weight 180g."
    }, headers=headers)
    assert project_res.status_code == 201
    project_id = project_res.json()["id"]

    first_res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)
    assert first_res.status_code == 201
    first_created = first_res.json()["created_count"]
    assert first_created >= 5

    second_res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)
    assert second_res.status_code == 201
    second_body = second_res.json()
    assert second_body["created_count"] == 0
    assert second_body["skipped_duplicates"] >= first_created


def test_auto_extract_reports_url_fallback_without_failing(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    project_res = client.post("/api/v1/projects", json={
        "name": "URL Fallback Product",
        "brand_id": DEFAULT_BRAND_ID,
        "raw_input_text": "Material silicone. BPA free. Microwave safe. Dishwasher safe. Capacity 500ml."
    }, headers=headers)
    assert project_res.status_code == 201
    project_id = project_res.json()["id"]
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).first()
    project.raw_input_url = "https://supplier.example.com/product/123"
    db_session.commit()

    res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)

    assert res.status_code == 201
    body = res.json()
    assert body["created_count"] >= 5
    assert body["failed_sources"] == [
        {
            "source": "url",
            "reason": "web_browsing_api_key_missing",
            "message": "AI web browsing fallback failed: web_browsing_api_key_missing",
        }
    ]


def test_auto_extract_creates_image_asset_candidate(client, db_session, setup_project):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    project_id = setup_project
    asset = Asset(
        project_id=project_id,
        source_type="sourced",
        filename="cooling-fan-detail.jpg",
        file_path="uploads/cooling-fan-detail.jpg",
        mime_type="image/jpeg",
        file_size=2048,
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)

    assert res.status_code == 201
    body = res.json()
    image_facts = [fact for fact in body["facts"] if fact["extraction_source"] == "image"]
    assert image_facts
    assert image_facts[0]["source_asset_id"] == asset.id
    assert "cooling-fan-detail.jpg" in image_facts[0]["source_text"]


def test_auto_extract_uses_image_ocr_text_for_fact_candidates(client, db_session, setup_project):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    project_id = setup_project
    asset = Asset(
        project_id=project_id,
        source_type="sourced",
        filename="portable_fan_4000mah_usb_c_spec.jpg",
        file_path="uploads/portable_fan_4000mah_usb_c_spec.jpg",
        mime_type="image/jpeg",
        file_size=2048,
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)

    assert res.status_code == 201
    body = res.json()
    image_facts = [fact for fact in body["facts"] if fact["source_asset_id"] == asset.id]
    assert any("USB-C" in fact["fact_text"] for fact in image_facts)
    assert any("4000mAh" in fact["fact_text"] for fact in image_facts)


def test_bulk_create_facts_deduplicates_existing_fact(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # 1. 湲곗〈 ?⑥씪 ?⑺듃 ?앹꽦
    client.post(
        f"/api/v1/projects/{project_id}/facts",
        json={
            "fact_text": "4,800mAh 諛고꽣由щ? ?묒옱?덉뒿?덈떎.",
            "source_text": "4,800mAh battery",
        },
        headers=headers,
    )

    # 2. ?쇨큵 ?앹꽦 ?붿껌
    response = client.post(
        f"/api/v1/projects/{project_id}/facts/bulk",
        json={
            "items": [
                {
                    "fact_text": "4,800mAh 諛고꽣由щ? ?묒옱?덉뒿?덈떎.",
                    "source_text": "4,800mAh battery",
                },
                {
                    "fact_text": "理쒕? 18?쒓컙 臾댁꽑 ?ъ슜??媛?ν빀?덈떎.",
                    "source_text": "理쒕? 18?쒓컙 臾댁꽑 ?ъ슜",
                },
                {
                    "fact_text": "FAN JET ULTRA 紐⑤뜽?낅땲??",
                    "source_text": "FAN JET ULTRA",
                },
            ],
            "default_status": "confirmed",
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] == 2
    assert body["duplicate_count"] == 1
    assert len(body["created"]) == 2
    
    # 3. Verify the full fact list contains the expected confirmed facts.
    list_res = client.get(f"/api/v1/projects/{project_id}/facts", headers=headers)
    facts = list_res.json()
    assert len(facts) == 3
    confirmed_facts = [f for f in facts if f["verification_status"] == "confirmed"]
    assert len(confirmed_facts) == 2


def test_bulk_create_facts_rejects_empty_items(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    response = client.post(
        f"/api/v1/projects/{project_id}/facts/bulk",
        json={
            "items": [],
            "default_status": "unknown",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Items size must be between 1 and 50"


def test_bulk_create_facts_rejects_more_than_fifty_items(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    response = client.post(
        f"/api/v1/projects/{project_id}/facts/bulk",
        json={
            "items": [
                {
                    "fact_text": f"Bulk fact {index}",
                    "source_text": f"Bulk source {index}",
                }
                for index in range(51)
            ],
            "default_status": "unknown",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Items size must be between 1 and 50"


def test_bulk_create_facts_counts_blank_fact_as_failed(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    response = client.post(
        f"/api/v1/projects/{project_id}/facts/bulk",
        json={
            "items": [
                {
                    "fact_text": "   ",
                    "source_text": "blank fact should not be created",
                },
                {
                    "fact_text": "4,800mAh battery is included.",
                    "source_text": "4,800mAh battery",
                },
            ],
            "default_status": "needs_revision",
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] == 1
    assert body["failed_count"] == 1
    assert body["duplicate_count"] == 0
    assert body["created"][0]["verification_status"] == "needs_revision"

    list_res = client.get(f"/api/v1/projects/{project_id}/facts", headers=headers)
    assert list_res.status_code == 200
    facts = list_res.json()
    assert len(facts) == 1
    assert facts[0]["fact_text"] == "4,800mAh battery is included."


def test_bulk_create_facts_uses_fact_text_as_source_when_source_is_blank(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    response = client.post(
        f"/api/v1/projects/{project_id}/facts/bulk",
        json={
            "items": [
                {
                    "fact_text": "Maximum wireless runtime is 18 hours.",
                    "source_text": "   ",
                },
            ],
            "default_status": "confirmed",
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] == 1
    assert body["created"][0]["source_text"] == "Maximum wireless runtime is 18 hours."


def test_parse_bulk_facts_returns_backend_candidates_with_full_source_context(client, setup_project):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    pasted_text = """
    모델명: FAN JET ULTRA
    무료배송
    배터리: 4,800mAh
    구매후기 1,234개
    최대 18시간 무선 사용 가능
    """

    response = client.post(
        f"/api/v1/projects/{project_id}/facts/bulk/parse",
        json={"text": pasted_text},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["candidate_count"] == 3
    assert body["excluded_count"] >= 2
    assert [item["fact_text"] for item in body["items"]] == [
        "모델명: FAN JET ULTRA",
        "배터리: 4,800mAh",
        "최대 18시간 무선 사용 가능",
    ]
    assert all("전체 붙여넣기 원문:" in item["source_text"] for item in body["items"])
    assert all("추출 후보:" in item["source_text"] for item in body["items"])


def test_auto_extract_uses_url_source_text_for_fact_candidates(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    
    # 1. ?꾨줈?앺듃 ?앹꽦
    project_res = client.post("/api/v1/projects", json={
        "name": "URL Source Product",
        "brand_id": DEFAULT_BRAND_ID,
    }, headers=headers)
    assert project_res.status_code == 201
    project_id = project_res.json()["id"]
    
    # DB ?몄뀡???듯빐 raw_input_url ?섏젙
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).first()
    project.raw_input_url = "https://example.com/product/spec"
    db_session.commit()

    # 2. URL ?섏쭛 ?깃났 ?쒕굹由ъ삤 Mocking
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = "<html><body><h1>Example Item</h1><p>Battery capacity 4000mAh. Foldable stand.</p></body></html>"

    with patch("httpx.get", return_value=mock_response):
        # 3. auto-extract API ?몄텧
        res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)
        assert res.status_code == 201
        body = res.json()
        
        # 4. 寃利? URL ?섏쭛 寃곌낵 ?띿뒪?몃? 湲곕컲?쇰줈 ?ъ떎 移대뱶媛 異붿텧?섏뿀?붿? ?뺤씤
        assert body["created_count"] > 0
        url_facts = [fact for fact in body["facts"] if fact["extraction_source"] == "url"]
        assert len(url_facts) > 0
        assert any("4000mAh" in fact["fact_text"] for fact in url_facts)


def test_auto_extract_reports_url_failure_gracefully(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    
    # 1. ?꾨줈?앺듃 ?앹꽦
    project_res = client.post("/api/v1/projects", json={
        "name": "URL Fail Product",
        "brand_id": DEFAULT_BRAND_ID,
    }, headers=headers)
    assert project_res.status_code == 201
    project_id = project_res.json()["id"]
    
    # DB ?몄뀡???듯빐 raw_input_url ?섏젙
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).first()
    project.raw_input_url = "https://coupang.com/forbidden"
    db_session.commit()

    # 2. 403 李⑤떒 ?묐떟 ?쒕굹由ъ삤 Mocking
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 403
    mock_response.text = "Forbidden"

    with patch("httpx.get", return_value=mock_response):
        res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)
        assert res.status_code == 201
        body = res.json()
        # ?ㅽ뙣 紐⑸줉??url ?섏쭛 ?ㅽ뙣 ?뺣낫媛 ?쒕윭?섏빞 ??        assert body["failed_sources"]
        assert any(failed["source"] == "url" and failed["reason"] == "web_browsing_api_key_missing" for failed in body["failed_sources"])


def test_auto_extract_uses_openai_adapter_when_api_key_is_configured(client, db_session, monkeypatch):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    project_res = client.post("/api/v1/projects", json={
        "name": "Real AI Fan",
        "brand_id": DEFAULT_BRAND_ID,
        "raw_input_text": "Portable fan with 4,800mAh battery and USB-C charging.",
    }, headers=headers)
    assert project_res.status_code == 201
    project_id = project_res.json()["id"]

    class FakeOpenAIAdapter:
        def extract_facts(self, raw_text, image_urls=None):
            assert "4,800mAh battery" in raw_text
            return AIResponse(
                data=ExtractionResultSchema(
                    product_name="Real AI Fan",
                    recommended_category="Living",
                    facts=[
                        ExtractedFactSchema(
                            fact_text="???곹뭹? 4,800mAh 諛고꽣由щ? ?묒옱?덉뒿?덈떎.",
                            source_text="4,800mAh battery",
                        ),
                        ExtractedFactSchema(
                            fact_text="???곹뭹? USB-C 異⑹쟾??吏?먰빀?덈떎.",
                            source_text="USB-C charging",
                        ),
                    ],
                ),
                provider="openai",
                model_name="gpt-test",
                input_tokens=100,
                output_tokens=40,
                duration_ms=123,
            )

    monkeypatch.setattr("src.services.llm_router.settings.OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("src.services.llm_router.OpenAIAdapter", lambda *args, **kwargs: FakeOpenAIAdapter())

    res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)

    assert res.status_code == 201
    body = res.json()
    assert body["created_count"] == 2
    assert body["failed_sources"] == []
    assert {fact["extraction_source"] for fact in body["facts"]} == {"ai"}
    assert {fact["verification_status"] for fact in body["facts"]} == {"unknown"}
    assert all(fact["needs_review"] is True for fact in body["facts"])


def test_auto_extract_falls_back_when_openai_adapter_fails(client, monkeypatch):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    project_res = client.post("/api/v1/projects", json={
        "name": "Fallback AI Fan",
        "brand_id": DEFAULT_BRAND_ID,
        "raw_input_text": "USB-C charging supported. Battery capacity 4000mAh.",
    }, headers=headers)
    assert project_res.status_code == 201
    project_id = project_res.json()["id"]

    class FailingOpenAIAdapter:
        def extract_facts(self, raw_text, image_urls=None):
            raise RuntimeError("provider timeout")

    monkeypatch.setattr("src.services.llm_router.settings.OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("src.services.llm_router.OpenAIAdapter", lambda *args, **kwargs: FailingOpenAIAdapter())

    res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)

    assert res.status_code == 201
    body = res.json()
    assert body["created_count"] >= 1
    assert any(failed["source"] == "ai" and failed["reason"] == "ai_adapter_failed" for failed in body["failed_sources"])
    assert all(fact["verification_status"] in {"unknown", "needs_revision"} for fact in body["facts"])


def test_auto_extract_uses_web_browsing_when_url_fetch_is_blocked(client, db_session, setup_project, monkeypatch):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).first()
    project.name = "Lumena portable wireless cooling fan"
    project.raw_input_url = "https://www.coupang.com/vp/products/example"
    project.raw_input_text = ""
    db_session.commit()

    from src.services.source_collector import URLCollectionResult
    from src.services.web_browsing_collector import WebBrowsingCollectionResult

    monkeypatch.setattr(
        "src.services.source_collector.fetch_url_source",
        lambda url: URLCollectionResult(
            ok=False,
            url=url,
            host="www.coupang.com",
            text="",
            status_code=403,
            failure_reason="blocked_or_forbidden",
        ),
    )

    class FakeWebCollector:
        def collect(self, url, product_name=None):
            return WebBrowsingCollectionResult(
                ok=True,
                text="4,800mAh 諛고꽣由ъ? 理쒕? 18?쒓컙 臾댁꽑 ?ъ슜 媛???뺣낫媛 ?뺤씤?섏뿀?듬땲??",
                provider="openai",
                model="gpt-5.4-nano",
            )

    monkeypatch.setattr("src.services.source_collector.WebBrowsingCollector", lambda: FakeWebCollector())

    response = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] >= 1
    assert any("4,800mAh" in fact["source_text"] for fact in body["facts"])

