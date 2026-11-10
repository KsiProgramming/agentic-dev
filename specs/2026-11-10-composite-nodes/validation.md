# Validation: `wrap` / `extract` operations; composite nodes (draft → published)

## Done when (from roadmap)

> AC-3: composite saved in one workflow is reused in another, updated by version

Made checkable:
1. A selection of steps in workflow A is extracted into a new composite with one edit, saved, and published.
2. The composite is added to workflow B from the palette's "Workspace nodes", and B runs with the composite's steps inside its run.
3. When the composite publishes a newer version, B's card offers that version. One edit moves B to it, and B's next run uses it. B never changes without that edit.

## Automated checks

### Engine (`uv run pytest packages/engine`)
- [ ] `wrap` into sequence, parallel, loop and map. Refusals: range not contiguous, parallel with one node, id taken, root, inside an orchestrator worker.
- [ ] `extract` of one node and of a range. The extracted document's root, `input` and port schemas. The subflow put in their place.
- [ ] `extract` refusals: a reduce `from`, a publisher `from_node` or a CEL `results.<id>` crossing the boundary in either direction; the root; a range that is not contiguous; two extracts in one batch.
- [ ] Every `graph-ops.json` wrap and extract case passes in the engine (`test_graph_ops_fixtures.py`).
- [ ] `subflow_unpublished` on a call to a composite's draft. No issue for a never-published workflow (6.5 callers unchanged).
- [ ] Typed subflow: `port_mismatch` through it, both sides. The `port-checks.json` cases pass.
- [ ] Runtime boundary check: wrong-shaped input or output of a typed subflow fails it with the port error and `node_failed.port`.
- [ ] What agents receive: an agent extracted into a composite gets the same instructions, input, tools and context as before extraction (lessons rule 1).
- [ ] `composite_manifest` is a valid manifest, and its `default` is a valid step.

### Store and API (`uv run pytest packages/store packages/api`, Postgres)
- [ ] Publish: OK on a valid version. `422` with issues. `409 already_published`. `404` unknown. The publication row cannot be updated or deleted.
- [ ] `published_version` / `published_at` on `GET /workflows`, `GET /workflows/{id}` and `/versions`.
- [ ] `PATCH` with `extract` creates both versions in one transaction. `workflow_exists` or a failing later op leaves nothing stored.
- [ ] `GET /workflows/{id}/callers` lists the latest versions that call it, with their versions.
- [ ] `GET /node-types?workspace_id=` adds one manifest per composite, pinned to its latest published version. Without `workspace_id`, it returns the primitives only (`node-types.json` unchanged).
- [ ] `POST /runs` refuses a composite's draft version (`422`) and runs its published one.
- [ ] Audit: `workflow.published`, `workflow.created` with `extracted_from`, `workflow.updated` counting `extract`.

### Web (`cd web && pnpm lint && pnpm typecheck && pnpm test`)
- [ ] `ops.test.ts` runs the shared wrap and extract cases.
- [ ] `edits.test.ts`: range helpers, the wrap and extract edits, update-to-version, and a composite added from its palette key. (A port mismatch through a typed subflow is the server's live check: the browser does not know the called workflow's schemas.)
- [ ] Builder: the Extract and Wrap dialogs (range select, slug, field errors, focus after), Publish with confirmation, Update to version N as one undo step, and the Used by list's three states.
- [ ] Palette "Workspace nodes" group with loading, empty and error rows. The workflow being edited is left out.
- [ ] History "Published" badge. Workflows list "Composite" badge (table and cards).
- [ ] `pnpm lint` passes: no raw colours, no arbitrary sizes. Badges are neutral and use no status colour.

### End to end (`cd web && pnpm test:e2e`)
- [ ] `composite.spec.ts`: the AC-3 journey (extract → publish v1 → add to B from the palette → run → publish v2 → Update → run on v2). Both runs nest the composite's steps under the subflow, and the second shows version 2.
- [ ] `a11y.spec.ts`: axe passes on the builder with the Extract dialog, the Publish dialog and the Used by list open, at 375, 768 and 1440 px, light and dark.
- [ ] `layout.spec.ts`: builder screenshots with a composite card and the "Workspace nodes" palette at 375 and 1440 px, with no horizontal scroll.

## Manual / demo checks

- [ ] **Real Claude run** (lessons rule 1):
  - Start the stack with `AGENTIC_RUNTIME=claude` and a Claude key in Settings.
  - Run workflow B, which calls a published composite with at least one agent that reads the repo, on a real repo.
  - In the console, open each composite step's **Activity** and **Input**. Each agent must have the instructions, input and tools it had when it was inline in A, and read the code it needed. Its answer must be what the next step needs.
  - Note any renamed id (`<subflow>-<id>`) and check that it changed nothing the agent sees.
  - Record the run id in the PR. Add a `specs/lessons.md` entry if anything went wrong.
- [ ] Look at the builder at 375 and 1440 px, light and dark: the Extract dialog, the Publish dialog, the composite card with "version N is published", and the palette group.

## Merge criteria

- [ ] All automated checks above pass locally (CI minutes are limited: run them locally and report the results in the PR).
- [ ] tech-stack updated in the same PR (graph ops, Composites contract, Subflow, Node manifests, Builder canvas, validation codes, decisions log). Roadmap `[Plan]` link. `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] `schemas/graph-ops.v1.json` and the OpenAPI client regenerated. The engine's stale-fixture tests pass.
- [ ] The real Claude run is read and recorded in the PR description.
- [ ] No spec content or secrets in the audit details (counts and ids only, as in 5.1).
