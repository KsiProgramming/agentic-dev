# Plan: Node manifests and a palette generated from them

Order: engine registry, then API, then web. The app keeps working after each group. The web keeps its hard-coded menu until group 4 swaps it.

## 1. Manifest model and registry (engine)

- [x] `packages/engine/src/agentic_engine/nodes.py` (or a `nodes/` package):
  - `NodeManifest` (Pydantic, `_Base` config): `kind`, `label`, `description`, `category` (`Literal["step", "flow", "combine"]`), `icon`, `parameters`, `slots: list[Slot]` (`{name, shape: "one" | "list" | "route_then"}`), `default: Node`, `fill: dict[Literal["previous_step"], str]`
  - `NODE_MANIFESTS` (palette order), `manifest_for(kind)`
- [x] `parameters_schema(model)`: `model.model_json_schema()` with `type`, `id` and the slot fields dropped from `properties` and `required`. `$defs` that are no longer referenced are pruned.
- [x] The 9 manifests with the defaults from requirements.md, each a validated `Node` instance (so a bad default fails at import).
- [x] Re-export from `agentic_engine` (or `agentic_engine.spec`, matching how `GraphOps` is exposed).
- [x] `packages/engine/tests/test_nodes.py`:
  - each member of the `Node` union has exactly one manifest
  - each `default` validates alone and as the only step of a root `sequence`
  - `parameters` never names `type`, `id` or a slot
  - every slot named exists on the model and holds nodes
  - each `fill` target is a parameter
  - kinds are unique and the order is stable

## 2. API

- [x] `packages/api/src/agentic_api/node_types/routes.py`: `GET /node-types` (`operation_id="listNodeTypes"`, tag `node-types`) returns `list[NodeManifest]`, registered in `app.py`.
- [x] `packages/api/tests/test_node_types.py`: `200`, the order and kinds match the registry, the agent manifest's `parameters` has `role` and `instructions` and lacks `id`, and the response matches the OpenAPI model.
- [x] `uv run python scripts/export_openapi.py`, then `cd web && pnpm gen:api` (regenerates `web/openapi.json` and `src/api/schema.d.ts`).

## 3. Web: manifest data and kind-agnostic helpers

- [x] `web/src/workflows/node-types.tsx`:
  - `useNodeTypes()` (TanStack Query, `staleTime: Infinity`)
  - `manifestIcon(name)` (a small lucide lookup with a `BoxIcon` fallback)
  - `paletteGroups(manifests)` (by category, in order, with group labels "Steps", "Flow", "Combine", and an unknown category last as "Other")
- [x] `edits.ts`:
  - replace `NEW_KINDS` and `newNode(spec, kind)` with `newNodeFrom(spec, manifest, afterId)`: a deep copy of `default` with fresh ids for every nested node (walk any object with a manifest `type` and an `id`; route ids untouched), plus `fill.previous_step`
  - `addStep(spec, afterId, manifest)` keeps returning one `addNode` edit
- [x] Unknown kinds:
  - `node-kinds.tsx`: `KindIcon` and `kindLabel` take an optional manifest fallback and never throw on an unknown kind
  - `spec-graph.ts`: `nodeDetail` returns `""` by default. Fresh ids walk the spec through the manifests' `slots` in `edits.ts` (no module-level cache).
- [x] Unit tests:
  - `node-types.test.ts`: grouping, icon fallback
  - `edits.test.ts`:
    - fresh ids for a nested default (parallel, router), with no clash with existing ids
    - `previous_step` fill
    - an unknown kind from a fake manifest becomes a valid `addNode`
  - `spec-graph.test.ts` and `run-map.test.tsx`: an unknown kind renders as a card with the fallback icon and label

## 4. Web: palette in the builder

- [x] `builder.tsx`: "Add a step after" becomes a submenu. `AddItems` and `AddMenu` render `paletteGroups(useNodeTypes().data)`:
  - `DropdownMenuLabel` per group and a `DropdownMenuSeparator` between groups
  - each item has its icon (`aria-hidden`), label and description (`text-muted-foreground`, `text-caption`)
  - rows for loading (`Loading node types…`), error (message and a Retry item) and empty (`No node types available`)
- [x] The menus still work from the keyboard. The trigger labels ("Add a step after", "Add first step") are unchanged.
- [x] `builder.test.tsx`:
  - the palette lists a mocked `/node-types` grouped, including a fake kind `echo` the web has never heard of
  - choosing it applies an `addNode` with `echo_1`, and Save sends it
  - choosing parallel adds two agent branches with fresh ids
  - loading, error with Retry, and empty
- [x] The builder tests answer `GET /node-types` with `schemas/fixtures/node-types.json`, written by `scripts/export_workflow_schema.py`. An engine test fails when it is stale.

## 5. Specs, changelog, demo

- [x] `specs/tech-stack.md`:
  - new "Node manifests (API contract)" section (model, registry, `GET /node-types`, `parameters` derivation, `slots`, `default`, `fill`, icon fallback)
  - Builder canvas bullet: the palette replaces the hard-coded kinds
  - Database row: node types are code-defined until 6.6 and 10.1
  - decisions log rows from requirements.md
- [x] `CHANGELOG.md` under `## [Unreleased]`.
- [ ] Manual demo (validation.md): register a throwaway primitive on a scratch branch, restart the API, and see it in the palette with `web/` untouched. Revert it.
