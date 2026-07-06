import pytest
from sqlalchemy.orm import Session
from src.db.models import ProductProject, ProductPage, PageSection, ImageGenerationJobRecord, Asset
from src.services.detail_page_orchestrator import DetailPageOrchestrator
from src.config import settings

@pytest.fixture(autouse=True)
def force_mock_generation_mode(monkeypatch):
    monkeypatch.setattr(settings, "SELLFORM_GENERATION_MODE", "mock")


@pytest.fixture

def setup_orchestrator_project(db_session: Session):
    project = ProductProject(
        id="orch-project-1",
        workspace_id="ws-1",
        brand_id="b-1",
        name="Orchestrator Test Fan",
        category="Living",
        selected_style="problem_solution",
        selected_background="cooling-blue",
        raw_input_text="4800mAh battery fan",
        status="draft"
    )
    db_session.add(project)
    db_session.commit()
    return project.id

def test_orchestration_normal_flow_requires_cost_approval(db_session: Session, setup_orchestrator_project):
    project_id = setup_orchestrator_project

    # 1. 파이프라인 첫 기동 - 고비용 이미지 잡 기획으로 인해 비용 승인 대기 상태로 정지되어야 함
    status = DetailPageOrchestrator.run_orchestration_pipeline(project_id, db_session, user_approved_cost=False)
    assert status == "image_cost_approval_required"
    
    # DB 상태 확인
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).first()
    assert project.status == "image_cost_approval_required"
    
    jobs = db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.project_id == project_id).all()
    assert jobs
    assert any(job.status == "awaiting_cost_approval" for job in jobs)

def test_orchestration_cost_approved_completes_pipeline(db_session: Session, setup_orchestrator_project):
    project_id = setup_orchestrator_project

    # 1. 1차 호출 (비용 승인 없음) -> approval required 대기
    status = DetailPageOrchestrator.run_orchestration_pipeline(project_id, db_session, user_approved_cost=False)
    assert status == "image_cost_approval_required"
    
    # 2. 비용 승인 부여하여 2차 호출 -> 이미지 생성 후 review 대기 상태로 정지
    status = DetailPageOrchestrator.run_orchestration_pipeline(project_id, db_session, user_approved_cost=True)
    assert status == "images_ready_for_review"
    
    # 3. 모든 이미지 생성 잡 승인 완료 처리 (사용자 검수 완료 시뮬레이션)
    jobs = db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == project_id
    ).all()
    for job in jobs:
        if job.status == "needs_review":
            job.status = "approved"
    db_session.commit()
    
    # 4. 3차 호출 -> package_ready 완료 상태로 진행
    status = DetailPageOrchestrator.run_orchestration_pipeline(project_id, db_session, user_approved_cost=True)
    assert status == "package_ready"
    
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).first()
    assert project.status == "package_ready"

def test_orchestration_url_gathering_failed_recovery(db_session: Session, setup_orchestrator_project):
    project_id = setup_orchestrator_project
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).first()
    project.raw_input_text = ""
    project.raw_input_url = "https://example.com/fail-crawling"
    db_session.commit()

    # URL 크롤링 실패 시나리오 -> failed_needs_input 상태로 빠지고 멈춤
    status = DetailPageOrchestrator.run_orchestration_pipeline(project_id, db_session)
    assert status == "failed_needs_input"
