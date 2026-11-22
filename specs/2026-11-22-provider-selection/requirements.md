# Provider selection per workspace, workflow and node

Roadmap phase: 8.3
Branch: plan/8.3-provider-selection

## Context

Last phase of Milestone 8 (Second provider), named by the roadmap's "Next up" line. 8.2 (#251) shipped the personal GitHub connection and `CopilotRuntime`, but as an all-or-nothing switch: a run started with `copilot_connection_id` runs **every** agent on Copilot, and the spec's `provider` field still only accepts `claude` (decisions log, "Provider per run (8.2)"). This phase makes the provider a property of the spec and the workspace, so that **the same workflow runs on Claude and on Copilot without changes (AC-6)**.

It depends on done work only: the `provider` / `model` fields on the four agent-like nodes (5.4), node manifests and the side panel generated from them (5.3, 5.4), validation and live canvas validation (3.4, 5.6), the 5.8 provider picker, Settings › Models and pricing (11.7), the run's frozen policy (3.2), budgets (3.3) and 8.2's connection, adapter and New run sheet. It unblocks Copilot lenses in independent review (13.6), the model replay (17.5) and governance of providers (20.3).

Principles and choices that drive it:
- **1. One spec, many views.** The provider is set in the spec (node, workflow) or the workspace, through the same graph operations (`setParam`), never only in the UI.
- **2. Open, but safe by construction.** Capability gaps are checked at validation time and again at `POST /runs`.
- **4. Tools live in the platform.** Both adapters already get the same MCP tools, so a node changes provider with no tool change.
- **8. Numbers are truthful.** Copilot reports AI credits in nano units (`total_nano_aiu`, 1 credit = 10⁹), and GitHub bills **1 AI credit = $0.01 USD** (GitHub docs, "GitHub Copilot billing" and the Copilot SDK's "Usage and billing" page). So a Copilot step gets an `estimated_usd` like a Claude step, which replaces 8.2's "tokens only" decision. Like Claude's estimate, it is the list-price value of the usage: a person whose plan still has included credits pays nothing extra for it.
- Decisions log, 8.1: **runs with no starter stay on Claude** (Jira 7.3, GitHub 7.6, later schedules 18.1).
- Lessons **10** (a provider is built on a real run), **11** (the provider a run uses decides what it needs) and **1** (this phase changes what agents receive, so it is done only once a real run on each provider has been read step by step in the console).

## Scope

### In scope
- **Spec:** `provider: "claude" | "copilot"` on `AgentNode`, `ReduceAgent`, `RouterClassifier` and the orchestrator hub; a workflow-level `provider` default on `WorkflowSpec`; the JSON Schema and node manifests regenerated, so the side panel and the 5.8 picker offer Copilot with no hand-written UI list.
- **Workspace default:** a `default_provider` (Claude unless set) and a `copilot_model` (the worker's `COPILOT_MODEL`, `auto`, unless set) per workspace, edited on Settings › Models and pricing, saved through the API and recorded in the audit log.
- **Resolution, frozen at run creation:** node `provider` > run override > workflow `provider` > workspace default > Claude. `POST /runs` works out each agent-like node's provider and stores the result on the run (`runs.provider` for the run's default, `runs.providers` for the set used). A resume or a rerun uses what was stored, as the run's policy does (3.2); a rerun from the beginning works it out again.
- **Run-level override:** the New run sheet's Claude / Copilot choice (8.2) becomes the run's provider. It beats the workflow and workspace defaults, never a node that names its own. `POST /runs` takes `provider`; `copilot_connection_id` with no `provider` keeps 8.2's meaning (Copilot for the run).
- **Model per provider:** a node's `model` is used only on the provider it was written for (its explicit `provider`, otherwise Claude). A node that inherits Copilot runs on the workspace's `copilot_model`, and a node that ends up on Claude by fallback uses Claude's default. Copilot's model names are per person (8.2 spike), so no Copilot model name is checked.
- **Per-node runtime in the worker:** the worker opens a runtime per provider the run uses, at most one Claude client and one Copilot client per attempt, and each agent call goes to its node's resolved provider. One run may mix the two.
- **Triggered runs stay on Claude:** a run a Jira or GitHub trigger starts resolves every node to Claude, including a node that names Copilot. The run records one `provider.fallback` event (the nodes and why), and the console shows it in the header's note. A trigger is never refused for this.
- **Copilot cost in USD:** the Copilot adapter turns each `assistant.usage`'s `copilot_usage.total_nano_aiu` into `ai_credits = nano / 10⁹` and `estimated_usd = ai_credits × price_per_credit`. The price is a workspace pricing row on Settings › Models and pricing, `$0.01` by default, so a change by GitHub is an edit and not a release. The usage event keeps `ai_credits` beside the tokens. A call with no `total_nano_aiu` stays unpriced (`estimated_usd: null`), and the budget meter already stops a budgeted run on unpriced usage (3.3). Budgets therefore hold for Copilot steps, and a mixed run's cost covers every step.
- **Capability-gap validation:**
  - `copilot_connection_required`: a run where a node resolves to Copilot has no usable personal connection (`POST /runs`, `422`; the sheet asks for one first).
  - The gaps are computed in one engine function (`provider_gaps`) used by `validate_workflow`, the canvas and `POST /runs`, so the three always agree. The typed-output question below may add a gap there.
- **API:** `GET /runs` and `GET /runs/{id}` return `provider` and `providers`; `GET /runs` filters by `provider` (a run matches when it used it); the agent's start event carries its `provider` and `model`.
- **Console and runs list:** each agent step shows the provider and model that ran it (step list and Usage tab); the runs list shows a provider column or chip and a provider filter chip; a Copilot step's Usage tab shows its AI credits beside the tokens and its cost through `Money`, and the cost's tooltip says it is the list price of the credits, not what the person's plan charged.
- **Specs and docs:** tech-stack (spec fields, resolution order, the `POST /runs` changes and codes, the workspace settings contract, decisions-log rows that replace "Provider per run (8.2)" and the 5.8 picker row), lessons if a real run teaches something, `docs/` pages that describe `provider`, `CHANGELOG.md`, and the roadmap row marked done by CI.

### Out of scope
- **Copilot for runs with no starter** (a trigger owner): not until a phase names one (decisions log, 8.1).
- **Tracking a person's included allowance** (how many of the plan's monthly credits are left, or whether a step was actually billed): the platform cannot see it, so the cost shown is always the list price. A budget counted in credits rather than USD is not needed, since one converts to the other at a fixed price.
- **Checking Copilot model names**, or a list of the models a person's account offers: per person and changing (8.2 spike). `model: auto` routing is 20.5.
- **Provider governance** (which providers a workspace may use) and **data rules by provider**: 20.3 and 20.4.
- **A new Playwright spec** (not chosen in the interview). The existing e2e, axe and layout specs stay green.
- **A hosted multi-tenant Copilot offer:** stays no-go (10.5, 8.1).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Resolution order | node > run override > workflow > workspace > Claude | Chosen in the interview. The most specific setting wins; a node pinned by its author is never overridden by a person at start. |
| When resolved | Once, at `POST /runs`, stored on the run | Like the frozen policy (3.2): a resume after a workspace change must not switch a half-done run's provider. |
| Triggered runs | Every node on Claude, one `provider.fallback` event, never refused | Roadmap row and 8.1 decision ("stay on Claude"). Refusing would break existing Jira and GitHub triggers on workflows that also run by hand on Copilot. |
| Model on another provider | A node's `model` belongs to the provider it was written for; otherwise that provider's default | Chosen in the interview. Without it, "unchanged" (AC-6) fails as soon as a node names `claude-opus-5-5` and runs on Copilot, or the reverse. |
| Copilot cost | `estimated_usd` = `total_nano_aiu` / 10⁹ × the workspace's price per credit (default $0.01) | GitHub bills 1 AI credit = $0.01 and the SDK reports credits in nano units. Replaces 8.2's "tokens only" decision. This also drops the interview's budget gap check (`budget_needs_usd`): it existed only because Copilot had no USD, and with a price a budget holds on Copilot as on Claude. |
| Price per credit | A workspace pricing row, not a constant | Same as model prices (3.1): a change in GitHub's price is an edit in settings. |
| One place for gaps | An engine function used by validation, the canvas and `POST /runs` | Principle 2: checked at validation time and again at runtime, with the same answer. |
| `copilot_connection_id` alone | Still means Copilot for the run | Keeps 8.2's API and its tests working; the sheet sends `provider` from now on. |
| Order of work | Contract first: engine, worker, API, UI, real runs | Chosen in the interview. Each group leaves the stack working; the UI comes last on a settled contract. |

## Open questions
- Does a Copilot router classifier or orchestrator hub answer the typed output (`output_schema`, plan schema) as reliably as Claude? Both are told the schema in their instructions, with no native structured output mode. The real Copilot run checks a hub's plan. If it fails, the gap becomes a validation error for typed nodes on Copilot, recorded in lessons.
- Should the workspace's `default_provider` also be the default for a new blank workflow (5.8 picker)? Proposed: yes, as the picker's preselected row. Confirm when building the UI.
