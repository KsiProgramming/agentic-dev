"""The "Plan, build and review" template (6.8): AC-2's flow, a parallel, an orchestrator in a
review loop, a gate and a pull request, as one sequence:

1. `explore`: a parallel of two read-only analysts on the request: `code_analyst` maps the code
   it touches, `test_analyst` the tests and how to check the change.
2. `review_loop`: a loop, until the reviewer's `verdict` is `ok` or `max_passes` ran, over
   - `implement`: an orchestrator. Its lead reads the analyses and the repo and splits the change
     into at most two tasks on different files; each task's `engineer` does it on its own branch,
     and the branches are merged into the orchestrator's integration branch. In a later pass the
     lead plans only what the review asks, on top of the merged work.
   - `synthesizer`: reads the merged code and writes the pull request's description
     (`pr-description.md`).
   - `reviewer`: reads the merged code and answers a typed `verdict` and `feedback`.
3. `approve_pr`: a gate on the integration branch's diff.
4. `publish`: `github.openPR` from `implement`, its body the synthesizer's description.

Only `engineer` writes and only `publish` publishes, after the gate (tests). The request reaches
every agent as data through the run's context (`RunContext.request`), so the lead keeps it in
every pass although its input is the analyses, then the review.
"""

from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from agentic_engine.spec import WorkflowSpec
from agentic_runtime.pricing import DEFAULT_PRICES

MODELS: Final[tuple[str, ...]] = tuple(DEFAULT_PRICES)
"""The models the agents may be set to: those with a price, so a run's cost is always known."""

MAX_PASSES = 3
DESCRIPTION_ARTIFACT = "pr-description.md"

_READ_TOOLS: Final[list[JsonValue]] = ["repo.list_files", "repo.read_file", "repo.search"]
_WRITE_TOOLS: Final[list[JsonValue]] = [*_READ_TOOLS, "repo.write_file", "repo.commit"]

_Model = Annotated[str, Field(json_schema_extra={"enum": list(MODELS)})] | None

_CODE_ANALYST = (
    "Your input is the change the person who started the run asked for. Your tools read the "
    "repository. Find the code the change touches: list the folders, search for the names in "
    "the request, and read the files involved and the code that calls them. Answer with a short "
    "map for the lead engineer: each file to change and why, the patterns the code already uses "
    "there, and any risk (shared code, public interfaces). Do not change anything."
)
_TEST_ANALYST = (
    "Your input is the change the person who started the run asked for. Your tools read the "
    "repository. Find how this change will be checked: the tests that cover the code it touches, "
    "where new tests belong and how they are written here, and the commands that build and test "
    "the project (from its README, package files or CI configuration). Answer with a short note "
    "for the lead engineer: the test files to add or change and what each should check. Do not "
    "change anything."
)
_LEAD = (
    "Your input is two analysts' notes on the requested change: a map of the code it touches and "
    "how to test it. The request itself is in the run's context. First check the notes with your "
    "tools: read the files they name. Then split the change into at most two independent tasks, "
    "one per engineer, each touching different files so their work merges cleanly; a task "
    "includes the tests for its code. Each task's instructions name exactly which files to change "
    "and what done looks like, following the patterns the code already uses.\n\n"
    "In a later pass, your input is the reviewer's answer (`input`: its `verdict` and "
    "`feedback`) and the tasks of the earlier passes (`previous`). Their work is already in the "
    "code you read: plan only what the feedback asks to change, with the feedback written into "
    "each task's instructions so the engineer fixes exactly what was asked."
)
_ENGINEER = (
    "Your input is your task (`task.instructions`) and the lead's input. Your tools read the "
    "repository on your own branch and write to it. Read the code you need, change only the "
    "files your task names, and commit your work with a clear message. End your answer with a "
    "short report: every file you changed and what you changed in it."
)
_SYNTHESIZER = (
    "Your input is the engineers' reports, one per task, for all the work done so far (every "
    "pass). Your tools read the code with that work in it: read the files the reports name to "
    "check what actually changed. Then write one pull request description for the whole change: "
    "a short summary, then what changed per file and why, then how to check it. Plain Markdown, "
    "no greeting; your answer is the description itself, never a tool call written out as text."
)
_REVIEWER = (
    "Your input is the pull request description of the change. Your tools read the code with "
    "the change in it: read the files it names and check them against the request in the run's "
    "context and against what the description says. Review it as one pull request: does it do "
    "what was asked, do the parts fit together, are there tests, is anything missing or risky? "
    'Answer `verdict` "ok" if it can be opened as a pull request, else "changes", and in '
    "`feedback` say exactly what to change in a few sentences."
)

VERDICT_SCHEMA: Final[dict[str, JsonValue]] = {
    "type": "object",
    "required": ["verdict", "feedback"],
    "properties": {
        "verdict": {"type": "string", "enum": ["ok", "changes"]},
        "feedback": {"type": "string"},
    },
}


class PlanBuildReviewParams(BaseModel):
    """The options of a "Plan, build and review" run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_passes: int = Field(
        default=MAX_PASSES,
        ge=1,
        le=MAX_PASSES,
        description="How many times the reviewer may send the work back to the lead, counting "
        "the first pass.",
    )
    analyst_model: _Model = Field(
        default=None, description="The model of the two analysts. Unset uses the workspace default."
    )
    engineer_model: _Model = Field(
        default=None,
        description="The model of the lead and the engineers. Unset uses the workspace default.",
    )
    reviewer_model: _Model = Field(
        default=None,
        description="The model of the synthesizer and the reviewer. Unset uses the workspace "
        "default.",
    )

    @field_validator("analyst_model", "engineer_model", "reviewer_model")
    @classmethod
    def _priced(cls, value: str | None) -> str | None:
        if value is not None and value not in MODELS:
            raise ValueError(f"must be a model the platform prices: {', '.join(MODELS)}")
        return value


def _agent(
    id: str, role: str, instructions: str, tools: list[JsonValue], model: str | None
) -> dict[str, JsonValue]:
    node: dict[str, JsonValue] = {
        "type": "agent",
        "id": id,
        "role": role,
        "instructions": instructions,
        "tools": list(tools),
    }
    if model is not None:
        node["model"] = model
    return node


def build_plan_build_review_spec(params: PlanBuildReviewParams) -> WorkflowSpec:
    """The workflow for `params`. It always validates: tests check every option."""
    hub: dict[str, JsonValue] = {
        "role": "Lead engineer",
        "instructions": _LEAD,
        "tools": list(_READ_TOOLS),
    }
    if params.engineer_model is not None:
        hub["model"] = params.engineer_model
    synthesizer = _agent(
        "synthesizer", "Release writer", _SYNTHESIZER, _READ_TOOLS, params.reviewer_model
    )
    synthesizer["writes"] = DESCRIPTION_ARTIFACT
    reviewer = _agent("reviewer", "Senior reviewer", _REVIEWER, _READ_TOOLS, params.reviewer_model)
    reviewer["output_schema"] = VERDICT_SCHEMA
    passes = "pass" if params.max_passes == 1 else "passes"
    return WorkflowSpec.model_validate(
        {
            "spec_version": "0",
            "id": "plan-build-review",
            "name": "Plan, build and review",
            "description": "Two analysts study the requested change in parallel, a lead splits "
            "it between two engineers, and a reviewer checks the whole; while the reviewer asks "
            f"for changes, the lead plans them on top of the work so far (at most "
            f"{params.max_passes} {passes}). Writes to the repository on agent branches, then "
            "opens one pull request after you approve.",
            "input": {
                "required": True,
                "label": "What should the team change?",
                "description": "The change to make in the repository, in a few sentences: two "
                "analysts study it, then a lead splits it between two engineers.",
                "example": "Add input validation to the signup form, with tests.",
            },
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {
                        "type": "parallel",
                        "id": "explore",
                        "join": "all",
                        "branches": [
                            _agent(
                                "code_analyst",
                                "Code analyst",
                                _CODE_ANALYST,
                                _READ_TOOLS,
                                params.analyst_model,
                            ),
                            _agent(
                                "test_analyst",
                                "Test analyst",
                                _TEST_ANALYST,
                                _READ_TOOLS,
                                params.analyst_model,
                            ),
                        ],
                    },
                    {
                        "type": "loop",
                        "id": "review_loop",
                        "until": 'results.reviewer.data.verdict == "ok"',
                        "max_iterations": params.max_passes,
                        "body": {
                            "type": "sequence",
                            "id": "pass",
                            "steps": [
                                {
                                    "type": "orchestrator",
                                    "id": "implement",
                                    "hub": hub,
                                    "body": _agent(
                                        "engineer",
                                        "Software engineer",
                                        _ENGINEER,
                                        _WRITE_TOOLS,
                                        params.engineer_model,
                                    ),
                                    "max_workers": 2,
                                    "max_concurrency": 2,
                                    "replan": {"on": "failure", "max_rounds": 1},
                                },
                                synthesizer,
                                reviewer,
                            ],
                        },
                    },
                    {
                        "type": "gate",
                        "id": "approve_pr",
                        "title": "Open the pull request?",
                        "prompt": "Every pass's work is merged on one branch. Check the diff and "
                        "the reviewer's last verdict: if it still asked for changes after the "
                        "last pass, its feedback says what is missing. Approving pushes the "
                        "branch to GitHub and opens a pull request.",
                    },
                    {
                        "type": "tool",
                        "id": "publish",
                        "tool": "github.openPR",
                        "args": {
                            "from_node": "implement",
                            "title": "Planned, built and reviewed change",
                            "body": "Agents planned, built and reviewed this change; the run was "
                            "approved at a gate before this pull request was opened. Review it "
                            "as you would any change: agents can be wrong.",
                            "body_from": DESCRIPTION_ARTIFACT,
                        },
                    },
                ],
            },
        }
    )
