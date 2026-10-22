# Runs page (new home)

Roadmap phase: 2.4
Branch: plan/2.4-runs-page-home

## Context
`/` already redirects to `/runs`, but `/runs` is a placeholder empty state. The summaries API from 2.3 (`GET /runs`, `GET /runs/{id}`) is merged, so past runs can now be listed. This phase makes the Runs page real: the user finds any past run and sees at a glance whether it succeeded, failed or is waiting. The run console (2.5), approval dock badge (2.6) and Rerun button (2.7) build on this list.

Depends on 2.1 (tokens, `StatusBadge`, states), 2.2 (shell, `PageHeader`) and 2.3 (summaries API). All three are done. It does not depend on 1.12, which is still unplanned.

Principles and choices that apply:
- **Mission 9, Nothing is lost:** every run is listed with its outcome and can be opened.
- **Mission 8, Enterprise-grade, calm UI:** what needs the user (a waiting gate) is never below the fold, so "Needs approval" comes first. Every data view has empty, loading and error states.
- **Mission 6, Transparency:** live status comes from the append-only log through the projection 2.3 put on the `runs` row, not from a second source.
- **Tech stack → UI design system:** a table at ≥ 768 px and cards below that. Status is shown as icon plus label. Inter at 13 px for dense tables, JetBrains Mono for ids, `tabular-nums` for numbers. `aria-live="polite"` announces status changes.
- **Tech stack → Frontend:** TanStack Query + SSE (`EventSource`) for data, and the generated OpenAPI client. TanStack Query is listed in the tech stack but not installed yet, so this phase adds it.
- **Tech stack → Event log:** `LISTEN/NOTIFY` fan-out for SSE, the same as `GET /runs/{id}/events`.

## Scope
### In scope
- **Backend: `GET /runs/stream?workspace_id`** (SSE). It sends one `run_summary` frame (a `RunSummary`) each time a run in the workspace changes.
  - `RunEventListener` gets a workspace-wide subscription. Today it only has a per-run one. On a wake-up, the stream re-reads the summaries of the runs that were notified, using `get_run_summary`.
  - A frame is sent only when the summary has changed since the last frame for that run, for example status, `finished_at`, `pr_url` or `waiting_gate`. 250 ms delta notifications that change nothing are dropped.
  - Each frame's `id` is the run's `updated_at`. There is no replay: after a reconnect the client refetches the list. A keep-alive comment is sent every 15 s.
  - The route is declared before `/{run_id}`. OpenAPI and `web/src/api/schema.d.ts` are regenerated.
- **Frontend data layer:** add `@tanstack/react-query` with a `QueryClientProvider` in the root layout.
  - `useRunSummaries(filters)` is an infinite query over the cursor.
  - `useRunsStream(workspaceId)` opens one `EventSource`. It patches matching items in the query cache. It invalidates the list queries when a run it doesn't know about appears, or when a run moves into or out of `waiting`.
- **Runs page `/runs`:**
  - **Needs approval** section on top (`?status=waiting`, every waiting run), shown only when there are any. Below it is **All runs**, newest first, with "Load more" pagination.
  - Columns: status badge, workflow name, repo (`owner/name`, mono), started (relative time with the absolute time as a tooltip), duration (ticks live while the run is running), PR link (external icon). The whole row links to `/runs/{id}`.
  - Table at ≥ 768 px, stacked cards below that, with the same fields.
  - Filters: status (multi-select: Needs approval, Running, Queued, Succeeded, Failed, Cancelled), template (the known template ids) and repo (from `GET /workspaces/{id}/repos`; hidden if GitHub is not connected). Filters are kept in the URL query, so a filtered view can be linked and survives a reload. A "Clear filters" button is included.
  - States: a skeleton table or cards while loading. An empty state with a "Browse templates" action when there are no runs at all. A separate "No runs match these filters" empty state with a "Clear filters" action. An error state with Retry.
  - `aria-live="polite"` region announces when a listed run changes status.
- The placeholder copy in `web/src/app/runs/page.tsx` is replaced.

### Out of scope
- Waiting badge in the sidebar and a "● Needs approval" browser tab title: 2.6.
- Rerun button in the list: 2.7.
- Console redesign: 2.5. Rows link to the existing `/runs/{id}` page.
- Cost column: 3.1.
- Free-text search, sorting other than newest first, total count, and bulk actions.
- Event replay on the summary stream (`Last-Event-ID`). A refetch on reconnect is enough.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Live updates | New workspace SSE `GET /runs/stream` (user choice), not polling | Status changes show within about 1 s. It reuses the existing `LISTEN/NOTIFY` listener. |
| Frame content | The full `RunSummary`, deduplicated per run | The client needs no extra fetch per change, and noisy delta events don't flood the stream. |
| Reconnect | No replay. Invalidate list queries on `open` | Summaries are state, not a log. A refetch is simpler and always correct. |
| Data fetching | TanStack Query (user choice), added now | It is the tech-stack choice. Infinite queries, cache patching and retry come with it, and 2.5 to 2.8 reuse it. |
| "Needs approval first" | A separate query `status=waiting`, shown above the main list | Waiting runs are never paged away (mission 8). It was noted as a 2.4 concern in 2.3. |
| Waiting runs in "All runs" | Still listed in their date position | The main list stays the complete, truthful history. The top section only highlights them. |
| Filter state | URL search params | Links can be shared, and the view survives a reload or the back button. |
| Pagination | "Load more" button, 25 per page | It matches the cursor API, it is keyboard friendly, and it needs no virtualisation yet. |
| Template filter options | A static list of known template ids (`generate-docs`) | There is no templates API yet. It grows with 2.8. |

## Open questions
- None.
