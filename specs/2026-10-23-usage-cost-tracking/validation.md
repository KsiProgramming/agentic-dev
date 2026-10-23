# Validation: Usage normalisation and cost per node and run

## Done when (from roadmap)
> Run console shows tokens and estimated USD per node and per run; the runs list shows cost per run

## Automated checks
- [ ] `packages/runtime/tests/test_pricing.py`:
  - `estimate_usd` for input and output only;
  - with cache read and cache write tokens;
  - with an unknown model (`None`);
  - overrides replacing a default and adding a new model;
  - `Decimal` sums over 1,000 small usages have no float drift.
- [ ] `packages/runtime/tests/test_claude_runtime.py`:
  - `usage_of` keeps cache tokens separate and sets `model`;
  - the emitted `Usage` carries `estimated_usd` from the injected table.
- [ ] `packages/runtime/tests/test_events.py`: the new `Usage` fields round-trip, and an old-shape payload (no model, no cache fields) still parses.
- [ ] `packages/engine/tests/`: on the fake runtime, for a sequence and for a map over 3 items:
  - the per-node usage sums equal the run's total usage;
  - one unpriced node makes the run total `estimated_usd=None`.
- [ ] `packages/store/tests/test_run_summaries.py` (Testcontainers):
  - after a run's events are written, the `runs` totals equal the sum over `run_events` of type `usage`;
  - `cost_complete` is false when one usage had no price;
  - `GET /runs` and `GET /runs/{id}` return the `usage` object.
- [ ] API tests for `GET` and `PUT /workspaces/{id}/pricing`:
  - defaults are listed with `as_of`;
  - an override changes `effective`;
  - a negative price gives 422 naming the field;
  - another workspace's overrides are not visible.
- [ ] Worker test: a run in a workspace with an override logs `estimated_usd` computed with the override price.
- [ ] Existing suites stay green: ruff, mypy/pyright strict, pytest, ESLint, Vitest, Playwright with axe and screenshots at 375, 768 and 1440 px.

## Manual / demo checks
- [ ] `docker compose up`, connect Claude and GitHub, and start a "Generate docs" run on a fixture repo with real Claude.
  - **Expected:** each agent step footer shows "in · out · $x". The map node shows its total and each item its own. The console header shows the run total, and it equals the sum of the step costs.
- [ ] Open the Runs page.
  - **Expected:** the run's Cost cell matches the console header. It updated while the run was live, without a reload.
- [ ] Compare the run's tokens with the usage shown in the Anthropic console for that key and time window.
  - **Expected:** the tokens match. The USD is within rounding of list price × tokens.
- [ ] In Settings → Model pricing, override the model's output price (for example ×2), then start a second run.
  - **Expected:** the new run's cost reflects the override. The first run's cost is unchanged.
- [ ] Reset the override.
  - **Expected:** the confirm dialog appears, and the card shows the default again.
- [ ] Point the run at a model that is not in the table (set the env or the spec).
  - **Expected:** the tokens are shown, the cost shows "—" with a tooltip naming the model, and the list cell shows "—".

## Merge criteria
- [ ] All checks above pass in CI (squash merge, all checks green).
- [ ] `PRICES_AS_OF` and the default prices are checked against Anthropic's pricing page, with the date in the PR.
- [ ] The demo numbers (run total, list cell, Anthropic console tokens) are pasted in the PR description.
- [ ] `tech-stack.md` and CHANGELOG are updated, and roadmap 3.1 is marked done.
- [ ] No API key or price-override payload appears in logs.
