# Node manifests and a palette generated from them

Roadmap phase: 5.3
Branch: plan/5.3-node-manifests-palette

## Context

Done when: **a new primitive appears in the palette with no frontend change.**

5.2 made the stored spec editable on a card tree, but its "Add step" menu is hard-coded in the browser (`NEW_KINDS` and `newNode` in `web/src/workflows/edits.ts`: agent, tool and gate with fixed defaults), and the cards know each kind by a `switch` (`KIND` in `web/src/runs/graph/node-kinds.tsx`, `nodeDetail` in `spec-graph.ts`). Each new primitive therefore needs a web change. This phase makes the engine describe its own building blocks. Each primitive gets a **node manifest** (what it is, how it is shown, its parameters as JSON Schema, a node to add). The builder's palette is drawn from the manifests the API serves.

What drives it:
- **Mission, "Open orchestration":** users extend the set (composites in 6.6, plugins in 10.1) and no engine release is needed. The same must hold for the UI: a node kind the engine knows must not need a web release.
- **Mission principle 1 (one spec, many views):** a palette item adds through the same `addNode` op as before. The manifest describes a node and is never a second model of it.
- **Tech-stack:** Pydantic v2 is already listed for "node manifests … exported as JSON Schema". Side panels are `@rjsf/core` forms "rendered from node manifests" (5.4 reads this phase's `parameters`). Tools are "granted per node through the node manifest" (left to 5.4 and 10.1).

Note: the roadmap's "Next up" line names 4.8, which is not planned. The user picked 5.3 on purpose. It depends only on 5.1 and 5.2 (both done).

It unblocks 5.4 (side panel from `parameters`), 5.5 (container `slots` say where children go), 9.2 (the Architect's `list_primitives` returns these manifests) and 6.6 and 10.1 (composites and plugins add manifests to the same list).

## Scope

### In scope

- **`NodeManifest` model** (Pydantic, `agentic_engine.nodes`): `kind` (the `type` value), `label` ("Agent"), `description` (one sentence), `category` (`step`, `flow` or `combine`), `icon` (a lucide icon name, e.g. `bot`), `parameters` (JSON Schema of the editable fields, derived from the node's Pydantic model: `type`, `id` and the slots that hold nodes are removed), `slots` (the fields that hold child nodes, with their shape: `steps` list, `body` one, `branches` list, `routes[].then` one, `default` one; empty for leaves), `default` (a whole node that validates, children included) and `fill` (optional generic hints the palette applies on add; v1 has one: `previous_step: <param>`, which sets that parameter to the id of the step the node is added after, as reduce's `from`).
- **A registry with a manifest for each of the 9 primitives**, ordered for the palette:
  - Steps: agent, tool, gate
  - Flow: sequence, parallel, router, loop, map
  - Combine: reduce

  Defaults:
  - agent and tool as in 5.2
  - gate: title "Approve"
  - sequence: one agent step
  - parallel: two agent branches, `join: all`
  - router: one rule route (`when: "true"`) to an agent, plus a `default` agent
  - loop: an agent body, `until: "iteration >= 3"`, `max_iterations: 3`
  - map: `over: "[last]"`, an agent body, `max_concurrency: 4`
  - reduce: `strategy: concat`, `from` filled from the previous step

  A test makes every member of the `Node` union need a manifest, so a primitive cannot ship without one.
- **`GET /node-types`** (`operationId: listNodeTypes`): the manifests in palette order, the same for every workspace (like `GET /templates`). It is added to the OpenAPI spec and the generated client.
- **Palette in the builder:** "Add a step after" (now a submenu of the step's "⋯" menu, since nine kinds and their group labels make the menu too long) and "Add first step" list the manifests from `GET /node-types` (TanStack Query, cached for the session), grouped by category with a separator and a group label, each item with its icon and label (and its description as the item's secondary line or title). Choosing one adds `manifest.default` with fresh ids: every node in it (any object whose `type` is a manifest kind and has an `id`) becomes `<kind>_<n>`, unique in the spec. `fill` is applied, then the item becomes one `addNode` edit. The menu has a loading row, an error row with Retry, and an empty row ("No node types available").
- **Cards tolerate a kind the web does not know:** `KindIcon` and `kindLabel` fall back to the manifest's icon and label when the web has them, else to a generic icon (`box`) and the kind itself. `nodeDetail` returns `""` for an unknown kind. Fresh ids are found by walking the spec through the manifests' `slots`, so they still work for a container the web does not know. The manifest icon name maps through a small lookup of lucide icons, and an unknown name falls back to `box` (no dynamic import of all of lucide).
- `NEW_KINDS` and the hard-coded `newNode` switch are removed.
- Specs: tech-stack gets a "Node manifests (API contract)" section, the Builder canvas bullet ("the manifest palette replaces them in 5.3") is updated, the database row's "node types" note says manifests are code-defined until 6.6 and 10.1, and decisions rows are added. `CHANGELOG.md` gets an entry.

### Out of scope

- Editing a node's parameters from `parameters` in a side panel (5.4).
- Adding or editing inside containers. A container added from the palette is added whole with its default children, which are drawn read-only (5.5).
- Port compatibility in the manifest and blocking bad connections (5.6). A node's typed ports stay its optional `input_schema` and `output_schema`, which are visible in `parameters`.
- Storing manifests in a `node_types` table, or per workspace (6.6 composites and 10.1 plugins). This phase's manifests are code-defined.
- Tools granted per node through the manifest, and a tool catalogue for the tool node's `tool` field (5.4 and 10.1).
- Drag from the palette onto the canvas, and palette search.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where manifests live | A code registry in `agentic_engine.nodes`, one per `Node` model, served by the API | The engine owns the primitives, so a new primitive and its manifest ship together. A union-coverage test enforces it. No DB until composites and plugins need per-workspace types. |
| How they reach the browser | `GET /node-types` at runtime, not a JSON file built into the web app | A file imported at build time would need a web rebuild for a new primitive, which breaks the Done-when. |
| `parameters` | Derived from the node's Pydantic JSON Schema, minus `type`, `id` and the child slots | One source with the spec schema, so the two never drift. 5.4 renders it with `@rjsf/core`. Child slots are structure, edited through ops, not as params (5.1's `setParam` already refuses them). |
| Defaults | A whole, schema-valid node per manifest. Ids are made fresh on add by a generic walk. | The palette never needs kind-specific code. A test checks each default validates, alone and inside a root sequence. A default may still raise validation issues in context (e.g. a reduce not after a map or parallel). The version is stored with its issues, as 5.1 allows for work in progress. |
| Context-dependent fields | A small closed set of generic `fill` hints (`previous_step`) | Reduce's `from` must name the step before it. One generic hint keeps the palette kind-agnostic without a per-kind branch. |
| Icons | A lucide icon name in the manifest, mapped by a small web lookup with a `box` fallback | Keeps the bundle small. An unknown name still renders, so a new primitive needs no web change, and adding it to the lookup later is cosmetic. |
| Ports | No separate `ports` field yet | Typed ports are per node (optional schemas in `parameters`). A manifest-level port contract waits for live validation (5.6), which will know what it needs. |

## Open questions

- None
