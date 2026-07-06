from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from src.db.models import ProductProject, Asset, ProductFact

def test_submit_intake_and_get_understanding(client: TestClient, db_session: Session):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }

    # 1. Create product project
    proj = ProductProject(
        id="proj-intake-test",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="테스트용 상품",
        status="draft",
        current_step="raw_input",
    )
    db_session.add(proj)
    db_session.commit()

    # 2. Test empty intake input rejection (400)
    intake_payload_empty = {
        "urls": [],
        "description": "   ",
        "asset_ids": [],
        "reference_urls": [],
        "competitor_urls": []
    }
    resp = client.post(
        "/api/v1/projects/proj-intake-test/intake",
        json=intake_payload_empty,
        headers=headers
    )
    assert resp.status_code == 400
    assert "cannot be completely empty" in resp.json()["detail"]

    # 3. Test valid intake input submission
    intake_payload_valid = {
        "urls": ["  https://detail.1688.com/offer/12345.html  ", "https://detail.1688.com/offer/12345.html"],
        "description": "  이 상품은 오가닉 대나무 테이블 매트 상품입니다.  ",
        "asset_ids": ["asset-intake-1"],
        "reference_urls": ["https://competitor.com/item1"],
        "competitor_urls": []
    }
    
    # Create the asset in database first to simulate upload
    asset = Asset(
        id="asset-intake-1",
        project_id="proj-intake-test",
        source_type="uploaded",
        filename="bamboo_mat.jpg",
        file_path="uploads/bamboo_mat.jpg",
        mime_type="image/jpeg",
        file_size=5000,
    )
    db_session.add(asset)
    db_session.commit()

    resp = client.post(
        "/api/v1/projects/proj-intake-test/intake",
        json=intake_payload_valid,
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["raw_input_url"] == "https://detail.1688.com/offer/12345.html"
    assert data["raw_input_text"] == "이 상품은 오가닉 대나무 테이블 매트 상품입니다."

    # 4. Get understanding of the project (should detect "테이블 매트")
    resp_und = client.get(
        "/api/v1/projects/proj-intake-test/understanding",
        headers=headers
    )
    assert resp_und.status_code == 200
    und_data = resp_und.json()
    assert und_data["product_type"]["value"] == "테이블 매트"
    assert und_data["product_type"]["is_suggestion"] is False
    assert "친환경" in und_data["target_customer"]["value"]
    assert "식사 중" in und_data["buyer_problem"]["value"]
    assert len(und_data["main_angle_candidates"]) > 0
    assert len(und_data["tone_candidates"]) > 0
    # bamboo_mat.jpg image candidate should be returned
    assert "bamboo_mat.jpg" in und_data["image_candidates"]

    # Since there are no sizes in text/facts, "상세 규격 및 사이즈 정보" should be in unknowns
    assert "상세 규격 및 사이즈 정보" in und_data["unknowns"]


def _sprint42_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def _create_sprint42_project(db_session: Session, project_id: str) -> ProductProject:
    project = ProductProject(
        id=project_id,
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="brand-1",
        name="테스트용 상품",
        status="draft",
        current_step="raw_input",
    )
    db_session.add(project)
    db_session.commit()
    return project


def test_submit_intake_rejects_invalid_external_url(client: TestClient, db_session: Session):
    _create_sprint42_project(db_session, "proj-invalid-url")

    resp = client.post(
        "/api/v1/projects/proj-invalid-url/intake",
        json={
            "urls": ["http://127.0.0.1/admin"],
            "description": None,
            "asset_ids": [],
            "reference_urls": [],
            "competitor_urls": [],
        },
        headers=_sprint42_headers(),
    )

    assert resp.status_code == 400
    assert "Invalid URL" in resp.json()["detail"]


def test_submit_intake_rejects_asset_from_another_project(client: TestClient, db_session: Session):
    _create_sprint42_project(db_session, "proj-target")
    _create_sprint42_project(db_session, "proj-source")
    asset = Asset(
        id="asset-owned-by-source",
        project_id="proj-source",
        source_type="uploaded",
        filename="source.jpg",
        file_path="uploads/source.jpg",
        mime_type="image/jpeg",
        file_size=1234,
    )
    db_session.add(asset)
    db_session.commit()

    resp = client.post(
        "/api/v1/projects/proj-target/intake",
        json={
            "urls": [],
            "description": "상품 설명",
            "asset_ids": ["asset-owned-by-source"],
            "reference_urls": [],
            "competitor_urls": [],
        },
        headers=_sprint42_headers(),
    )

    assert resp.status_code == 400
    assert "Invalid asset_ids" in resp.json()["detail"]
    db_session.refresh(asset)
    assert asset.project_id == "proj-source"


def test_confirm_understanding_persists_reviewed_values(client: TestClient, db_session: Session):
    _create_sprint42_project(db_session, "proj-confirm-understanding")

    resp = client.post(
        "/api/v1/projects/proj-confirm-understanding/understanding/confirm",
        json={
            "product_type": {"value": "수정한 상품 분류", "is_suggestion": False},
            "target_customer": {"value": "수정한 타겟 고객", "is_suggestion": False},
            "buyer_problem": {"value": "수정한 구매 고민", "is_suggestion": False},
            "main_angle_candidates": ["각도 A"],
            "tone_candidates": ["톤 A"],
            "image_candidates": [],
            "unknowns": ["추가 정보"],
        },
        headers=_sprint42_headers(),
    )

    assert resp.status_code == 200
    project = db_session.query(ProductProject).filter(ProductProject.id == "proj-confirm-understanding").first()
    assert project.intake_snapshot["confirmed_understanding"]["product_type"]["value"] == "수정한 상품 분류"
    assert project.intake_snapshot["confirmed_understanding"]["buyer_problem"]["value"] == "수정한 구매 고민"
