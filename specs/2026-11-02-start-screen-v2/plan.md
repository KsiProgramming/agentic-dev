# Plan: Start screen v2: provider picker and "Blank canvas"

The API comes first, then the web, then the e2e. The repo works after each group.

## 1. Store: list workflows
- [x] `agentic_store/workflows.py`: add `list_workflows(sessions, workspace_id)`. It joins `workflows` with each one's latest `workflow_versions` row and returns `StoredWorkflowSummary {workflow_id, name, description, latest_version, created_at, updated_at}`, sorted by `updated_at` desc.
- [x] Store tests (Testcontainers):
  - an empty workspace returns an empty list;
  - two workflows come back ordered by their last change;
  - name and description come from the latest version after a `PATCH` that renames;
  - another workspace's workflows are not listed.

## 2. API: `blank` body and `GET /workflows`
- [x] `agentic_engine` (next to the manifests): add `blank_spec(name, id?, description?, provider?) -> WorkflowSpec` and `slug(name) -> str`. The starter agent is the agent manifest's `default` with `id: "agent_1"`. The root is `sequence_1`.
- [x] `agentic_api/workflows/models.py`:
  - add `BlankWorkflow {name, id?, description?, provider?}`;
  - `CreateWorkflowRequest.blank` is a third body, and exactly one of `spec`, `template`, `blank` is allowed;
  - the spec is built with `exclude_none`;
  - add `WorkflowSummary` and `WorkflowList`.
- [x] `agentic_api/workflows/routes.py`: add `GET ""` (`listWorkflows`). Document the `blank` body on `createWorkflow`.
- [x] Engine tests: the `slug` cases (spaces, punctuation, unicode, leading digit, 63-character cut, empty after slugging). `blank_spec` matches the schema, has no issues and keeps the provider.
- [x] `packages/api/tests/test_workflows.py`:
  - `blank` returns `201` with version 1;
  - the id comes from the name;
  - an explicit id, description and provider are kept;
  - `provider: "copilot"` is `422`;
  - a bad id, an unknown provider or an empty name is a `422` validation error naming the field;
  - two bodies are `422`;
  - an existing id is `409`;
  - a `workflow.created` audit row is written;
  - `GET /workflows` returns the order and fields, and `404` for an unknown workspace.
- [x] Run `scripts/export_openapi.py` to update `web/openapi.json`, then `pnpm gen:api`. Refresh `schemas/` fixtures if the export script touches them.

## 3. Web: data and sheet (`web/src/workflows/`)
- [x] `api.ts`: add `useWorkflows(workspaceId)` and `useCreateBlankWorkflow()`. On success it seeds the workflow query and invalidates the list. Add `slugify(name)`, which mirrors the server, with a test against shared cases in `schemas/fixtures/workflow-slugs.json` written by the engine test.
- [x] `new-workflow.tsx`: add `NewWorkflowSheet`.
  - It is a side `Sheet` from `md` and a bottom `Sheet` below, like the New run sheet. It has Name, Id (mono, follows the name until edited), Description and Provider.
  - Provider is a `RadioGroup` built from the agent manifest's provider enum (`useNodeTypes`) plus the static Copilot row (disabled, "Comes with the Copilot adapter."). Each row has a connection chip from `useReadiness`. When the chosen provider is not connected, a hint links to `/settings/integrations`.
  - Field errors are tied by `aria-describedby`. A `409` is shown on Id with "Open it". Other errors go in an `Alert`. The submit button shows a pending spinner.
  - On success it routes to `/workflows/{id}?node=agent_1`. If the builder has no `?node=`, it adds it so the starter agent is selected.
- [x] Extract `RequirementChip` from `template-gallery.tsx` into a shared `ConnectionChip` (`@/runs/new-run/`) so the sheet reuses it.
- [x] `new-workflow.test.tsx`:
  - the slug follows the name, then stops once the id is edited;
  - an invalid id shows its error;
  - Claude is preselected and Copilot is disabled with its reason;
  - a not-connected hint shows when needed;
  - the posted body is right;
  - `409` and `422` show on their fields;
  - a successful create navigates to the builder.

## 4. Web: start screen
- [x] `templates-view.tsx`: change the header title and description. Read `?blank=1` to open the sheet and remove it on close.
- [x] `template-gallery.tsx`: add a `BlankCanvasCard` first (lucide `SquareDashedIcon`, "Create" button). The skeleton count and the empty state keep it in mind: with no templates, the Blank canvas card still shows.
- [x] `templates-view.test.tsx`: the card comes first, the sheet opens from it and from `?blank=1`, and the existing template flows are unchanged.

## 5. Web: Workflows list, nav and palette
- [x] `web/src/app/workflows/page.tsx` and `workflows-view.tsx`:
  - `PageHeader` with "New workflow" (`?blank=1`, the sheet);
  - a table from `md` and cards below;
  - `RelativeTime` with `focusable={false}`;
  - loading, empty and error states.
- [x] `components/shell/nav.ts`: add "Workflows" (lucide `WorkflowIcon`) between Runs and Templates. In `breadcrumbsFor`, `/workflows` is "Workflows" and `/workflows/[id]` is "Workflows" (a link) › id. Update the `nav.test.ts` cases.
- [x] `command-palette.tsx`: add "New workflow" under Actions (to `/workflows?blank=1`) and "Workflows" under Go to. Add `command-palette.test.tsx` cases.
- [x] `workflows-view.test.tsx`: rows, links, the three states, and the sheet opening from the header.

## 6. E2E and checks
- [x] `web/e2e/start-screen.spec.ts`, which uses `workflows.ts` helpers and the E2E workspace:
  1. `/templates` → Blank canvas → name "My review flow" → the id reads `my-review-flow` → Claude → Create workflow.
  2. The builder opens with `agent_1` selected. Set role and instructions in the side panel.
  3. Add a step after it from the palette (Gate). Save → Version 2. Run opens the run sheet with Claude in "Before you start".
  4. `/workflows` lists it. Its name opens the builder.
  5. ⌘K → "New workflow" opens the sheet.
- [ ] `a11y.spec.ts`: add `/workflows` and the open sheet. `layout.spec.ts`: add screenshots of `/templates` (with the new card), `/workflows` and the sheet at 375/768/1440, light and dark. Update baselines.
- [ ] Run `pnpm lint && pnpm typecheck && pnpm test`, then `pnpm test:e2e`. Run `uv run ruff check`, `uv run pyright` and `uv run pytest`.

## 7. Specs and changelog
- [x] `specs/tech-stack.md`:
  - Workflows API contract: the `blank` body, `GET /workflows`, and the "Not yet" line;
  - Start and settings: the Blank canvas card, the sheet and the provider picker;
  - Builder canvas: the breadcrumb link, the Entry line, and a "Workflows list" subsection;
  - Layout: the sidebar and the command palette;
  - decisions log: "Blank workflow (5.8)", "Provider picker (5.8)", "Workflows list (5.8)".
- [x] `CHANGELOG.md`: an entry under `## [Unreleased]`.
- [ ] Open the PR with the `open-pr` skill. CI marks 5.8 done in `roadmap.md`.
