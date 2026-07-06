from src.services.intake_structuring_service import structure_intake


def test_structure_intake_extracts_basic_fields_from_freeform_text():
    draft = structure_intake(
        {
            "freeform_input": (
                "아이 첫 자전거입니다. LED 조명이 있고 보조바퀴 탈착 가능해요. "
                "가격은 39,900원이고 무료배송입니다. 안전하고 감성적인 느낌으로 만들어주세요."
            ),
            "product_name": "",
            "description": "",
            "product_url": "",
            "reference_urls": [],
            "desired_mood": "",
            "asset_ids": [],
        }
    )

    assert draft["product_name"]["value"] == "아이 첫 자전거"
    assert {"text": "LED 조명", "source": "freeform_input", "confidence": "needs_review"} in draft["selling_points"]
    assert {"text": "보조바퀴 탈착 가능", "source": "freeform_input", "confidence": "needs_review"} in draft["selling_points"]
    assert draft["price"]["value"] == "39,900원"
    assert draft["shipping"]["value"] == "무료배송"
    assert "안전한" in draft["desired_mood"]
    assert "감성적인" in draft["desired_mood"]


def test_structure_intake_prefers_explicit_fields_over_freeform_guess():
    draft = structure_intake(
        {
            "freeform_input": "아이 첫 자전거입니다. 가격은 39,900원입니다.",
            "product_name": "베이비 라이트 밸런스 바이크",
            "description": "LED 라이트와 탈착형 보조바퀴가 있는 유아용 자전거",
            "product_url": "https://example.com/products/bike",
            "reference_urls": ["https://example.com/reference"],
            "desired_mood": "프리미엄, 안전한",
            "asset_ids": ["asset-1"],
        }
    )

    assert draft["product_name"] == {
        "value": "베이비 라이트 밸런스 바이크",
        "source": "explicit_field",
        "confidence": "confirmed",
    }
    assert draft["product_url"]["value"] == "https://example.com/products/bike"
    assert draft["reference_urls"] == ["https://example.com/reference"]
    assert "프리미엄" in draft["desired_mood"]


def test_structure_intake_api(client):
    response = client.post(
        "/api/agent-runs/structure-intake",
        json={
            "freeform_input": "아이 첫 자전거입니다. LED 조명이 있습니다. 가격은 39,900원입니다.",
            "asset_ids": [],
        },
        headers={
            "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["product_name"]["value"] == "아이 첫 자전거"
    assert data["price"]["value"] == "39,900원"
