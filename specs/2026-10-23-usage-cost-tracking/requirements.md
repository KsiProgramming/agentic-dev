# Usage normalisation and cost per node and run

Roadmap phase: 3.1
Branch: plan/3.1-usage-cost-tracking

## Context
Milestone 3 is about policies, cost and the monitor. Cost comes first because the optional budget (3.3) stops a run at 100% of a USD amount, and that needs a trusted USD figure for each usage event. Today:
- The `Usage` event has `input_tokens`, `output_tokens` and an `estimated_usd` that is never set. Claude's `usage_of` folds cache reads and cache writes into `input_tokens`, which are priced very differently. The model is not recorded.
- The console step footer shows "N in · M out tokens". It shows no USD and no run total.
- `GET /runs` and the runs list show no cost.

Principles that drive it:
- **Mission 6 (transparency):** every cost is visible live and kept in the append-only log.
- **Mission v1 decision "Budget is optional":** cost is always tracked and shown, with or without a budget.
- **Tech stack, agent runtime:** both adapters emit one normalised usage event (tokens, premium requests, estimated USD).
- **Tech stack, run history:** summary fields are kept on the `runs` row when events are written, so listing does not scan the log.
- **Tech stack, platform admin persona:** admins control cost, so a workspace can override prices.

Depends on: 0.7 (Claude adapter), 2.3 (run summaries), 2.5 (run console), 2.6 (settings connection cards). All are done.
Unblocks: 3.3 (budget), 6.4 (cost of dynamic children), 9.6 (Architect cost estimate).

## Scope
### In scope
- **Richer `Usage` event:** add `model`, `cache_read_tokens` and `cache_write_tokens`. `input_tokens` becomes uncached input only. Claude's `usage_of` stops folding cache tokens into it.
- **Price table in code:** `agentic_runtime.pricing` holds the USD per million tokens for input, output, cache write and cache read, per model id. It has a `PRICES_AS_OF` date and a `price(usage, table)` function.
- **Cost frozen at write time:** the adapter sets `estimated_usd` from the run's effective price table (defaults plus workspace overrides) when it emits `Usage`. If the model has no price, `estimated_usd` is `null` and the tokens are still logged. Past runs never change cost.
- **Workspace price overrides:**
  - stored per workspace and model in a new `workspace_model_prices` table;
  - `GET /workspaces/{id}/pricing` returns defaults, overrides and effective prices;
  - `PUT /workspaces/{id}/pricing` replaces the overrides, validated as `>= 0`, with known models only plus free-form model ids;
  - a "Model pricing" card in Settings shows the defaults and lets the user edit overrides and reset them.
- **Run totals on the `runs` row:** token counts, `estimated_usd` and `cost_complete` (false if any usage had no price). They are incremented by `summary_values` on each `usage` event and exposed in `GET /runs` and `GET /runs/{id}` as a `usage` object.
- **Console:**
  - the header shows the run's tokens and USD;
  - each step footer shows its tokens and USD;
  - a map or loop node shows the total of its items, and each item shows its own;
  - an unpriced model shows "—" with a tooltip naming the model.
- **Runs list:** a Cost column on desktop and a cost line on mobile cards, updated live through the existing changed-summaries stream.

### Out of scope
- Budgets and the hard stop: 3.3.
- Copilot premium-request pricing: 8.2. `premium_requests` stays in the event, and the Copilot adapter will price it.
- Cost per user or workspace dashboards and OpenTelemetry metrics: 3.7 and 10.3.
- Fetching prices from a provider API automatically.
- Roles and permissions on who may edit prices. There is no RBAC yet; the audit log of price changes is 3.7.
- Repricing past runs.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where cost is computed | In the adapter at emit time, from a `PriceTable` that the worker passes when it builds the runtime | Matches the tech stack ("adapters emit estimated USD"). The logged event is the truth that 3.3 enforces on. |
| Past runs | Frozen at write time, never recomputed | The append-only log stays truthful, and a budget stop can be explained later. |
| Default prices | Python constant in `agentic_runtime.pricing`, with a `PRICES_AS_OF` date | Reviewable in PRs, needs no DB seed, and is easy to update. |
| Overrides storage | `workspace_model_prices(workspace_id, model, input, output, cache_write, cache_read, updated_at)`, PK `(workspace_id, model)` | A full override per model keeps the merge logic trivial. |
| Price precision | `Decimal` in Python. Each call's cost is kept to 1e-8 USD. Run totals use `NUMERIC(16,8)`, and USD per MTok uses `NUMERIC(12,4)` | Avoids float drift across many small events: a Haiku cache read of a few tokens is still non-zero. The JSON shows a float for display. |
| Cache writes | Priced per TTL (5 minute or 1 hour) from the API's `cache_creation` breakdown, as 5 minute writes when there is none. The event keeps one `cache_write_tokens` total | The two TTLs cost different amounts, and the breakdown is only needed at pricing time. |
| Long prompts | `ModelPricing.long_context` applies above `long_context_above` prompt tokens (Haiku 5.5 over 100K). A workspace override is one flat price | It matches the list price. Overrides stay simple. |
| Unknown model | Tokens logged, `estimated_usd = null`, run `cost_complete = false`. The run's `estimated_usd` stays the sum of its priced usage, shown as "≥ $x", or "—" when nothing was priced | Never shows a wrong number. The UI says what is missing. |
| Run totals | Incremented columns on `runs`, not a view over `run_events` | Same pattern as `pr_url` and `status` (2.3). Listing stays O(page). |
| Old events | Events written before 3.1 have cache tokens folded into `input_tokens` and no price. They are read as they are: totals sum them and cost shows "—". Migration `0014` adds up the run totals once from the log | The log is immutable, and old runs still show their tokens in the list. |
| UI money format | `$0.042`: three significant digits below $1, two decimals above, and "<$0.001" for tiny amounts; `tabular-nums` | Agent turns cost fractions of a cent. |

## Open questions
None. Settled during implementation:
- **List prices:** checked against https://platform.claude.com/docs/en/about-claude/pricing on 2026-10-23 (`PRICES_AS_OF`).
- **Cache-write TTL:** both TTLs are priced (see Decisions).
