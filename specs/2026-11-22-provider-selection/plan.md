# Plan: Provider selection per workspace, workflow and node

Contract first (interview): the engine's spec and rules, then the worker, then the API, then the UI, then real runs. The stack stays working after each group: until group 3, every run still resolves to Claude, or to Copilot through 8.2's `copilot_connection_id`.

## 1. Engine: spec, resolution and gaps
- [ ] `packages/engine/src/agentic_engine/spec/models.py`: `Provider = Literal["claude", "copilot"]`; use it for `provider` on `AgentNode`, `ReduceAgent`, `RouterClassifier` and the orchestrator hub; add `provider: Provider | None` to `WorkflowSpec` ("unset means the workspace default").
- [ ] New `agentic_engine/providers.py`: `resolve_providers(spec, *, run_override, workspace_default, triggered) -> ResolvedProviders` (a node id → `{provider, model}` map, the run's default, the set used, and the fallback list for triggered runs), walking subflows and composites as the validator does (6.5, 6.6). Apply the model rule: a node's `model` only on its explicit provider, otherwise Claude; a Copilot node with no own model gets `None` (the worker fills the workspace's `copilot_model`).
- [ ] `provider_gaps(resolved, *, has_copilot_connection)` → a list of `ValidationIssue` (`copilot_connection_required`; room for a typed-output gap if the real run needs one). Called by `spec/validate.py::validate_workflow` (with the workspace default passed in) so the canvas's live validation (5.6) shows it per node.
- [ ] `graph/compile.py`: the agent, reduce, router and hub call sites take the resolved `{provider, model}` from the run's stored map instead of the raw spec field; `AgentRequest` gains `provider`.
- [ ] Regenerate the JSON Schema and node manifests; update `packages/api/tests/test_node_types.py` (enum is now `["claude", "copilot"]`) and the 5.8 blank-workflow test (Copilot is accepted and set as the workflow's `provider`).
- [ ] Engine tests: the resolution table (every level set and unset, explicit node vs run override, triggered fallback, models across providers, nested subflow); gap tests.

## 2a. Runtime: Copilot cost in USD
- [ ] `packages/runtime/src/agentic_runtime/copilot_sdk.py` (`translate`): read `copilot_usage.total_nano_aiu` from each `assistant.usage` and put `ai_credits = nano / 1e9` on the usage event (a new optional `Usage.ai_credits`, summed like `premium_requests` in `agent.py`).
- [ ] Price it where Claude usage is priced (the pricing lookup behind 3.1): `estimated_usd = ai_credits × price_per_credit`, with the price a workspace pricing row (`copilot_ai_credit`, default `0.01`); no `total_nano_aiu` leaves it `None`.
- [ ] Update the module docstring in `copilot.py` ("`estimated_usd` stays `None`") and add a test on a stand-in shaped like the spike's event: 1,260,000,000 nano AIU gives 1.26 credits and $0.0126. Add a budget test: a budgeted Copilot run stops at 100% like a Claude one.

## 2. Worker: a runtime per provider
- [ ] `packages/worker/src/agentic_worker/main.py`: replace `open_runtime`'s "one opener per run" with a `ProviderRouter` runtime that opens the Claude runtime and/or the Copilot runtime lazily, on the first request for each, and sends each `AgentRequest` to `request.provider`; close both when the attempt ends.
- [ ] `copilot.py`: a Copilot request with `model=None` uses the workspace's `copilot_model`, then `COPILOT_MODEL`; the token loader runs only if a node needs Copilot.
- [ ] Emit `provider.fallback` once per run for triggered runs that dropped Copilot nodes; put `provider` and `model` in the agent's start event payload.
- [ ] Worker tests: a mixed spec (Claude agent → Copilot reviewer) on `FakeRuntime` and `FakeCopilotConnector` asserts which runtime got each node; a Claude-only run never loads a personal token; a resume reuses the stored map after the workspace default changed.

## 3. API and store
- [ ] Alembic migration: `workspaces.default_provider`, `workspaces.copilot_model`; `runs.provider`, `runs.providers` (array), `runs.provider_map` (JSON, the frozen resolution); backfill existing runs (`copilot_connection_id` set → `copilot`, else `claude`).
- [ ] Workspace settings: read and write `default_provider` and `copilot_model` (beside pricing on the Models sub-page's routes), with a `workspace.settings_changed` audit entry.
- [ ] `runs/routes.py` `POST /runs`: accept `provider`; resolve with the stored workspace default (triggered runs pass `triggered=True`); refuse `422` `copilot_connection_required` (nodes named, from `provider_gaps`); store the result. `rerun.py`: keep the stored map for a rerun from a step, resolve again from the beginning.
- [ ] `GET /runs` / `GET /runs/{id}`: return `provider` and `providers`; `GET /runs?provider=` filter.
- [ ] `POST /workflows/{id}/validate` passes the workspace default to `validate_workflow`.
- [ ] Regenerate the OpenAPI client for `web/`.
- [ ] API tests (run from `packages/api`): each refusal code, the run override, 8.2's `copilot_connection_id`-only compatibility, the trigger fallback via the Jira and GitHub webhook paths, the filter.

## 4. Web
- [ ] Read `specs/tech-stack.md` → UI design system, `specs/design-language.md` and `web/AGENTS.md` first.
- [ ] Settings › Models and pricing: a "Default provider" segmented choice, a "Copilot model" field and a "Copilot AI credit" price row (`Money kind="price"`, $0.01 by default), saved from the sticky bar (11.7 pattern), with the three states.
- [ ] Canvas: the workflow settings panel shows the workflow `provider`; the node side panel offers Copilot from the manifest (no hand-written list); the 5.8 picker preselects the workspace default and its Copilot row creates a workflow with `provider: "copilot"`.
- [ ] New run sheet (`provider-choice.tsx`, `readiness.ts`): the choice sends `provider`, preselected from the workflow/workspace default; `requiredFor` derives the needed connections from the resolved providers (lessons 11); a node pinned to the other provider is named under the choice; `copilot_connection_required` is shown in the sheet.
- [ ] Console: provider and model per agent step (step list one-liner and Usage tab, mono font for the model); a Copilot step's AI credits beside its tokens and its cost through `Money`, with the "list price of the credits" tooltip; the header note for `provider.fallback`.
- [ ] Runs list: a provider chip in the Run column and a provider filter chip (saved views keep working).
- [ ] Component tests for each of the above; `pnpm lint && pnpm typecheck && pnpm test`, `pnpm test:e2e` locally.

## 5. Real runs, specs and docs
- [ ] Run one template (Generate docs, or Plan, build and review, which has a hub) unchanged on real Claude, then with the workspace default set to Copilot, and read both step by step in the console (lessons 1); confirm a Copilot hub's plan validates (open question). Record what it showed; add a lessons entry if something reached the run that tests missed.
- [ ] Browser check on a real stack at 375 and 1440 px, light and dark: settings, canvas errors, sheet, console, runs list.
- [ ] `specs/tech-stack.md`: Agent runtime (resolution order, model rule), the personal connection contract's `POST /runs` changes, Run history (`provider`, `providers`, filter), the workspace settings contract, the Copilot adapter's usage paragraph (credits and USD); decisions-log rows replacing "Provider per run (8.2)" and "Copilot cost (8.2)" and updating "Provider picker (5.8)", plus rows for the decisions in `requirements.md`. Add the conversion and its sources to `2026-11-18-copilot-sdk-terms/findings.md`.
- [ ] `docs/` pages that describe the spec's `provider` field or Copilot runs; `CHANGELOG.md` under `[Unreleased]`.
