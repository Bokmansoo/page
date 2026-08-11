"""Contracts for the UX-2E-0 provider-free generation pipeline.

The plan APIs deliberately do not call an AI provider.  The typed job contracts
below are the stable hand-off point for UX-2E, when a provider is connected.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class GenerationPlanSceneUpdateSchema(BaseModel):
    id: str
    objective: str | None = None
    reference_asset_ids: list[str] | None = None
    source_fact_ids: list[str] | None = None
    expected_copy: dict[str, str] | None = None
    seller_note: str | None = None
    regeneration_reason: str | None = None
    seller_approved: bool | None = None


class GenerationPlanUpdateSchema(BaseModel):
    product_brief: "ProductBriefUpdateSchema | None" = None
    scenes: list[GenerationPlanSceneUpdateSchema] = Field(default_factory=list)


class ProductBriefUpdateSchema(BaseModel):
    product_name: str | None = None
    category: str | None = None
    model_option: str | None = None
    options: list[str] | None = None
    color: str | None = None
    sales_channel: str | None = None
    seller_input: str | None = None
    forbidden_claims: list[str] | None = None
    identity_criteria: dict[str, Any] | None = None


GenerationJobStatus = Literal[
    "draft", "pending_provider", "running", "needs_seller_review",
    "succeeded", "failed", "cancelled", "stale",
]
GenerationFailureCategory = Literal[
    "provider_error", "safety_blocked", "identity_mismatch",
    "seller_rejected", "validation_failed", "not_connected",
]


class GenerationOutputSpecSchema(BaseModel):
    kind: Literal["generated_image", "generated_copy"]
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    format: str | None = None


class GenerationJobRequestSchema(BaseModel):
    """Provider-neutral request. Sensitive provider credentials are never here."""

    request_id: str
    project_id: str
    plan_version: int
    scene_id: str
    product_brief: dict[str, Any]
    reference_asset_ids: list[str] = Field(default_factory=list)
    prompt_blueprint: dict[str, Any]
    output_spec: GenerationOutputSpecSchema
    seller_approved: bool


class GenerationValidationResultSchema(BaseModel):
    product_identity: Literal["pending", "passed", "failed"] = "pending"
    ocr: Literal["pending", "passed", "failed"] = "pending"
    rights: Literal["pending", "passed", "failed"] = "pending"
    warnings: list[str] = Field(default_factory=list)


class GenerationJobResultSchema(BaseModel):
    request_id: str
    status: GenerationJobStatus
    provider_job_id: str | None = None
    generated_text: str | None = None
    output_asset_id: str | None = None
    estimated_cost: float | None = Field(default=None, ge=0)
    actual_cost: float | None = Field(default=None, ge=0)
    provider_response_id: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    validation: GenerationValidationResultSchema = Field(default_factory=GenerationValidationResultSchema)
    failure_category: GenerationFailureCategory | None = None
    retryable: bool = False
    message: str | None = None


class ApiReadyGenerationPlanSchema(BaseModel):
    version: int
    provider_mode: str
    created_at: str
    updated_at: str | None = None
    product_brief: dict[str, Any]
    scenes: list[dict[str, Any]]
    summary: dict[str, int]


class GroundedCopyDraftRequestSchema(BaseModel):
    scene_ids: list[str] = Field(default_factory=list)
    seller_cost_approved: bool = False


class GroundedCopyDraftEstimateSchema(BaseModel):
    project_id: str
    scene_count: int
    estimated_cost: float = 0
    provider: str
    model: str


class GroundedCopyDraftResponseSchema(BaseModel):
    project_id: str
    estimated_cost: float = 0
    actual_cost: float = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    plan: dict[str, Any]


class GroundedCopyDraftDecisionSchema(BaseModel):
    seller_approved: bool
