# Plan: Usage normalisation and cost per node and run

Backend first, in slices that keep `main` working after each group.

## 1. Usage event and price table
- [x] `packages/runtime/src/agentic_runtime/events.py`: add `model: str | None`, `cache_read_tokens: Count = 0` and `cache_write_tokens: Count = 0` to `Usage`. Document that `input_tokens` is uncached input only.
- [x] `packages/runtime/src/agentic_runtime/pricing.py`:
  - `ModelPrice` (USD per MTok, as `Decimal`, for input, output, cache_write and cache_read);
  - `PriceTable` (a mapping from model to `ModelPrice`);
  - `DEFAULT_PRICES` and `PRICES_AS_OF`;
  - `PriceTable.with_overrides(...)`;
  - `estimate_usd(usage, table) -> Decimal | None`.
- [x] `claude.py`: `usage_of` maps `cache_read_input_tokens` and `cache_creation_input_tokens` to the new fields and sets `model`. `ClaudeRuntime` takes `prices: PriceTable = DEFAULT_PRICES` and sets `estimated_usd` on each emitted `Usage`.
- [x] `fake.py` and `testing.py`: the fake runtime emits a deterministic `Usage` with a model in the default table, so engine tests get prices.
- [x] `engine/agent.py`: `sum_usage` adds the new fields. `estimated_usd` sums when all parts are priced and is `None` otherwise.
- [x] Re-export the OpenAPI client (`scripts/export_openapi.py`, `pnpm gen:api`). `Usage` is not in the workflow JSON Schema.

## 2. Run totals on the `runs` row
- [x] Alembic migration in `packages/api/alembic`:
  - `runs.input_tokens`, `output_tokens`, `cache_read_tokens` and `cache_write_tokens` (`BIGINT NOT NULL DEFAULT 0`);
  - `runs.estimated_usd` (`NUMERIC(16,8) NOT NULL DEFAULT 0`);
  - `runs.cost_complete` (`BOOLEAN NOT NULL DEFAULT true`).
- [x] `store/models.py`: map the columns.
- [x] `store/sink.py` `summary_values`: on a `usage` event, increment the token columns and `estimated_usd`, and set `cost_complete=false` when `estimated_usd` is null. Use SQL increments, not read-modify-write. Update the docstring table.
- [x] `store/summaries.py` and the API run models: add `usage: {input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, estimated_usd, cost_complete}` to the run summary for both `GET /runs` and `GET /runs/{id}`.
- [x] Regenerate the web API client.

## 3. Workspace price overrides (API)
- [x] Migration: the `workspace_model_prices` table (see the requirements decisions).
- [x] `store`: functions to list, replace and load the effective `PriceTable` for a workspace.
- [x] `api/workspaces/routes.py`:
  - `GET /workspaces/{id}/pricing` returns `{as_of, models: [{model, default, override, effective}]}`;
  - `PUT /workspaces/{id}/pricing` replaces the overrides, with 422 on negative values or an empty model id.
- [x] `worker/main.py` `run_runtimes`: load the workspace's effective table at run start and pass `prices=` to `ClaudeRuntime`. The table is fixed for the attempt, and a resumed attempt reloads it.

## 4. Console and runs list
- [x] `web/src/runs/timeline.ts`: `TokenUsage` gains cache tokens, `estimatedUsd: number | null` and `costComplete`. Aggregate per step, per map item or loop iteration, and per node (sum of its items).
- [x] `web/src/runs/console/step-view.tsx` `UsageFooter`: "12.3k in · 2.1k out · $0.042"; cache tokens appear in a tooltip; an unpriced model shows "—" with the model name.
- [x] Console header: run total tokens and USD, from the run summary (live via the existing summary updates).
- [x] Runs page: a Cost column (desktop table) and a cost line (mobile card), with `tabular-nums` and "—" when `cost_complete` is false and the total is 0.
- [x] Shared `formatUsd` helper next to the existing number formatters.

## 5. Settings: "Model pricing" card
- [x] `web/src/settings/model-pricing.tsx`:
  - a connection-card style card with a table of effective prices (model in mono, a "Custom" badge on overrides), in its own scroll box on mobile;
  - "Edit" opens a dialog per model, "Add model" adds one, and "Reset" or "Reset all" go back to list prices (each with a confirm dialog);
  - field-level 422 errors;
  - a toast on success;
  - the `as_of` date shown as muted text.
- [x] Add it to `web/src/app/settings/page.tsx` under the connections.

## 6. Docs and demo
- [x] `tech-stack.md`:
  - note the price table, the frozen-at-write rule and the overrides endpoint under "Security & secrets / Observability";
  - add a decisions-log row "Cost frozen at write time".
- [x] CHANGELOG entry under [Unreleased].
- [ ] Run the manual real-Claude demo (validation.md) and paste the numbers in the PR.
