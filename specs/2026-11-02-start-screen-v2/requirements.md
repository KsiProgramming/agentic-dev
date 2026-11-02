# Start screen v2: provider picker and "Blank canvas"

Roadmap phase: 5.8
Branch: plan/5.8-start-screen-v2

## Context

Done when: **a user starts a canvas workflow without touching JSON.**

Today a workflow can only be created from a template ("Edit in builder" on a template card, 5.2) or by posting a spec by hand. The builder (5.2 to 5.7) can edit, validate, version and run any stored workflow. What is missing is a way in that starts empty, a way to say which model provider it runs on, and a place to find a stored workflow again. The breadcrumb "Workflows" is not a link because no list page exists (tech-stack → Builder canvas).

What drives it:
- **Mission, "Who we serve":** the tech lead builds workflows on the canvas. Templates are not the only starting point.
- **Mission, "Bring your own model access":** the provider is chosen by the user. Only Claude exists until Milestone 8, so the picker names Claude and shows GitHub Copilot as not available yet. The picker does not pretend Copilot works.
- **Mission principle 1 (one spec, many views):** a blank workflow is an ordinary stored spec (version 1). The builder then changes it through graph ops like any other.
- **Tech-stack decision "Builder entry (5.2)":** specs are built on the server so templates stay in Python. A blank spec is built the same way.
- **Tech-stack, Start and settings:** gallery cards, connection chips, form errors on the field and sheets follow the 2.6 start screen rules.

Note: the roadmap's "Next up" line names Milestone 4 at 4.8. The user picked 5.8 on purpose. It depends on 5.1 to 5.7, which are all done. It finishes Milestone 5. It unblocks 8.3 (per-workflow and per-workspace provider defaults build on the picker) and 9.x (the Architect's drafts are found in the Workflows list).

## Scope

### In scope

- **Blank workflow on the server** (`POST /workflows {blank: {name, id?, description?, provider?}}`): a third body, beside `spec` and `template`. Exactly one of the three is allowed; otherwise `422`.
  - The spec is `{spec_version: "0", id, name, description?, root: {type: "sequence", id: "sequence_1", steps: [agent_1]}}`. `agent_1` is the agent manifest's `default` with `id: "agent_1"` and `provider` set when given. A sequence needs at least one step, so "blank" is one starter agent.
  - `id` defaults to the name as a slug (lowercase, runs of other characters become `-`, cut to 63 characters, prefixed `w-` when it does not start with a letter). An id that does not match `NodeId` is a `422` validation error on `id`.
  - `provider` is a value of the agent's `provider` enum (`claude` today). Unset means the workspace default, as on a node.
  - `409` `workflow_exists` and the `workflow.created` audit row work as for the other bodies.
- **List workflows** (`GET /workflows`, `listWorkflows`): `{items: [{workflow_id, name, description, latest_version, created_at, updated_at}]}` for the workspace, the most recently changed first. `name` and `description` come from the latest version. `updated_at` is when the latest version was made. No pagination yet. Store: `agentic_store.list_workflows`.
- **Start screen** (`/templates`):
  - The page header reads "Start" with "Pick a template, or start from a blank canvas. Every change lands as a pull request you review."
  - A **"Blank canvas"** card comes first in the gallery. It shows an icon, "Blank canvas", one line ("Draw your own workflow, one step at a time.") and a "Create" button. The card opens the sheet. `?blank=1` opens the sheet directly.
- **New workflow sheet** (`NewWorkflowSheet`, `@/workflows/new-workflow`): a side sheet from 768 px and a bottom sheet below, shaped as the New run sheet. It has these fields:
  - **Name** (required).
  - **Id** (mono). It follows the name as a slug until the user edits it. It is checked against `NodeId` in the browser, with the rule as help text.
  - **Description** (optional).
  - **Provider**: a radio group. Each provider has an icon, name and connection state chip (as on template cards).
    - Claude is selectable and selected by default.
    - GitHub Copilot is shown disabled with "Comes with the Copilot adapter." under it.
    - A provider that is not connected can still be chosen, with "Connect it before you run the workflow." and a link to `/settings/integrations`. Creating a workflow needs no key.
  - A footer with Cancel and "Create workflow". The submit button shows a spinner and is disabled while pending.
  - A `409` shows on the Id field: "A workflow with this id exists." and an "Open it" link. A `422` shows on the field it names. Other errors show in an `Alert` above the footer.
  - On success the builder opens at `/workflows/{id}`, with the starter agent selected in the side panel.
- **Provider list:** the selectable providers are the agent manifest's `parameters.properties.provider.enum` (`GET /node-types`). The web adds no list of its own. The web holds one static "not available yet" row for GitHub Copilot, removed in 8.2.
- **Workflows list page** (`/workflows`):
  - `PageHeader` reads "Workflows" with "Workflows stored in this workspace. Open one to edit, compare versions or run it." Its action is "New workflow", which opens the sheet (`?blank=1`).
  - From `md` it is a table: Name (link to the builder, with the description under it), Id (mono, full), Version ("Version N"), Updated (`RelativeTime`, `focusable={false}`). Below `md` it is cards.
  - It has the three states: loading skeleton; empty ("No workflows yet." with "New workflow"); error with Retry.
  - "Workflows" goes into the sidebar between Runs and Templates. The builder's "Workflows" breadcrumb becomes a link.
- **Command palette:** a "New workflow" action under Actions, which goes to `/workflows?blank=1`. "Workflows" is added under *Go to*.
- **Specs:**
  - `tech-stack.md` → Workflows and graph operations: the `blank` body, `GET /workflows`, and the "Not yet" line, which loses "listing".
  - `tech-stack.md` → Start and settings: the Blank canvas card, the sheet and the provider picker.
  - `tech-stack.md` → Builder canvas: the breadcrumb, the Entry line and a new Workflows list subsection.
  - `tech-stack.md` → Layout: the sidebar and the command palette.
  - Decisions log rows. `CHANGELOG.md`. `roadmap.md` 5.8 is marked done by CI.

### Out of scope

- Workflow-level or workspace-level provider defaults, and capability-gap validation (8.3). The Copilot adapter (8.2).
- Deleting, renaming or duplicating workflows. Pagination, search or filters on the Workflows list.
- An empty root (a sequence with no steps). The schema keeps `min_length=1`.
- "Start from a goal" with the Flow Architect (9.x).
- Runs filtered by workflow.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Provider picker | Picked per new blank workflow and written as `provider` on its starter agent. Claude is selectable; Copilot is shown disabled. | User choice. It needs no spec change. The node-level field already exists (5.4). Defaults per workflow or workspace are 8.3. |
| Blank spec | Built on the server from a `blank` body: a root sequence with one starter agent from the agent manifest's `default` | User choice. This follows "Builder entry (5.2)": specs are built in Python. The manifest default keeps one source for a new agent. A sequence cannot be empty. |
| Providers offered | The agent manifest's `provider` enum, plus one static Copilot row in the web | The web gains no list of providers. Copilot's row says it is not available yet, so the start screen is truthful. |
| Id | Slug from the name, editable, checked against `NodeId` in the browser and on the server | User choice. Ids are readable slugs in URLs and branch names. Users rarely need to type one. |
| Not connected | The user can still create; the sheet says to connect before running | Creating a workflow uses no credentials. The run sheet already blocks Start until connections are there (5.7). |
| Workflows list | `GET /workflows` and a `/workflows` page, in the sidebar | User choice. A blank workflow must be findable again. It also makes the breadcrumb a link (tech-stack names 5.8 for it). |
| Palette | "New workflow" action and "Workflows" go-to | User choice. Every main action is reachable by keyboard from anywhere. |
| Order | API first (store, routes, OpenAPI), then the web, then the e2e | User choice. The UI is built on tested endpoints. |

## Open questions

- None
