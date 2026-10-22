"""Workflow templates: named, parameterised builders of workflow specs.

A template turns a small set of options (a Pydantic model, exported as JSON Schema for forms)
into an ordinary `WorkflowSpec`, which is validated and run like any other. Templates are code
for now; saved and versioned templates come later (4.7, 8.9).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, JsonValue

from agentic_engine.spec import WorkflowSpec
from agentic_engine.templates.docs import DocsParams, build_docs_spec


@dataclass(frozen=True)
class Template[P: BaseModel]:
    id: str
    name: str
    description: str
    params: type[P]
    build: Callable[[P], WorkflowSpec]

    def parameters_schema(self) -> dict[str, Any]:
        """The JSON Schema of the template's options."""
        return self.params.model_json_schema()

    def build_spec(self, parameters: Mapping[str, JsonValue]) -> WorkflowSpec:
        """The spec for `parameters`; raises `pydantic.ValidationError` if they are invalid."""
        return self.build(self.params.model_validate(dict(parameters)))


TEMPLATES: tuple[Template[Any], ...] = (
    Template(
        id="generate-docs",
        name="Generate docs",
        description="Documents each module of the repository in Markdown, then opens a pull "
        "request after you approve.",
        params=DocsParams,
        build=build_docs_spec,
    ),
)


def get_template(template_id: str) -> Template[Any] | None:
    return next((t for t in TEMPLATES if t.id == template_id), None)


__all__ = ["TEMPLATES", "DocsParams", "Template", "build_docs_spec", "get_template"]
