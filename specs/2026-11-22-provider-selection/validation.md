# Validation: Provider selection per workspace, workflow and node

## Done when (from roadmap)
> AC-6: same workflow runs on Claude and Copilot unchanged

Made checkable: one stored workflow version, with no edit between the two runs, completes once with every agent on Claude and once with every agent on Copilot, only the workspace default (or the sheet's choice) changing; each run's steps show the provider and model that ran them.

## Automated checks
- [ ] Engine: resolution table tests (node > run override > workflow > workspace > Claude; nested subflow and composite; triggered fallback lists the dropped nodes; a node's `model` kept only on its own provider).
- [ ] Engine: `provider_gaps` returns `copilot_connection_required` with the node ids when a node resolves to Copilot and there is no connection, and nothing otherwise; `validate_workflow` reports it per node.
- [ ] Runtime: a stand-in `assistant.usage` with 1,260,000,000 nano AIU gives `ai_credits` 1.26 and `estimated_usd` 0.0126 at the default price, and a changed workspace price changes it; a call with no `total_nano_aiu` stays unpriced; a budgeted Copilot run stops at 100% with `budget_usd` as its reason.
- [ ] Engine: the regenerated JSON Schema and manifests offer `["claude", "copilot"]` on the four agent-like nodes and the workflow.
- [ ] Worker: a mixed Claude → Copilot spec on `FakeRuntime` and `FakeCopilotConnector` sends each node to the right runtime and opens each at most once; a Claude-only run loads no personal token; a resume after the workspace default changed keeps the stored providers; `provider.fallback` is emitted once for a triggered run; the token still appears in no event (8.2's redaction test passes).
- [ ] API (from `packages/api`): `POST /runs` refuses `copilot_connection_required` naming the nodes; the run override beats the workflow and workspace but not an explicit node; `copilot_connection_id` alone still means Copilot; Jira- and GitHub-triggered runs store Claude only; `GET /runs?provider=copilot` returns only runs that used it; workspace settings round-trip with an audit entry; the migration backfills `provider` for existing runs.
- [ ] Web: component tests for the settings fields (with the credit price), the sheet's `requiredFor` from resolved providers and its connection refusal, the provider per step, a Copilot step's credits and cost, the fallback note, and the runs list filter.
- [ ] `uv run` lint, type check (strict) and tests for every package touched; `pnpm lint && pnpm typecheck && pnpm test`; `pnpm test:e2e` (axe and layout specs) green locally before CI.

## Manual / demo checks
- [ ] **AC-6 on real providers:** with Claude and a personal GitHub connection set up, start one template (one with a hub, so a typed plan is exercised) on Claude, then set Settings › Models › Default provider to Copilot and start the same version again. Both complete; the console shows `claude` and `copilot` on every step; each was read step by step (lessons 1).
- [ ] **Mixed run:** pin one node to Copilot on the canvas, leave the workspace on Claude, and start it: only that step shows Copilot, its Usage tab shows AI credits and a cost, and the run's total includes it. Check the cost against the credits GitHub's usage page shows for that person (credits × $0.01).
- [ ] **Budget on Copilot:** set a small `budget_usd` on a Copilot run: it stops cleanly at 100% with the budget as its reason, as a Claude run does.
- [ ] **Trigger fallback:** fire a Jira trigger on a workflow whose default is Copilot: the run runs on Claude and the console header shows the fallback note.
- [ ] **Browser check on a real stack** (lessons 11): settings, canvas, sheet, console and runs list at 375 and 1440 px, in light and dark; no horizontal page scroll; keyboard reaches every new control.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] Both real runs were read in the console; anything they taught is in `specs/lessons.md`.
- [ ] `specs/tech-stack.md` updated (contracts, resolution and model rules, refusal codes, decisions-log rows replacing "Provider per run (8.2)"); `docs/` updated; `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] No token in any event, log line, audit entry or error message; no raw colours or arbitrary text sizes (`pnpm lint`).
