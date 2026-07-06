from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentRunMode(str, Enum):
    MOCK = "mock"
    REAL = "real"


class AgentStage(str, Enum):
    INPUT_ROUTER = "input_router"
    SOURCE_COLLECTION = "source_collection"
    PRODUCT_UNDERSTANDING = "product_understanding"
    REFERENCE_ANALYSIS = "reference_analysis"
    SALES_STRATEGY = "sales_strategy"
    PAGE_PLANNING = "page_planning"
    COPYWRITING = "copywriting"
    VISUAL_PLANNING = "visual_planning"
    IMAGE_GENERATION = "image_generation"
    PAGE_ASSEMBLY = "page_assembly"
    QA_REVIEW = "qa_review"


class ProductInput(BaseModel):
    product_name: str | None = None
    description: str | None = None
    product_url: str | None = None
    freeform_input: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    reference_urls: list[str] = Field(default_factory=list)
    selling_points: list[str] = Field(default_factory=list)
    price: str | None = None
    shipping: str | None = None
    desired_mood: list[str] = Field(default_factory=list)



class AgentRunState(BaseModel):
    run_id: str | None = None
    project_id: str
    mode: AgentRunMode = AgentRunMode.MOCK
    current_stage: AgentStage = AgentStage.INPUT_ROUTER
    product_input: ProductInput = Field(default_factory=ProductInput)
    outputs: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    cost_approval_status: str = "not_required"
    estimated_cost: float | None = None
    actual_cost: float | None = None
    provider_trace: list[dict[str, Any]] = Field(default_factory=list)

    # New fields for Sprint 54
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    collected_sources: dict[str, Any] = Field(default_factory=dict)
    selected_image_candidates: dict[str, str] = Field(default_factory=dict)
    missing_inputs: list[str] = Field(default_factory=list)
    routing_hints: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("current_stage", mode="before")
    @classmethod
    def validate_stage(cls, v: Any) -> Any:
        legacy_map = {
            "intake": "input_router",
            "review_editor": "qa_review",
            "export_package": "qa_review",
            "copy_generation": "copywriting",
            "visual_planning": "visual_planning",
        }
        if isinstance(v, str):
            v_lower = v.lower()
            if v_lower in legacy_map:
                return AgentStage(legacy_map[v_lower])
            try:
                return AgentStage(v_lower)
            except ValueError:
                return AgentStage.INPUT_ROUTER
        return v
