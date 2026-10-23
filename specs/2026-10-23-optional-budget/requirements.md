# Optional budget: hard stop at 100% if set, no cap if unset

Roadmap phase: 3.3
Branch: plan/3.3-optional-budget

## Context
3.1 made cost trusted: each `usage` event is priced by the adapter when it is emitted, and `runs` keeps the run's total (`estimated_usd`, `cost_complete`). 3.2 added the policy model, the per-run frozen `runs.policy`, and the clean stop (`policy_limit_exceeded` → `run_failed`). 3.3 adds the one limit that is optional: a USD budget. Together with 3.2 it closes AC-7 (clean stop on limits).

Principles that drive it:
- **Mission v1 decision "Budget is optional":** a workspace, workflow or run *may* set a USD budget. If set, it is a hard stop at 100%. If unset, the run has no cost cap, the other limits still apply, and cost is always tracked and shown.
- **Mission 2 (safe by construction):** the engine enforces the limit, not the graph. It is checked before the run (can it be enforced at all?) and while it runs.
- **Mission 6 (transparency):** the stop is in the append-only log with what was spent.
- **Tech stack, cost decision:** cost is priced when usage is logged and never recomputed, so "a budget stop (3.3) can always be explained".
- **Tech stack, policy decision:** the limits a run is given are frozen when it is created, resumes included.

Depends on: 3.1 (priced usage, run totals) and 3.2 (policy model, `runs.policy`, stop event, Run limits card). Both are done.
Unblocks: 3.4 (validation endpoint reuses the "budget is enforceable" check), 5.4 (per-workflow budget in the side panel), 6.4 (cost of dynamic children counts toward the same meter), 9.6 (Architect estimate against a budget).

## Scope
### In scope
- **Workspace default budget:**
  - an optional `budget_usd` on the workspace policy (null means no cap);
  - `GET`/`PUT /workspaces/{id}/policy` include it;
  - a "Budget (USD)" field in the Settings "Run limits" card, where empty means "No budget".
- **Per-run budget:**
  - an optional `budget_usd` on `POST /runs`, which replaces the workspace default for that run;
  - a "Budget (USD)" field in the "New run" sheet, prefilled with the workspace default and empty when there is none.
- **Frozen per run:** the run's budget is stored in `runs.policy` (`budget_usd`, null = no cap) when the run is created, and kept across resumes.
- **Rerun:** `POST /runs/{id}/rerun` takes an optional `budget_usd`. When it is omitted, the rerun gets the current workspace default, the same as its other limits (3.2). The original run's spend is not carried over.
- **Checked before the run** (on `POST /runs` and rerun, 422 with a `PolicyErrorDetail`):
  - `budget_usd` must be > 0;
  - when a budget is set, every agent node's model (its own `model`, else the worker's default) must have a price in the workspace's effective price table. A cap that cannot be measured is rejected, e.g. `agent 'writer' at steps[1]: model 'x' has no price, so a budget cannot be enforced`.
- **Enforced while it runs (engine meter):**
  - The worker seeds a run-wide budget meter with `runs.estimated_usd` when an attempt starts, so spend from earlier attempts and before a gate counts.
  - The engine adds each `usage` event's `estimated_usd` as it is emitted.
  - When spend reaches the budget (≥ 100%), it raises `PolicyLimitExceeded("budget_usd", budget, spent)`. In-flight agents are cancelled (`node_cancelled`) and the 3.2 stop path writes `policy_limit_exceeded` then `run_failed`.
  - An attempt that starts with spend already at or above the budget stops before its first node.
  - A `usage` event with no price under a budget (a model that was not caught before the run) also stops the run, with a reason that names the model. This fails safe.
- **Reason:** `policy limit: budget $5.00 reached ($5.03 spent)` becomes `runs.failure_reason`. The event payload has `limit: "budget_usd"`, `value` and `observed` as decimal strings, plus `node_id`.
- **Unbudgeted runs:** no meter and no check. Cost is tracked and shown exactly as in 3.1.
- **Display:**
  - `GET /runs` and `GET /runs/{id}` expose `budget_usd` in the `usage` object;
  - the console header shows "$1.23 of $5.00" when a budget is set;
  - the stop reason shows in the header and the runs list like any failure reason.

### Out of scope
- A per-workflow budget in the spec: 5.4 (canvas side panel), as for the other per-workflow limits.
- Soft warnings (for example at 80%) and notifications: later, with the monitor work.
- Pre-call cost estimates (refusing a call that would cross the budget): 9.6 brings estimates.
- A workspace budget *ceiling* that runs cannot go above, and per-user or monthly workspace spend caps: 3.7 / 10.5.
- Copilot premium-request pricing under a budget: 8.2 (until then, Copilot is not priced, so the pre-run check rejects a budget on it).
- Web component tests and Playwright coverage (the user chose engine and worker/API tests; lint and type checks still run).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where a budget is set | Workspace default plus per-run, where the run's value replaces the default | Covers the mission's "workspace or run". The workflow level waits for the side panel (5.4). |
| Default vs. ceiling | The workspace value is a **default**, not a ceiling. A run may set a higher or lower budget, but cannot remove the default by leaving the field empty | "Budget is optional" is a user choice. A ceiling is an admin feature for later. An empty field means "use the default", so an admin's default is never silently dropped. |
| Storage | `workspace_policies.budget_usd NUMERIC(16,8) NULL`. The run's budget goes in `runs.policy` JSONB as a decimal string. `Policy.budget_usd: Decimal \| None = None` | It reuses the 3.2 frozen policy. Old rows have no key, which means no cap, so no backfill is needed. The precision matches `runs.estimated_usd`. |
| Enforcement point | An engine meter seeded from `runs.estimated_usd`, checked on every `usage` emit | It stops right after the call that crosses the budget, with no polling lag across parallel agents, and it is restart safe because the seed comes from the DB. |
| Threshold | Stop when spent ≥ budget | "Hard stop at 100%". The call that crosses is already paid, so it is logged in full and `observed` shows the overshoot. |
| Unpriced model with a budget | 422 before the run. Fail-safe stop if one appears at runtime | You cannot enforce a cap you cannot measure (mission 2). An unbudgeted run still allows unpriced models (3.1 behaviour). |
| Stop event | Reuse `policy_limit_exceeded` with `limit: "budget_usd"`, and `run_failed` | Planned in 3.2. No new status, so filters and UI are unchanged. |
| Rerun budget | Optional body field, else the current workspace default | The same rule as the 3.2 limits: a rerun gets the policy as it is then. |
| API money type | Decimal strings in the stored payload and the event; `float` with `ge>0` in the request and response models, like `estimated_usd` | Exact in storage and simple for clients. |

## Open questions
- Should leaving the per-run field empty mean "use the workspace default" (as planned), or should the sheet offer an explicit "No budget" choice that overrides a workspace default? The plan keeps the default. Revisit if users ask.
