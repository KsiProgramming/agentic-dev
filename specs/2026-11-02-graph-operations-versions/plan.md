# Plan: Graph operations and workflow versions

Engine first (pure, no database), then storage, then the API, then the specs. The repo works after each group.

## 1. Ops model (engine)
- [x] `packages/engine/src/agentic_engine/spec/ops.py`: `AddNode`, `RemoveNode`, `Connect`, `Disconnect`, `SetParam` (frozen, `extra="forbid"`), `Placement` (`After {after}` | `Into {parent, index?, route?}`), `GraphOp` (annotated union on `op`), `GraphOps = list[GraphOp]` (1 to 200 ops).
- [x] `OpErrorCode` literal and `OpError` exception (`code`, `op_index`, `node_id`, `message`): `unknown_node`, `duplicate_node_id`, `root_node`, `invalid_placement`, `slot_taken`, `invalid_move`, `not_in_sequence`, `not_connected`, `not_a_param`, `invalid_path`, `detached_nodes`, `missing_child`, `schema`.
- [x] Re-export from `agentic_engine.spec`; add `graph-ops.v1.json` to `scripts/export_workflow_schema.py` and export it to `schemas/`.

## 2. Apply (engine)
- [x] `apply_ops(spec: Mapping, ops) -> dict`: deep copy as JSON, an index of each id → (parent node, slot, index), a detached pool.
- [x] Each op, on the working tree:
  - `addNode`: ids of the new subtree unique against placed and detached; place by `at` (sequence/parallel insert at `index`; loop/map body, router `then`/`default` only when empty) or detach.
  - `removeNode`: not root; drop the node and its subtree from its slot (a required slot becomes a hole) or from the pool.
  - `connect`: `to` not `from` nor an ancestor of `from` (`invalid_move`); take `to` out of its place (holes as for remove); insert after `from` in its sequence, or wrap `from` in a new sequence `sequence_id` (new id) when `from` is not a sequence step.
  - `disconnect`: `to` follows `from` in a sequence; move `to` to the pool.
  - `setParam`: parse the path (`name(.name|[i])*`), refuse `id`, `type`, `op`-level child slots and paths through them, set or (`null`) unset; document-level `name`/`description` without `node_id`.
- [x] End of batch: pool empty (`detached_nodes`), no holes (`missing_child`: "loop 'revise' has no body"), result passes `validate_workflow`'s schema stage (`schema`, with its first issue's message). Expose a `schema_issues(raw)` helper in `spec/validate.py` rather than duplicating its parse.
- [x] `packages/engine/tests/test_graph_ops.py`: each op on each container kind, error codes, atomicity (input unchanged), JSON Schema export matches `schemas/graph-ops.v1.json`.

## 3. Storage (store + migration)
- [x] `packages/api/alembic/versions/0024_workflows.py`: `workflows`, `workflow_versions`, append-only trigger on `workflow_versions` (as `0019_audit_events`); down drops them.
- [x] `agentic_store/models.py`: `Workflow`, `WorkflowVersion` ORM rows.
- [x] `agentic_store/workflows.py`: `create_workflow`, `get_workflow_version`, `list_workflow_versions`, `update_workflow` (locks the `workflows` row `FOR UPDATE`, checks `base_version`, applies ops, inserts the version, bumps `latest_version`, writes the audit row) with `WorkflowExistsError`, `WorkflowNotFoundError`, `VersionConflictError`; `OpError` passes through.
- [x] `AuditAction` gains `workflow.created`, `workflow.updated`; the web audit formatter learns their one-line details.
- [x] Store tests (Testcontainers): create, update, conflict, versions immutable (UPDATE/DELETE raise), audit rows, workspace scoping.
- [x] `test_migrations.py` covers 0024 up and down.

## 4. API
- [x] `agentic_api/workflows/models.py`: `CreateWorkflowRequest`, `UpdateWorkflowRequest {base_version, ops}`, `WorkflowVersionResponse`, `WorkflowVersionsResponse`, `OpErrorDetail`.
- [x] `agentic_api/workflows/routes.py`: `POST /workflows`, `GET /workflows/{id}`, `GET /workflows/{id}/versions`, `PATCH /workflows/{id}`, workspace via the runs routes' `existing_workspace` dependency; issues from `check_workflow`.
- [x] `packages/api/tests/test_workflows.py`: the four routes, every status code, the Done-when test (PATCH → v2, v1 unchanged).
- [x] `scripts/export_openapi.py` → `web/openapi.json`; `pnpm gen:api`; audit-log formatter for the two new actions (+ its unit test).

## 5. Specs and changelog
- [x] `tech-stack.md`: "Workflows and graph operations (API contract)" section; audit table rows; the validate contract's "until 5.1" note (the id still must match the spec's); decisions log rows (edge model, detached nodes, version validity, concurrency, ops in versions).
- [x] `CHANGELOG.md` entry under `[Unreleased]`.
