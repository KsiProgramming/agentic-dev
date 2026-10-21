from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agentic_engine.spec import WorkflowSpec


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: WorkflowSpec
    input: str = ""


class CreateRunResponse(BaseModel):
    run_id: UUID
    status: Literal["queued"] = "queued"
    events_url: str
