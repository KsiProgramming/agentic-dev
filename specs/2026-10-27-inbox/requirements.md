# Inbox

Roadmap phase: 11.5
Branch: plan/11.5-inbox

## Context
Approvals are made only on the run console (2.6): an approver opens each waiting run one by one, and the runs list (11.4) only links to them. Mission principle 8 ("what needs the user is always visible") and the UI v2 success measure "an approver clears every waiting gate from one Inbox" drive this phase. tech-stack → UI v2 → "Inbox (11.5)" fixes its shape, and the decisions log already chose "an Inbox beside the console's dock, both on the same review components".

It builds on 11.1 (display components), 11.2 (`active_ms` / `waiting_ms`), 11.3 (`expires_at`, gate expiry) and 11.4 (`branch`, `useWorkspaceId`, the E2E workspace), all done. It unblocks 11.6 (the console's waiting banner links to the decision) and 11.7 (the palette's Approve action).

There are no users yet, so "gates waiting on the user" means the gates waiting in the browser's workspace.

## Scope
### In scope
- **API: the pending gate.** `GET /runs/{id}/gate` (`RunGate`) returns the gate the run waits at, read from its last `gate_waiting` event: `node_id`, `title`, `prompt`, `artifact`, `changes`, `changes_error`, `expires_at`, and what approving does: `repo` (`repoLabel` source), `base` (the run's `branch`) and `branches` (each writer's `agent/<run>/<node>` from the changes' `node_id`s). `404` for an unknown run, `409` when the run is not waiting (or its gate expired). The store reuses `_waiting_gate_changes` (`agentic_store.approvals`).
- **Shared review components.** The dock's review content and decision logic move out of `approval-dock.tsx` into components both screens use: a `GateReview` panel (summary or changed files with the same `DiffView`), and a `useGateDecision` hook (approve with edits, reject with comment dialog, `A` / `R` via `useGateShortcuts`, toasts, `409` on expiry). The dock looks and behaves as today.
- **`/inbox` page:**
  - `PageHeader` ("Inbox", one line), then a list of the workspace's waiting runs from `GET /runs?status=waiting`, **oldest first**, leaving out a gate past `expires_at`. Each row: gate title, workflow, `repoLabel`, `WaitingTime`, `ExpiresIn`. Kept live by the runs stream.
  - Selecting a row shows its review beside the list from 1024 px, below it under 1024 px. The selection lives in the URL (`/inbox?run=<id>`); the first row is selected by default from 1024 px.
  - The review: gate title and `ExpiresIn`; "what approving does" (repo, `branch → base` per writer); the summary or the changed files (editable, "Approve with N edits"); the run's `Money` and `Duration` so far; Approve, Reject (comment dialog), Open run. `A` / `R` work as in the dock while the review is shown and focus is not in a field.
  - After a decision the next gate is selected; the decided run drops out when the stream reports it.
  - `LoadingState`, `EmptyState` ("Nothing waits for your approval.", action "Show all runs") and `ErrorState`, for the list and for the review.
- **Shell.** "Inbox" is the first sidebar entry (`InboxIcon`), and the waiting count badge moves to it from "Runs" (and stays on the mobile menu button). The page title prefix stays as it is.
- **Specs, in the same PR.** tech-stack moves "Inbox (11.5)" from UI v2 into the main rules (a new "Inbox" section; "Waiting signals" and "Approval dock" updated; the gate review contract gets `GET /runs/{id}/gate`). A `CHANGELOG.md` entry.

### Out of scope
- Per-user assignment of gates ("waiting on *me*"): comes with users and sign-in.
- Bulk approve or reject.
- The console's waiting banner (11.6) and the palette's Approve action (11.7).
- Notifications outside the app (email, Slack).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where the review reads the gate | A new `GET /runs/{id}/gate` | The summary's `waiting_gate` has only the title and expiry. Replaying a run's whole event stream for each selected row is heavy; one small read of the last `gate_waiting` is not. The console keeps reading events. |
| List source | `GET /runs?status=waiting`, sorted oldest first on the client | The waiting set is small (the shell already lists up to 100), and the stream already refreshes it. No new list endpoint. |
| One review for both screens | Extract `GateReview` + `useGateDecision` from the dock first | The decisions log says the dock and the Inbox never disagree; one set of components makes that structural. |
| Selection | In the URL (`?run=`) | A reload or a shared link keeps the gate; the back button works. |
| Waiting count | Moves to Inbox; the Runs tab "Needs approval" keeps its own count | The sidebar points to where approvals are made; the runs list's views stay a filter. |

## Open questions
- None
