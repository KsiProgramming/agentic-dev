"""Policy limits: what a run may use, whatever its spec says (mission principle 2).

`PLATFORM_POLICY` holds the tech-stack defaults, which are also the ceilings: a workspace may
lower each limit, never raise it. A run gets its effective policy when it is created and keeps it,
resumes included. Specs are checked against it before the run starts (`policy_errors` in
`agentic_engine.spec`), and the engine and worker enforce it while the run executes.
"""

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

type PolicyLimit = Literal[
    "agents_alive", "agents_spawned", "max_depth", "loop_iterations", "wall_time_s"
]

Limit = Annotated[int, Field(ge=1)]


class Policy(BaseModel):
    """The limits one run executes under."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agents_alive: Limit = Field(description="Agents running at once.")
    agents_spawned: Limit = Field(description="Agents a run may start in all.")
    max_depth: Limit = Field(description="How deep loops and maps may nest.")
    loop_iterations: Limit = Field(description="The highest `max_iterations` a loop may have.")
    wall_time_s: Limit = Field(
        description="Seconds a run may spend executing; time waiting at a gate does not count."
    )


PLATFORM_POLICY: Final = Policy(
    agents_alive=8, agents_spawned=40, max_depth=2, loop_iterations=5, wall_time_s=2 * 60 * 60
)
"""The tech-stack defaults, and the ceilings a workspace policy cannot go above."""


class PolicyOverrides(BaseModel):
    """A workspace's own limits; `None` keeps the platform's."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agents_alive: Limit | None = None
    agents_spawned: Limit | None = None
    max_depth: Limit | None = None
    loop_iterations: Limit | None = None
    wall_time_s: Limit | None = None


def effective_policy(overrides: PolicyOverrides | None = None) -> Policy:
    """`PLATFORM_POLICY` with each limit lowered to the workspace's, where it set one."""
    base = PLATFORM_POLICY.model_dump()
    if overrides is not None:
        for name, value in overrides.model_dump(exclude_none=True).items():
            base[name] = min(base[name], value)
    return Policy.model_validate(base)


LIMIT_LABELS: Final[dict[PolicyLimit, str]] = {
    "agents_alive": "agents alive",
    "agents_spawned": "agents spawned",
    "max_depth": "nesting depth",
    "loop_iterations": "loop iterations",
    "wall_time_s": "wall time",
}


def format_duration(seconds: int) -> str:
    """`7200` → `2h 0m`, `90` → `1m 30s`, `5` → `5s`."""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    return f"{secs}s"


class PolicyLimitExceeded(Exception):
    """A run went over one of its limits. `value` is the limit, `observed` what the run reached
    or would have reached; `node_id` names the node that hit it, if one did. The worker also
    cancels a run's task with one of these, so the run ends `failed` instead of `cancelled`."""

    limit: PolicyLimit
    value: int
    observed: int
    node_id: str | None

    def __init__(
        self, limit: PolicyLimit, value: int, observed: int, node_id: str | None = None
    ) -> None:
        self.limit = limit
        self.value = value
        self.observed = observed
        self.node_id = node_id
        super().__init__(self.reason)

    @property
    def reason(self) -> str:
        """The run's failure reason, e.g. `policy limit: wall time of 2h 0m exceeded`."""
        label = LIMIT_LABELS[self.limit]
        if self.limit == "wall_time_s":
            return f"policy limit: {label} of {format_duration(self.value)} exceeded"
        return f"policy limit: {label} would reach {self.observed}, above the limit of {self.value}"

    def payload(self) -> dict[str, JsonValue]:
        """The `policy_limit_exceeded` event's payload."""
        return {"limit": self.limit, "value": self.value, "observed": self.observed}
