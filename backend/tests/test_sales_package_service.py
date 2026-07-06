import datetime

import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from src.db.models import (
    ProductProject,
    ProductPage,
    ExportJob,
    Asset,
    PageSection,
    ImageGenerationJobRecord,
)
from src.services.sales_package_service import SalesPackageService

@pytest.fixture
def setup_sales_package_data(db_session: Session):
    # 1. Project 생성
    project = ProductProject(
        id="test-pkg-proj-id",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="00000000-0000-0000-0000-000000000001",
        name="테스트 상품",
        category="Living",
        selected_style="problem_solution",
        selected_background="cooling-blue",
        intake_snapshot={
            "price": 25000,
            "tags": ["가정용", "리빙"],
            "delivery": "무료배송",
            "returns": "7일 이내 교환/반품 가능"
        }
    )
    db_session.add(project)
    
    # 2. Page 생성
    page = ProductPage(
        id="test-pkg-page-id",
        project_id=project.id,
        theme_color="#3B82F6",
        font_family="sans-serif"
    )
    db_session.add(page)
    
    # 3. Section 생성
    section = PageSection(
        page_id=page.id,
        section_type="hero",
        title="시원한 여름을 위한 바람",
        body_copy="FAN JET ULTRA 18시간 연속 무선 사용",
        sort_order=0,
        is_visible=True
    )
    db_session.add(section)
    
    # 4. Completed ExportJob 생성
    export_job = ExportJob(
        id="test-pkg-job-id",
        project_id=project.id,
        preset_name="smartstore",
        status="completed",
        output_images=["/uploads/exports/test_long.png"],
        created_by="00000000-0000-0000-0000-000000000001"
    )
    db_session.add(export_job)
    
    # 5. Asset 생성
    asset = Asset(
        project_id=project.id,
        source_type="sourced",
        filename="test_image.jpg",
        file_path="uploads/test_image.jpg",
        mime_type="image/jpeg",
        file_size=1024
    )
    db_session.add(asset)
    
    db_session.commit()
    return project.id

def test_get_sales_package(db_session: Session, setup_sales_package_data):
    project_id = setup_sales_package_data
    
    # SalesPackageService 테스트 실행
    package = SalesPackageService.get_sales_package(project_id, db_session)
    
    assert "long_png" in package
    assert "editable_web_page" in package
    assert "figma_payload" in package
    assert "marketplace_package" in package
    assert "copy_sheet" in package
    assert "visual_assets" in package
    
    # long_png 검증
    assert package["long_png"]["url"] == "/uploads/exports/test_long.png"
    
    # editable_web_page 검증
    assert package["editable_web_page"]["url"] == f"/workspace/projects/{project_id}/page-editor"
    
    # marketplace_package 검증
    market_pkg = package["marketplace_package"]
    assert market_pkg["title"] == "테스트 상품"
    assert market_pkg["category"] == "Living"
    assert market_pkg["price"] == 25000
    assert market_pkg["delivery"] == "무료배송"
    assert market_pkg["returns"] == "7일 이내 교환/반품 가능"
    assert market_pkg["detail_page_artifact"] == "/uploads/exports/test_long.png"
    
    # copy_sheet 검증
    assert len(package["copy_sheet"]) > 0
    assert package["copy_sheet"][0]["section_type"] == "hero"
    assert package["copy_sheet"][0]["title"] == "시원한 여름을 위한 바람"
    
    # visual_assets 검증
    assert len(package["visual_assets"]) == 1
    assert package["visual_assets"][0]["filename"] == "test_image.jpg"


def test_sales_package_does_not_invent_required_marketplace_fields(db_session: Session):
    project = ProductProject(
        id="marketplace-missing-fields-project",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="00000000-0000-0000-0000-000000000001",
        name="입력 부족 상품",
        category=None,
        intake_snapshot={},
    )
    db_session.add(project)
    db_session.commit()

    package = SalesPackageService.get_sales_package(project.id, db_session)
    market_pkg = package["marketplace_package"]

    assert market_pkg["price"] is None
    assert market_pkg["category"] is None
    assert market_pkg["delivery"] is None
    assert market_pkg["returns"] is None
    assert package["marketplace_readiness"]["ready"] is False
    assert set(package["marketplace_readiness"]["missing_fields"]) >= {
        "category",
        "representative_image",
        "detail_page_artifact",
        "price",
        "delivery",
        "returns",
    }


def test_sales_package_filters_unapproved_generated_assets(db_session: Session):
    project = ProductProject(
        id="asset-policy-project",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="00000000-0000-0000-0000-000000000001",
        name="이미지 정책 상품",
        category="Living",
        intake_snapshot={"price": 12000, "delivery": "무료배송", "returns": "7일 이내 반품"},
    )
    db_session.add(project)

    unapproved = Asset(
        id="unapproved-ai-asset",
        project_id=project.id,
        source_type="ai_generated",
        filename="unapproved.png",
        file_path="uploads/unapproved.png",
        mime_type="image/png",
        file_size=10,
    )
    uploaded = Asset(
        id="uploaded-asset",
        project_id=project.id,
        source_type="uploaded",
        filename="uploaded.png",
        file_path="uploads/uploaded.png",
        mime_type="image/png",
        file_size=10,
    )
    db_session.add_all([unapproved, uploaded])
    db_session.commit()

    package = SalesPackageService.get_sales_package(project.id, db_session)

    assert package["marketplace_package"]["representative_image"] == "/uploads/uploaded.png"
    assert [asset["id"] for asset in package["visual_assets"]] == ["uploaded-asset"]


def test_sales_package_allows_approved_generated_asset(db_session: Session):
    project = ProductProject(
        id="approved-ai-project",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="00000000-0000-0000-0000-000000000001",
        name="승인 이미지 상품",
        category="Living",
        intake_snapshot={"price": 12000, "delivery": "무료배송", "returns": "7일 이내 반품"},
    )
    db_session.add(project)

    generated = Asset(
        id="approved-ai-asset",
        project_id=project.id,
        source_type="ai_generated",
        filename="approved.png",
        file_path="uploads/approved.png",
        mime_type="image/png",
        file_size=10,
    )
    db_session.add(generated)
    db_session.add(
        ImageGenerationJobRecord(
            project_id=project.id,
            job_id="approved-job",
            section_id="hero",
            role="lifestyle_scene",
            prompt="approved prompt",
            status="approved",
            output_asset_id=generated.id,
        )
    )
    db_session.commit()

    package = SalesPackageService.get_sales_package(project.id, db_session)

    assert package["marketplace_package"]["representative_image"] == "/uploads/approved.png"
    assert [asset["id"] for asset in package["visual_assets"]] == ["approved-ai-asset"]


def test_marketplace_submit_requires_explicit_approval(client: TestClient, db_session: Session):
    project = ProductProject(
        id="approval-required-project",
        workspace_id="00000000-0000-0000-0000-000000000002",
        brand_id="00000000-0000-0000-0000-000000000001",
        name="승인 필요 상품",
        category="Living",
        intake_snapshot={"price": 25000, "delivery": "무료배송", "returns": "7일 이내 교환/반품 가능"},
    )
    db_session.add(project)
    db_session.add(
        Asset(
            project_id=project.id,
            source_type="uploaded",
            filename="rep.jpg",
            file_path="uploads/rep.jpg",
            mime_type="image/jpeg",
            file_size=1024,
        )
    )
    db_session.add(
        ExportJob(
            project_id=project.id,
            preset_name="smartstore",
            status="completed",
            output_images=["/uploads/exports/approval_required.png"],
            created_by="00000000-0000-0000-0000-000000000001",
            completed_at=datetime.datetime.utcnow(),
        )
    )
    db_session.commit()

    prepare_res = client.post(f"/api/v1/projects/{project.id}/marketplace/packages")
    assert prepare_res.status_code == 200
    assert prepare_res.json()["status"] == "ready"

    submit_before_approval = client.post(f"/api/v1/projects/{project.id}/marketplaces/submit")
    assert submit_before_approval.status_code == 409
    assert submit_before_approval.json()["detail"] == "Marketplace package must be approved before submit."

    approve_res = client.post(f"/api/v1/projects/{project.id}/marketplace/packages/approve")
    assert approve_res.status_code == 200

    submit_after_approval = client.post(f"/api/v1/projects/{project.id}/marketplaces/submit")
    assert submit_after_approval.status_code == 200
    assert submit_after_approval.json()["status"] == "submitted"
