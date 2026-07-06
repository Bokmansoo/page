from pydantic import BaseModel, Field


class ReferenceAnalysisOutput(BaseModel):
    skipped: bool = False
    reference_available: bool = False
    structure_takeaways: list[str] = Field(default_factory=list)
    visual_takeaways: list[str] = Field(default_factory=list)
    copy_risk_notes: list[str] = Field(default_factory=list)
    recommended_rewrite_direction: str = ""


AgentOutputSchema = ReferenceAnalysisOutput
