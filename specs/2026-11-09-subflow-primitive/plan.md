# Plan: `subflow` primitive

Contract first, then engine, then web (interview choice). The repo stays green after each group.

**Changed while building** (see requirements → Decisions): a child's clashing ids are renamed `<subflow>-<id>` instead of every id being scoped, the child's events carry no `subflow` tag, and `GET /runs/{id}` returns `calls` (each call's root as it runs) instead of the raw copies. Items below that named the old shapes are done in the new one.

## 1. Contract: spec model, manifest, tech-stack
- [x] `packages/engine/src/agentic_engine/spec/models.py`: add `SubflowNode` (`type: "subflow"`, `id`, `workflow: {id: NodeId-like workflow id, version: int ≥ 1}`, `input: str | None`, a CEL expression) to the `Node` union. Re-export the JSON Schema (`scripts/export_workflow_schema.py`).
- [x] `agentic_engine/nodes.py`: add the `subflow` manifest (category `flow`, icon, no slots, `default` with a placeholder ref, `ui` with `workflow: {"ui:field": "workflow_ref"}`). Regenerate `schemas/fixtures/node-types.json`.
- [x] Move `packages/engine/tests/fixtures/specs/invalid/unknown-node-type.json` off `subflow` (use a type that will never exist).
- [x] `specs/tech-stack.md`:
  - a new "Subflow (API contract)" section (spec, resolution and snapshot, scoping, validation, events, compile and resume, where it is allowed, in the web);
  - add `subflow_unknown` and `subflow_cycle` to the validation codes;
  - add `subflows` to `GET /runs/{id}` in the run history contract;
  - Node manifests: the `workflow_ref` field;
  - decisions log rows (inline execution, pinned version, snapshot column, expanded-tree validation).

## 2. Validation with a resolver
- [x] `agentic_engine/spec/validate.py`:
  - `validate_workflow(..., resolve: Callable[[str, int], dict | None] = no_subflows)`, with `expand_subflows(root, resolve)` returning the expanded tree plus `subflow_unknown` and `subflow_cycle` issues (the call path is tracked by workflow id).
  - Run the existing structure, policy, port and artifact checks on the expanded tree. Map issues found inside a child back to the subflow node, with the prefix "in workflow '<id>' version <n>: ".
- [x] `agentic_engine/policy.py`: a subflow is a level of `max_depth`. `agents_spawned` and the other counts include the child.
- [x] Add `subflow` to the `not_allowed_in_orchestrator` kinds.
- [x] `ops.py`: `subflow` is a leaf. `setParam` on `workflow`, `workflow.version` and `input`. Add cases to `schemas/fixtures/graph-ops.json`, and a port-check case showing a subflow breaks the edge in `port-checks.json`.
- [x] Tests (`packages/engine/tests/`): unknown workflow, unknown version, direct and indirect cycles, depth over the limit, a child with a gate called from a map (refused, on the subflow), a child's `unknown_tool` re-pathed, id clashes allowed, and artifacts across the call (parent reads what the child writes).

## 3. Store and API: resolve, snapshot, expose
- [x] Alembic `packages/api/alembic/versions/0026_run_subflows.py`: `runs.subflows JSONB NULL`.
- [x] `agentic_store/workflows.py`: `resolver(session, workspace_id)` returning `resolve(id, version)` over `workflow_versions`.
- [x] `agentic_api/runs/routes.py` (`POST /runs`, rerun): resolve the subflows of the run's spec (inline, template or stored), refuse with `422` and the issues on failure, and store `runs.subflows`. Rerun copies the snapshot.
- [x] `agentic_api/workflows`: `POST /workflows/{id}/validate` and the stored-version `valid`/`issues` use the workspace resolver.
- [x] `GET /runs/{id}`: add `calls` (each call's root as it runs). Regenerate the OpenAPI client for the web.
- [x] Integration tests (Testcontainers Postgres): a stored parent calling a stored child by id+version, the run's snapshot, a `422` for a missing version, and a rerun keeping the snapshot.

## 4. Engine: compile, run, events, resume
- [x] `agentic_engine/graph/compile.py`: a subflow at the top of a run compiles to an entry node `<id>` (`node_started` with `workflow`, then `input`), the called root, and `<id>.done` (`node_completed` with the called workflow's output and `data`). Inside a map item or parallel branch it runs in-process (`_subflow_inline`).
- [x] `input` is a CEL value (`compile_value`) over `last`, `results` and `artifacts`. Without it, the subflow's input passes through.
- [x] Ids: a called node whose id the run already has runs as `<subflow>-<id>`, with its references renamed. Its expressions read `results` by its own ids (`expression_views` on `_Limits.views`).
- [x] Worker: `run_spec` expands `runs.spec` from `runs.subflows` when a run is loaded, so compile, writers and the repo checks see the called nodes.
- [x] Tests on the fake runtime (`test_subflow.py`): a parent calling a child end to end, with ordered events and the call's `node_started` payload; `input` mapping and its failure; a child gate pausing and resuming; a run cut off inside the child resuming there (AC-8); a failure inside the child ending the run; a subflow in a map; a child loop reading its own `x` while it runs as `call-x`.
- [x] A child writer committing on its own branch (`agent/<run>/<run id>`), with a gate in the caller showing it.
- [x] `test_subflow_fixture.py` writes and checks `schemas/fixtures/subflow-run.json` (`UPDATE_FIXTURES=1`).

## 5. Web: palette, side panel, canvas
- [x] `web/src/workflows/form/theme`: a `workflow_ref` field: a combobox of `GET /workflows` (this workflow left out, so a direct self-call cannot be picked; deeper cycles are the live check's), then a version select from `GET /workflows/{id}/versions` (newest first, "Latest" badge), and an "Open workflow" link. It has loading, empty ("No other workflows yet.") and error with Retry states.
- [x] `@/workflows/ops.ts` mirror: subflow is a leaf (from the shared fixture).
- [x] `node-kinds.tsx` / builder: the subflow card says "Calls <name> · version N" and "· version M is the latest" when newer (from `GET /workflows`' `latest_version`); the link to the called version is the side panel's "Open workflow" (a card holds no second link). Live issues show on the card as for any node.
- [x] Vitest: the field (pick, version default, readonly on an old version) and the ops mirror cases. The card's line is checked in the e2e test.

## 6. Web: run console and run map
- [x] `@/runs/timeline.ts`: the subflow step holds the called steps (`Step.subflow`), placed by `specParents` over the spec with `calls` attached (`withCalls`, `@/runs/calls`); step keys `<subflow>/<run id>`.
- [x] Step list: child steps nested under the subflow. The subflow's line reads "Calls docs · version 3", then "4 of 6 steps".
- [x] Output (the child's answer), Input (workflow and version linked, the `input` expression in mono), Usage (the child's steps' tokens and cost).
- [x] Run map (`run-map.tsx`): the child's tree hangs off the subflow card from the snapshot, with the same status dots and selection.
- [x] Vitest from `subflow-run.json`: folding, keys, nesting, the one-liners, the totals (subflow cost = sum of its child's steps), and older runs unchanged.

## 7. End to end, docs, changelog
- [ ] Playwright e2e (`web/e2e/subflow.spec.ts`, written, not run yet, against the e2e stack with fakes): create child and parent workflows, add a subflow to the child on the canvas through the picker, save, run the parent, and see the child's steps under the subflow in the console and the map.
- [ ] Add the builder and console with a subflow to `a11y.spec.ts` / `layout.spec.ts` (375, 768, 1440; light and dark).
- [x] `docs/architecture/overview.md`, `decisions.md`, `business-flows.md`: subflow is no longer "planned".
- [x] `specs/roadmap.md`: add the `[Plan]` link on 6.5.
- [x] `CHANGELOG.md`: add an entry under `## [Unreleased]`.
