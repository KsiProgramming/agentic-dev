# Validation: Graph operations and workflow versions

## Done when (from roadmap)
> Applying ops produces a new immutable version

## Automated checks
- [ ] Engine (`packages/engine/tests/test_graph_ops.py`):
  - [ ] `addNode` into a sequence (at `index`, after a node), a parallel branch, an empty loop/map body, a router route's `then` and `default`; detached then `connect`ed in the same batch.
  - [ ] `removeNode` of a step (neighbours join), of a container with its subtree, of a detached node; the root is refused (`root_node`); removing a loop body leaves `missing_child`.
  - [ ] `connect` moves a placed node with its subtree; wraps a non-sequence `from` with `sequence_id`, refused without it (`not_in_sequence`); `to` an ancestor of `from` is `invalid_move`.
  - [ ] `disconnect` of consecutive steps (the next step joins `from`), `not_connected` otherwise; left detached at the end → `detached_nodes`.
  - [ ] `setParam` sets and unsets (`null`) a field, a nested path (`classifier.instructions`, `routes[0].when`), the document's `name`; `id`, `type` and child slots are `not_a_param`; a bad path is `invalid_path`; a value off the schema is `schema`.
  - [ ] Duplicate ids (`duplicate_node_id`), unknown ids (`unknown_node`), placement into a taken slot (`slot_taken`) or a non-container (`invalid_placement`).
  - [ ] Atomic: a failing op at index 2 leaves the input spec unchanged and names `op_index: 2`.
  - [ ] `schemas/graph-ops.v1.json` matches the exported model.
- [ ] Store (Testcontainers Postgres):
  - [ ] create → version 1; update → version 2 with `base_version` 1 and its ops; version 1's row is byte-for-byte unchanged.
  - [ ] Stale `base_version` raises `VersionConflictError`; an `OpError` stores nothing.
  - [ ] `UPDATE` and `DELETE` on `workflow_versions` raise.
  - [ ] `workflow.created` / `workflow.updated` audit rows are written with the version, not the spec.
  - [ ] A workflow in one workspace is not seen from another.
- [ ] API (`packages/api/tests/test_workflows.py`):
  - [ ] `POST /workflows` `201`, again `409 workflow_exists`, bad spec `422`.
  - [ ] `PATCH /workflows/{id}` `201` with `version: 2` and `issues`; `GET ?version=1` returns the old spec; `GET /versions` lists 2 then 1.
  - [ ] `409 version_conflict`, `422` with `op_index`, `404` unknown workflow and workspace.
  - [ ] A version with structure issues (e.g. a loop over the workspace limit) is stored and its `issues` returned.
- [ ] `test_migrations.py` runs 0024 up and down.
- [ ] Web: audit formatter unit test for the two new actions; `pnpm lint && pnpm typecheck && pnpm test` after regenerating `schema.d.ts`.
- [ ] `uv run ruff check`, `uv run pyright` (strict), `uv run pytest`.

## Manual / demo checks
- [ ] None beyond the tests (the API tests are the demo: create, patch, read both versions).

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] `tech-stack.md` has the API contract and decisions rows; the validate note is updated.
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`.
- [ ] No spec content in audit rows or logs.
