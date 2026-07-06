from typing import List, Dict, Any

class AICostPolicy:
    COST_TIERS = {
        "text_generation": "low",
        "vision_analysis": "standard",
        "image_planning": "standard",
        "image_generation": "premium",
        "export_rendering": "standard"
    }
    HIGH_COST_TIERS = {"high", "premium"}
    APPROVAL_PENDING_STATUSES = {"awaiting_cost_approval", "planned", "needs_generation"}
    APPROVED_OR_RUNNING_STATUSES = {"generating", "needs_review", "approved"}

    @staticmethod
    def get_tier_for_action(action: str) -> str:
        return AICostPolicy.COST_TIERS.get(action, "standard")

    @staticmethod
    def should_require_approval(job_records: List[Any]) -> bool:
        """
        고비용(high) 등급의 이미지 생성 작업이 포함되어 있을 경우 
        사용자의 명시적 승인이 필요한지 판정합니다.
        """
        for job in job_records:
            # SQLAlchemy 모델 객체 또는 딕셔너리 대응
            cost_tier = getattr(job, "cost_tier", None)
            if cost_tier is None and isinstance(job, dict):
                cost_tier = job.get("cost_tier")
                
            if cost_tier in AICostPolicy.HIGH_COST_TIERS:
                status = getattr(job, "status", None)
                if status is None and isinstance(job, dict):
                    status = job.get("status")
                # awaiting_cost_approval 상태이거나 planned(아직 승인 요청 전) 상태인 고비용 잡이 있으면 승인 필요
                if status in AICostPolicy.APPROVAL_PENDING_STATUSES:
                    return True
        return False

    @staticmethod
    def filter_cost_approved_jobs(job_records: List[Any]) -> List[Any]:
        """
        비용 승인을 마친(status가 generating, needs_review, approved 등인) 고비용 잡들과,
        승인 절차가 필요 없는 저비용/표준 잡들을 추려냅니다.
        """
        approved_jobs = []
        for job in job_records:
            cost_tier = getattr(job, "cost_tier", None)
            if cost_tier is None and isinstance(job, dict):
                cost_tier = job.get("cost_tier")
                
            status = getattr(job, "status", None)
            if status is None and isinstance(job, dict):
                status = job.get("status")
                
            if cost_tier in AICostPolicy.HIGH_COST_TIERS:
                # high cost 작업은 승인됨(generating, needs_review, approved)인 경우만 허용
                if status in AICostPolicy.APPROVED_OR_RUNNING_STATUSES:
                    approved_jobs.append(job)
            else:
                # low / standard cost 작업은 승인 필요 없음
                approved_jobs.append(job)
        return approved_jobs
