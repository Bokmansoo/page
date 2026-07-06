from typing import List, Literal
from pydantic import BaseModel, Field, model_validator

VISUAL_ROLES = [
    "representative_product",
    "cutout_product",
    "lifestyle_scene",
    "problem_scene",
    "benefit_visual",
    "detail_closeup",
    "comparison_graphic",
    "badge_set",
    "faq_graphic",
    "thumbnail",
    "cta_visual",
]

VisualRole = Literal[
    "representative_product",
    "cutout_product",
    "lifestyle_scene",
    "problem_scene",
    "benefit_visual",
    "detail_closeup",
    "comparison_graphic",
    "badge_set",
    "faq_graphic",
    "thumbnail",
    "cta_visual",
]

class ImageGenerationJob(BaseModel):
    job_id: str
    section_id: str
    plan_signature: str
    role: VisualRole
    source_asset_ids: List[str] = Field(default_factory=list)
    prompt: str
    negative_prompt: str = ""
    preserve_product_identity: bool = True
    output_size: str = "1024x1024"
    cost_tier: Literal["standard", "premium"] = "standard"
    status: Literal["planned", "needs_generation"] = "planned"

    @model_validator(mode="after")
    def validate_job(self) -> 'ImageGenerationJob':
        if not self.job_id or not self.job_id.strip():
            raise ValueError("job_id must not be empty.")
        if not self.section_id or not self.section_id.strip():
            raise ValueError("section_id must not be empty.")
        if not self.plan_signature or not self.plan_signature.strip():
            raise ValueError("plan_signature must not be empty.")
        if self.status == "planned" and not self.source_asset_ids:
            raise ValueError(
                "source_asset_ids must not be empty for planned status."
            )
        if self.status == "needs_generation":
            if not self.prompt or not self.prompt.strip():
                raise ValueError("Prompt must not be empty for needs_generation status.")
            if self.preserve_product_identity and not self.source_asset_ids:
                raise ValueError("source_asset_ids must not be empty if preserve_product_identity is True and status is needs_generation.")
            if not self.output_size or not self.output_size.strip():
                raise ValueError("output_size must not be empty.")
            if not self.cost_tier or self.cost_tier not in ("standard", "premium"):
                raise ValueError("cost_tier must be standard or premium.")
        return self
