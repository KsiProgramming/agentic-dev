"""Holds a run to its USD budget (the policy's `budget_usd`), as its agents report usage.

The meter starts from what the run had spent before this attempt (`runs.estimated_usd`), so an
earlier attempt's spend, and the spend before a gate, counts. It adds each `usage` event's
`estimated_usd`, priced by the adapter when it was emitted, and stops the run once the spend
reaches the budget: the call that crossed it is already paid, so it is counted in full. A usage
with no price cannot be held to a budget, so it stops the run too.
"""

from decimal import Decimal

from agentic_engine.policy import Policy, PolicyLimitExceeded
from agentic_runtime import Usage


class BudgetMeter:
    """The spend of one run against its budget, for one attempt."""

    def __init__(self, budget: Decimal, spent: Decimal = Decimal(0)) -> None:
        self.budget = budget
        self.spent = spent

    def check(self, node_id: str | None = None) -> None:
        """Raise `PolicyLimitExceeded` if the run has spent its budget."""
        if self.spent >= self.budget:
            raise PolicyLimitExceeded("budget_usd", self.budget, self.spent, node_id)

    def add(self, usage: Usage, node_id: str) -> None:
        """Count one usage of `node_id`'s agent; raises `PolicyLimitExceeded` once the budget is
        spent, or if the usage has no price."""
        if usage.estimated_usd is None:
            raise PolicyLimitExceeded(
                "budget_usd",
                self.budget,
                self.spent,
                node_id,
                unpriced_model=usage.model or "unknown",
            )
        self.spent += Decimal(str(usage.estimated_usd))
        self.check(node_id)


def budget_meter(policy: Policy, spent: Decimal = Decimal(0)) -> BudgetMeter | None:
    """A meter for a run under `policy` that has spent `spent`; `None` if it has no budget."""
    return None if policy.budget_usd is None else BudgetMeter(policy.budget_usd, spent)
