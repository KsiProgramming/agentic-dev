# Validation: `wrap` / `extract` operations; composite nodes (draft → published)

## Done when (from roadmap)

> AC-3: composite saved in one workflow is reused in another, updated by version

Made checkable:
1. A selection of steps in workflow A is extracted into a new composite with one edit, saved, and published.
2. The composite is added to workflow B from the palette's "Workspace nodes", and B runs with the composite's steps inside its run.
3. When the composite publishes a newer version, B's card offers that version. One edit moves B to it, and B's next run uses it. B never changes without that edit.

## Automated checks

### Engine (`uv run pytest packages/engine`)
- [x] `wrap` into sequence, parallel, loop and map. Refusals: range not contiguous, parallel with one node, id taken, root, inside an orchestrator worker.
- [x] `extract` of one node and of a range. The extracted document's root, `input` and port schemas. The subflow put in their place.
- [x] `extract` refusals: a reduce `from`, a publisher `from_node` or a CEL `results.<id>` crossing the boundary in either direction; the root; a range that is not contiguous; two extracts in one batch.
- [x] Every `graph-ops.json` wrap and extract case passes in the engine (`test_graph_ops_fixtures.py`).
- [x] `subflow_unpublished` on a call to a composite's draft. No issue for a never-published workflow (6.5 callers unchanged).
- [x] Typed subflow: `port_mismatch` through it, both sides. The `port-checks.json` cases pass.
- [x] Runtime boundary check: wrong-shaped input or output of a typed subflow fails it with the port error and `node_failed.port`.
- [x] What agents receive: an agent extracted into a composite gets the same instructions, input, tools and context as before extraction (lessons rule 1).
- [x] `composite_manifest` is a valid manifest, and its `default` is a valid step.

### Store and API (`uv run pytest packages/store packages/api`, Postgres)
- [x] Publish: OK on a valid version. `422` with issues. `409 already_published`. `404` unknown. The publication row cannot be updated or deleted.
- [x] `published_version` / `published_at` on `GET /workflows`, `GET /workflows/{id}` and `/versions`.
- [x] `PATCH` with `extract` creates both versions in one transaction. `workflow_exists` or a failing later op leaves nothing stored.
- [x] `GET /workflows/{id}/callers` lists the latest versions that call it, with their versions.
- [x] `GET /node-types?workspace_id=` adds one manifest per composite, pinned to its latest published version. Without `workspace_id`, it returns the primitives only (`node-types.json` unchanged).
- [x] `POST /runs` refuses a composite's draft version (`422`) and runs its published one.
- [x] Audit: `workflow.published`, `workflow.created` with `extracted_from`, `workflow.updated` counting `extract`.

### Web (`cd web && pnpm lint && pnpm typecheck && pnpm test`)
- [x] `ops.test.ts` runs the shared wrap and extract cases.
- [x] `edits.test.ts`: range helpers, the wrap and extract edits, update-to-version, and a composite added from its palette key. (A port mismatch through a typed subflow is the server's live check: the browser does not know the called workflow's schemas.)
- [x] Builder: the Extract and Wrap dialogs (range select, slug, field errors, focus after), Publish with confirmation, Update to version N as one undo step, and the Used by list's three states.
- [x] Palette "Workspace nodes" group with loading, empty and error rows. The workflow being edited is left out.
- [x] History "Published" badge. Workflows list "Composite" badge (table and cards).
- [x] `pnpm lint` passes: no raw colours, no arbitrary sizes. Badges are neutral and use no status colour.

### End to end (`cd web && pnpm test:e2e`)
- [x] `composite.spec.ts`: the AC-3 journey (extract → publish v1 → add to B from the palette → run → publish v2 → Update → run on v2). Both runs nest the composite's steps under the subflow, and the second shows version 2.
- [x] `a11y.spec.ts`: axe passes on the builder with the Extract dialog, the Publish dialog and the Used by list open, at 375, 768 and 1440 px, light and dark.
- [x] ~~`layout.spec.ts`~~ replaced by screenshots taken by hand with Playwright (see Results): the builder's layout screenshots already cover the canvas, and the Workspace nodes entries depend on what the E2E workspace has published.

## Manual / demo checks

- [x] **Real Claude run** (lessons rule 1):
  - Start the stack with `AGENTIC_RUNTIME=claude` and a Claude key in Settings.
  - Run workflow B, which calls a published composite with at least one agent that reads the repo, on a real repo.
  - In the console, open each composite step's **Activity** and **Input**. Each agent must have the instructions, input and tools it had when it was inline in A, and read the code it needed. Its answer must be what the next step needs.
  - Note any renamed id (`<subflow>-<id>`) and check that it changed nothing the agent sees.
  - Record the run id in the PR. Add a `specs/lessons.md` entry if anything went wrong.
- [x] Look at the builder at 375 and 1440 px, light and dark: the Extract dialog, the Publish dialog, the composite card with "version N is published", and the palette group.

## Merge criteria

- [x] All automated checks above pass locally (CI minutes are limited: run them locally and report the results in the PR).
- [x] tech-stack updated in the same PR (graph ops, Composites contract, Subflow, Node manifests, Builder canvas, validation codes, decisions log). Roadmap `[Plan]` link. `CHANGELOG.md` entry under `[Unreleased]`.
- [x] `schemas/graph-ops.v1.json` and the OpenAPI client regenerated. The engine's stale-fixture tests pass.
- [x] The real Claude run is read and recorded in the PR description.
- [x] No spec content or secrets in the audit details (counts and ids only, as in 5.1).

## Results (2026-11-10)

- **Engine, store, API:** `uv run pytest api store engine` 1,290 passed; the full suite without the sandbox package 1,799 passed. Ruff and pyright clean.
- **Web:** `pnpm lint && pnpm typecheck && pnpm test`: 1,059 passed (237 in `src/workflows`).
- **End to end:** `pnpm test:e2e` on the local stack in fake mode: 277 passed in the parallel run. `composite.spec.ts`, the composite a11y check, `builder.spec.ts` and `subflow.spec.ts` pass on their own (the last two needed to ignore the E2E workspace's composites, and the run found the palette growing past the screen, now scrolling). The other failures are known and not from this phase: `layout.spec.ts:307/334/361` at 375 px (stale since 5.9), and `audit`, `console`, `inbox`, `monitor`, `runs-page` and two mobile a11y checks, which fail only in the parallel run and pass with `--workers=1`.
- **Look:** the Extract dialog, the Used by popover and bottom sheet, the Published badge, the composite card and the palette's Workspace nodes, at 375 and 1440 px in light and dark. At 375 px a nested palette submenu overflows the right edge, as it already did before this phase (a follow-up).
- **Real Claude run** `cfdc0f47-c213-4b9e-bf78-ddfcfeed6117` on `KsiProgramming/GildedRoseKata`, `composite-demo-caller` version 2 calling `risk-review` version 1 (extracted from `composite-demo-source`, then published): completed, 25 s active, about $0.08. `draft` listed and searched the repo and named three files; inside the call, `check` received that answer as its input, exactly as it did inline, read the three files (and `ItemKind.cs` to check a claim) and gave one risk each; `verdict`, with no tools, received the risks and picked one in two sentences, saying plainly what it had not read. No agent id was renamed (only the called root, `risk_review-main`). Nothing went wrong, so no lessons entry.
