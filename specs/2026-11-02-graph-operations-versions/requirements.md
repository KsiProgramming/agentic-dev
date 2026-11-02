# Graph operations and workflow versions

Roadmap phase: 5.1
Branch: plan/5.1-graph-operations-versions

## Context

Done when: **applying ops produces a new immutable version.**

Milestone 5 (builder canvas) starts here. Today nothing stores a workflow: a run carries its spec inline (`runs.spec`), templates build specs in code, and `POST /workflows/{id}/validate` only checks a spec it is sent ("until 5.1 stores workflows, `{id}` must equal the spec's `id`"). This phase adds the stored, versioned workflow and the one way to change it: a batch of graph operations.

Mission principle 1, **one spec, many views**, is the reason: the canvas (5.2), the side panel (5.4), the Architect (`propose_ops`, 9.3) and version history (5.7) all change a workflow through the same ops, so undo, diffs and audit come for free. Principle 6 (transparency) and the audit log pattern (3.7) give the audit rows; the append-only `run_events` / `audit_events` pattern gives immutable versions.

Note: the roadmap's "Next up" line names 4.8, which is not planned yet. 5.1 was picked on purpose by the user; it does not depend on 4.8. It depends only on what is done: the spec models (0.2 onwards, `agentic_engine.spec`), the one validator (3.4, `validate_workflow`) and the audit log (3.7).

It unblocks 5.2 (the canvas emits ops), 5.4 (side panel emits `setParam`), 5.7 (history, diff, restore, run a version), 6.6 (`wrap` / `extract` are more ops) and 9.3 (the Architect's graph-ops schema).

### The spec is a tree

A workflow spec is a tree (`root` holds a `sequence`, `parallel` branches, a `loop`/`map` body, a router's routes), not a list of nodes and edges. The ops keep it that way (one spec, no second representation):

- **Nodes are addressed by id** (ids are unique in a spec, `duplicate_node_id`).
- **An edge is sequence order:** `from → to` means `to` is the step right after `from` in a `sequence`. That is what the canvas draws as an arrow between two steps; a container's children hang off it, as in the run map.
- **A batch may detach nodes while it runs** (a new node not placed yet, a node taken out by `disconnect`) but nothing may be left detached at its end.

## Scope

### In scope

- **Ops model** (`agentic_engine.spec.ops`, Pydantic, discriminated on `op`, exported as JSON Schema `schemas/graph-ops.v1.json`):
  - `addNode {node, at?}`: add a node (a leaf, or a container with its children; every id in it new). `at` places it: `{after: <id>}` (the step after a node in its sequence) or `{parent: <id>, index?, route?}` (a sequence's step or a parallel's branch at `index`, default last; a loop's or map's empty body; a router route's empty `then`, or `route: "default"`). No `at`: detached.
  - `removeNode {node_id}`: remove a node and everything under it (placed or detached). Its sequence's neighbours join up. Not the root.
  - `connect {from, to, sequence_id?}`: place `to` (detached, or moved from where it is, with its subtree) right after `from`. If `from` is not a step of a sequence (a loop body, a branch, a route, the root), `sequence_id` names a new sequence that wraps `from` and gets `to` after it; without it the op is refused (`not_in_sequence`).
  - `disconnect {from, to}`: `to` must be the step right after `from` (`not_connected` otherwise). `to` and its subtree are detached; the step after `to`, if any, now follows `from`.
  - `setParam {node_id?, path, value}`: set one parameter of a node, at a path in the issues' style (`instructions`, `classifier.instructions`, `routes[1].when`); `value: null` unsets it. Never `id`, `type` or a child slot (`steps`, `body`, `branches`, `then`, `default`): those change through the other ops (`not_a_param`). Without `node_id` it targets the document: `name`, `description`.
- **Apply** (`apply_ops(spec, ops) -> spec`): pure, on a copy, atomic. The first op that cannot apply refuses the whole batch with `OpError {code, op_index, node_id, message}`; the result must parse as a spec (`schema` issues of `validate_workflow` refuse it too).
- **Storage** (Alembic `0024_workflows`): `workflows` (`workspace_id`, `id`, `latest_version`, `created_at`, `updated_at`; key `(workspace_id, id)`) and the append-only `workflow_versions` (`workspace_id`, `workflow_id`, `version` 1, 2, …, `spec`, `base_version`, `ops` — the batch that made it, `null` for version 1 — `created_at`; a trigger refuses `UPDATE` and `DELETE`).
- **API** (workspace from `?workspace_id=`, default workspace otherwise, as `GET /runs`):
  - `POST /workflows {spec}` → `201` version 1. `409` `workflow_exists`; `422` when the spec does not parse.
  - `GET /workflows/{id}` → the latest version (`?version=n` for another): `{workflow_id, version, base_version, created_at, spec, issues}`.
  - `GET /workflows/{id}/versions` → `{items}` newest first: `version`, `base_version`, `created_at`, `op_count` (no spec).
  - `PATCH /workflows/{id} {base_version, ops}` → `201` the new version, with its `issues`. `409` `version_conflict` when `base_version` is not the latest; `422` `{code, op_index, node_id, message}` for a batch that cannot apply; `404` unknown workflow or workspace.
- **Issues are returned, not blocking:** a version must parse as a spec; its structure and policy issues (`validate_workflow` under the workspace's limits) come back with it. The canvas shows them (5.6); `POST /runs` still refuses a spec with issues.
- **Audit:** `workflow.created` (`version`) and `workflow.updated` (`version`, `base_version`, `op_count`, the ops' kinds), in the same transaction. Never spec content.
- Web: regenerate `web/src/api/schema.d.ts`; the audit log shows the two new actions under a new "Workflows" filter category. No other screen changes.
- Specs: a "Workflows and graph operations (API contract)" section and decisions log rows in `tech-stack.md`; the validate contract's "until 5.1" note updated; `CHANGELOG.md`.

### Out of scope

- The canvas and anything in the web UI (5.2), side panel forms (5.4), live validation on the canvas (5.6).
- Adding or removing router routes and renaming node ids (later ops; a route's `when` and `description` are `setParam`).
- Running a stored version, history UI, visual diff and restore (5.7). `POST /runs` keeps taking a spec.
- `wrap` / `extract` and composites, draft → published (6.6).
- Deleting a workflow, listing a workspace's workflows (comes with the start screen, 5.8), and moving templates into stored workflows.
- Users and who made a version (`actor_id` stays `NULL`, as in the audit log).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Edge model | Ops over the tree; an edge is sequence order; nodes addressed by id | One spec (mission 1): the engine, validator and run map already read the tree. A nodes + edges form would be a second representation to keep in sync. |
| Detached nodes | Allowed inside a batch, refused at its end (`detached_nodes`) | The canvas's "drop a node, then draw the edge" is one batch, and every stored version is still a complete spec. |
| What a version must satisfy | Parse as a spec; other issues returned with it | An editor saves work in progress (a port mismatch, an over-limit loop) and shows what to fix; runs still refuse it, so nothing unsafe runs (mission 2). |
| Concurrency | `base_version` must be the latest, else `409` | Two editors (or the canvas and the Architect) never overwrite each other silently; the client rebases its ops. |
| Ops in the version row | Each version keeps the batch that made it and its base | Undo, diff and history (5.7) and the Architect's edit distance (9.x) read them; the spec alone cannot say what changed. |
| Immutability | Append-only `workflow_versions`, enforced by a trigger | Same pattern as `audit_events`: a version never changes, so a run of version 3 can always be explained. |
| Ops are plain JSON, not JSON Patch | `{op, …}` objects in a list | JSON Patch addresses array positions, which shift as the tree changes; ids do not. The Architect gets a small typed schema. |

## Open questions

- None
