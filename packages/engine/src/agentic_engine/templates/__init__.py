"""Workflow templates: named, parameterised builders of workflow specs.

A template turns a small set of options (a Pydantic model, exported as JSON Schema for forms)
into an ordinary `WorkflowSpec`, which is validated and run like any other. Templates are code
for now; saved and versioned templates come later (5.7, 9.9).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, JsonValue

from agentic_engine.spec import WorkflowSpec
from agentic_engine.templates.audit import AuditParams, build_audit_spec
from agentic_engine.templates.docs import DocsParams, build_docs_spec
from agentic_engine.templates.jira_issue_answer import (
    JiraIssueAnswerParams,
    build_jira_issue_answer_spec,
)
from agentic_engine.templates.new_repo import (
    APPROVE_NODE_ID,
    CREATE_NODE_ID,
    Gitignore,
    License,
    NewRepo,
    wrap_with_create_repo,
)
from agentic_engine.templates.plan_build_review import (
    PlanBuildReviewParams,
    build_plan_build_review_spec,
)
from agentic_engine.templates.sdd import SddParams, build_sdd_spec

type Requirement = Literal["claude", "github", "jira"]
"""A connection a workspace needs before it can run a template: `claude` for its agents,
`github` for a repo picked from the GitHub App's installation and for `github.*` tools, `jira`
for `jira.*` tools (7.2)."""


@dataclass(frozen=True)
class Template[P: BaseModel]:
    id: str
    name: str
    description: str
    params: type[P]
    build: Callable[[P], WorkflowSpec]
    requires: tuple[Requirement, ...] = ()

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
        requires=("claude", "github"),
    ),
    Template(
        id="audit-codebase",
        name="Audit codebase",
        description="Checks the repository with scanners and reviewer agents, then writes "
        "findings.json and a readable report. Read-only: it changes nothing and opens no pull "
        "request.",
        params=AuditParams,
        build=build_audit_spec,
        requires=("claude", "github"),
    ),
    Template(
        id="plan-build-review",
        name="Plan, build and review",
        description="Two analysts study the change you ask for, a lead splits it between two "
        "engineers and a reviewer sends it back until it is right. Writes to the repository on "
        "agent branches, then opens one pull request after you approve.",
        params=PlanBuildReviewParams,
        build=build_plan_build_review_spec,
        requires=("claude", "github"),
    ),
    Template(
        id="sdd",
        name="Build from a Jira issue",
        description="Writes a specification from a Jira issue and the code, then plans it, "
        "builds it with a team of engineers and a reviewer, and opens one pull request with the "
        "specification, plan and tasks. Links it on the issue. You approve the specification "
        "and the pull request.",
        params=SddParams,
        build=build_sdd_spec,
        requires=("claude", "github", "jira"),
    ),
    Template(
        id="jira-issue-answer",
        name="Answer a Jira issue",
        description="Reads a Jira issue and the code it is about, then posts a comment on the "
        "issue after you approve it.",
        params=JiraIssueAnswerParams,
        build=build_jira_issue_answer_spec,
        requires=("claude", "github", "jira"),
    ),
)


def get_template(template_id: str) -> Template[Any] | None:
    return next((t for t in TEMPLATES if t.id == template_id), None)


__all__ = [
    "APPROVE_NODE_ID",
    "CREATE_NODE_ID",
    "TEMPLATES",
    "AuditParams",
    "DocsParams",
    "Gitignore",
    "JiraIssueAnswerParams",
    "License",
    "NewRepo",
    "PlanBuildReviewParams",
    "SddParams",
    "Requirement",
    "Template",
    "build_audit_spec",
    "build_docs_spec",
    "build_jira_issue_answer_spec",
    "build_plan_build_review_spec",
    "build_sdd_spec",
    "get_template",
    "wrap_with_create_repo",
]
