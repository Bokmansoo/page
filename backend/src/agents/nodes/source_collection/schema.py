from typing import Literal

from pydantic import BaseModel, Field


class CollectedImageSource(BaseModel):
    asset_id: str | None = None
    filename: str = ""
    source_type: Literal["uploaded", "url-extracted", "url-imported"] = "uploaded"
    url: str | None = None


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
    reference_text_blocks: list[str] = Field(default_factory=list)
    source_summary: SourceSummary = Field(default_factory=SourceSummary)


AgentOutputSchema = SourceCollectionOutput
