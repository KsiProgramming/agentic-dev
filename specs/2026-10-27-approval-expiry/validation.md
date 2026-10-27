# Validation: Approval expiry

## Done when (from roadmap)
> A gate past its time to live cancels its run cleanly, drops out of every waiting count and shows "Expired" with the reason

"Cleanly": the run ends `cancelled` through the normal cancel path (sandbox removed, `run_cancelled` written by a worker, `run.ended` audit row), not by an API write. "Every waiting count": the sidebar badge, the page-title prefix and the "Needs approval" filter.

## Automated checks
- [ ] Engine: `Policy` loads a frozen policy without `approval_ttl_s` (72 h); a workspace cannot raise it; a gate with `ttl_s` above it gives a `policy_limit` issue (`limit: "approval_ttl_s"`); `gate_waiting` carries `expires_at` = event time + the gate's `ttl_s`, else the policy's.
- [ ] Store (Testcontainers Postgres): the sink sets `gate_expires_at` and `waiting_gate.expires_at` on `gate_waiting` and clears them on resume, decision and end; `run_cancelled` sets `cancel_reason`.
- [ ] Store: `expire_gates` expires only waiting runs past their time with no decision; it writes `gate.expired`; two concurrent sweeps expire each run once.
- [ ] Store: `record_approval` past `gate_expires_at` raises `GateExpiredError`; `request_cancel` keeps an existing reason.
- [ ] Migration `0021`: upgrade gives a waiting run paused 4 days ago a past `gate_expires_at`, one paused an hour ago a future one; downgrade drops the columns.
- [ ] Worker (fake runtime, temp-dir sandboxes): a run with a `ttl_s=1` gate ends `cancelled`, its last event `run_cancelled {reason: "Approval expired", expired: true}`, sandbox gone, audit has `gate.expired` and `run.ended`; a user cancel still writes "cancelled by user".
- [ ] API: `GET /runs` / `GET /runs/{id}` for a waiting run (`waiting_gate.expires_at`) and an expired run (`status: cancelled`, `expired: true`, `cancel_reason: "Approval expired"`); `?status=waiting` no longer lists it; policy `GET`/`PUT` with `approval_ttl_s` (above 259 200 → `422`); `POST /workflows/{id}/validate` with a gate over the workspace's limit gives the `policy_limit` issue (the same validator `POST /runs` uses). Late approval → `409` is checked in the store and the e2e test.
- [ ] Web unit (Vitest): `badgeStatus` / `statusLabel` give "Expired" in Cancelled's tone; waiting count and title prefix skip a waiting run past `expires_at`; `ExpiresIn` ("Expires in 2 d", "Expires in 12 min", ticking, tooltip); dock shows it; console status for an expired `run_cancelled`; limits form field in hours.
- [ ] E2E (Playwright): a run with an 8 s gate shows "Expires in", then "Expired" with "Approval expired" in the console and the runs list, is gone from "Needs approval" and `?status=waiting`, and a late approval gets `409` (the sidebar count is covered by the unit test, since other e2e runs wait in parallel); `a11y.spec.ts` (axe) and `layout.spec.ts` screenshots at 375 / 768 / 1440 pass.
- [ ] `uv run pytest`, `ruff`, `pyright`; `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`.

## Manual / demo checks
- [ ] None required beyond the e2e run (decided in the interview); screenshots from `layout.spec.ts` are reviewed in the PR.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `openapi.json`, `schema.d.ts` and the workflow JSON Schema regenerated and committed
- [ ] tech-stack (UI v2 entry moved into the main rules, contracts, limits, audit table), `CLAUDE.md` rule 3 and `CHANGELOG.md` updated in the same PR
- [ ] No expired run counts as waiting anywhere in the UI; the expiry never approves or rejects a gate
