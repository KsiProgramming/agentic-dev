# Audit log view for admins

Roadmap phase: 3.7
Branch: plan/3.7-audit-log-view

## Context
The mission names the **platform admin** persona ("control of cost, tools, secrets and data") with the **audit log** as an entry point. Today what happened in a workspace is spread over `runs`, `approvals` and `run_events`, and settings changes (connections, run limits, prices) leave no trace at all. This phase adds one append-only record of who did what, and a page that lists it per workspace.

Principles that drive it:
- **Mission 6 (transparency):** every action is kept in an append-only log. The audit log is written in the same transaction as the action, so a row exists exactly when the action happened.
- **Mission 3 (humans approve irreversible actions):** every gate decision is listed with its comment and edits, so an admin can see who let what through.
- **Mission 9 (nothing is lost):** every run is listed, including runs created before this phase (backfilled).
- **Tech stack, security:** secrets never appear in logs. Audit rows hold the key hint at most, never key material.
- **Tech stack, UI design system:** tables on desktop, cards on mobile, defined empty, loading and error states. New patterns are written into `tech-stack.md` first.

There are **no users or roles yet** (`approvals.decided_by` is always unset, every run is in `DEFAULT_WORKSPACE_ID`). So "for admins" means the admin's view of the workspace. Restricting it to an admin role waits for auth. Every row has an actor column ready for it.

It depends on 2.3 / 2.4 (run summaries and the runs page), 2.6 (approvals, rerun, cancel, settings) and 3.2 / 3.3 / 3.6 (run limits, budget, gate edits). All are done. It unblocks role-gated admin views and per-user actors once auth exists, and later audit entries for workflow versions (5.1) and Jira (7.x).

## Scope
### In scope

**Audit table (store)**
- A new append-only table `audit_events` (Alembic `0019_audit_events`):
  - `id` (identity), `workspace_id`, `at`, `action`, `actor_type` (`user` | `system`), `actor_id` (`NULL` until auth), `run_id` (nullable), `node_id` (nullable), `details` JSONB.
  - Index `(workspace_id, at DESC, id DESC)` for listing.
  - A trigger refuses `UPDATE` and `DELETE`, so append-only holds in the database too, not only by convention.
- Actions, each written **in the same transaction** as the change it records:

  | Action | Written by | `details` |
  |---|---|---|
  | `run.created` | `create_run` | `template_id`, `repo_url`, `budget_usd` |
  | `run.rerun` | `create_rerun` | `rerun_of`, `budget_usd` |
  | `run.cancel_requested` | `request_cancel` (first request only) | status before |
  | `run.ended` | `PostgresEventSink` on `run_completed` / `run_failed` / `run_cancelled` (actor `system`) | `status`, `failure_reason`, `pr_url`, `estimated_usd` |
  | `gate.approved` / `gate.rejected` | `record_approval` | `comment`, `edited_files`, edited paths (never contents) |
  | `connection.added` / `connection.removed` | `put_connection`, `put_github_connection`, `delete_connection` | `provider`, `key_hint` or `account_login` |
  | `policy.updated` | `replace_policy_overrides` | the limits before and after |
  | `pricing.updated` | `replace_price_overrides` | models added, changed and removed |

- **Backfill** in the migration from existing data:
  - `run.created` or `run.rerun` per run;
  - `run.cancel_requested` where `cancel_requested_at` is set;
  - `run.ended` per finished run;
  - `gate.*` per approval.

  Settings changes made before this phase cannot be recovered and are not invented.
- Store function `list_audit_events(workspace_id, cursor, limit, actions, run_id, since, until)`, newest first, with the same cursor encoding as `list_run_summaries`.

**API**
- `GET /workspaces/{id}/audit`, operation `listAuditEvents`:
  - query: `cursor`, `limit` (1–200, default 50), `action` (repeatable), `run_id`, `since`, `until`;
  - answer: `{items, next_cursor}`. Each item has `id`, `at`, `action`, `actor {type, id}`, `run_id`, `node_id` and `details`, plus `run {template_id, repo_url, status}` when it has a run, so the page needs no second call;
  - `404` for an unknown workspace, `422` for a bad cursor or filter.
- A workspace only ever sees its own rows.

**Web**
- A new **Audit log** page at `/audit`, with a sidebar entry (`ScrollTextIcon`) after Settings, in the shell's nav and breadcrumbs.
- Page header: title, a one-line description, no primary action.
- From 768 px a table with the columns Time (relative, exact time on hover, `tabular-nums`), Action (icon + label), Actor ("System", or "—" with a tooltip explaining that names arrive with sign-in), Run (id8 in mono, linking to the console; template and repo under it) and Details (one readable line, e.g. "Approved `approve` with edits to 2 files · 'looks good'"). Below 768 px, stacked cards.
- Filters: action category (Runs, Approvals, Settings), run id, and date range. They are kept in the URL like the runs page's filters.
- "Load more" with the cursor, plus skeleton, empty ("No activity yet") and error (Retry) states.
- Data is read as data: `details` is shown as text through a formatter per action, never as HTML. Unknown actions fall back to the action name.
- No live updates: the page shows a "Refresh" button. Every list of runs stays live on the Runs page.

**Docs**
- `specs/tech-stack.md`, written first:
  - "Audit log (API contract)": the table, actions, `details` per action, endpoint, and append-only trigger;
  - UI design system: the Audit log page and the new sidebar item;
  - a decisions-log row.
- CHANGELOG entries.

### Out of scope
- Users, sign-in, roles, and restricting the page to admins (a later auth phase; `actor_id` is ready for it).
- CSV / JSON export, retention and purge, and shipping audit rows to an external SIEM.
- Per-node or per-tool-call entries. Those stay in `run_events` and the run console's Raw events tab.
- Audit entries for workflow versions (5.1), composites (6.6), Jira (7.x) and plugins (10.1). Each of those phases adds its own actions.
- Live streaming of the audit page.
- Recovering settings changes made before the migration.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Storage | A new append-only `audit_events` table | User choice. It records settings changes, which no other table keeps, and its rows never change, unlike `runs`. |
| Write path | In the store function's transaction, next to the change | A row exists if and only if the change was committed. No outbox and no second writer. |
| Append-only | A Postgres trigger refuses `UPDATE` / `DELETE` | An audit log that can be edited is not one. It is cheap and testable. |
| Run outcomes | `run.ended` written by the event sink, actor `system` | The sink already projects end events onto `runs` in one transaction, so every run's story (created → decided → ended) is in one place. |
| Actor | `actor_type` + nullable `actor_id`; UI shows "—" for users | There are no users yet. The column is ready for auth, and showing "—" says so honestly instead of inventing a name. |
| Admin gating | None now; the page is in the sidebar for everyone | User choice. Without auth, any gate would be a stand-in to throw away. |
| Edits and keys in `details` | Paths and counts, key hints; never file contents or secrets | File contents already live in `run_events`. Secrets must never be logged (tech stack, security). |
| Backfill | Runs and approvals from existing rows; settings not invented | Done when says "every run and approval". Inventing past settings changes would make the log untruthful. |
| Delivery | Contract first, then two PRs: A backend (store, migration, API), B web + e2e | User choice; the same as 3.6. Only PR B touches this spec folder, so CI marks 3.7 done once. |
| Validation | Store/API tests, Vitest, Playwright (+ axe, layout), manual demo | User choice. |

## Open questions
- None. (Sidebar placement could move under Settings once a role-aware nav exists. Revisit in the auth phase.)
