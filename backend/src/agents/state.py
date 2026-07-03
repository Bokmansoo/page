from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentRunMode(str, Enum):
    MOCK = "mock"
    REAL = "real"


class AgentStage(str, Enum):
    INTAKE = "intake"
    PRODUCT_UNDERSTANDING = "product_understanding"
    MISSING_INFO_CHECK = "missing_info_check"
    SALES_STRATEGY = "sales_strategy"
    USER_STRATEGY_CONFIRMATION = "user_strategy_confirmation"
    PAGE_PLANNING = "page_planning"
    COPY_GENERATION = "copy_generation"
    VISUAL_PLANNING = "visual_planning"
    IMAGE_COST_APPROVAL = "image_cost_approval"
    IMAGE_GENERATION = "image_generation"
    IMAGE_REVIEW = "image_review"
    PAGE_ASSEMBLY = "page_assembly"
    QA_REVIEW = "qa_review"
    REVIEW_EDITOR = "review_editor"
    EXPORT_PACKAGE = "export_package"


class ProductInput(BaseModel):
    product_name: str | None = None
    description: str | None = None
    product_url: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    reference_urls: list[str] = Field(default_factory=list)


class AgentRunState(BaseModel):
    run_id: str | None = None
    project_id: str
    mode: AgentRunMode = AgentRunMode.MOCK
    current_stage: AgentStage = AgentStage.INTAKE
    product_input: ProductInput
    outputs: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    cost_approval_status: str = "not_required"
    estimated_cost: float | None = None
    actual_cost: float | None = None
    provider_trace: list[dict[str, Any]] = Field(default_factory=list)
