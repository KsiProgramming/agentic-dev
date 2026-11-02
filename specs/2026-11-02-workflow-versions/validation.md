# Validation: Versions: history, visual diff, restore, run any version

## Done when (from roadmap)
> User restores and runs an older version

## Automated checks
- [ ] Store (Testcontainers Postgres):
  - [ ] `restore_workflow` from version 1 on a workflow at version 3 stores version 4 with version 1's spec, `base_version` 3, `restored_from` 1, `ops` null; versions 1 to 3 unchanged.
  - [ ] Stale `base_version` raises `VersionConflictError`; an unknown version raises `WorkflowNotFoundError`; the latest raises `AlreadyLatestError`; nothing is stored then.
  - [ ] A `workflow.restored` audit row with the versions and no spec.
  - [ ] A run created from a ref keeps `workflow_id` / `workflow_version`; its rerun has the same.
- [ ] `test_migrations.py`: 0025 up and down.
- [ ] API:
  - [ ] `POST /workflows/{id}/restore`: `201` with `version`, `restored_from` and `issues`; `404` (workspace, workflow, version), `409 version_conflict`, `422 already_latest`.
  - [ ] `GET /workflows/{id}/versions` and `GET /workflows/{id}?version=n` return `restored_from`.
  - [ ] `POST /runs {stored_workflow: {id, version: 1}}` queues a run of version 1's spec; without `version` the latest; the summary's `workflow.version` is set; unknown workflow or version `404`; a version with issues `422`; two sources at once `422`.
  - [ ] Rerun of such a run keeps its workflow version.
- [ ] Web:
  - [ ] `diff.test.ts`: every case in the plan.
  - [ ] `builder.test.tsx`: history rows and labels; choosing a version navigates; an older version is read-only with Restore, Run and Back to latest; Compare puts the right badges on cards and the right entries in the changes list; restore success (toast, latest opened) and `409`; Run disabled while dirty or with issues, with the reason.
  - [ ] `workflow-run-sheet.test.tsx`: the run sheet for a workflow posts `stored_workflow` with `trigger: manual` and has no template fields.
  - [ ] Run console header links to the version.
  - [ ] Audit formatter for `workflow.restored`.
- [ ] `uv run ruff check`, `uv run pyright`, `uv run pytest`; `pnpm lint && pnpm typecheck && pnpm test` green.
- [ ] `pnpm test:e2e` (axe and layout): no new failures against `main` (see the known stale console specs); builder screenshots updated if the header changes them.

## Manual / demo checks
- [ ] Open a template in the builder (`/templates` → Edit in builder), change an agent's instructions and Save (version 2), remove a step and Save (version 3).
- [ ] History lists 3, 2, 1 with "Latest" on 3, "N changes" on 2 and 3, "Created" on 1.
- [ ] Open version 1: read-only canvas; Compare with version 3 shows the removed step as "Added" and the changed agent as "Changed", its side panel listing the instructions before and after.
- [ ] Restore version 1: the dialog names version 4; the builder opens version 4 with the toast; History shows "Restored from version 1".
- [ ] Run it: the sheet shows the checklist, repo, Input and budget; Start run opens the run console, whose header reads "<id> · version 4" and links back to it. The run completes as a run of the template would.
- [ ] With an unsaved edit, Run is disabled with "Save your changes first"; opening another version from History asks before dropping the edit.
- [ ] Do history, compare, restore and run from the keyboard only.
- [ ] At 375 and 1440 px, light and dark: the history sheet, the changes list and the badges fit, no horizontal page scroll.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `specs/tech-stack.md` (Workflows API, Run history, Builder canvas, Run console, audit table, decisions log) and `CHANGELOG.md` updated in the PR
- [ ] No spec content in audit rows or logs; versions stay immutable (the trigger still refuses `UPDATE` and `DELETE`)
