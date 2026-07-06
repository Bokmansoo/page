import os

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from src.db.models import (
    Asset,
    ImageGenerationJobRecord,
    ProductFact,
    ProductPage,
    ProductProject,
)
from src.services.detail_page_orchestrator import DetailPageOrchestrator


@pytest.fixture
def orchestrator_project(db_session: Session):
    project = ProductProject(
        id="orch-remediation-project",
        workspace_id="ws-1",
        brand_id="b-1",
        name="Orchestrator Remediation Fan",
        category="Living",
        selected_style="problem_solution",
        selected_background="cooling-blue",
        raw_input_text="4800mAh battery fan",
        status="draft",
        intake_snapshot={
            "confirmed_sales_strategy": {
                "target_customer": "small-home buyers",
                "buyer_problem": "summer rooms feel stuffy",
                "main_selling_point": "portable cooling airflow",
                "supporting_points": ["4800mAh battery"],
                "tone": "clear",
            }
        },
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(
        ProductFact(
            project_id=project.id,
            fact_text="4800mAh battery fan",
            source_text="manual",
            verification_status="confirmed",
            needs_review=False,
        )
    )
    db_session.commit()
    return project.id


@pytest.fixture
def source_asset(db_session: Session, orchestrator_project, tmp_path):
    img_path = tmp_path / "source.png"
    Image.new("RGB", (512, 512), color="white").save(img_path)
    asset = Asset(
        id="orch-remediation-source",
        project_id=orchestrator_project,
        source_type="sourced",
        filename="source.png",
        file_path=str(img_path),
        mime_type="image/png",
        file_size=os.path.getsize(img_path),
    )
    db_session.add(asset)
    db_session.commit()
    return asset


def test_premium_image_generation_requires_explicit_cost_approval(
    db_session: Session,
    orchestrator_project,
    source_asset,
):
    status = DetailPageOrchestrator.run_orchestration_pipeline(
        orchestrator_project,
        db_session,
        user_approved_cost=False,
    )

    assert status == "image_cost_approval_required"
    jobs = db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == orchestrator_project
    ).all()
    assert jobs
    assert any(job.status == "awaiting_cost_approval" for job in jobs)
    assert any(job.cost_tier == "premium" for job in jobs)


def test_cost_approved_generation_pauses_at_image_review(
    db_session: Session,
    orchestrator_project,
    source_asset,
    monkeypatch,
):
    DetailPageOrchestrator.run_orchestration_pipeline(
        orchestrator_project,
        db_session,
        user_approved_cost=False,
    )

    def fake_execute(project_id, job_id, db, cost_approved=False, provider_override=None):
        record = db.query(ImageGenerationJobRecord).filter(
            ImageGenerationJobRecord.project_id == project_id,
            ImageGenerationJobRecord.job_id == job_id,
        ).first()
        record.status = "needs_review"
        record.output_asset_id = source_asset.id
        db.commit()
        return record

    monkeypatch.setattr(
        "src.services.detail_page_orchestrator.execute_image_generation",
        fake_execute,
    )

    status = DetailPageOrchestrator.run_orchestration_pipeline(
        orchestrator_project,
        db_session,
        user_approved_cost=True,
    )

    assert status == "images_ready_for_review"
    project = db_session.query(ProductProject).filter(ProductProject.id == orchestrator_project).first()
    assert project.status == "images_ready_for_review"
    assert db_session.query(ProductPage).filter(ProductPage.project_id == orchestrator_project).first() is not None


def test_reviewed_images_allow_pipeline_to_complete_package(
    db_session: Session,
    orchestrator_project,
    source_asset,
):
    project = db_session.query(ProductProject).filter(ProductProject.id == orchestrator_project).first()
    project.status = "images_ready_for_review"
    db_session.add(
        ImageGenerationJobRecord(
            project_id=orchestrator_project,
            job_id="job-approved",
            section_id="sec-main",
            role="lifestyle_scene",
            source_asset_ids=[source_asset.id],
            prompt="Use the approved source product photo in a lifestyle section",
            cost_tier="premium",
            status="approved",
            output_asset_id=source_asset.id,
        )
    )
    db_session.commit()

    status = DetailPageOrchestrator.run_orchestration_pipeline(
        orchestrator_project,
        db_session,
        user_approved_cost=True,
    )

    assert status == "package_ready"
    assert db_session.query(ProductPage).filter(ProductPage.project_id == orchestrator_project).first() is not None


def test_url_failure_continues_when_manual_input_exists(
    db_session: Session,
    orchestrator_project,
    source_asset,
):
    project = db_session.query(ProductProject).filter(ProductProject.id == orchestrator_project).first()
    project.status = "draft"
    project.raw_input_text = "Manual fallback description"
    project.raw_input_url = "https://example.com/fail-crawling"
    db_session.commit()

    status = DetailPageOrchestrator.run_orchestration_pipeline(orchestrator_project, db_session)

    assert status != "failed_needs_input"
