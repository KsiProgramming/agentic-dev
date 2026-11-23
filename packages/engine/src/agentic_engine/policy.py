"""Policy limits: what a run may use, whatever its spec says (mission principle 2).

`PLATFORM_POLICY` holds the tech-stack defaults, which are also the ceilings: a workspace may
lower each limit, never raise it. Two retention limits (12.3) have a ceiling above their default,
in `CEILINGS`: how long a failed or cancelled run's sandbox is kept, and how long its saved
commits are; so does `review_rounds`, how many follow-ups a pull request review may start (7.6).
A run gets its effective policy when it is created and keeps it,
resumes included. Specs are checked against it before the run starts (`policy_errors` in
`agentic_engine.spec`), and the engine and worker enforce it while the run executes.

The budget is the one optional limit: no budget means no cost cap. It has no platform ceiling;
a workspace's budget is a default that a workflow (its spec's `budget_usd`) and then a run may
replace (`with_budget`).
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

type PolicyLimit = Literal[
    "agents_alive",
    "agents_spawned",
    "max_depth",
    "loop_iterations",
    "wall_time_s",
    "approval_ttl_s",
    "budget_usd",
]

Limit = Annotated[int, Field(ge=1)]
Usd = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=8)]

BUDGET_MIN_USD: Final = 0.01
BUDGET_MAX_USD: Final = 1_000_000
"""The range of a budget, wherever it is set (workspace, workflow, run)."""

APPROVAL_TTL_S: Final = 72 * 60 * 60
"""How long a gate waits for a decision by default, and at most: 72 h."""

SANDBOX_TTL_S: Final = 24 * 60 * 60
"""How long a failed or cancelled run's sandbox is kept by default (12.3): 24 h."""
SANDBOX_TTL_MAX_S: Final = 72 * 60 * 60
BRANCH_RETENTION_DAYS: Final = 30
"""How long a finished run's saved commits (its branches' bundles) are kept by default: 30 days.
Their changed files are kept for good."""
BRANCH_RETENTION_MAX_DAYS: Final = 90
REVIEW_ROUNDS: Final = 3
"""How many follow-up runs a pull request review may start by default (7.6)."""
REVIEW_ROUNDS_MAX: Final = 10


BREAKER_RANGES: Final[dict[str, tuple[float, float]]] = {
    "repeat_calls": (2, 50),
    "repeat_errors": (2, 50),
    "cost_multiple": (1.5, 20),
    "cost_floor_usd": (0, 1_000),
    "flip_flops": (1, 10),
}
"""The platform range of each circuit-breaker threshold (13.7), wherever it is set (workspace,
workflow). A value outside it is clamped when resolved, and refused when a workflow sets it."""


class BreakerPolicy(BaseModel):
    """The thresholds of the four circuit breakers (13.7): the engine pauses a step that crosses
    one. Defaults are the platform's; a workspace and a workflow may tune each within
    `BREAKER_RANGES`, never turn one off."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repeat_calls: int = Field(
        default=5, description="Calls of one tool with the same arguments in one step."
    )
    repeat_errors: int = Field(
        default=3, description="Errors with the same text from one tool in one step."
    )
    cost_multiple: float = Field(
        default=3.0, description="A step's cost, as a multiple of its node's average."
    )
    cost_floor_usd: float = Field(
        default=0.5, description="USD a step must also cost above its node's average to trip."
    )
    flip_flops: int = Field(
        default=2, description="Times one step rewrites a file back to an earlier content."
    )


class BreakerOverrides(BaseModel):
    """A workspace's own breaker thresholds (13.7); `None` keeps the platform's. Held to
    `BREAKER_RANGES` when the policy is resolved (`effective_policy`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repeat_calls: int | None = None
    repeat_errors: int | None = None
    cost_multiple: float | None = None
    cost_floor_usd: float | None = None
    flip_flops: int | None = None


def clamp_breakers(values: Mapping[str, float]) -> dict[str, float]:
    """`values` (threshold name → value) with each value held to its `BREAKER_RANGES`."""
    return {
        name: min(BREAKER_RANGES[name][1], max(BREAKER_RANGES[name][0], value))
        for name, value in values.items()
    }


class Policy(BaseModel):
    """The limits one run executes under."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agents_alive: Limit = Field(description="Agents running at once.")
    agents_spawned: Limit = Field(description="Agents a run may start in all.")
    max_depth: Limit = Field(description="How deep loops, maps and parallels may nest.")
    loop_iterations: Limit = Field(description="The highest `max_iterations` a loop may have.")
    wall_time_s: Limit = Field(
        description="Seconds a run may spend executing; time waiting at a gate does not count."
    )
    # A default, so the policy frozen on a run created before phase 11.3 still loads.
    approval_ttl_s: Limit = Field(
        default=APPROVAL_TTL_S,
        description="Seconds a gate waits for a decision before its run is cancelled; a gate "
        "may set a shorter time of its own.",
    )
    budget_usd: Usd | None = Field(
        default=None,
        description="USD the run may spend, a hard stop once reached; `None` is no cost cap.",
    )
    # Defaults, so the policy frozen on a run created before phase 12.3 still loads.
    sandbox_ttl_s: Limit = Field(
        default=SANDBOX_TTL_S,
        description="Seconds a failed or cancelled run's sandbox is kept before it is removed.",
    )
    branch_retention_days: Limit = Field(
        default=BRANCH_RETENTION_DAYS,
        description="Days a finished run's saved commits are kept; their changed files stay.",
    )
    # A default, so the policy frozen on a run created before phase 7.6 still loads.
    review_rounds: Limit = Field(
        default=REVIEW_ROUNDS,
        description="Follow-up runs that review comments on one pull request may start "
        "(`@<app> fix this`).",
    )
    # A default, so the policy frozen on a run created before phase 13.7 still loads.
    breakers: BreakerPolicy = Field(
        default_factory=BreakerPolicy,
        description="When the engine pauses a step: the circuit-breaker thresholds (13.7).",
    )


PLATFORM_POLICY: Final = Policy(
    agents_alive=8,
    agents_spawned=40,
    max_depth=2,
    loop_iterations=5,
    wall_time_s=2 * 60 * 60,
    approval_ttl_s=APPROVAL_TTL_S,
    sandbox_ttl_s=SANDBOX_TTL_S,
    branch_retention_days=BRANCH_RETENTION_DAYS,
    review_rounds=REVIEW_ROUNDS,
)
"""The tech-stack defaults, and the ceilings a workspace policy cannot go above, except those in
`CEILINGS`."""

CEILINGS: Final[dict[str, int]] = {
    "sandbox_ttl_s": SANDBOX_TTL_MAX_S,
    "branch_retention_days": BRANCH_RETENTION_MAX_DAYS,
    "review_rounds": REVIEW_ROUNDS_MAX,
}
"""The limits a workspace may set above their default, up to these values."""


def ceiling(name: str) -> int:
    """The most a workspace may set the integer limit `name` to."""
    value = CEILINGS.get(name, getattr(PLATFORM_POLICY, name))
    assert isinstance(value, int)
    return value


class PolicyOverrides(BaseModel):
    """A workspace's own limits; `None` keeps the platform's."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agents_alive: Limit | None = None
    agents_spawned: Limit | None = None
    max_depth: Limit | None = None
    loop_iterations: Limit | None = None
    wall_time_s: Limit | None = None
    approval_ttl_s: Limit | None = None
    budget_usd: Usd | None = None
    sandbox_ttl_s: Limit | None = None
    branch_retention_days: Limit | None = None
    review_rounds: Limit | None = None
    breakers: BreakerOverrides | None = None


def effective_policy(overrides: PolicyOverrides | None = None) -> Policy:
    """`PLATFORM_POLICY` with each limit replaced by the workspace's, where it set one, up to the
    limit's `ceiling`, and the workspace's budget, which has no platform ceiling."""
    base = PLATFORM_POLICY.model_dump()
    if overrides is not None:
        for name, value in overrides.model_dump(exclude_none=True).items():
            if name == "breakers":
                continue
            base[name] = value if name == "budget_usd" else min(ceiling(name), value)
    policy = Policy.model_validate(base)
    if overrides is not None and overrides.breakers is not None:
        policy = with_breakers(policy, overrides.breakers.model_dump(exclude_none=True))
    return policy


def with_breakers(policy: Policy, spec_breakers: Mapping[str, float] | None) -> Policy:
    """`policy` with the workflow's own thresholds (its spec's `breakers`, the fields it set) over
    the workspace's, each held to its `BREAKER_RANGES`. The workspace's own are already in
    `policy.breakers`, over the platform's defaults."""
    merged = clamp_breakers({**policy.breakers.model_dump(), **(spec_breakers or {})})
    for name in ("repeat_calls", "repeat_errors", "flip_flops"):
        merged[name] = round(merged[name])
    return policy.model_copy(update={"breakers": BreakerPolicy.model_validate(merged)})


def with_budget(
    policy: Policy, budget_usd: Decimal | None, workflow_budget_usd: float | None = None
) -> Policy:
    """`policy` with the run's own budget in place of the workspace's, if the run set one, else
    the workflow's (its spec's `budget_usd`), if it set one."""
    if budget_usd is None and workflow_budget_usd is not None:
        budget_usd = Decimal(str(round(workflow_budget_usd, 8)))
    return policy if budget_usd is None else policy.model_copy(update={"budget_usd": budget_usd})


LIMIT_LABELS: Final[dict[PolicyLimit, str]] = {
    "agents_alive": "agents alive",
    "agents_spawned": "agents spawned",
    "max_depth": "nesting depth",
    "loop_iterations": "loop iterations",
    "wall_time_s": "wall time",
    "approval_ttl_s": "approval time to live",
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
