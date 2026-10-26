# Plan: Graph tab in the run console

API first, then the pure spec → graph mapping, then the UI, then end-to-end checks. The project stays green after each group.

## 1. Spec on the run detail (API)
- [ ] Add `spec: WorkflowSpec` to `RunDetail` in `packages/api/src/agentic_api/runs/models.py`, with a description ("The workflow spec the run was created with").
- [ ] Fill it in `routes.py` (`get_run`) with `WorkflowSpec.model_validate(row.spec)`. Rerun already copies the spec, so a rerun shows its own copy.
- [ ] API test in `packages/api/tests/test_runs.py`: `GET /runs/{id}` returns the posted spec unchanged; `GET /runs` items have no `spec`.
- [ ] Regenerate `web/openapi.json` and `web/src/api/schema.d.ts` (`npm run gen:api`); `RunDetail` in `web/src/runs/use-run-detail.ts` now carries `spec`. Update the console fixtures (`web/src/runs/fixtures/docs-run.json` and test helpers) with the docs template spec.

## 2. Spec → graph mapping (pure, no React)
- [ ] `web/src/runs/graph/spec-graph.ts`: `specToGraph(spec)` → `{nodes, edges}` for React Flow. One `switch` over node types (`sequence`, `loop`, `map`, `agent`, `tool`, `gate`, `reduce`). Fixed node sizes, vertical gap, container padding; containers sized from their children. Node ids are spec node ids, so status lookups are direct.
- [ ] Edges: sequence order (solid), `reduce.from` (dashed, labelled "reduces"). Edges enter and leave containers at the group box.
- [ ] `web/src/runs/graph/node-status.ts`: `nodeStatuses(spec, steps)` → `Map<nodeId, {status, summary}>`. Not-started nodes, aggregate status for body nodes inside a map (failed > running > waiting > completed), map item counts, loop iteration counts. Reuses `StepStatus` and the `Step` tree from `timeline.ts`.
- [ ] `stepsForNode(nodeId, steps)` → the node's step(s): one step for a top-level node, one per item for a map body node, one per iteration for a loop body node. Used by the detail sheet.
- [ ] Vitest: `spec-graph.test.ts` and `node-status.test.ts` (see validation.md).

## 3. Graph tab and node detail (UI)
- [ ] Add `@xyflow/react` to `web/package.json`; import its base stylesheet once and override its colours with our tokens in `globals.css` (`--xy-*` variables mapped to `--background`, `--border`, `--muted`, `--primary`). `colorMode` follows `next-themes`.
- [ ] `web/src/runs/graph/graph-nodes.tsx`: custom node components (`LeafNode`, `ContainerNode`) built from the design system: lucide icon per type, mono node id, one-line role/tool/title, status icon + label from `--status-*` tokens (reuse `stepBadge` / `StatusMarker`), container summary line. `aria-label` per node.
- [ ] `web/src/runs/graph/run-graph.tsx`: `<ReactFlow>` read-only (`nodesDraggable={false}`, `nodesConnectable={false}`, `elementsSelectable`, `nodesFocusable`), `fitView`, `<Controls showInteractive={false}>`, no minimap. Layout memoised on the spec; statuses memoised on the timeline. Bounded box: `h-[calc(100dvh-…-var(--dock-height,0px))]` with a minimum height, `overflow-hidden`.
- [ ] `web/src/runs/graph/node-detail-sheet.tsx`: `Sheet` (right 480 px from 768 px, bottom below, via `useMediaQuery`), title = node id + type, body = `StepList` / step view for `stepsForNode(...)`, grouped by item name or iteration. Empty state for a not-started node; waiting marker for a waiting gate. Opens on node click and on Enter/Space on a focused node; closing returns focus to the node.
- [ ] `run-console.tsx`: `Tab = "timeline" | "graph" | "raw"`, `?tab=graph` in the URL, a `NetworkIcon` "Graph" trigger between Timeline and Raw events. Loading skeleton until the run detail arrives; error state with Retry if it fails.
- [ ] Component tests in `web/src/runs/graph/run-graph.test.tsx` (Testing Library; React Flow needs `ResizeObserver` and `DOMMatrixReadOnly` stubs in the test setup).

## 4. End to end and docs
- [ ] Playwright `web/e2e/graph.spec.ts` on the docs fixture run (fake runtime, as `monitor.spec.ts`): open the Graph tab, see every spec node, click a map body agent, see its messages and tool calls per item; check the waiting gate shows "Needs approval". A second test does the same with the keyboard only (Tab to the node, Enter, Escape returns focus).
- [ ] Add the Graph tab to `web/e2e/a11y.spec.ts` (axe) and `web/e2e/layout.spec.ts` (375 / 768 / 1440 px screenshots, no horizontal scroll).
- [ ] `specs/tech-stack.md`: replace "Graph tab: added in 3.5." with the graph rules (read-only, containers, status icon + label, detail sheet, bounded box). Add a decisions-log row: "Run graph: drawn from the stored spec with a hand-written tree layout".
- [ ] CHANGELOG entry under `[Unreleased]`.
