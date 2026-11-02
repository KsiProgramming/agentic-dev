# Plan: Versions: history, visual diff, restore, run any version

API first, then the web. The repo works after each group.

## 1. Storage
- [x] `packages/api/alembic/versions/0025_workflow_restore.py`: `workflow_versions.restored_from` (int, null), `runs.workflow_id` (text, null), `runs.workflow_version` (int, null); down drops them. The append-only trigger is untouched.
- [x] `agentic_store/models.py`: the three columns; `StoredWorkflowVersion.restored_from`.
- [x] `agentic_store/workflows.py`: `restore_workflow(sessions, workspace_id, workflow_id, base_version, version)`: lock the workflow `FOR UPDATE`, check `base_version` (`VersionConflictError`), `version` exists (`WorkflowNotFoundError`) and is not the latest (`AlreadyLatestError`), insert the copy, bump `latest_version`, audit `workflow.restored`.
- [x] `AuditAction` gains `workflow.restored`; web audit formatter's one-line detail ("Restored version 2 as version 6").
- [x] Runs store: `create_run` takes `workflow_version=(id, n)`; rerun copies it; summaries read it.
- [x] Store tests (Testcontainers): restore makes N+1 with the old spec and `restored_from`, older rows unchanged, stale base, unknown version, latest refused, audit row; a run with a ref keeps it, its rerun too.
- [x] `test_migrations.py`: 0025 up and down.

## 2. API
- [x] `agentic_api/workflows`: `RestoreWorkflowRequest {base_version, version}`; `POST /workflows/{id}/restore` (`restoreWorkflow`): 201, 404, 409 `version_conflict`, 422 `already_latest`; `restored_from` on `WorkflowVersionResponse` and `WorkflowVersionItem`.
- [x] `agentic_api/runs/models.py`: `StoredWorkflowRun {id, version?}`; `CreateRunRequest.stored_workflow`, exactly one of `workflow`, `template`, `stored_workflow`, its spec checked once read (`with_spec`); `WorkflowRef.version` on the summaries.
- [x] `agentic_api/runs/routes.py`: resolve the ref (`get_workflow_version`, 404 when unknown), run its spec through the same checks, store the resolved version.
- [x] `packages/api/tests/test_workflows.py` (restore) and `test_runs.py` (by reference: latest and a given version, 404, a version with issues 422, summary and rerun carry the ref).
- [x] `scripts/export_openapi.py` → `web/openapi.json`; `pnpm gen:api`.

## 3. Diff (`web/src/workflows/diff.ts`)
- [x] Index each spec's nodes by id (parent id, slot, sibling order) through the manifests' `slots` logic already in `@/workflows/edits` / `ops`.
- [x] `diffSpecs(before, after)`: `{nodes: Map<id, {kind: "added" | "changed" | "moved", changes?: {path, before, after}[]}>, removed: {id, type}[], document: {path, before, after}[]}`; a node both moved and changed is `changed` with a `moved` flag.
- [x] `summarizeDiff(diff)`: "2 added · 1 changed · 1 removed", "No changes".
- [x] `diff.test.ts`: add, remove (with subtree), move within and across containers, param change (nested path, unset), router route `when`, document fields, identical specs, sibling insert not counted as a move.

## 4. History and older versions (`web/src/workflows/history.tsx`, `api.ts`, `builder.tsx`)
- [x] `api.ts`: `useWorkflow(…, version?)`, `useWorkflowVersions`, `useRestoreWorkflow` (sets the latest in the cache, invalidates versions).
- [x] The builder reads `?version` and `?compare` (`useSearchParams`); an unknown version is the not-found state ("This workflow has no version N.", Back to latest).
- [x] `HistorySheet`: rows as in the requirements, each a link; the shown one marked (`aria-current`); three states.
- [x] Read-only mode in `builder.tsx`: no edit items, side panel form disabled, status line "Version N of M · read-only", header actions Restore this version, Run this version, Back to latest.
- [x] Leaving unsaved edits for another version asks first (same dialog as Discard).
- [x] Tests (`builder.test.tsx`): list and labels, navigation, read-only menus, the confirm on leaving edits.

## 5. Compare on the canvas
- [x] "Compare with" `NativeSelect` (None, base version default, any other) in the status line, kept in `?compare=`.
- [x] Card badges (`Badge` outline, lucide `Plus` / `PencilLine` / `MoveRight` + label) through the `SpecTree` card slot the builder already uses for issues.
- [x] Summary line button opening the changes list (`Popover` from `md`, bottom `Sheet` below, as the issues list): node ids as buttons selecting the card, removed ids as text, document fields.
- [x] Side panel: a "Changes" block listing each changed path, before → after as text (`JsonView` for objects).
- [x] Tests: badges on the right cards, list contents and selection, side panel changes.

## 6. Restore and run (web)
- [x] Restore dialog (`AlertDialog`) with the version numbers; success opens the latest and toasts; `409` reloads versions and shows the reason in the dialog.
- [x] `NewRunForm` takes a `source`: `{template}` or `{workflow: {id, version, name, requires}}`; a `WorkflowRunSheet` beside `NewRunSheet` for a workflow: no template fields, an "Input" textarea, posts `stored_workflow`; its connections from the spec (`workflowRequires`). Readiness and repo parts unchanged.
- [x] Builder "Run" / "Run this version": disabled with the reason when dirty or with issues; opens the sheet; Start run navigates to the run.
- [x] Run console header: "<id> · version N" link when the run's `workflow.version` is set.
- [x] Tests: restore success and conflict; sheet for a workflow posts `stored_workflow` with `trigger: manual`; Run disabled reasons; console link.

## 7. Specs and checks
- [x] `specs/tech-stack.md`: Workflows and graph operations (restore, `restored_from`, "Not yet"), Run history and rerun (`stored_workflow`), Builder canvas (History, older versions, Compare, Restore, Run), Run console (version link), audit table (`workflow.restored`); decisions log rows "Workflow restore (5.7)", "Runs by workflow version (5.7)", "Version diff (5.7)".
- [x] `CHANGELOG.md` under `## [Unreleased]`.
- [x] `uv run ruff check`, `uv run pyright`, `uv run pytest`; `cd web && pnpm lint && pnpm typecheck && pnpm test`.
- [ ] `pnpm test:e2e` (axe and layout): no new failures against `main`.
