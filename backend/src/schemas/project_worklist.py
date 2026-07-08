from pydantic import BaseModel


class ProjectWorklistItem(BaseModel):
    project_id: str
    project_name: str
    status: str
    thumbnail_url: str | None = None
    result_url: str | None = None
    review_url: str | None = None
    export_history_url: str
    last_export_status: str | None = None
    run_id: str | None = None
    updated_at: str


class ProjectWorklistResponse(BaseModel):
    items: list[ProjectWorklistItem]
