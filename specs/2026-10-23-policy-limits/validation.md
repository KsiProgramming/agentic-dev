# Validation: Policy limits

## Done when (from roadmap)
> Exceeding a limit stops the run cleanly with a reason

"Cleanly" means:
- the log ends `policy_limit_exceeded` → `run_failed`, with no event after it;
- every running node ends `node_cancelled`;
- no asyncio task or sandbox is left behind;
- the lease is released;
- `runs.status = failed` and `runs.failure_reason` names the limit, its value and what was observed.

## Automated checks
### Engine (`packages/engine/tests`, fake runtime)
- [ ] `effective_policy`: null keeps the default and the lower value wins.
- [ ] `policy_problems`: one test each for loop iterations, map concurrency and depth above the limit. A spec exactly at every limit passes. Each message names the node path, the limit and the value.
- [ ] Agents spawned, map: a map whose items would pass the limit fails before fan-out. No `map_item_started` is written.
- [ ] Agents spawned, sequence and loop: agent starts (loop iterations included) pass the limit and the run stops at the next start.
- [ ] Agents spawned, resume: the count survives a checkpoint resume (`test_resume.py` style).
- [ ] Agents alive: with a counting fake, concurrent agent calls never exceed `agents_alive`, and the run completes (it throttles, it does not fail).
- [ ] The stop event sequence and payloads match the shape above, and the old per-map `ValueError` path is gone.
- [ ] The docs template's worst case fits `PLATFORM_POLICY.agents_spawned`.

### Worker and API integration (Testcontainers Postgres)
- [ ] Wall time: `wall_time_s=2` on a slow fake run stops it, writes `policy_limit_exceeded` + `run_failed`, discards the sandbox and releases the lease.
- [ ] Wall time excludes gates: a run that waits at a gate longer than its limit is approved, resumes and completes.
- [ ] Wall time across a restart: the active time of an earlier attempt counts toward the limit.
- [ ] `POST /runs` and rerun: 422 with the list of problems when a spec exceeds the workspace policy. On success, `runs.policy` equals the effective policy.
- [ ] Frozen policy: lowering the workspace policy while a run waits at a gate does not change that run's limits.
- [ ] `GET`/`PUT /workspaces/{id}/policy`: the round trip and reset work. 422 above a ceiling, on 0 and on a negative value.
- [ ] Migration `0016` upgrades and downgrades, and existing runs get `PLATFORM_POLICY` (`test_migrations.py`).

### Web
- [ ] Vitest: Run limits card validation, hours/minutes ↔ seconds, reset dialog.

### CI
- [ ] `ruff`, `mypy`/`pyright` strict, ESLint, Prettier and type check are green.
- [ ] The OpenAPI export and generated client are up to date (the existing drift check).

## Manual / demo checks
- [ ] `docker compose up`, then `PUT /workspaces/{id}/policy` with `{"wall_time_s": 60}`, start a docs run and stream `GET /runs/{id}/events` with curl. Expected: `policy_limit_exceeded {limit: "wall_time_s", value: 60, …}` then `run_failed`. The console header and runs list show "policy limit: wall time 1m exceeded".
- [ ] Settings → Run limits: lower loop iterations to 2 and start the docs template (its reviewer loop is above 2). Expected: the start sheet shows the 422 message in its form-level alert. Then reset to the defaults and the run starts.
- [ ] The Run limits card renders without horizontal scroll at 375, 768 and 1440 px (existing shell screenshot job).

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] `specs/tech-stack.md` is updated (configurable limits, frozen per run, wall time excludes gates).
- [ ] The roadmap phase is marked done (`complete-phase`) and `CHANGELOG.md` has an entry under [Unreleased].
- [ ] No secrets in the new logs or events (the policy payloads hold only numbers).
