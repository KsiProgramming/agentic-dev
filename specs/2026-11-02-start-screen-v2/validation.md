# Validation: Start screen v2: provider picker and "Blank canvas"

## Done when (from roadmap)
> A user starts a canvas workflow without touching JSON

## Automated checks
- [ ] Engine:
  - [ ] `slug` cases;
  - [ ] `blank_spec` matches the schema and has no `validate_workflow` issues;
  - [ ] its starter agent equals the agent manifest's `default` (id `agent_1`), with `provider` set only when given.
- [ ] Store (Testcontainers Postgres): `list_workflows` returns:
  - [ ] an empty list for an empty workspace;
  - [ ] workflows ordered by last change;
  - [ ] name and description from the latest version;
  - [ ] only the workspace's own workflows.
- [ ] API:
  - [ ] `POST /workflows {blank: {name}}` returns `201`, version 1, and an id slugged from the name;
  - [ ] an explicit `id`, `description` and `provider: "claude"` are kept in the stored spec;
  - [ ] `provider: "copilot"` is `422`;
  - [ ] an id that is not a `NodeId`, `provider: "copilot"` or an empty name is a `422` naming that field;
  - [ ] `blank` with `spec` or `template` is `422`;
  - [ ] an existing id is `409` `workflow_exists`;
  - [ ] a `workflow.created` audit row is written without the spec;
  - [ ] `GET /workflows` returns items with `workflow_id`, `name`, `description`, `latest_version`, `created_at` and `updated_at`, newest change first;
  - [ ] `GET /workflows` is `404` for an unknown workspace.
- [ ] Web (vitest):
  - [ ] `slugify` matches the shared `workflow-slugs.json` fixture;
  - [ ] the sheet: the id follows the name until edited; an invalid id shows an error on the field; Claude is selected by default; Copilot is disabled with its reason; the not-connected hint and link show; the posted body is right; `409` shows on Id with "Open it"; `422` shows on the field it names; other errors show in an `Alert`; success navigates to `/workflows/{id}` with the starter agent selected;
  - [ ] the start screen: the Blank canvas card comes first and still shows with no templates; `?blank=1` opens the sheet; template Start and Edit in builder are unchanged;
  - [ ] the Workflows list: rows link to the builder, and the loading, empty ("No workflows yet." + New workflow) and error (Retry) states work;
  - [ ] the nav: Workflows is in the sidebar, and the `/workflows/[id]` breadcrumb "Workflows" is a link;
  - [ ] the command palette: "New workflow" goes to `/workflows?blank=1`, and "Workflows" is under Go to.
- [ ] E2E (`start-screen.spec.ts`): the Done-when flow from the plan, group 6, passes.
- [ ] `a11y.spec.ts`: no serious axe issues on `/templates`, `/workflows` or the open sheet.
- [ ] `layout.spec.ts`: no horizontal page scroll at 375/768/1440 in light and dark, with baselines updated.
- [ ] `uv run ruff check`, `uv run pyright` and `uv run pytest` pass. `pnpm lint && pnpm typecheck && pnpm test` passes (no raw colours, type-scale sizes only). `pnpm test:e2e` has no new failures against `main` (see the known stale console specs).

## Manual / demo checks
- [ ] On the local stack, open `/templates`. "Blank canvas" is the first card. Click Create, type "Release notes", and check the id reads `release-notes`. Leave Claude selected and click Create workflow.
- [ ] The builder opens on Version 1 with one agent `agent_1`, selected in the side panel. Set role and instructions, add a Gate after it from the palette, and Save. Version 2 reads "Ready to run" or lists only real issues.
- [ ] Click Run. The sheet shows Claude in "Before you start". With Claude connected, Start run starts the run and its console opens. No JSON was typed at any point.
- [ ] `/workflows` lists "Release notes", Version 2, updated just now. The builder's "Workflows" breadcrumb leads back to it.
- [ ] With the Claude key removed, the sheet shows Claude "not connected" and the hint, and Create still works.
- [ ] Creating "Release notes" again shows the id error with "Open it".
- [ ] Check at 375 and 1440 px, in light and dark: the sheet is a bottom sheet on mobile, the list shows cards on mobile, and there is no horizontal scroll.
- [ ] Keyboard only: ⌘K → New workflow → fill in → Enter → the builder opens.

## Merge criteria
- [ ] Every check above passes locally (CI minutes are limited; CI runs on the PR).
- [ ] `tech-stack.md` (API contract, Start and settings, Builder canvas, Layout, decisions log) and `CHANGELOG.md` are updated in the same PR.
- [ ] No palette colours, hex values or arbitrary sizes. Status is shown only through `StatusBadge`/chips with icon + label.
- [ ] Agent, repo and user text stays text: names and descriptions are never rendered as HTML.
