# Plan: Approval expiry

Backend first (spec and policy, projection and migration, worker sweep, API), then the web. The project builds and its tests pass after each group.

## 1. Policy limit and gate field
- [x] `packages/engine/src/agentic_engine/policy.py`: `approval_ttl_s` in `Policy` (default `72 * 60 * 60`, so frozen pre-11.3 policies still load), `PolicyOverrides`, `PLATFORM_POLICY`, `PolicyLimit` and `LIMIT_LABELS` ("approval time to live").
- [x] `packages/engine/src/agentic_engine/spec/models.py`: `GateNode.ttl_s: int | None` (≥ 1, "Seconds the gate waits for a decision before the run is cancelled; at most the run's `approval_ttl_s`").
- [x] `packages/engine/src/agentic_engine/spec/validate.py` → `policy_issues`: a gate with `ttl_s > policy.approval_ttl_s` gives a `policy_limit` issue (`limit`, `value`, `observed`, path and node id).
- [x] Re-export the JSON Schema (`schemas/`).
- [x] Engine tests: policy defaults and overrides (lower only), old policy JSON without the field loads, validation issue for a too-long gate.

## 2. Expiry time on the pause
- [x] `packages/engine/src/agentic_engine/gate.py` / `graph/compile.py`: the gate node's interrupt request carries `ttl_s` (the gate's, else the run policy's).
- [x] `packages/engine/src/agentic_engine/graph/run.py` → `_wait`: `gate_waiting` payload gets `expires_at` (ISO, the event's time + `ttl_s`); `ttl_s` stays in the payload too.
- [x] Engine tests: `gate_waiting` has `expires_at` from the gate's own ttl and from the policy's.

## 3. Projection and migration
- [x] `packages/store/src/agentic_store/models.py`: `Run.gate_expires_at`, `Run.cancel_reason` (with an index on `gate_expires_at` where `status = 'waiting'`), `WorkspacePolicy.approval_ttl_s`.
- [x] `packages/store/src/agentic_store/sink.py` → `summary_values`: `gate_waiting` sets `gate_expires_at` and `waiting_gate.expires_at`; `run_resumed`, `gate_decided` and end events clear `gate_expires_at`; `run_cancelled` sets `cancel_reason` from its `reason`. Docstring table updated.
- [x] `packages/api/alembic/versions/0021_approval_expiry.py`: the three columns and the index; `UPDATE runs SET gate_expires_at = waiting_since + interval '72 hours' WHERE status = 'waiting'` (and `waiting_gate.expires_at` to match); downgrade drops them.
- [x] `packages/store/src/agentic_store/policy.py`: read and write `approval_ttl_s` with the other overrides.
- [x] Store tests (Testcontainers): projection set and cleared; migration upgrade on a stale waiting run and a fresh one, downgrade.

## 4. Sweep, cancel reason and late decisions
- [x] `packages/store/src/agentic_store/expiry.py`: `APPROVAL_EXPIRED_REASON = "Approval expired"`; `expire_gates(sessions) -> list[UUID]`: lock expired waiting runs (`FOR UPDATE SKIP LOCKED`, no approval recorded for the gate), set `cancel_requested_at`, `cancel_reason`, `status = queued`, lease cleared, `attempt = 0`, and an audit row `gate.expired` (actor `system`, `node_id`, `details: {title, expires_at}`) per run.
- [x] `packages/store/src/agentic_store/cancel.py`: `request_cancel` sets `cancel_reason = coalesce(cancel_reason, 'cancelled by user')`; `cancel_reason(sessions, run_id)` reader. Export from `agentic_store/__init__.py`.
- [x] `packages/store/src/agentic_store/approvals.py` → `record_approval`: `GateExpiredError` (a `RunNotWaitingError`) when `gate_expires_at <= now()`.
- [x] `packages/worker/src/agentic_worker/main.py`: `WorkerSettings.gate_sweep_s` (default 30); in the main loop, sweep when due and enqueue what it returns; `_end_cancelled` and the running-run cancel path write the stored reason, with `expired: true` when it is `APPROVAL_EXPIRED_REASON`. Module docstring updated.
- [x] `docker-compose.yml`: `GATE_SWEEP_S` (default 30); CI's e2e stack sets `GATE_SWEEP_S=1`.
- [x] Tests: `expire_gates` (expired, not yet, decided, already queued, two workers sweeping at once); worker end to end on the fake runtime: a gate with `ttl_s=1` ends `run_cancelled` `{reason: "Approval expired", expired: true}`, sandbox discarded, `gate.expired` and `run.ended` audit rows; a user cancel still says "cancelled by user"; approval past `expires_at` raises.

## 5. API contract
- [x] `packages/api/src/agentic_api/runs/models.py`: `WaitingGate.expires_at: datetime | None`; `RunSummary.cancel_reason: str | None`, `RunSummary.expired: bool`.
- [x] `packages/store/src/agentic_store/summaries.py` + `runs/routes.py` → `_summary_fields`: select and map them.
- [x] `runs/routes.py` → approvals: `GateExpiredError` → `409` "approval expired".
- [x] `packages/api/src/agentic_api/workspaces/models.py` / routes: `approval_ttl_s` in the policy read and write models.
- [x] API tests: summaries of an expired run and a waiting one; policy `GET`/`PUT` with `approval_ttl_s` (above the ceiling → 422); `POST /runs` with a gate over the limit → 422; late approval → 409.
- [x] `scripts/export_openapi.py` → `web/openapi.json`, regenerate `web/src/api/schema.d.ts`.

## 6. Web: status, counts and the dock
- [x] `web/src/runs/summaries.ts`: `expiredLabel(run)` ("Expired" or the status's own wording) for the badge, `runStatusLabel(run)` for announcements, `gateExpired(run, now)`, `formatTimeLeft`; `badgeStatus` keeps Cancelled's tone. Used by the runs list (table and cards), the runs view and the console header.
- [x] `web/src/runs/timeline.ts`: the timeline keeps `cancelReason` and `expired` from `run_cancelled`; `headerFacts` words a cancelled run "Expired" from it (or the summary's `expired`), and the console shows the reason in a neutral alert above the timeline.
- [x] Waiting counts (`components/shell/attention.tsx`: sidebar badge and title prefix; `runs/runs-view.tsx`: "Needs approval"): a waiting run whose `waiting_gate.expires_at` has passed is not counted. `runs/gates.ts` reads the gate's `expiresAt`.
- [x] `web/src/components/display/expires-in.tsx`: `ExpiresIn({ at, focusable })` → "Expires in 2 d" / "Expires in 12 min" / "Expired", ticking with `useNow`, exact time in the tooltip, through `@/lib/locale`; export from `index.ts`.
- [x] Approval dock: `ExpiresIn` beside the title from the `gate_waiting` payload's `expires_at` (nothing for a gate without one).
- [x] Settings → Run limits card: "Approval time to live" in hours (converted to `approval_ttl_s`), max 72 as help text, same validation and save as the other limits.
- [x] Unit tests: `badgeStatus` / `statusLabel`, waiting counts with an expired gate, `ExpiresIn`, dock, timeline status, limits form field.

## 7. E2E and specs
- [x] `web/e2e/runs.ts`: `EXPIRING_GATE` (`ttl_s: 8`, so the dock is seen before it expires); `web/e2e/expiry.spec.ts`: start a run with it, see "Needs approval" with "Expires in", then "Expired" in the console and the runs list, the sidebar badge cleared; axe on the expired console.
- [x] `specs/tech-stack.md`: move "Approval expiry (11.3)" from UI v2 into the main rules (Display values `ExpiresIn`, run-history and gate-review contracts, Security & secrets limit list, Audit log `gate.expired` row); `CLAUDE.md` rule 3 table gets `ExpiresIn`; `CHANGELOG.md` under `[Unreleased]`.
