# Plan: `subflow` primitive

Contract first, then engine, then web (interview choice). The repo stays green after each group.

## 1. Contract: spec model, manifest, tech-stack
- [ ] `packages/engine/src/agentic_engine/spec/models.py`: add `SubflowNode` (`type: "subflow"`, `id`, `workflow: {id: NodeId-like workflow id, version: int ≥ 1}`, `input: str | None`, a CEL expression) to the `Node` union. Re-export the JSON Schema (`scripts/export_workflow_schema.py`).
- [ ] `agentic_engine/nodes.py`: add the `subflow` manifest (category `flow`, icon, no slots, `default` with a placeholder ref, `ui` with `workflow: {"ui:field": "workflow_ref"}`). Regenerate `schemas/fixtures/node-types.json`.
- [ ] Move `packages/engine/tests/fixtures/specs/invalid/unknown-node-type.json` off `subflow` (use a type that will never exist).
- [ ] `specs/tech-stack.md`:
  - a new "Subflow (API contract)" section (spec, resolution and snapshot, scoping, validation, events, compile and resume, where it is allowed, in the web);
  - add `subflow_unknown` and `subflow_cycle` to the validation codes;
  - add `subflows` to `GET /runs/{id}` in the run history contract;
  - Node manifests: the `workflow_ref` field;
  - decisions log rows (inline execution, pinned version, snapshot column, expanded-tree validation).

## 2. Validation with a resolver
- [ ] `agentic_engine/spec/validate.py`:
  - `validate_workflow(..., resolve: Callable[[str, int], dict | None] = no_subflows)`, with `expand_subflows(root, resolve)` returning the expanded tree plus `subflow_unknown` and `subflow_cycle` issues (the call path is tracked by `<id>@<version>`).
  - Run the existing structure, policy, port and artifact checks on the expanded tree. Map issues found inside a child back to the subflow node, with the prefix "in workflow '<id>' version <n>: ".
- [ ] `agentic_engine/policy.py`: a subflow is a level of `max_depth`. `agents_spawned` and the other counts include the child.
- [ ] Add `subflow` to the `not_allowed_in_orchestrator` kinds.
- [ ] `ops.py`: `subflow` is a leaf. `setParam` on `workflow`, `workflow.version` and `input`. Add cases to `schemas/fixtures/graph-ops.json`, and a port-check case showing a subflow breaks the edge in `port-checks.json`.
- [ ] Tests (`packages/engine/tests/`): unknown workflow, unknown version, direct and indirect cycles, depth over the limit, a child with a gate called from a map (refused, on the subflow), a child's `unknown_tool` re-pathed, id clashes allowed, and artifacts across the call (parent reads what the child writes).

## 3. Store and API: resolve, snapshot, expose
- [ ] Alembic `packages/api/alembic/versions/0026_run_subflows.py`: `runs.subflows JSONB NULL`.
- [ ] `agentic_store/workflows.py`: `resolver(session, workspace_id)` returning `resolve(id, version)` over `workflow_versions`.
- [ ] `agentic_api/runs/routes.py` (`POST /runs`, rerun): resolve the subflows of the run's spec (inline, template or stored), refuse with `422` and the issues on failure, and store `runs.subflows`. Rerun copies the snapshot.
- [ ] `agentic_api/workflows`: `POST /workflows/{id}/validate` and the stored-version `valid`/`issues` use the workspace resolver.
- [ ] `GET /runs/{id}` summary: add `subflows`. Regenerate the OpenAPI client for the web.
- [ ] Integration tests (Testcontainers Postgres): a stored parent calling a stored child by id+version, the run's snapshot, a `422` for a missing version, and a rerun keeping the snapshot.

## 4. Engine: compile, run, events, resume
- [ ] `agentic_engine/graph/compile.py`: compile a subflow at the top of a run as entry node `<id>` (logs `node_started` with `workflow`), then the child's root compiled under scope `<id>/` (graph node names prefixed), then `<id>.done` (`node_completed` with the child's output and `data`). Inside a map item or parallel branch, run it in-process with `_run_inline`.
- [ ] `input` CEL evaluated over `ROUTE_VARIABLES` plus `input`. Without it, the subflow's input passes through.
- [ ] Event scoping: every child event carries `subflow: [<ids>]`. Writer keys inside the child are `<subflow>.<node>` (as `task_writer_key`). Branch, gate review and `FileEdit.node_id` take the key.
- [ ] `graph/run.py` / worker: build the compiled graph from `runs.spec` plus `runs.subflows`.
- [ ] Tests on the fake runtime:
  - a 2-node parent calling a 2-node child end to end, with ordered, tagged events;
  - a child with a gate pausing and resuming;
  - a worker kill inside the child resuming after its last completed node (AC-8 holds);
  - a failure inside the child failing the subflow and naming the child's step;
  - a child writer committing on `agent/<run>/<subflow>.<node>`.
- [ ] `test_subflow_fixture.py` writes and checks `schemas/fixtures/subflow-run.json` (`UPDATE_FIXTURES=1`).

## 5. Web: palette, side panel, canvas
- [ ] `web/src/workflows/form/theme`: a `workflow_ref` field: a combobox of `GET /workflows` (this workflow left out, so a direct self-call cannot be picked; deeper cycles are the live check's), then a version select from `GET /workflows/{id}/versions` (newest first, "Latest" badge), and an "Open workflow" link. It has loading, empty ("No other workflows yet.") and error with Retry states.
- [ ] `@/workflows/ops.ts` mirror: subflow is a leaf (from the shared fixture).
- [ ] `SpecTree` / `node-kinds.tsx`: the subflow card says "Calls <name> · version N" (id in mono), a link to `/workflows/<id>?version=N`, and "Version M is the latest" in `muted-foreground` when newer (from `GET /workflows`' `latest_version`). Live issues show on the card as for any node.
- [ ] Vitest: the field (pick, version default, readonly on an old version), the card, and the ops mirror cases.

## 6. Web: run console and run map
- [ ] `@/runs/timeline.ts`: fold events with a `subflow` tag under the subflow step, with keys `<subflow>/<node>`. `specParents` places them using `subflows` from `GET /runs/{id}`.
- [ ] Step list: child steps nested under the subflow. The subflow's line reads "Calls docs · version 3", then "4 of 6 steps".
- [ ] Output (the child's answer), Input (workflow and version linked, the `input` expression in mono), Usage (the child's steps' tokens and cost).
- [ ] Run map (`run-map.tsx`): the child's tree hangs off the subflow card from the snapshot, with the same status dots and selection.
- [ ] Vitest from `subflow-run.json`: folding, keys, nesting, the one-liners, the totals (subflow cost = sum of its child's steps), and older runs unchanged.

## 7. End to end, docs, changelog
- [ ] Playwright e2e (`web/e2e/subflow.spec.ts`, against the e2e stack with fakes): create child and parent workflows, add a subflow to the child on the canvas through the picker, save, run the parent, and see the child's steps under the subflow in the console and the map.
- [ ] Add the builder and console with a subflow to `a11y.spec.ts` / `layout.spec.ts` (375, 768, 1440; light and dark).
- [ ] `docs/architecture/overview.md`, `decisions.md`, `business-flows.md`: subflow is no longer "planned".
- [ ] `specs/roadmap.md`: add the `[Plan]` link on 6.5.
- [ ] `CHANGELOG.md`: add an entry under `## [Unreleased]`.
