# Graph tab in the run console

Roadmap phase: 3.5
Branch: plan/3.5-run-console-graph-tab

## Context
The 2.5 run console reads a run as a story (timeline) and keeps the raw log one click away. What it does not show is the *shape* of the workflow: which nodes the run will go through, which are nested in a map or a loop, and where it is now. 3.5 adds a **Graph** tab: a read-only drawing of the run's spec, coloured live by each node's status, where clicking a node shows what that node did, using the 2.5 step view.

Today the console cannot draw the spec: `runs.spec` holds it, but `GET /runs/{id}` only returns `workflow: {id, name}`. The timeline is built from events alone, so nodes that have not started yet are invisible. The graph needs the spec itself.

Principles that drive it:
- **Mission 1 (one spec, many views):** the graph is drawn from the run's stored spec, never from a second model of the workflow. 5.2 draws the same spec on the editable canvas.
- **Mission 6 (transparency):** every node, started or not, is visible with its live status.
- **Mission 8 (calm UI) and the [run console rules](../tech-stack.md#run-console):** status colours from `--status-*` tokens with icon + label, never colour alone; the waiting gate stays reachable through the approval dock; no horizontal page scroll at any width.
- **Tech stack:** React Flow (`@xyflow/react`) is the chosen library for canvas and monitor; data comes from TanStack Query + the existing SSE stream.

Depends on: 2.3 (`GET /runs/{id}`), 2.5 (timeline, step view), 2.6 (approval dock). All are done.
Unblocks: 5.2 (canvas renders a spec, reusing the spec → graph mapping and node components), 6.4 (dynamic children shown live on the graph).

## Scope
### In scope
- **API:** `RunDetail` gains `spec: WorkflowSpec`, the spec the run was created with (`runs.spec`, parsed with the engine model). It is not added to `RunSummary`, so `GET /runs` stays light. OpenAPI and `web/src/api/schema.d.ts` regenerated.
- **Spec → graph mapping** `web/src/runs/graph/spec-graph.ts`, a pure function `specToGraph(spec)` → React Flow nodes and edges, with a deterministic top-to-bottom layout:
  - a `sequence` draws its steps as a vertical chain; the root sequence and sequences nested in a sequence are not drawn as boxes;
  - `loop` and `map` are **container groups** with their body drawn inside them (React Flow parent nodes);
  - `agent`, `tool`, `gate` and `reduce` are leaf nodes showing an icon per type, the node id (mono) and its role/tool/title in one line;
  - a `reduce` is linked to its map, labelled "reduces" (dashed when the map is not the step right before it).
- **Status overlay** `nodeStatuses(spec, steps)`: each node's status from the timeline (`buildTimeline`), by node id. Nodes not started yet are "Not started" (muted). Container summaries: a map shows "3 of 5 items · 1 failed", a loop "iteration 2 of 5". A body node inside a map takes the aggregate status of its items (failed > running > waiting > completed). Updates arrive live from the existing SSE stream; the layout is computed once per spec, only node data changes.
- **Graph tab:** a third tab "Graph" (`?tab=graph`) next to Timeline and Raw events.
  - React Flow read-only: no dragging, no connecting, no deleting; pan and zoom allowed; `fitView` on open; zoom controls; light and dark theme from tokens.
  - The canvas sits in its own bounded box (height from the viewport, reserved padding for the approval dock), so it never causes page scroll sideways at 375, 768 or 1440 px.
  - The waiting gate shows "Needs approval"; a failed node shows "Failed". Status is icon + label.
- **Node detail:** clicking (or Enter on a focused node) opens a sheet (side sheet 480 px from 768 px, bottom sheet below) with the 2.5 step view for that node: messages, tool calls, usage footer. For a body node in a map, the sheet lists the node's run per item (by item name); for a loop body node, per iteration. A node that ran inside a container is always shown there, even when an event without an `item` (a budget stop's `policy_limit_exceeded`) also names it. A not-started node says "This step has not run yet". A gate node shows the waiting marker linking to the dock.
- **Accessibility:** each node is a button (one tab stop, Enter or Space opens it), each has an accessible name ("worker, agent, Done"), and status changes keep the console's existing `aria-live` announcement.
- **Docs:** `specs/tech-stack.md` "Graph tab" line replaced with the rules above.

### Out of scope
- Drawing each map item or loop iteration as its own node, per-node cost or duration on the graph, and a deep link to a node (`?node=`): later, if needed (6.4 adds live dynamic children).
- Editing the graph, palette, side panel forms: 5.2 to 5.4.
- Validation issues drawn on nodes: 5.6.
- `parallel`, `router`, `orchestrator`, `subflow` nodes: they do not exist yet (4.1, 4.6, 6.1, 6.5); the mapping has one `switch` over node types, so each adds a case.
- A layout library: the spec is a chain with boxes today, so a hand-written layout is enough. ELK (`elkjs`) replaces it when branching arrives (4.1 `parallel` or 4.6 `router`); Dagre is ruled out because it lays out a box wrongly when a node inside it links to one outside (React Flow → Layouting).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where the graph comes from | The run's stored spec on `GET /runs/{id}` (`spec`) | One spec, many views (mission 1). Events alone cannot show nodes that have not started. |
| Spec only on the detail | `RunDetail.spec`, not `RunSummary` | The runs list does not need it and stays small. |
| Layout | Hand-written, deterministic top-to-bottom layout now; ELK (`elkjs`) from 4.1 or 4.6 | The spec is a tree (3.4: no cycles) with no branches yet, so placement is simple and testable as a pure function. Only `@xyflow/react` is added. Branches need edge routing around boxes, which ELK does and Dagre does not do correctly for sub-flows. Only the inside of `specToGraph` changes then. |
| Node interaction | Each node is a `<button>`; React Flow's node focus and selection are off, and each node keeps `pointer-events: all` | One tab stop and native Enter/Space per node (React Flow's own focus only selects on Enter). React Flow turns pointer events off on nodes that are neither selectable nor draggable, which let the pane take every click (found in manual testing). |
| Containers | Loop and map as React Flow group nodes holding their body; items and iterations shown as counts | Shows the spec's real shape while keeping the graph the size of the spec, not of the run. |
| Status source | The same `buildTimeline(events)` the Timeline tab uses | Graph and timeline can never disagree; no new events or endpoints. |
| Node detail | A sheet reusing the 2.5 step view | Same reading of "what the agent did" in both tabs; the sheet pattern already exists (2.6). |
| Order of work | API first, then the pure mapping, then the UI, then e2e | The contract settles first and the mapping is unit-tested before any rendering (user's choice). |

## Open questions
- None.
