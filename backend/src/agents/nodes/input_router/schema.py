from typing import Literal

from pydantic import BaseModel, Field


class InputRouterOutput(BaseModel):
    input_type: Literal["image", "url", "mixed", "text_only"] = "mixed"
    missing_inputs: list[str] = Field(default_factory=list)


AgentOutputSchema = InputRouterOutput
