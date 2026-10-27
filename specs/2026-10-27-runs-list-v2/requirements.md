# Runs list v2

Roadmap phase: 11.4
Branch: plan/11.4-runs-list-v2

## Context
The runs page (2.4) pins a "Needs approval" section above "All runs". With a few waiting runs, real work drops below the fold. Test runs from e2e and demos also land in the default workspace beside real ones. The Workflow column shows only the workflow's name, so two runs of one workflow look the same. Mission principle 8 ("what needs the user is always visible and never below the fold") and the UI v2 success measure "no test run appears in a real workspace" drive this phase. tech-stack → UI v2 → "Runs list (11.4)" fixes its shape.

It builds on 11.1 (display components), 11.2 (`active_ms` / `waiting_ms`) and 11.3 (`expired`, `waiting_gate.expires_at`), all done. It unblocks 11.5 (the Inbox takes over the waiting count), 11.7 (`⌘K` jumps to a run by id) and every e2e test after it (they no longer touch the user's default workspace).

## Scope
### In scope
- **API: trigger.** A `runs.trigger` column (`manual` | `api` | `rerun`) and `RunSummary.trigger`. `CreateRunRequest.trigger` is optional (`manual` | `api`, default `api`); the web's New run sheet sends `manual`; `POST /runs/{id}/rerun` stores `rerun`. Migration backfill: `rerun_of` set → `rerun`, `template_id` set → `manual`, else `api`.
- **API: branch.** `RunSummary.branch` (str | null): the run's requested `repo.ref`, else the `default_branch` of a repo the run created (`repo_created`), else null. The sink projects it into a `runs.branch` column. No new event, and no clone-time lookup.
- **API: counts.** `GET /runs/counts?workspace_id&template&repo` returns `{all, running, waiting, failed}` for the saved views. `running` counts `queued` + `running`. `waiting` leaves out a gate past `gate_expires_at`.
- **API: workspaces.** `POST /workspaces {name}` creates a workspace (no auth yet, like the rest of the API).
- **Test runs in their own workspace.** The e2e global setup finds or creates the "E2E" workspace and connects it, instead of the default one. Every e2e helper starts runs there. The browser reads its workspace from the `agentic-workspace` cookie, which Playwright sets. `scripts/sandbox_demo.py` uses a "Demo" workspace.
- **Web workspace.** `useWorkspaceId()` (`@/workspace`) reads the cookie, falling back to `DEFAULT_WORKSPACE_ID`, and replaces each hard-coded `DEFAULT_WORKSPACE_ID` default (runs, rerun, shell attention, settings, templates, audit). There is no switcher UI: the cookie is a test seam until users and workspaces arrive.
- **Runs list v2 (web):**
  - Saved views as tabs (All, Running, Needs approval, Failed), each with its count from `GET /runs/counts`, kept live by the runs stream. The view lives in the URL (`?view=running`) beside the template and repo filters. The status dropdown goes: the views replace it. Nothing is pinned above the list.
  - Columns: Status, Run (workflow name; under it the `IdChip` short id and the trigger: "Manual", "API", "Rerun of <id8>"), Repository (`repoLabel` in mono, with the branch under it), Started, Duration, Cost, Pull request, actions.
  - A waiting row's status badge is a link to its review (`/runs/{id}`), replacing the "Review" button. The badge stays icon + label.
  - Rows are grouped under sticky date headers (Today, Yesterday, This week, Earlier) by when the run was created (the order the list is in), in the display time zone, in the table and in the cards. From 1024 px the headers stick under the top bar; below that the table scrolls in its own box.
  - Each view has its own empty state ("Nothing needs approval.", …). Loading and error states stay as they are.
- **Specs, in the same PR.** tech-stack moves "Runs list (11.4)" from UI v2 into the main rules (a new "Runs list" section, and the run history contract gets `trigger`, `branch`, `/runs/counts` and `POST /workspaces`). A `CHANGELOG.md` entry.

### Out of scope
- A workspace switcher in the sidebar and per-user workspaces (with sign-in, later).
- Moving the waiting count from Runs to an Inbox entry (11.5).
- Jira and webhook triggers (`jira` joins `trigger` with the Jira phases).
- The branch a writer pushed (the PR head): the PR link already covers it.
- Deleting e2e runs already in users' default workspaces. They stay, because the history is append-only (mission principle 9).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Trigger | A stored `trigger` column set when the run is created; the client says `manual` | Only the client knows whether a person or a script started a run. Storing it keeps the list from deriving it on read, and a later `jira` value fits the same column. |
| Branch | The requested ref, or the created repo's default branch, else none | The value is known without cloning and is truthful. Resolving the default branch at clone time would need a new event for a muted secondary line. |
| Counts | One `GET /runs/counts` endpoint, refetched when the stream reports a change | Counting loaded pages is wrong past the first page. One query serves all four tabs. |
| Test isolation | A real "E2E" workspace created by the e2e setup, chosen per browser by a cookie | Local e2e shares the user's dev stack and its single web container, so an env var on the web would switch everyone. A cookie scopes it to the test browser. Connections are per workspace, so the journey test no longer changes the user's own. |
| Status filter | Removed in favour of the four views | Two ways to filter by status in one bar disagree. Statuses the views do not cover (cancelled, succeeded) still show under All. |

## Open questions
- None
