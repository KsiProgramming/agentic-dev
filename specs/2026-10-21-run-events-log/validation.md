# Validation: Append-only run_events table; engine writes events

## Done when (from roadmap)
> A run produces ordered events in Postgres

## Automated checks
- [ ] `packages/store/tests/test_postgres_sink.py` (Testcontainers, `integration`): a 2-node sequence on the fake runtime writes rows to `run_events` where
  - `seq` is 1..N with no gaps or duplicates for the run;
  - the first row is `run_started` and the last is `run_completed`;
  - each node's rows sit between its `node_started` and `node_completed`, node `a` before node `b`;
  - every agent-level row has the right `node_id`, and its `payload` round-trips to the original `AgentEvent`;
  - `runs.status` is `completed`.
- [ ] `test_migrations.py` reaches head `0002_run_events`.
- [ ] Engine tests (including the in-memory sink ordering test) pass with no network.
- [ ] `ruff check`, `ruff format --check`, strict type check pass for all packages.
- [ ] CI green, including the integration job.

## Manual / demo checks
- None. The Testcontainers test is the demo for this phase.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] Engine package imports no SQLAlchemy or database driver.
- [ ] No secrets or API keys in event payloads or logs.
- [ ] README and CHANGELOG updated.
- [ ] Roadmap phase 0.5 marked done on the implementing PR.
