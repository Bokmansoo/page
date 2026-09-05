from typing import Literal

from pydantic import BaseModel, Field


class CollectedImageSource(BaseModel):
    asset_id: str | None = None
    filename: str = ""
    # Additive expansion: existing records have always contained self_shot and
    # sourced provenance, so the LG-2 schema must not discard it.
    source_type: Literal["uploaded", "self_shot", "sourced", "local_upscaled", "url-extracted", "url-imported"] = "uploaded"
    url: str | None = None
    asset_role: str = "unknown"
    role_confidence: float = 0.0
    quality_status: str = "warning"
    quality_warnings: list[str] = Field(default_factory=list)
    is_representative: bool = False
    usage_status: str = "seller_owned"


class SourceSummary(BaseModel):
    has_uploaded_image: bool = False
    has_product_url: bool = False
    has_freeform_input: bool = False
    has_reference_url: bool = False
    primary_visual_source: Literal["uploaded", "url", "none"] = "none"


class SourceCollectionOutput(BaseModel):
    product_url: str = ""
    freeform_input: str = ""
    reference_urls: list[str] = Field(default_factory=list)
    uploaded_images: list[CollectedImageSource] = Field(default_factory=list)
    url_images: list[CollectedImageSource] = Field(default_factory=list)
    reference_images: list[CollectedImageSource] = Field(default_factory=list)
    reference_text_blocks: list[str] = Field(default_factory=list)
    source_summary: SourceSummary = Field(default_factory=SourceSummary)
    collection_failures: list[dict[str, str]] = Field(default_factory=list)
    asset_understanding_blockers: list[dict[str, str]] = Field(default_factory=list)


AgentOutputSchema = SourceCollectionOutput
