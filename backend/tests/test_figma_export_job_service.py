import pytest
from sqlalchemy.orm import Session
from src.db.models import FigmaExportJob, ProductProject, Brand
from src.services.figma_export_job_service import FigmaExportJobService


def test_figma_export_job_service_idempotency_running(client, db_session: Session):
    # Setup project and brand
    brand = Brand(id="b-job-1", workspace_id="ws-job-1", name="루메나 브랜드")
    db_session.add(brand)
    db_session.commit()

    proj = ProductProject(
        id="p-job-1",
        workspace_id="ws-job-1",
        brand_id="b-job-1",
        name="테스트 상품",
        category="Living"
    )
    db_session.add(proj)
    db_session.commit()

    service = FigmaExportJobService(db_session)
    
    # 1. Create a job
    job1 = service.get_or_create_job(
        project_id="p-job-1",
        workspace_id="ws-job-1",
        target_file_url="https://figma.com/design/xxx",
        payload_hash="hash-12345"
    )
    
    assert job1.status == "queued"
    assert job1.attempt_count == 1
    
    # Update status to rendering
    job1.status = "rendering"
    db_session.commit()

    # 2. Get or create with same details -> should return existing job
    job2 = service.get_or_create_job(
        project_id="p-job-1",
        workspace_id="ws-job-1",
        target_file_url="https://figma.com/design/xxx",
        payload_hash="hash-12345"
    )
    
    assert job2.id == job1.id
    assert job2.status == "rendering"


def test_figma_export_job_service_completed_same_payload(client, db_session: Session):
    brand = Brand(id="b-job-2", workspace_id="ws-job-1", name="루메나 브랜드")
    db_session.add(brand)
    db_session.commit()

    proj = ProductProject(
        id="p-job-2",
        workspace_id="ws-job-1",
        brand_id="b-job-2",
        name="테스트 상품",
        category="Living"
    )
    db_session.add(proj)
    db_session.commit()

    service = FigmaExportJobService(db_session)
    
    job1 = service.get_or_create_job(
        project_id="p-job-2",
        workspace_id="ws-job-1",
        target_file_url="https://figma.com/design/xxx",
        payload_hash="hash-12345"
    )
    job1.status = "completed"
    job1.result_file_url = "https://figma.com/design/xxx?node-id=0"
    db_session.commit()

    # Should return the completed job directly
    job2 = service.get_or_create_job(
        project_id="p-job-2",
        workspace_id="ws-job-1",
        target_file_url="https://figma.com/design/xxx",
        payload_hash="hash-12345"
    )
    
    assert job2.id == job1.id
    assert job2.status == "completed"


def test_figma_export_job_service_payload_change(client, db_session: Session):
    brand = Brand(id="b-job-3", workspace_id="ws-job-1", name="루메나 브랜드")
    db_session.add(brand)
    db_session.commit()

    proj = ProductProject(
        id="p-job-3",
        workspace_id="ws-job-1",
        brand_id="b-job-3",
        name="테스트 상품",
        category="Living"
    )
    db_session.add(proj)
    db_session.commit()

    service = FigmaExportJobService(db_session)
    
    job1 = service.get_or_create_job(
        project_id="p-job-3",
        workspace_id="ws-job-1",
        target_file_url="https://figma.com/design/xxx",
        payload_hash="hash-old"
    )
    
    # Hash changes -> should spawn a new job
    job2 = service.get_or_create_job(
        project_id="p-job-3",
        workspace_id="ws-job-1",
        target_file_url="https://figma.com/design/xxx",
        payload_hash="hash-new"
    )
    
    assert job2.id != job1.id
    assert job2.payload_hash == "hash-new"


def test_figma_export_job_service_retry_failed_job(client, db_session: Session):
    brand = Brand(id="b-job-4", workspace_id="ws-job-1", name="루메나 브랜드")
    db_session.add(brand)
    db_session.commit()

    proj = ProductProject(
        id="p-job-4",
        workspace_id="ws-job-1",
        brand_id="b-job-4",
        name="테스트 상품",
        category="Living"
    )
    db_session.add(proj)
    db_session.commit()

    service = FigmaExportJobService(db_session)
    
    job = service.get_or_create_job(
        project_id="p-job-4",
        workspace_id="ws-job-1",
        target_file_url="https://figma.com/design/xxx",
        payload_hash="hash-12345"
    )
    
    # Transition to failed
    job.status = "failed"
    job.error_code = "AUTH_DENIED"
    job.error_message = "Figma credentials expired"
    db_session.commit()

    # Retry job
    retried_job = service.retry_export_job(job.id)
    
    assert retried_job.status == "queued"
    assert retried_job.attempt_count == 2
    assert retried_job.error_code is None
    assert retried_job.error_message is None


def test_figma_export_job_service_rejects_retry_for_completed_job(client, db_session: Session):
    brand = Brand(id="b-job-5", workspace_id="ws-job-1", name="Retry Brand")
    db_session.add(brand)
    project = ProductProject(
        id="p-job-5",
        workspace_id="ws-job-1",
        brand_id="b-job-5",
        name="Completed product",
        category="Living",
    )
    db_session.add(project)
    db_session.commit()

    service = FigmaExportJobService(db_session)
    job = service.get_or_create_job(
        project_id=project.id,
        workspace_id=project.workspace_id,
        target_file_url="https://www.figma.com/design/ABC/Test",
        payload_hash="completed-hash",
    )
    job.status = "completed"
    db_session.commit()

    with pytest.raises(ValueError, match="failed"):
        service.retry_export_job(job.id)
