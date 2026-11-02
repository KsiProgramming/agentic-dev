# Versions: history, visual diff, restore, run any version

Roadmap phase: 5.7
Branch: plan/5.7-workflow-versions

## Context

Done when: **user restores and runs an older version.**

5.1 stores every change to a workflow as an immutable version (`workflow_versions`, append-only, each with its `base_version` and the ops that made it), and `GET /workflows/{id}/versions` lists them. Nothing uses that history yet: the builder (5.2 to 5.6) opens only the latest version, there is no way back to an earlier one, and a run cannot start from a stored workflow at all. `POST /runs` takes an inline spec or a template, so a run cannot say which version it ran.

What drives it:
- **Mission principle 1 (one spec, many views):** history, diff and restore read the same stored specs; a restore is a new version, never a rewrite, so the version log stays the one record.
- **Mission principle 6 (transparency):** a run says which workflow version it ran, and links back to it; restores are audited.
- **Mission principle 2 (safe by construction):** running a version goes through the same validation and limits as any run (`POST /runs` refuses a spec with issues).
- **Tech-stack decisions "Version validity", "Version concurrency" and "Versions keep their ops" (5.1):** a restore is checked against `base_version` like a `PATCH`, and every version stays immutable.
- **Tech-stack, Builder canvas:** every action is a button or menu item, works from the keyboard, and colour means status only, so diff marks are labelled badges, not coloured cards.

Note: the roadmap's "Next up" line names Milestone 4 at 4.8. The user picked 5.7 on purpose. It depends on 5.1 (versions), 5.2 to 5.6 (builder, side panel, live validation), all done, and reuses the New run sheet (2.6, 11.x).

It unblocks 5.8 (a blank canvas workflow is run the same way), 6.5 (`subflow` calls a workflow by id and version) and 9.x (the Architect's drafts are versions a user can compare and restore).

## Scope

### In scope

- **Storage** (Alembic `0025_workflow_restore`):
  - `workflow_versions.restored_from` (int, nullable): the version a restore copied. A restored version has `ops` and `restored_from` set as `null` and `n`.
  - `runs.workflow_id` (text, nullable) and `runs.workflow_version` (int, nullable): the stored version a run was started from; `null` for runs from an inline spec or a template.
- **Restore** (`agentic_store.restore_workflow`, `POST /workflows/{id}/restore {base_version, version}`): stores version `latest + 1` with version `version`'s spec, `base_version` and `restored_from`. `201` with the new version (and its issues, as `PATCH`). `409` `version_conflict` when `base_version` is not the latest; `422` `already_latest` when `version` is the latest; `404` unknown workspace, workflow or version. Audit `workflow.restored` (`workflow_id`, `version`, `base_version`, `restored_from`), never the spec.
- **Versions in the API:** `WorkflowVersionResponse` and each `GET /versions` item gain `restored_from`.
- **Run a stored version** (`POST /runs`): a third source `stored_workflow {id, version?}` beside `workflow` and `template` (exactly one of the three). No `version` means the latest; the run stores the resolved version in `runs.workflow_id` / `workflow_version` and the version's spec in `runs.spec` as today. Unknown workflow or version is `404`; a version that cannot run (structure issues, unknown tools, a repo its tools need) is `422` ("version 3 of workflow docs cannot run: …"), and one above the limits `422` `policy_limits`, as any run. Rerun copies `workflow_id` and `workflow_version`. The summaries' `workflow` ref (`GET /runs`, `GET /runs/{id}`) gains `version` (`null` for a run of a template or an inline spec).
- **Visual diff** (`@/workflows/diff`, pure, web only): `diffSpecs(before, after)` matches nodes by id and returns, per node of `after`, `added`, `changed` (its parameters differ, child slots left out, with each changed path and its before and after values) or `moved` (its parent, slot, or order among the siblings both versions share changed); the nodes of `before` that are gone (`removed`, with their kind); and the document's changed fields (`name`, `description`, `budget_usd`).
- **History** (builder, `@/workflows/history`):
  - A "History" button in the builder's header opens a sheet (right from 768 px, bottom below): every version, newest first, with "Version N", when (`RelativeTime`), what made it ("Created", "N changes", "Restored from version M") and a "Latest" badge; the version shown is marked. Loading, error with Retry.
  - Choosing a version opens `/workflows/{id}?version=n`. While unsaved edits exist, leaving them asks first (as `beforeunload`).
- **An older version** (`?version=n`, n not the latest): the canvas is read-only (no edit items in the "⋯" menu, the side panel's form disabled), the status line reads "Version N of M · read-only", and the header's actions are "Restore this version", "Run this version" and "Back to latest". Its issues are the version's own.
- **Show changes:** on any version, a "Compare with" select in the status line ("Nothing" by default, or any other version). The comparison includes unsaved edits. With a version chosen, each card shows a neutral badge with icon and label ("Added", "Changed", "Moved"); a "Changed" card's side panel lists each changed path with its before and after values as text; a summary line above the canvas ("2 added · 1 changed · 1 removed") opens a list of every change, removed nodes and document fields included, each node id a button that selects its card (a removed node's id is plain text). The compared version is in the URL (`?compare=m`).
- **Restore** (UI): "Restore this version" opens a confirm dialog ("Restore version 2? It becomes version 6; versions 3 to 5 are kept."), calls restore with the latest version as base, then opens the latest with a toast ("Restored version 2 as version 6."). On `409`, the history is reloaded and the dialog says why.
- **Run** (UI): a "Run" button on the latest version and "Run this version" on an older one open the New run sheet with a stored workflow in place of a template: the same connection checklist (Claude, GitHub), repo (existing or new), an "Input" text field and the budget; Start run posts `stored_workflow {id, version}` with `trigger: manual` and opens the run. Run is disabled, with the reason, while there are unsaved edits ("Save your changes first") or while the version has issues ("Fix the N issues first").
- **Run console:** a run started from a stored version shows "<id> · version N" in its header, a link to `/workflows/{id}?version=n`.
- **Specs:** tech-stack → Workflows and graph operations (restore, `restored_from`, the "Not yet" line), Run history and rerun (`stored_workflow`, the summary's `workflow.version`), Builder canvas (history, older versions, compare, restore, run), Run console (the version link), the audit table (`workflow.restored`); decisions log rows; `CHANGELOG.md`.

### Out of scope

- A Workflows list page and a runs filter by workflow (5.8 and later).
- Diff on the server, a three-way merge, or diffing the ops log rather than the specs.
- Deleting or renaming versions, labels or tags on versions, draft → published (6.6).
- Restoring part of a version (one node) and undoing a restore other than by another restore.
- A Playwright e2e for the Done-when flow (the user chose unit, component, store and API tests plus a manual demo; the axe and layout suites still run).
- Who made a version (users come later; `actor_id` stays `NULL`).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | History, read-only older versions, visual diff, restore and run, with runs recording their version | User choice. Covers the whole roadmap row; recording the version is what makes "runs an older version" explainable (mission 6). |
| Restore | A server endpoint storing a copy as the next version with `restored_from`, `ops` null | User choice. Ops from latest back to an old spec would be a large, noisy batch the browser must compute; a copy is exact, one row, and keeps versions immutable. |
| Run a version | `POST /runs {stored_workflow: {id, version?}}`, the run keeping `workflow_id` / `workflow_version` and the spec | User choice. The server reads the stored spec, so the browser cannot send a different one; the spec stays on the run so an old run reads the same even if the workflow goes later. |
| Diff | In the browser, by node id, on two specs | Ids are stable across ops (5.1), the canvas already holds both trees, and no API is needed; the ops log does not say what a restore changed. |
| Diff marks | Neutral badges with icon and label; removed nodes in a list | Colour means status only (CLAUDE.md rule 2); a removed node has no card in the tree shown. |
| Older versions | Read-only, with Restore and Run | Edits always start from the latest (5.1's `base_version`); editing an old version is Restore, then edit. |
| Run gating | Disabled with a reason while dirty or with issues | A run must be of a stored version, and the server would refuse a spec with issues anyway. |
| Order | API first (store, restore, runs by reference), then the web | User choice. The UI is built on endpoints that exist and are tested. |

## Open questions

- None
