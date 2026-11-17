"""Shapes of the Jira trigger routes (7.3)."""

from datetime import datetime
from typing import Annotated, Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentic_api.jira.models import CloudId
from agentic_api.runs.models import StoredWorkflowRun
from agentic_sandbox import RepoSource
from agentic_store import JiraTriggerFields, JiraTriggerInfo

ProjectKey = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]
TriggerValue = Annotated[str, Field(min_length=1, max_length=255)]
TriggerOn = Literal["status", "label"]
FireOutcome = Literal["started", "already_running", "start_failed"]


class _TriggerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _label_has_no_space(self) -> Self:
        on, value = getattr(self, "on", None), getattr(self, "value", None)
        if on == "label" and isinstance(value, str) and any(c.isspace() for c in value.strip()):
            raise ValueError("a Jira label cannot hold a space")
        return self


class JiraTriggerIn(_TriggerBody):
    """A rule: when an issue of `project_key` on the site moves to the status `value` (`on:
    status`) or gets the label `value` (`on: label`), run `template_id` or `workflow` on `repo`
    with the issue key as input. Give `template_id` or `workflow`, not both."""

    cloud_id: CloudId
    project_key: ProjectKey
    on: TriggerOn
    value: TriggerValue
    template_id: Annotated[str | None, Field(max_length=128)] = None
    workflow: StoredWorkflowRun | None = Field(
        default=None, description="A stored workflow; no `version` runs the latest."
    )
    repo: RepoSource | None = Field(
        default=None, description="The repo the run works on, when its workflow needs one."
    )
    enabled: bool = True

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.template_id is None) == (self.workflow is None):
            raise ValueError("give one of `template_id` and `workflow`")
        return self

    def fields(self) -> JiraTriggerFields:
        return JiraTriggerFields(
            cloud_id=self.cloud_id,
            project_key=self.project_key.upper(),
            on=self.on,
            value=self.value.strip(),
            template_id=self.template_id,
            workflow_id=self.workflow.id if self.workflow else None,
            workflow_version=self.workflow.version if self.workflow else None,
            repo_url=self.repo.url if self.repo else None,
            ref=self.repo.ref if self.repo else None,
            enabled=self.enabled,
        )


class JiraTriggerPatch(_TriggerBody):
    """Changes to a rule: only the fields given change. Setting `template_id` drops the
    workflow and the other way round; `repo: null` drops the repo."""

    cloud_id: CloudId | None = None
    project_key: ProjectKey | None = None
    on: TriggerOn | None = None
    value: TriggerValue | None = None
    template_id: Annotated[str | None, Field(max_length=128)] = None
    workflow: StoredWorkflowRun | None = None
    repo: RepoSource | None = None
    enabled: bool | None = None

    def applied_to(self, rule: JiraTriggerFields) -> JiraTriggerIn:
        given = self.model_fields_set
        repo = rule_repo(rule)
        workflow = rule_workflow(rule)
        template_id = rule.template_id
        if "template_id" in given and self.template_id is not None:
            template_id, workflow = self.template_id, None
        if "workflow" in given and self.workflow is not None:
            template_id, workflow = None, self.workflow
        return JiraTriggerIn(
            cloud_id=self.cloud_id or rule.cloud_id,
            project_key=self.project_key or rule.project_key,
            on=self.on or rule.on,
            value=self.value or rule.value,
            template_id=template_id,
            workflow=workflow,
            repo=self.repo if "repo" in given else repo,
            enabled=rule.enabled if self.enabled is None else self.enabled,
        )


def rule_repo(rule: JiraTriggerFields) -> RepoSource | None:
    return RepoSource(url=rule.repo_url, ref=rule.ref) if rule.repo_url else None


def rule_workflow(rule: JiraTriggerFields) -> StoredWorkflowRun | None:
    if rule.workflow_id is None:
        return None
    return StoredWorkflowRun(id=rule.workflow_id, version=rule.workflow_version)


class JiraTriggerLast(BaseModel):
    """The last thing the rule did with an issue."""

    at: datetime
    outcome: FireOutcome = Field(
        description="`started` a run, found one `already_running` on the issue, or the start "
        "was refused (`start_failed`, with `reason`)."
    )
    issue_key: str
    run_id: UUID | None
    reason: str | None


class JiraTriggerOut(BaseModel):
    id: UUID
    cloud_id: str
    project_key: str
    on: TriggerOn
    value: str
    template_id: str | None
    workflow: StoredWorkflowRun | None
    repo: RepoSource | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last: JiraTriggerLast | None

    @classmethod
    def of(cls, info: JiraTriggerInfo) -> "JiraTriggerOut":
        rule = info.fields
        last = info.last
        return cls(
            id=info.id,
            cloud_id=rule.cloud_id,
            project_key=rule.project_key,
            on=rule.on,
            value=rule.value,
            template_id=rule.template_id,
            workflow=rule_workflow(rule),
            repo=rule_repo(rule),
            enabled=rule.enabled,
            created_at=info.created_at,
            updated_at=info.updated_at,
            last=None
            if last is None
            else JiraTriggerLast(
                at=last.at,
                outcome=cast(FireOutcome, last.outcome),
                issue_key=last.issue_key,
                run_id=last.run_id,
                reason=last.reason,
            ),
        )


class JiraTriggerList(BaseModel):
    triggers: list[JiraTriggerOut]


class JiraStatusList(BaseModel):
    """The project's status names, read live from Jira."""

    statuses: list[str]
