from typing import Any, List, Optional

from pydantic import BaseModel, Field


class PlanningDraftCardSchema(BaseModel):
    id: str = Field(..., description="기획 카드 고유 ID")
    type: str = Field(..., description="카드 타입")
    label: str = Field(..., description="화면에 표시할 카드 이름")
    title: str = Field(..., description="섹션 제목 또는 핵심 메시지")
    bullets: List[str] = Field(default_factory=list, description="본문 포인트 목록")
    source_fact_ids: List[str] = Field(default_factory=list, description="근거가 되는 product fact ID 목록")
    visual_strategy: str = Field(..., description="추천 시각화 전략")
    is_enabled: bool = Field(True, description="상세페이지 조립에 포함할지 여부")
    sort_order: int = Field(..., description="정렬 순서")
    image_asset_id: Optional[str] = Field(None, description="최종 출력에 사용할 승인 자산 ID")
    candidate_asset_ids: List[str] = Field(default_factory=list, description="이 섹션에 추천할 자산 후보")
    image_requirement: Optional[str] = Field(None, description="asset_ready, ai_redesign_required, seller_upload_required, derived_graphic")
    scene_request: Optional[str] = Field(None, description="Sprint 5 이미지 생성에 전달할 장면 요청")
    rendering_template: Optional[str] = Field(None, description="Sprint 6 렌더링 템플릿 키")
    facts_stale: bool = Field(False, description="연결된 사실 변경으로 재검토가 필요한지")
    missing_reasons: List[str] = Field(default_factory=list, description="이미지 또는 근거 누락 사유")


class PlanningDraftSchema(BaseModel):
    cards: List[PlanningDraftCardSchema] = Field(default_factory=list)
    storyboard_version: int = 1
    selected_candidate_key: Optional[str] = None
    recommendations: List[dict[str, Any]] = Field(default_factory=list)
    fact_snapshot_id: Optional[str] = None
    fact_snapshot_hash: Optional[str] = None
    status: str = "draft"
    stale_fact_ids: List[str] = Field(default_factory=list)
    estimated_cost: float = 0.0
    revision: int = 1
    revision_history: List[dict[str, Any]] = Field(default_factory=list)
