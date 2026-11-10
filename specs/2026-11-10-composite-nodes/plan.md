# Plan: `wrap` / `extract` operations; composite nodes (draft → published)

One PR, in this order. The project builds and the tests pass after each group.

## 1. Contract first (specs only)

- [ ] `specs/tech-stack.md` → "Workflows and graph operations":
  - [ ] `wrap {node_ids, with, sequence_id?}` and `extract {node_ids, subflow_id, workflow}`.
  - [ ] New op codes `invalid_wrap` and `invalid_extract`, and at most one `extract` per batch.
  - [ ] Drop "`wrap` and `extract` (6.6)" from "Not yet".
- [ ] New "Composites (API contract)" section:
  - [ ] What a composite is and the draft and published states.
  - [ ] `POST /workflows/{id}/publish` and `GET /workflows/{id}/callers`.
  - [ ] The new `published_version` and `published_at` fields.
  - [ ] The extract transaction.
  - [ ] The palette entries.
  - [ ] Audit actions.
- [ ] "Subflow (API contract)": the `subflow_unpublished` rule, and ports from the called workflow's `input_schema` / `output_schema` (a typed subflow no longer breaks the edge).
- [ ] "Node manifests": category `workspace`, the `composite` field, and `GET /node-types?workspace_id=`.
- [ ] Validation codes list: `subflow_unpublished`.
- [ ] "Builder canvas":
  - [ ] Extract to composite… and Wrap in…, with the range dialog.
  - [ ] Publish version N, and the Draft / Published status line.
  - [ ] Update to version N, and Used by.
  - [ ] The History badge and the Workflows list badge.
- [ ] Database row (node types: composites are stored workflows).
- [ ] Decisions-log rows from `requirements.md`.
- [ ] `specs/roadmap.md`: the `[Plan](2026-11-10-composite-nodes/requirements.md)` link on 6.6.
- [ ] `schemas/graph-ops.v1.json`: regenerate with `scripts/export_workflow_schema.py` once the models land (group 2).

## 2. Engine: spec, ops, validation

- [ ] `agentic_engine/spec/models.py`: `WrapOp` and `ExtractOp` in the ops union. Workflow-level `input_schema` / `output_schema` on the document, with the same checks as a node's (`invalid_schema`, 16 KB, local `$ref`, object root).
- [ ] `agentic_engine/spec/ops.py`:
  - [ ] `wrap`: contiguous-range check, building each kind (sequence, parallel, loop, map, starting from the manifest `default`), id checks.
  - [ ] `extract`: contiguous range or a single node, and the boundary check (reduce `from`, publisher `from_node`, CEL `results.<id>` identifiers in both directions).
  - [ ] The new document's root, `input` and port schemas.
  - [ ] Put the `subflow` (`workflow: {id, version: 1}`) in place of the range.
  - [ ] `apply_ops` returns the extracted document beside the spec (`OpsResult.extracted`).
- [ ] `agentic_engine/spec/subflows.py` / `validate.py`:
  - [ ] The resolver also reports publication state, so `subflow_unpublished` can be found for a composite's unpublished version.
  - [ ] `port_mismatch` reads a subflow's ports from its resolved workflow.
- [ ] Compiler: check the subflow's input and output against the called workflow's schemas at its boundary, with the existing port errors and `node_failed.port`.
- [ ] `agentic_engine/nodes`: `composite_manifest(workflow, version)` builds a workspace manifest (`kind: subflow`, category `workspace`, `composite`, a pinned `default`).
- [ ] `schemas/fixtures/graph-ops.json`: wrap and extract cases (every kind, every refusal, the extracted document). `port-checks.json`: typed subflow cases.
- [ ] Tests:
  - [ ] `test_ops_wrap.py` and `test_ops_extract.py`.
  - [ ] Validation tests for `subflow_unpublished` and the typed subflow edge.
  - [ ] A compile test for the boundary port check.
  - [ ] An engine test that asserts an extracted node's agent receives the same instructions, input and tools as before extraction (lessons rule 1).

## 3. Store and API

- [ ] Alembic `0027_workflow_publications`: `(workspace_id, workflow_id, version, published_at)`, primary key `(workspace_id, workflow_id, version)`, with a trigger that refuses `UPDATE` and `DELETE` (as `0024`).
- [ ] `agentic_store/workflows.py`:
  - [ ] `publish_version` (issues → refuse, `already_published`).
  - [ ] `published_version` on the summaries.
  - [ ] `published_at` on versions.
  - [ ] `list_callers`.
  - [ ] `apply_patch` writes an extracted workflow (version 1) and the caller's version in one transaction, refusing `workflow_exists`.
  - [ ] Audit `workflow.published`, and `workflow.created` with `extracted_from`.
- [ ] `agentic_store/subflows.py`: the loader returns publication state for each version it loads.
- [ ] `agentic_api/workflows`: `POST /workflows/{id}/publish` and `GET /workflows/{id}/callers`. Fields on the existing answers. `PATCH` answers with the extracted workflow's id and version.
- [ ] `agentic_api/node_types`: `?workspace_id=` adds the composite manifests.
- [ ] Regenerate the OpenAPI spec and the web's generated client.
- [ ] Tests (Postgres): publish rules, refusing a version with issues, the extract transaction (rollback when the id exists or a later op fails), callers, the palette entries, and `POST /runs` refusing an unpublished composite version while a never-published workflow still runs.

## 4. Web: ops mirror and builder

- [ ] `@/workflows/ops`: `wrap` and `extract` mirrored, passing the shared `graph-ops.json` cases (`ops.test.ts`).
- [ ] `@/workflows/edits`:
  - [ ] Range helpers (`laterSteps`, `rangeOf`).
  - [ ] `stayReason` and `blockReason` for wrap and extract (port check through typed subflows in `@/workflows/ports`).
- [ ] Builder card menu: **Extract to composite…** and **Wrap in…** with the range dialog (Dialog, select of later steps, name, id slug, description; field errors as in 5.8). Focus goes to the new subflow or container card.
- [ ] Palette (`@/workflows/node-types`): a "Workspace nodes" group from the manifests with category `workspace`. Leave out the workflow being edited. Show loading, empty and error rows.
- [ ] Subflow card: "· version N is published" and **Update to version N** (one `setParam`).
- [ ] Builder header:
  - [ ] **Publish version N** with a confirm dialog naming the callers.
  - [ ] Status line "Draft" / "Published version N".
  - [ ] **Used by** list (loading, empty "No workflow calls this one yet.", error with Retry).
- [ ] History: a "Published" `DiffBadge`-style neutral badge. Workflows list: a "Composite" badge and the published version (table and cards).
- [ ] Workflow panel: "Inputs and outputs" (advanced) with `input_schema` / `output_schema` as JSON fields.
- [ ] Unit tests for each of the above (`builder.test.tsx`, `edits.test.ts`, `node-types.test.tsx`, `history`, `workflows-view.test.tsx`).

## 5. End to end, real run, docs

- [ ] `web/e2e/composite.spec.ts`, the AC-3 journey:
  1. Extract 2–3 steps of workflow A into "Security review" and save.
  2. Publish version 1.
  3. Add it to workflow B from "Workspace nodes", save, and run on the fake runtime: its steps are nested under the subflow.
  4. Edit the composite and publish version 2. B's card offers Update to version 2.
  5. Update, save, and run again: the console shows version 2.
- [ ] Add the new dialogs and the Used by list to `a11y.spec.ts` / `layout.spec.ts` at 375 and 1440 px, light and dark.
- [ ] Real run with Claude (`AGENTIC_RUNTIME=claude`) of workflow B on a real repo, read step by step in the console's Activity tab. Record what each agent in the composite received. Add a `specs/lessons.md` entry if anything differs from the inline version.
- [ ] `docs/architecture/business-flows.md` (composites no longer planned), `CHANGELOG.md` under `[Unreleased]`.
