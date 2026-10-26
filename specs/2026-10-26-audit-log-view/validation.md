# Validation: Audit log view for admins

## Done when (from roadmap)
> Every run and approval is listed per workspace

Checkable as: on `/audit`, every run of the workspace has a `run.created` (or `run.rerun`) entry, an ended run has a `run.ended` entry, and every gate decision has a `gate.approved` / `gate.rejected` entry. That includes runs and approvals made before the migration. Another workspace's activity is never listed.

## Automated checks
### Store (`packages/store/tests/test_audit.py`, Testcontainers Postgres)
- [ ] Each of these writes exactly one row with the right `action`, `run_id`, `node_id` and `details`: create run, rerun, first cancel request, approve, reject, add / remove a Claude key, connect / disconnect GitHub, update the policy, and update pricing.
- [ ] A refused action writes no row: over-policy run, decided gate, ended run cancel, invalid edits. A second cancel request writes none.
- [ ] `gate.approved` with edits has `edited_files` and paths but no file contents. Connection rows have the key hint and no secret.
- [ ] `UPDATE` and `DELETE` on `audit_events` raise.
- [ ] `list_audit_events`:
  - lists newest first, with stable cursor pages and no duplicates or gaps;
  - filters by action, run and date range;
  - never returns another workspace's rows.
- [ ] Sink: `run_completed`, `run_failed` and `run_cancelled` each add one `run.ended` with actor `system`. Other events add none.

### Migration
- [ ] `0019` upgrade on a database with existing runs (one rerun, one cancelled, one finished) and approvals backfills the matching rows with their original timestamps. Downgrade removes the table, trigger and function.

### API (`packages/api/tests/test_audit_api.py`)
- [ ] `GET /workspaces/{id}/audit` returns `200 {items, next_cursor}` with `actor` and the `run` ref.
- [ ] `404` for an unknown workspace. `422` for a bad cursor, a `limit` outside 1–200, or an unknown `action`.

### Web (Vitest + Testing Library)
- [ ] `describe(event)` gives the right line for every action, falls back for unknown actions, and ignores malformed `details`. Text is never rendered as HTML.
- [ ] The list shows a table from 768 px and cards below. The run id links to `/runs/<id>`, and the actor shows "System" or "—" with its tooltip.
- [ ] Skeleton, empty and error (Retry) states. Load more fetches the next cursor.
- [ ] Filters round-trip through the URL.
- [ ] The sidebar and drawer show "Audit log", and its breadcrumbs read "Audit log".

### End to end (Playwright, CI "Compose smoke test + e2e")
- [ ] `audit.spec.ts`: after a docs run with an approved gate, a rerun cancelled, and a run-limit change, `/audit` lists each action in order. The run filter narrows it to one run.
- [ ] axe finds no serious issues on `/audit`, light and dark.
- [ ] Screenshots at 375 / 768 / 1440 px show no horizontal page scroll.

### CI
- [ ] `ruff`, `pyright` strict, `pytest`, ESLint, Prettier, `tsc`, Vitest, and the compose e2e job are all green.
- [ ] OpenAPI client regenerated with no diff in CI.

## Manual / demo checks
- [ ] On an existing dev database, `docker compose up` (migration runs): `/audit` already lists past runs and approvals.
- [ ] Start a docs run, approve its gate with an edit and a comment. The audit row reads "Approved … with edits to 1 file · '<comment>'" and links to the run.
- [ ] Remove and re-add the Claude key. The rows show only the key hint.
- [ ] Lower "Agents alive" in Run limits. The row shows the before and after values.
- [ ] At 375 px the list shows cards and the filters stack; nothing scrolls sideways.
- [ ] `psql`: `DELETE FROM audit_events` fails with the append-only error.

## Merge criteria
- [ ] All checks above pass in CI (PR A: backend groups; PR B: web, e2e and the rest).
- [ ] `specs/tech-stack.md` has the audit contract and UI rules, merged with PR A before any UI is built.
- [ ] CHANGELOG entries under `[Unreleased]` in both PRs.
- [ ] No secrets or file contents in `audit_events` or application logs.
