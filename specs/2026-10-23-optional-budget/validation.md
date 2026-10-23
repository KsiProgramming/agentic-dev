# Validation: Optional budget

## Done when (from roadmap)
> AC-7 for budgeted runs; an unbudgeted run continues and still reports cost

"Cleanly" (AC-7, as defined in 3.2) means:
- the log ends `policy_limit_exceeded {limit: "budget_usd"}` → `run_failed`, with no event after it;
- every running node ends `node_cancelled`;
- no asyncio task or sandbox is left behind and the lease is released;
- `runs.status = failed` and `runs.failure_reason` names the budget and the amount spent.

## Automated checks
### Engine (`packages/engine/tests`, fake runtime)
- [ ] Policy: a workspace default copies into the effective policy, a run budget replaces it, null means no cap, and the reason format is right.
- [ ] `budget_problems`: an unpriced agent node is named by its path when a budget is set. The check is skipped with no budget.
- [ ] Sequence: the budget is crossed by node 1, so node 2 never starts and the stop sequence and payload match.
- [ ] Map: an item crosses the budget while siblings run. The siblings end `node_cancelled` and no task is orphaned.
- [ ] Exactly 100%: spent equal to the budget stops the run.
- [ ] Seeded spend at or above the budget stops before the first node.
- [ ] Unpriced `usage` under a budget stops the run with the model named.
- [ ] **Unbudgeted:** the same spend with no budget completes, and its `usage` events and totals equal the 3.1 behaviour.

### Worker and API integration (Testcontainers Postgres)
- [ ] A budgeted run on a priced fake stops: `policy_limit_exceeded` + `run_failed`, the sandbox is discarded, the lease is released, and `failure_reason` is set.
- [ ] Restart: a run killed mid-way with spend X resumes with the meter seeded at X and stops at the budget.
- [ ] Gate: a run whose spend reaches the budget before a gate stops when it resumes, before the next node.
- [ ] Frozen: changing the workspace default while a run waits does not change that run's budget.
- [ ] `POST /runs`: the budget is stored in `runs.policy`, the run value replaces the default, and a 422 is returned on ≤ 0 and on an unpriced model.
- [ ] Rerun: with no body it gets the current workspace default, and with a body it gets that value.
- [ ] `GET`/`PUT /workspaces/{id}/policy`: the round trip with `budget_usd`, reset to null, and 422 on ≤ 0.
- [ ] `GET /runs` and `GET /runs/{id}` return `usage.budget_usd`.
- [ ] Migration `0017` upgrades and downgrades (`test_migrations.py`). Old runs read as no budget.

### CI
- [ ] `ruff`, `mypy`/`pyright` strict, ESLint, Prettier and the web type check are green.
- [ ] The OpenAPI export and generated client are up to date (drift check).
- [ ] Existing web tests and the shell screenshot job still pass.

## Manual / demo checks
- [ ] `docker compose up`, start a docs run with `budget_usd: 0.01` and stream `GET /runs/{id}/events` with curl. Expected: `policy_limit_exceeded {limit: "budget_usd", value: "0.01", observed: "0.0…"}` then `run_failed`. The console header and runs list show "policy limit: budget $0.01 reached (…)".
- [ ] Start the same run with no budget. Expected: it completes, and the header and runs list show its cost.
- [ ] Settings → Run limits: set a $2 budget. The New run sheet prefills $2 and the console header shows "$x of $2.00". Reset clears it.
- [ ] `POST /runs` with a budget and a spec whose agent sets a `model` that has no price. Expected: 422 naming the node and model. The same request without a budget starts, and its cost shows "—".

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] `specs/tech-stack.md` is updated (budget default + per-run, frozen, metered in the engine, unpriced rejected).
- [ ] The roadmap phase is marked done (`complete-phase`) and `CHANGELOG.md` has an entry under [Unreleased].
- [ ] No secrets in the new events or logs (the budget payloads hold only amounts).
