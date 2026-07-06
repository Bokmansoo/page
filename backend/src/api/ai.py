import uuid
import datetime
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import ProductProject, ProductFact, Asset, JobStatus, AiJobLog
from src.services.ai_adapter import get_ai_adapter
from src.services.compliance import check_compliance

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AI Analysis"])

# =====================================================================
# Request / Response Schemas
# =====================================================================

class AnalyzeRequest(BaseModel):
    provider: Optional[str] = Field(None, description="AI 공급자명 (openai, google, anthropic)")
    model_name: Optional[str] = Field(None, description="사용할 AI 모델명")

class AnalyzeResponse(BaseModel):
    job_id: str
    project_id: str
    status: str
    message: str


# =====================================================================
# Background Task for AI Analysis
# =====================================================================

def run_ai_analysis(
    job_id: str,
    project_id: str,
    provider: str,
    model_name: Optional[str],
    db: Session
):
    # JobStatus 및 로그 초기화
    job_status = db.query(JobStatus).filter(JobStatus.id == job_id).first()
    if not job_status:
        return
    
    job_status.status = "running"
    db.commit()

    project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
    if not project:
        job_status.status = "failed"
        job_status.error_message = "Project not found"
        db.commit()
        return

    # 1. 원본 텍스트 및 이미지 준비
    raw_text = project.raw_input_text or ""
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    image_urls = [asset.file_path for asset in assets if asset.mime_type.startswith("image/")]

    # 2. AI 어댑터 로드 및 분석 호출
    start_time = datetime.datetime.utcnow()
    ai_log = AiJobLog(
        project_id=project_id,
        task_type="fact_extraction",
        provider=provider,
        model_name=model_name or "default",
        prompt_version="1.0.0",
        duration_ms=0,
        status="pending"
    )
    db.add(ai_log)
    db.commit()

    try:
        adapter = get_ai_adapter(provider, model_name)
        ai_response = adapter.extract_facts(raw_text=raw_text, image_urls=image_urls)
        
        # 3. AI 응답 기반 정보 업데이트
        extracted_data = ai_response.data
        project.name = extracted_data.product_name
        project.category = extracted_data.recommended_category
        project.current_step = "facts_verification"  # 다음 단계인 사실 확인 보드로 진행

        # 기존 임시 팩트 카드 일괄 삭제
        db.query(ProductFact).filter(ProductFact.project_id == project_id).delete()

        # 새로운 사실 카드 적재
        new_facts_list = []
        for fact_schema in extracted_data.facts:
            new_fact = ProductFact(
                project_id=project_id,
                fact_text=fact_schema.fact_text,
                source_text=fact_schema.source_text,
                verification_status="unknown"  # 기본 검증 상태는 '모름'
            )
            db.add(new_fact)
            new_facts_list.append({
                "fact_text": fact_schema.fact_text,
                "source_text": fact_schema.source_text
            })
        
        db.flush() # ID 등 갱신

        # 4. 규제 검수 엔진 구동
        compliance_issues = check_compliance(
            category=project.category,
            product_name=project.name,
            raw_input=raw_text,
            extracted_facts=new_facts_list
        )

        # Blocker 또는 Major 이슈가 존재하면 프로젝트 상태를 checking(검수 필요)으로 설정
        # 이슈가 없으면 ready(출력 준비) 상태로 전이
        has_blocker_or_major = any(
            issue.severity in ["Blocker", "Major"] for issue in compliance_issues
        )
        if has_blocker_or_major:
            project.status = "checking"
        else:
            project.status = "ready"

        # 5. AI 로그 및 작업 완료 처리
        duration = int((datetime.datetime.utcnow() - start_time).total_seconds() * 1000)
        ai_log.duration_ms = duration
        ai_log.input_tokens = ai_response.input_tokens
        ai_log.output_tokens = ai_response.output_tokens
        ai_log.model_name = ai_response.model_name
        ai_log.status = "success"

        # 예상 비용 대략적 산출 (어댑터 공급자에 따라 대입)
        # 1M 토큰 당 단가 계산
        cost = 0.0
        p = provider.lower()
        if p == "openai":
            # gpt-4o-mini 기준: $0.150/1M prompt, $0.600/1M completion
            # gpt-4o 기준: $5.00/1M prompt, $15.00/1M completion
            is_mini = "mini" in ai_response.model_name.lower()
            prompt_cost = 0.15 if is_mini else 5.00
            completion_cost = 0.60 if is_mini else 15.00
            cost = (ai_response.input_tokens * prompt_cost + ai_response.output_tokens * completion_cost) / 1000000
        elif p == "anthropic":
            # claude-3-5-sonnet 기준: $3.00/1M prompt, $15.00/1M completion
            cost = (ai_response.input_tokens * 3.00 + ai_response.output_tokens * 15.00) / 1000000
        elif p == "google":
            # gemini-1.5-flash 기준: $0.075/1M prompt, $0.30/1M completion
            cost = (ai_response.input_tokens * 0.075 + ai_response.output_tokens * 0.30) / 1000000
        
        ai_log.estimated_cost = cost
        
        job_status.status = "completed"
        db.commit()
        logger.info(f"프로젝트 {project_id} AI 분석 완료. 소요 시간: {duration}ms, 비용: ${cost:.6f}")

    except Exception as e:
        db.rollback()
        duration = int((datetime.datetime.utcnow() - start_time).total_seconds() * 1000)
        ai_log.duration_ms = duration
        ai_log.status = "failed"
        ai_log.error_message = str(e)
        
        job_status.status = "failed"
        job_status.error_message = str(e)
        db.commit()
        logger.error(f"프로젝트 {project_id} AI 분석 중 오류 발생: {e}", exc_info=True)


# =====================================================================
# API Endpoints
# =====================================================================

@router.post("/projects/{project_id}/analyze", response_model=AnalyzeResponse, status_code=202)
def analyze_project(
    project_id: str,
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    role = auth_ctx.get("role") or "owner"
    
    # 1. Enforce RBAC (viewer cannot analyze)
    if role not in ["owner", "admin", "member"]:
        raise HTTPException(
            status_code=403,
            detail="Access denied: Insufficient permissions for this workspace"
        )
        
    # 2. Check budget and rate limits
    from src.api.auth import check_workspace_limits
    check_workspace_limits(db, workspace.id)

    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Product project not found")

    # 기본 AI 공급자는 환경변수에 따라 폴백
    provider = req.provider or "openai"
    model_name = req.model_name

    # JobStatus 생성
    job_id = str(uuid.uuid4())
    job_status = JobStatus(
        id=job_id,
        project_id=project_id,
        status="processing"
    )
    db.add(job_status)
    db.commit()

    # 백그라운드 태스크 등록
    background_tasks.add_task(
        run_ai_analysis,
        job_id=job_id,
        project_id=project_id,
        provider=provider,
        model_name=model_name,
        db=db
    )

    return AnalyzeResponse(
        job_id=job_id,
        project_id=project_id,
        status="processing",
        message="AI analysis and compliance check has been scheduled."
    )
