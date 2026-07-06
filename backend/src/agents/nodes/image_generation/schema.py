from pydantic import BaseModel, Field


class GeneratedImageAsset(BaseModel):
    id: str = ""
    role: str
    url: str = ""
    filename: str = ""
    prompt: str = ""


class ImageCandidate(BaseModel):
    candidate_id: str
    slot_id: str
    asset_id: str
    source_type: str
    label: str
    is_recommended: bool = False
    needs_identity_review: bool = False


class ImageGenerationOutput(BaseModel):
    images: list[GeneratedImageAsset] = Field(default_factory=list)
    candidates: dict[str, list[ImageCandidate]] = Field(default_factory=dict)
    skipped: bool = False
    reason: str | None = None


AgentOutputSchema = ImageGenerationOutput
