# Approval expiry

Roadmap phase: 11.3
Branch: plan/11.3-approval-expiry

## Context
A gate waits forever today. Runs nobody approves stay `waiting`, keep their sandbox, and count in every waiting signal (the sidebar badge, the "(N) ● Needs approval" title prefix, the "Needs approval" filter), so the real ones drown among stale ones. Mission principle 8 says "an approval nobody gives expires instead of waiting forever", and tech-stack → UI v2 → "Approval expiry (11.3)" and the decisions-log row "Approval expiry (11.3)" fix the shape: a time to live per gate, expiry cancels the run with a reason, no new run status.

Depends on 11.2 (done, #130): `waiting_since` on the `runs` row dates the open wait, which the migration uses for gates that paused before 11.3. Unblocks 11.5 (the Inbox shows time left before expiry) and 11.6 (the console banner shows time left).

Drivers: mission principles 2 (limits enforced by the engine, not the graph), 3 (gates stay mandatory: expiry never approves), 6 and 9 (the history stays truthful: the reason is kept); tech-stack → "Security & secrets" (policy limits are platform ceilings a workspace may lower, frozen on the run), "Run history and rerun" (`POST /runs/{id}/cancel`: only workers write events), "Audit log".

## Scope
### In scope
- **Time to live as a policy limit:** `approval_ttl_s` in `Policy` / `PolicyOverrides` (`agentic_engine.policy`). Platform default and ceiling 72 h (259 200 s); a workspace may lower it (`PUT /workspaces/{id}/policy`, a field in the "Run limits" card). Frozen on the run with its other limits; a run created before 11.3 reads the platform default (the field has a default in `Policy`).
- **Per gate:** `GateNode.ttl_s` (optional, whole seconds ≥ 1). Validation refuses a gate whose `ttl_s` is above the run's `approval_ttl_s` with a `policy_limit` issue (`limit: "approval_ttl_s"`), at `POST /workflows/{id}/validate`, `POST /runs` and rerun.
- **Expiry time on the pause:** the gate's interrupt carries its time to live (`ttl_s`, else the policy's); `gate_waiting` adds `expires_at` (event time + ttl). The sink projects it into a new `runs.gate_expires_at` column and into `waiting_gate.expires_at`; `run_resumed`, `gate_decided` and end events clear it.
- **Expiry sweep in the worker:** each worker, between runs and at most every `gate_sweep_s` (default 30 s), calls `expire_gates()` (`agentic_store.expiry`): in one transaction per run, every `waiting` run with `gate_expires_at <= now()` and no decision gets `cancel_requested_at`, `cancel_reason = 'Approval expired'`, `status = queued` (like a user cancel), a `gate.expired` audit row (actor `system`, `node_id`, `details: {title, expires_at}`); the ids are enqueued. The existing cancel path then ends it: sandbox discarded, `run_cancelled` with `{reason: "Approval expired", expired: true}`.
- **Cancel reason:** a new `runs.cancel_reason` column. `request_cancel` sets "cancelled by user" (only if none is set); `_end_cancelled` writes the stored reason. The sink projects `run_cancelled`'s reason into `cancel_reason`.
- **Late decisions:** `POST /runs/{id}/approvals` on a gate past `gate_expires_at` answers `409` ("approval expired") even before the sweep ran.
- **API:** `RunSummary.waiting_gate.expires_at` (datetime, null for a gate paused without one), `RunSummary.cancel_reason` (str | null) and `RunSummary.expired` (bool). `GET /workspaces/{id}/policy` and `PUT` carry `approval_ttl_s`. OpenAPI and `web/src/api/schema.d.ts` regenerated.
- **Migration `0021_approval_expiry`:** adds `runs.gate_expires_at`, `runs.cancel_reason`, `workspace_policies.approval_ttl_s`; sets `gate_expires_at = waiting_since + 72 h` for every `waiting` run, so stale ones expire on the first sweep after deploy (the "expired once by a migration" of the roadmap, without Redis in a migration).
- **Web:**
  - Status: an expired run shows `StatusBadge` with Cancelled's grey and the label "Expired", in the runs list, the console header and the runs filter results; the reason "Approval expired" where a cancelled run's reason shows. `badgeStatus` / `statusLabel` take the summary's `expired`; the console's `displayStatus` reads `expired` from `run_cancelled`.
  - Waiting counts: expired runs are `cancelled`, so they drop out of the sidebar badge, the title prefix and the "Needs approval" filter; the client also ignores a waiting run whose `expires_at` has passed, so counts never lag the sweep.
  - Approval dock: "Expires in 2 d" (or "Expires in 12 min") next to the title, from `expires_at`, through a new `ExpiresIn` display component (a moment ahead, ticking; exact time in the tooltip).
  - Settings → Run limits card: an "Approval time to live" field in hours, with the 72 h maximum as help text.
- **Specs and docs, in the same PR:** tech-stack moves "Approval expiry (11.3)" from UI v2 into the main rules (Display values gets `ExpiresIn`; "Gate review" and "Run history" contracts get `expires_at`, `cancel_reason`, `expired`; "Security & secrets" lists the new limit; "Audit log" table gets `gate.expired`); `CLAUDE.md` rule 3 table gets `ExpiresIn`; `CHANGELOG.md` entry.

### Out of scope
- Time left in the Inbox list (11.5) and the console's waiting banner (11.6); the dock's "Expires in" is the only surface now.
- Reminders or notifications before expiry (no notification channel yet).
- Expiry that rejects instead of cancelling, or that auto-approves (mission principle 3: never).
- A new `expired` run status (decisions log: no new status).
- Extending a gate's time to live once it is waiting.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where the time to live lives | `approval_ttl_s` policy limit (72 h default and ceiling, workspace may lower, frozen on the run) + optional `GateNode.ttl_s` ≤ it | Same model as the other limits (tech-stack decisions log "Policy limits"): safe by construction, and a stop can be explained by the limits the run was given. |
| When a gate expires | `gate_waiting.created_at + ttl`, stored as `expires_at` in the event and `runs.gate_expires_at` | The log says when it will expire; the column makes the sweep one indexed query; a later policy change never moves a gate already waiting. |
| Who ends the run | A periodic sweep in every worker that requests a cancel; the existing cancel path writes the events | Only workers write events (tech-stack, cancel contract). Reusing cancel discards the sandbox and writes `run_cancelled` with no new code path. Lazy expiry on read would leave unread runs waiting forever. |
| Reason | `runs.cancel_reason` + `run_cancelled.payload.expired = true`; API `cancel_reason` and `expired` | The UI decides "Expired" from a flag, not by matching text; the reason stays readable in the history and audit. |
| Stale runs at deploy | Migration sets `gate_expires_at = waiting_since + 72 h`; the first sweep expires them | A migration cannot enqueue on Redis; letting the normal path end them writes the same events and audit rows as any expiry. |
| Late approval | `409` once `gate_expires_at` has passed | A decision never races the sweep: what the dock says expired is expired. |
| Minimum per-gate ttl | 1 s, like every other limit | A gate expires on the first sweep after its time; tests and demos use a few seconds with a short `GATE_SWEEP_S`. |

## Open questions
- None
