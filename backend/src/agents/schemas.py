from typing import List
from pydantic import BaseModel, Field


class ProductUnderstandingOutput(BaseModel):
    product_type: str
    target_customer: str
    verified_facts: List[str]
    assumptions: List[str]
    verification_required: List[str] = Field(default_factory=list)
    forbidden_claims: List[str] = Field(default_factory=list)
    buyer_problem: str = ""
    risk_notes: List[str] = Field(default_factory=list)


class SalesStrategyOutput(BaseModel):
    hook_headline: str = ""
    selling_points: List[str] = Field(default_factory=list)
    tone_and_manner: str = ""
    recommended_direction: str = ""
    alternatives: List[str] = Field(default_factory=list)
    main_claim: str = ""
    support_claims: List[str] = Field(default_factory=list)
    reason: str = ""


class DetailPagePlanSection(BaseModel):
    id: str
    name: str


class DetailPagePlanOutput(BaseModel):
    layout_concept: str
    sections: List[DetailPagePlanSection]


class CopySetOutput(BaseModel):
    hero_title: str
    hero_subtitle: str
    painpoint_title: str
    painpoint_body: str
    feature_1_title: str
    feature_1_body: str
    feature_2_title: str
    feature_2_body: str
    guarantee_title: str
    guarantee_body: str
    cta_text: str


class VisualPlanOutput(BaseModel):
    hero_image_prompt: str
    detail_image_prompt: str
    color_palette: List[str]


class QAReportOutput(BaseModel):
    status: str
    checked_at: str
    warnings: List[str] = Field(default_factory=list)
    passed_checks: List[str] = Field(default_factory=list)
