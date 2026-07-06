from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from src.db.models import ProductProject, Asset

def test_get_sales_strategy_api_success(client: TestClient, db_session: Session):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }

    # 1. Create kids product project
    proj = ProductProject(
        id="proj-strategy-kids",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="어린이용 아기 매트",
        raw_input_text="안전하고 튼튼한 장난감 놀이 매트입니다.",
        status="draft",
        current_step="raw_input",
    )
    
    # 2. Add an image asset to verify image selection high confidence
    asset = Asset(
        id="asset-strategy-1",
        project_id="proj-strategy-kids",
        source_type="uploaded",
        filename="kids_mat.jpg",
        file_path="uploads/kids_mat.jpg",
        mime_type="image/jpeg",
        file_size=1024,
    )
    db_session.add(proj)
    db_session.add(asset)
    db_session.commit()

    # 3. Request Sales Strategy API
    resp = client.get(
        "/api/v1/projects/proj-strategy-kids/sales-strategy",
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    
    # Assert kids strategy values
    assert "부모" in data["target_customer"]
    assert "안전" in data["main_selling_point"]
    assert data["price_strategy"] == "N/A"
    assert "kids_mat.jpg" in data["image_selection"]
    
    # Verify confirmation rows
    rows = data["confirmation_rows"]
    assert len(rows) == 5
    
    # No actual price or promotion was provided, so the service must ask.
    price_row = next(r for r in rows if r["field_key"] == "price_strategy")
    assert price_row["confidence"] == "low"
    assert "없습니다" in price_row["suggested_value"]
    
    # Assert image row has high confidence because asset is uploaded
    image_row = next(r for r in rows if r["field_key"] == "image_selection")
    assert image_row["confidence"] == "high"
    assert "kids_mat.jpg" in image_row["suggested_value"]

    # Verify direction variants
    directions = data["directions"]
    assert len(directions) == 3
    # Kids product defaults to persuasion recommended
    persuasion = next(d for d in directions if d["key"] == "persuasion")
    assert persuasion["is_recommended"] is True


def test_get_sales_strategy_api_missing_price_and_image(client: TestClient, db_session: Session):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }

    # Create general product without assets and without price details
    proj = ProductProject(
        id="proj-strategy-general",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="일반 물품",
        raw_input_text="그저 평범한 상품의 상세 설명입니다.",
        status="draft",
        current_step="raw_input",
    )
    db_session.add(proj)
    db_session.commit()

    resp = client.get(
        "/api/v1/projects/proj-strategy-general/sales-strategy",
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    
    rows = data["confirmation_rows"]
    
    # Assert price row is low confidence
    price_row = next(r for r in rows if r["field_key"] == "price_strategy")
    assert price_row["confidence"] == "low"
    assert "없습니다" in price_row["suggested_value"]
    
    # Assert image row is low confidence
    image_row = next(r for r in rows if r["field_key"] == "image_selection")
    assert image_row["confidence"] == "low"
    assert "없습니다" in image_row["suggested_value"]


def test_confirm_sales_strategy_persists_edits_and_maps_direction(client: TestClient, db_session: Session):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }
    project = ProductProject(
        id="proj-strategy-confirm",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="확정 전략 상품",
        raw_input_text="사용자가 전략을 수정하는 상품",
        status="draft",
        current_step="facts_verification",
        intake_snapshot={"intake": {"description": "원본 설명"}},
    )
    db_session.add(project)
    db_session.commit()

    payload = {
        "target_customer": "직접 수정한 고객",
        "buyer_problem": "직접 수정한 구매 고민",
        "main_selling_point": "직접 수정한 핵심 소구점",
        "supporting_points": ["확인된 보조 근거"],
        "tone": "직접 수정한 톤",
        "price_strategy": "할인 없이 정가 판매",
        "image_selection": [],
        "risk_notes": ["인증 정보 확인 필요"],
        "selected_direction": "emotional",
    }
    response = client.post(
        "/api/v1/projects/proj-strategy-confirm/sales-strategy/confirm",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 200
    db_session.refresh(project)
    assert project.selected_style == "lifestyle"
    assert project.intake_snapshot["confirmed_sales_strategy"]["target_customer"] == "직접 수정한 고객"
    assert project.intake_snapshot["confirmed_sales_strategy"]["selected_direction"] == "emotional"
