from typing import Dict, List, Literal
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


class SalesStrategyCandidate(BaseModel):
    """One auditable sales-strategy option produced by LG-3."""

    id: str
    headline: str
    main_claim: str = ""
    supporting_fact_ids: List[str] = Field(default_factory=list)


class SalesStrategyOutput(BaseModel):
    schema_version: Literal["lg3-v1"] = "lg3-v1"
    candidates: List[SalesStrategyCandidate] = Field(default_factory=list)
    selected_candidate_id: str = ""
    selection_reason: str = ""
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
    purpose: str = ""
    source_fact_ids: List[str] = Field(default_factory=list)


class DetailPagePlanOutput(BaseModel):
    schema_version: Literal["lg3-v1"] = "lg3-v1"
    layout_concept: str
    sections: List[DetailPagePlanSection]


class CopySetOutput(BaseModel):
    schema_version: Literal["lg3-v1"] = "lg3-v1"
    hero_title: str
    hero_subtitle: str
    painpoint_title: str
    painpoint_body: str
    feature_1_title: str
    feature_1_body: str
    feature_2_title: str
    feature_2_body: str
    # UX-2 fields are defaulted so existing real-text providers that still
    # return the legacy copy-set shape remain compatible.
    feature_3_title: str = "확인된 핵심 정보 3"
    feature_3_body: str = "입력된 사양과 옵션을 기준으로 안내합니다."
    usage_title: str = "사용 방법 또는 충전 안내"
    usage_body: str = "판매자 제공 안내를 확인한 뒤 사용해 주세요."
    details_title: str = "제품 디테일과 구성품"
    details_body: str = "구성품과 세부 사양은 아래 상품 정보에서 확인할 수 있습니다."
    guarantee_title: str
    guarantee_body: str
    cta_text: str
    # These fields are part of the LG-3 artifact contract.  Keeping them in
    # the schema prevents fact links from being discarded by model validation.
    section_fact_ids: Dict[str, List[str]] = Field(default_factory=dict)
    copy_provenance: Dict[str, dict] = Field(default_factory=dict)


class ScenePlanOutput(BaseModel):
    """Frozen, provider-ready scene contract used by UX-2E and LG-3."""

    id: str
    scene_type: str
    objective: str
    source_fact_ids: List[str] = Field(default_factory=list)
    reference_asset_ids: List[str] = Field(default_factory=list)
    generation_mode: Literal[
        "safe_existing_photo", "ai_redesign", "html_information_fallback"
    ]
    requested_output: str
    rendering_strategy: str
    mock_status: str


class VisualPlanOutput(BaseModel):
    schema_version: Literal["lg3-v1"] = "lg3-v1"
    hero_image_prompt: str
    detail_image_prompt: str
    color_palette: List[str]
    # Legacy 11-agent output used this key for a richer free-form object.
    # LG-3 always writes the typed list; accepting the old shape here preserves
    # the LG-0 characterization contract during the staged migration.
    scene_plan: List[ScenePlanOutput] | dict = Field(default_factory=list)


class QAWarning(BaseModel):
    """A structured QA issue emitted by the review and export gates."""

    code: str
    message: str
    section_id: str | None = None
    claims: List[str] = Field(default_factory=list)


class QAReportOutput(BaseModel):
    status: str
    checked_at: str
    # LLM-only reviews can return concise strings, while deterministic export
    # gates attach a code and section identifier for a repairable UI action.
    warnings: List[str | QAWarning] = Field(default_factory=list)
    passed_checks: List[str] = Field(default_factory=list)


class CreativeBriefSectionStrategy(BaseModel):
    """Structured creative intent; approved facts remain the only claim source."""

    section: str
    target: str
    objective: str
    fact_ids: List[str] = Field(default_factory=list)
    copy_classification: Literal["fact", "creative", "mixed"]
    source: Literal["approved_facts", "creative_insight", "seller_direction", "mixed"]
    claim_policy: Literal["approved_fact_required", "narrative_non_claim"]


class CreativeBriefStructuredOutput(BaseModel):
    """LG-7R provider contract used by real and fake-real text adapters."""

    schema_version: Literal["lg7r-v1"] = "lg7r-v1"
    target_audience: str = ""
    customer_problem: List[str] = Field(default_factory=list)
    purchase_motivation: List[str] = Field(default_factory=list)
    desired_mood: List[str] = Field(default_factory=list)
    emphasis: List[str] = Field(default_factory=list)
    forbidden_claims: List[str] = Field(default_factory=list)
    forbidden_scenes: List[str] = Field(default_factory=list)
    section_strategy: List[CreativeBriefSectionStrategy] = Field(min_length=1)
