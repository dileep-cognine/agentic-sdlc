from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.state import WorkflowState


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    state: WorkflowState
    version: int
    created_at: datetime
    updated_at: datetime


class RequirementSubmit(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    text: str = Field(min_length=1, max_length=100000)
    expected_version: int = Field(ge=1)


class RequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    requirement_id: str
    version: int
    text: str
    created_at: datetime
