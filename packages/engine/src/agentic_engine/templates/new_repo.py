"""Running a workflow on a repo it creates first (phase 1.12).

`wrap_with_create_repo` puts two steps before a workflow's own: a gate that asks to create the
repo, then a `github.createRepo` tool node. The run is given the new repo's URL from the start;
the worker clones it once it exists (see `agentic_engine.graph.compile`).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from agentic_engine.spec import Node, SequenceNode, WorkflowSpec, parse_spec

Gitignore = Literal["Python", "Node", "Go", "Rust", "Java", "VisualStudio"]
"""The `.gitignore` templates a new repo may start with (GitHub's names; the same list as
`agentic_github.GITIGNORE_TEMPLATES`)."""

License = Literal["mit", "apache-2.0"]
"""The licenses a new repo may start with (GitHub's keys; `agentic_github.LICENSE_TEMPLATES`)."""

APPROVE_NODE_ID = "approve_repo"
CREATE_NODE_ID = "create_repo"

_LICENSE_NAMES: dict[str, str] = {"mit": "MIT", "apache-2.0": "Apache 2.0"}


class NewRepo(BaseModel):
    """A repo to create in the organisation the workspace's GitHub App is installed on."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str,
        Field(
            pattern=r"^[A-Za-z0-9._-]{1,100}$",
            title="Name",
            description="Letters, digits, `.`, `-` and `_`, up to 100 characters.",
        ),
    ]
    private: bool = Field(
        default=True, title="Private", description="Only the organisation can see it."
    )
    description: str | None = Field(default=None, max_length=350, title="Description")
    gitignore: Gitignore | None = Field(
        default=None, title=".gitignore", description="A template for the first commit."
    )
    license: License | None = Field(
        default=None, title="License", description="A license for the first commit."
    )

    @field_validator("name")
    @classmethod
    def _not_dots(cls, name: str) -> str:
        if name in (".", ".."):
            raise ValueError("a repo cannot be named '.' or '..'")
        return name


def wrap_with_create_repo(spec: WorkflowSpec, repo: NewRepo, owner: str) -> WorkflowSpec:
    """`spec` with a gate and a `github.createRepo` node for `owner/<repo.name>` before its
    steps. A root sequence keeps its id, with the two steps first."""
    args: dict[str, JsonValue] = {"name": repo.name, "private": repo.private}
    if repo.description:
        args["description"] = repo.description
    if repo.gitignore:
        args["gitignore"] = repo.gitignore
    if repo.license:
        args["license"] = repo.license
    first: list[dict[str, JsonValue]] = [
        {
            "type": "gate",
            "id": APPROVE_NODE_ID,
            "title": f"Create the repo {owner}/{repo.name}?",
            "prompt": create_prompt(repo, owner),
        },
        {"type": "tool", "id": CREATE_NODE_ID, "tool": "github.createRepo", "args": args},
    ]
    root = spec.root
    steps: list[JsonValue] = [*first]
    if isinstance(root, SequenceNode):
        root_id = root.id
        steps += [_dump(step) for step in root.steps]
    else:
        root_id = "main" if root.id != "main" else "workflow"
        steps.append(_dump(root))
    raw = spec.model_dump(mode="json", by_alias=True)
    raw["root"] = {"type": "sequence", "id": root_id, "steps": steps}
    return parse_spec(raw)


def create_prompt(repo: NewRepo, owner: str) -> str:
    """What the approver is asked: the repo and what its first commit holds."""
    visibility = "private" if repo.private else "public"
    holds = ["a README"]
    if repo.gitignore:
        holds.append(f"a {repo.gitignore} .gitignore")
    if repo.license:
        holds.append(f"the {_LICENSE_NAMES[repo.license]} license")
    listed = ", ".join(holds[:-1]) + f" and {holds[-1]}" if len(holds) > 1 else holds[0]
    return (
        f"Creates the {visibility} repo {owner}/{repo.name} on GitHub, with a first commit "
        f"holding {listed}. The workflow then runs on it."
    )


def _dump(node: Node) -> JsonValue:
    return node.model_dump(mode="json", by_alias=True)
