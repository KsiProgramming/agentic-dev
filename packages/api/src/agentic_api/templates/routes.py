from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agentic_engine.templates import TEMPLATES

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateOut(BaseModel):
    id: str
    name: str
    description: str
    parameters: dict[str, Any] = Field(description="JSON Schema of the template's options.")


@router.get("", operation_id="listTemplates")
async def list_templates() -> list[TemplateOut]:
    """The workflow templates a run can start from (`POST /runs` with `template`)."""
    return [
        TemplateOut(
            id=t.id, name=t.name, description=t.description, parameters=t.parameters_schema()
        )
        for t in TEMPLATES
    ]
