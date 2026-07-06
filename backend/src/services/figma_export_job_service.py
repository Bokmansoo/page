import datetime
from sqlalchemy.orm import Session
from src.db.models import FigmaExportJob, ProductProject


class FigmaExportJobService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_job(
        self,
        project_id: str,
        workspace_id: str,
        target_file_url: str,
        payload_hash: str
    ) -> FigmaExportJob:
        self.db.query(ProductProject).filter(
            ProductProject.id == project_id,
            ProductProject.workspace_id == workspace_id,
        ).with_for_update().first()

        # Check for any active or completed job with identical file and payload
        existing_job = self.db.query(FigmaExportJob).filter(
            FigmaExportJob.project_id == project_id,
            FigmaExportJob.workspace_id == workspace_id,
            FigmaExportJob.target_file_url == target_file_url,
            FigmaExportJob.payload_hash == payload_hash,
            FigmaExportJob.status != "failed"
        ).first()

        if existing_job:
            return existing_job

        # Otherwise, spawn a new job
        new_job = FigmaExportJob(
            project_id=project_id,
            workspace_id=workspace_id,
            target_file_url=target_file_url,
            payload_hash=payload_hash,
            status="queued",
            attempt_count=1
        )
        self.db.add(new_job)
        self.db.commit()
        self.db.refresh(new_job)
        return new_job

    def retry_export_job(self, job_id: str) -> FigmaExportJob:
        job = self.db.query(FigmaExportJob).filter(FigmaExportJob.id == job_id).first()
        if not job:
            raise ValueError(f"FigmaExportJob with id {job_id} not found")
        if job.status != "failed":
            raise ValueError("Only failed Figma export jobs can be retried")

        job.status = "queued"
        job.attempt_count += 1
        job.error_code = None
        job.error_message = None
        job.auth_url = None
        job.result_file_url = None
        job.result_node_url = None
        job.updated_at = datetime.datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job
