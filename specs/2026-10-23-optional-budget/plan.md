# Plan: Optional budget

Engine first, then storage and the API, then the worker, then the UI. `main` keeps working after each group.

## 1. Policy model
- [ ] `packages/engine/src/agentic_engine/policy.py`:
  - add `"budget_usd"` to `PolicyLimit` and `LIMIT_LABELS` ("budget");
  - add `Policy.budget_usd: Decimal | None = None` (`gt=0`) and `PolicyOverrides.budget_usd`;
  - in `effective_policy`, the budget is copied from the overrides (it is a default with no ceiling, so `min` does not apply);
  - add `with_budget(policy, run_budget)`, where the run's value replaces the default.
- [ ] `PolicyLimitExceeded`: allow `Decimal` `value`/`observed` and build the reason `policy limit: budget $5.00 reached ($5.03 spent)`. Keep the existing int limits unchanged.
- [ ] `events.py`: the docstring of `POLICY_LIMIT_EXCEEDED` says money values are decimal strings.
- [ ] Unit tests: the default copies through, the run value replaces it, a null budget is no cap, and the reason format is right.

## 2. Pre-run check
- [ ] `spec` (next to `policy_problems`): `budget_problems(spec, policy, prices, default_model) -> list[str]`. When `budget_usd` is set, it names every agent node (by path) whose model has no price.
- [ ] Engine tests: a priced spec passes, an unpriced node is named, and an unbudgeted policy skips the check.

## 3. Engine meter
- [ ] `agentic_engine/budget.py`: `BudgetMeter(limit: Decimal, spent: Decimal)` with `add(usage, node_id)`. It raises `PolicyLimitExceeded("budget_usd", …)` when `spent >= limit` or when the usage has no price.
- [ ] `compile_workflow` / `run_workflow` / `resume_workflow` take `spent: Decimal = 0`. They build a meter when `policy.budget_usd` is set, and call `meter.add` where agent `Usage` events are emitted (one place for agent, map item, reduce and loop steps).
- [ ] At run or resume start, if `spent >= budget`, stop before the first node.
- [ ] The existing `_finish` path handles the stop: `policy_limit_exceeded` → `run_failed`, and in-flight nodes end `node_cancelled`. Check that this holds when the raise comes from inside a map item while siblings are running.
- [ ] Fake runtime: allow a per-call `estimated_usd` (or a priced script) so tests can cross the budget exactly.
- [ ] Engine tests (fake runtime):
  - the budget is crossed in a sequence and the next node never starts;
  - the budget is crossed in one map item while others run, and they are cancelled with no orphaned tasks;
  - spent exactly equal to the budget stops the run;
  - a seeded `spent` at or above the budget stops before the first node;
  - unpriced usage under a budget stops the run;
  - the same spend with no budget completes and reports cost.

## 4. Storage and API
- [ ] Alembic `0017_optional_budget`: `workspace_policies.budget_usd NUMERIC(16,8) NULL`. `runs.policy` needs no change (a missing key means no cap).
- [ ] `store/models.py`, `workspace_policy` / `replace_workspace_policy`: read and write `budget_usd`.
- [ ] `api/workspaces`: `WorkspacePolicy` and `PutPolicy` gain `budget_usd` (`gt=0`, nullable, no ceiling). The description says it is a default that runs may replace.
- [ ] `api/runs/models.py`:
  - `CreateRunRequest.budget_usd` (optional, `gt=0`);
  - an optional rerun body `{budget_usd}`;
  - `RunUsage.budget_usd`.
- [ ] `api/runs/routes.py`: `POST /runs` and rerun build the policy with `with_budget`, run `budget_problems` against the workspace's effective prices (a 422 `PolicyErrorDetail`), and store it on `runs.policy`. Run summaries read `budget_usd` from `runs.policy`.
- [ ] API tests:
  - the budget is stored on the run;
  - the run value replaces the workspace default;
  - a rerun with no body gets the current default;
  - 422 on ≤ 0 and on an unpriced model;
  - the policy round trip with a budget and reset;
  - migration up/down.
- [ ] Re-export OpenAPI and regenerate the web client.

## 5. Worker
- [ ] `worker/main.py` `_attempt`: read `runs.estimated_usd` and pass it as `spent` to `run_workflow` / `resume_workflow`. The stop comes from the graph, so there is no new watchdog.
- [ ] Worker integration tests (Testcontainers):
  - a budgeted run on a priced fake stops with the reason, discards its sandbox and releases its lease;
  - after a worker restart mid-run, the earlier spend counts;
  - a run that waited at a gate resumes and stops if its spend is already at the budget;
  - lowering the workspace default while a run waits does not change that run's budget.

## 6. UI
- [ ] Settings "Run limits" card: a "Budget (USD)" field (empty = "No budget"), included in Save and Reset.
- [ ] "New run" sheet: an optional "Budget (USD)" field prefilled from the workspace policy. A 422 budget problem is shown on the field.
- [ ] Run console header: "$1.23 of $5.00" when `usage.budget_usd` is set. The raw events summary for `policy_limit_exceeded` covers `budget_usd`.
- [ ] Shared components and tokens only. The existing shell screenshot job covers the layouts.

## 7. Docs
- [ ] `specs/tech-stack.md`, security section: the budget is a workspace default replaced per run, frozen in `runs.policy`, metered in the engine from the run's priced usage, and an unpriced model is rejected when a budget is set. Add a decisions log row.
- [ ] `CHANGELOG.md` entry (done by `open-pr`).
