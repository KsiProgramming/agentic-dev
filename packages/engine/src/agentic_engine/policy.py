"""Policy limits: what a run may use, whatever its spec says (mission principle 2).

`PLATFORM_POLICY` holds the tech-stack defaults, which are also the ceilings: a workspace may
lower each limit, never raise it. A run gets its effective policy when it is created and keeps it,
resumes included. Specs are checked against it before the run starts (`policy_errors` in
`agentic_engine.spec`), and the engine and worker enforce it while the run executes.

The budget is the one optional limit: no budget means no cost cap. It has no platform ceiling;
a workspace's budget is a default that a run may replace (`with_budget`).
"""

from decimal import Decimal
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

type PolicyLimit = Literal[
    "agents_alive", "agents_spawned", "max_depth", "loop_iterations", "wall_time_s", "budget_usd"
]

Limit = Annotated[int, Field(ge=1)]
Usd = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=8)]


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
    budget_usd: Usd | None = Field(
        default=None,
        description="USD the run may spend, a hard stop once reached; `None` is no cost cap.",
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
    budget_usd: Usd | None = None


def effective_policy(overrides: PolicyOverrides | None = None) -> Policy:
    """`PLATFORM_POLICY` with each limit lowered to the workspace's, where it set one, and the
    workspace's budget, which has no platform ceiling."""
    base = PLATFORM_POLICY.model_dump()
    if overrides is not None:
        for name, value in overrides.model_dump(exclude_none=True).items():
            base[name] = value if name == "budget_usd" else min(base[name], value)
    return Policy.model_validate(base)


def with_budget(policy: Policy, budget_usd: Decimal | None) -> Policy:
    """`policy` with the run's own budget in place of the workspace's, if the run set one."""
    return policy if budget_usd is None else policy.model_copy(update={"budget_usd": budget_usd})


LIMIT_LABELS: Final[dict[PolicyLimit, str]] = {
    "agents_alive": "agents alive",
    "agents_spawned": "agents spawned",
    "max_depth": "nesting depth",
    "loop_iterations": "loop iterations",
    "wall_time_s": "wall time",
    "budget_usd": "budget",
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


def format_usd(amount: Decimal) -> str:
    """`Decimal("5")` → `$5.00`, `Decimal("0.01034567")` → `$0.0103`: cents from $1, else up to
    four decimals, so a small budget still reads exactly."""
    if amount >= 1:
        return f"${amount:.2f}"
    whole, _, decimals = f"{amount.quantize(Decimal('0.0001')):f}".rstrip("0").partition(".")
    return f"${whole}.{decimals.ljust(2, '0')}"


class PolicyLimitExceeded(Exception):
    """A run went over one of its limits. `value` is the limit, `observed` what the run reached
    or would have reached; `node_id` names the node that hit it, if one did. The worker also
    cancels a run's task with one of these, so the run ends `failed` instead of `cancelled`.

    The budget's amounts are USD `Decimal`s. `unpriced_model` names the model of a usage that had
    no price: the budget cannot be held to it, so that stops the run too."""

    limit: PolicyLimit
    value: int | Decimal
    observed: int | Decimal
    node_id: str | None
    unpriced_model: str | None

    def __init__(
        self,
        limit: PolicyLimit,
        value: int | Decimal,
        observed: int | Decimal,
        node_id: str | None = None,
        *,
        unpriced_model: str | None = None,
    ) -> None:
        self.limit = limit
        self.value = value
        self.observed = observed
        self.node_id = node_id
        self.unpriced_model = unpriced_model
        super().__init__(self.reason)

    @property
    def reason(self) -> str:
        """The run's failure reason, e.g. `policy limit: wall time of 2h 0m exceeded`."""
        label = LIMIT_LABELS[self.limit]
        if isinstance(self.value, Decimal) and isinstance(self.observed, Decimal):
            budget = format_usd(self.value)
            if self.unpriced_model is not None:
                return (
                    f"policy limit: {label} of {budget} cannot be enforced: model "
                    f"{self.unpriced_model!r} has no price"
                )
            return f"policy limit: {label} of {budget} reached ({format_usd(self.observed)} spent)"
        if self.limit == "wall_time_s":
            return f"policy limit: {label} of {format_duration(int(self.value))} exceeded"
        return f"policy limit: {label} would reach {self.observed}, above the limit of {self.value}"

    def payload(self) -> dict[str, JsonValue]:
        """The `policy_limit_exceeded` event's payload; USD amounts are decimal strings."""
        payload: dict[str, JsonValue] = {
            "limit": self.limit,
            "value": _json_number(self.value),
            "observed": _json_number(self.observed),
        }
        if self.unpriced_model is not None:
            payload["model"] = self.unpriced_model
        return payload


def _json_number(value: int | Decimal) -> JsonValue:
    """An amount as JSON: a `Decimal` as its shortest decimal string (`1.20000000` → `1.2`)."""
    return f"{value.normalize():f}" if isinstance(value, Decimal) else value
