# Plan: Canvas renders a spec; edits emit graph operations

Contract first (API, then the pure TS ops module), then the shared tree, then the page and its edits. The app works after each group.

## 1. API: a workflow from a template
- [x] `agentic_api/workflows/models.py`: `CreateWorkflowRequest` takes `spec` or `template` + `parameters` (exactly one; a model validator); `WorkflowErrorDetail` gains `workflow_id` for `workflow_exists`.
- [x] `CreateWorkflowRequest` builds the spec through `TemplateRun.build_spec` (as `POST /runs`: an unknown template or bad parameters are `422`); `create` keeps its path.
- [x] `packages/api/tests/test_workflows.py`: create from each template with defaults, second create `409` with `workflow_id`; unknown template, bad parameter, both bodies and neither → `422`.
- [x] `scripts/export_openapi.py` → `web/openapi.json`; `pnpm gen:api`.

## 2. Ops module (web, pure)
- [x] `web/src/workflows/ops.ts`: `GraphOp` types from `@/api/schema`; `applyOps(spec, ops)` returning the spec or an `OpError {code, message, op_index, node_id}`; placement by id, detached pool, holes, `connect` wrap with `sequence_id`, `setParam` paths.
- [x] `web/src/workflows/edits.ts`: edit builders the canvas calls, each returning ops: `addAfter(spec, afterId | null, kind)` (new id `<kind>_<n>`), `moveUp`/`moveDown(spec, id)` (one `connect`), `remove(id)`, `setName`/`setDescription`.
- [x] Parity fixtures: `schemas/fixtures/graph-ops.json` (one spec, cases `{ops, result | error}`), read by a new engine test (`test_graph_ops_fixtures.py`) and by `ops.test.ts`, so both apply them alike (`schema` cases engine only).
- [x] `edits.test.ts`: each builder's ops, moves at the ends, ids unique.

## 3. Shared tree
- [x] Extract the chain layout and card from `web/src/runs/graph/run-map.tsx` into `web/src/runs/graph/spec-tree.tsx` (`SpecTree`): cards from the spec, a `renderStatus` slot (the run map's dot and line) and a `renderActions` slot (the canvas's menu).
- [x] `RunMap` uses it; `run-map.test.tsx` and the layout screenshots stay unchanged.

## 4. Builder page (read)
- [x] `web/src/workflows/api.ts`: TanStack Query hooks `useWorkflow(workspace, id)`, `useSaveWorkflow` (PATCH), `useWorkflowFromTemplate` (POST from a template).
- [x] `web/src/app/workflows/[id]/page.tsx` + `web/src/workflows/builder.tsx`: `PageHeader` (name, description, `IdChip`, "Version N", issue count), `SpecTree` of the spec, `LoadingState` / `EmptyState` / `ErrorState`.
- [x] Shell breadcrumbs: "Workflows › <id>", the first segment not linked (`nav.ts` unlisted sections).

## 5. Edits, buffer and Save
- [x] Edit state in the builder: edits (each a list of ops), the applied spec, undo, discard, `dirty`.
- [x] Card "⋯" menu (`DropdownMenu`): Add step after (agent, tool, gate), Move up, Move down, Remove (confirm `AlertDialog` naming the node and its subtree size); "Add first step" above the first card. Root-sequence steps only.
- [x] Header: Edit details (a dialog, `setParam` on name and description as one edit), Undo, Discard (confirm), Save ("Saving…" while pending); a status line with the version, issues and unsaved changes.
- [x] Save: `PATCH`; on `201` show the new version and clear; `409` → refetch latest, re-apply the buffer locally, keep or drop with a toast; `422` → toast and an error line on `node_id`'s card.
- [x] Leave guard: `beforeunload` while dirty (as the gate review's edits do).
- [x] `builder.test.tsx`: each menu item emits the expected ops and redraws; undo; a mocked `409` keeps rebasable edits.

## 6. Entry point
- [x] Templates: "Edit in builder" on the gallery card → `useWorkflowFromTemplate`; `409` with `workflow_id` opens it; navigate to `/workflows/<id>`.
- [x] `templates-view.test.tsx`: the action calls the API and navigates.

## 7. E2E and specs
- [x] `web/e2e/builder.spec.ts`: create a workflow via the API (E2E workspace), open it, add an agent after the first step, move it down, remove a step, rename, Save, reload: the canvas and `GET /workflows/{id}` show version 2 with that spec; `GET ?version=1` unchanged.
- [x] `layout.spec.ts` and `a11y.spec.ts`: the builder page at their widths and themes.
- [x] `tech-stack.md`: Frontend "Canvas" row (the card tree, no React Flow); a "Builder canvas" section under UI design system; `POST /workflows {template, parameters}` in the workflows contract; decisions rows (canvas technology, edit gestures, save model, client apply). `CHANGELOG.md` under `[Unreleased]`.
