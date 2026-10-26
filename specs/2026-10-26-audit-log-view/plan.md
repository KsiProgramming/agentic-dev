# Plan: Audit log view for admins

Contract first, then backend (PR A: groups 1–4), then the web and end-to-end checks (PR B: groups 5–7). The project stays green after each group. PR B is the one that touches this spec folder.

## 1. Contract first (docs)
- [x] `specs/tech-stack.md`: add "Audit log (API contract)":
  - the `audit_events` columns and the append-only trigger;
  - the action table with who writes each action and its `details`;
  - `GET /workspaces/{id}/audit` (query, answer, `404` / `422`);
  - the rule that no file contents or secrets go in `details`.
- [x] Same file, UI design system:
  - Layout → App shell: the sidebar gains "Audit log";
  - a new "Audit log" subsection: columns, the per-action detail line, actor display, filters, Load more, Refresh.
- [x] Decisions-log row "Audit log".

## 2. Store: table, writers, backfill
- [x] `packages/store/src/agentic_store/models.py`: `AuditEvent` model and index `ix_audit_events_workspace_at`.
- [x] `packages/store/src/agentic_store/audit.py`:
  - `AuditAction` (a `Literal`) and `audit(session, workspace_id, action, *, actor_type="user", run_id=None, node_id=None, details={})`, which adds a row to the caller's session;
  - `list_audit_events(...)` with cursor encode/decode shared with `summaries.py` (move `encode_cursor` / `decode_cursor` into a small helper if needed).
- [x] `packages/api/alembic/versions/0019_audit_events.py`:
  - the table, the index, and a trigger function `audit_events_append_only()` raising on `UPDATE` / `DELETE`;
  - the backfill `INSERT … SELECT` from `runs` and `approvals`;
  - `downgrade` drops all of it.
- [x] Call `audit(...)` inside the existing transactions:
  - `runs.create_run`, `rerun.create_rerun`;
  - `cancel.request_cancel` (only when it sets `cancel_requested_at`);
  - `approvals.record_approval`: paths only, never `content`;
  - `connections.put_connection` / `put_github_connection` / `delete_connection`;
  - `policy.replace_policy_overrides` (read before, write after);
  - `pricing.replace_price_overrides` (diff by model).
- [x] `sink.PostgresEventSink.emit`: on `run_completed` / `run_failed` / `run_cancelled`, add `run.ended` (actor `system`) in the same transaction as the summary update.

## 3. API: `GET /workspaces/{id}/audit`
- [x] `packages/api/src/agentic_api/workspaces/models.py`: `AuditEventOut`, `AuditActor`, `AuditRunRef`, `AuditPage`.
- [x] `workspaces/routes.py`: the `listAuditEvents` route. It joins `runs` for `run {template_id, repo_url, status}`, maps `InvalidCursorError` to `422`, and an unknown workspace to `404`.
- [x] Export the OpenAPI schema; there is no client diff in PR A, because the web regenerates it in PR B.

## 4. Backend tests and PR A
- [x] `packages/store/tests/test_audit.py` (Testcontainers):
  - each action writes exactly one row with the right `details`;
  - a failed action (e.g. `ApprovalError`, `PolicyViolationError`) writes none;
  - a second cancel request writes none;
  - approval `details` carry paths, never contents. Connection `details` carry the key hint, never the key;
  - `UPDATE` / `DELETE` on `audit_events` raise;
  - listing: newest first, cursor, filters by action, run and date, and workspace isolation.
- [x] `packages/store/tests/test_sink.py`: the end events add one `run.ended` with actor `system`.
- [x] Migration test: upgrade over seeded runs and approvals backfills them in the right order; downgrade is clean.
- [x] `packages/api/tests/test_audit_api.py`: `200` page shape with the `run` ref, `404` unknown workspace, `422` bad cursor / limit / action.
- [ ] CHANGELOG entry (backend part). Open PR A.

## 5. Web: Audit log page
- [x] `npm run gen:api`.
- [x] `web/src/components/shell/nav.ts`: add `{ href: "/audit", label: "Audit log", icon: ScrollTextIcon }`; update `nav.test.ts` and `app-shell.test.tsx`.
- [x] `web/src/audit/`:
  - `actions.ts`: label, icon and category per action, and a `describe(event)` that turns `details` into one text line, defensive against bad payloads;
  - `filters.ts`: URL ↔ filters, mirroring `runs/filters.ts`;
  - `use-audit-events.ts`: TanStack `useInfiniteQuery` over the cursor;
  - `audit-list.tsx`: table from 768 px, cards below; skeleton, empty and error states; Load more;
  - `audit-filters.tsx`: category, run id and date range.
- [x] `web/src/app/audit/page.tsx`: page header with a Refresh action, the filters and the list.

## 6. Web tests
- [x] Vitest:
  - `actions.test.ts`: every action's label and line, unknown actions, and malformed `details`;
  - `filters.test.ts`;
  - `audit-list.test.tsx`: rows and cards, run link, actor display, the three states, Load more.

## 7. End to end, demo and wrap-up
- [ ] Playwright `web/e2e/audit.spec.ts` (fake runtime, fake GitHub):
  - start a docs run, approve its gate with a comment, and let it finish;
  - rerun it and cancel the rerun;
  - change a run limit;
  - `/audit` lists, newest first: `policy.updated`, `run.cancel_requested`, `run.ended`, `run.rerun`, …, `gate.approved`, `run.created`;
  - the run filter narrows to one run.
- [x] Add `/audit` to `a11y.spec.ts` (light and dark) and `layout.spec.ts` (375 / 768 / 1440 px).
- [ ] Manual demo (see validation.md).
- [ ] CHANGELOG entry (web part). Open PR B; CI marks 3.7 done.
