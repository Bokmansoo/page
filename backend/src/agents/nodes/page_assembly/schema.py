from typing import Any

from pydantic import BaseModel, Field


class PageAssemblySection(BaseModel):
    id: str
    kind: str = "content"
    title: str = ""
    body: str = ""
    image: dict[str, Any] | None = None


class PageAssemblyOutput(BaseModel):
    sections: list[PageAssemblySection] = Field(default_factory=list)
    preview: dict[str, Any] = Field(default_factory=dict)


AgentOutputSchema = PageAssemblyOutput
