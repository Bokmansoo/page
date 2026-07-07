from typing import List

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


class PlanningDraftSchema(BaseModel):
    cards: List[PlanningDraftCardSchema] = Field(default_factory=list)
