# Active and waiting time

Roadmap phase: 11.2
Branch: plan/11.2-active-waiting-time

## Context
Every duration in the product today is wall clock: `RunSummary.duration_ms` is `finished_at − started_at`, the console header computes the same from the event stream, and a gate step's duration is the time it waited for a human. A run that waited a weekend for approval reads as a 60-hour run. Mission principle 8 says "a run's duration is the time it worked, never the time it waited for a human", and tech-stack → UI v2 → Time (11.2) splits a run's time into *active*, *waiting* and *wall clock*.

The engine already knows what "active" means: the wall-time limit counts only executing time (`agentic_store.policy.active_seconds`, a window query over the event log). 11.2 projects that same definition onto the `runs` row, adds waiting time beside it, and shows both.

Depends on 11.1 (done, #129): `Duration`, `RelativeTime` and the display-component rules. Unblocks 11.4 (Duration column = active + waiting chip), 11.5 (waiting time in the Inbox) and 11.6 (Active time stat tile).

Drivers: mission principles 8 (truthful numbers) and 6 (transparency); tech-stack → "Run history and rerun (API contract)" (summaries are a projection kept in the `runs` row, listing never scans the log), → "UI v2 → Time (11.2)", decisions log "Run durations (11.2)"; `CLAUDE.md` rule 4.

## Scope
### In scope
- **Definitions** (the same in the store, the API, the worker and the console):
  - *Active*: each stretch from `run_started` or `run_resumed` to `gate_waiting` or the run's end event. A crashed attempt counts until its last event (as `active_seconds` does today); the gap before the next attempt counts as neither.
  - *Waiting*: each stretch from `gate_waiting` to `run_resumed`, or to the end event when a waiting run is cancelled. The short queue time between a decision and the resume is counted as waiting.
  - *Wall clock*: `started_at` to `finished_at` (or now).
- **Projection in the `runs` row:** new columns `active_ms` (bigint, null before the run starts), `waiting_ms` (bigint, default 0), `active_since` and `waiting_since` (timestamptz, the start of the open stretch, null when none is open). `PostgresEventSink` updates them in SQL with each `run_started`, `gate_waiting`, `run_resumed` and end event (`summary_values`).
- **Migration** `0020`: adds the columns and backfills them for **live runs only** (`queued`, `running`, `waiting`) from their events, so the wall-time limit and the console stay right for runs in flight at deploy. Ended runs created before 11.2 keep `active_ms = null` and show "—".
- **API:** `RunSummary` (so `GET /runs` and `GET /runs/{id}`) gains `active_ms: int | null` and `waiting_ms: int`, each including its open stretch up to the time of the response. `duration_ms` stays, deprecated in the OpenAPI schema, described as wall clock. The OpenAPI file and `web/src/api/schema.d.ts` are regenerated.
- **Wall-time limit:** `active_seconds` reads the projected columns (`active_ms` plus an open stretch up to the run's last event) instead of scanning the log. The worker's behaviour does not change.
- **Display:** a new `WaitingTime` component in `@/components/display`: "waiting 12 h"-style while the run waits (ticking), "waited 1m 52s" after; renders nothing when no time was waited. `RelativeTime` takes an optional extra tooltip line, used for the wall clock on the start time ("2h 03m start to end").
- **Runs list:** the Duration cell (table and card) shows active time, then `· waited …` / `· waiting …` when waiting time > 0. A live run's open stretch keeps ticking from the time the summary was received. The Started time's tooltip adds the wall clock.
- **Console header:** active time with the waiting chip, derived live from the event stream (the timeline builder tracks the stretches the same way as the sink), the summary's values before events arrive. Wall clock in the Started tooltip.
- **Gate steps** in the console timeline show a `WaitingTime` chip instead of a `Duration`, so no step duration counts human waiting.
- **Specs and docs, in the same PR:** tech-stack moves "Time (11.2)" from UI v2 into the main rules (Display values gets a `WaitingTime` row and the wall-clock tooltip; the run-history contract lists `active_ms` / `waiting_ms` and the deprecated `duration_ms`); a decisions-log row for the projection; `CLAUDE.md` rule 3 table gets `WaitingTime`, rule 4 drops "Until 11.2 ships…"; `CHANGELOG.md` entry.

### Out of scope
- Backfilling ended runs created before 11.2 (they show "—"; decided in the interview).
- Removing `duration_ms` from the API (kept, deprecated; a later cleanup).
- Approval expiry and "time left" (11.3); the runs list redesign and its columns (11.4); the Inbox (11.5); the Active time stat tile (11.6).
- Per-node active time inside agent steps (tool calls and agent turns already measure their own work, not gates).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where the times are recorded | Projection on the `runs` row, kept by `PostgresEventSink` | Same pattern as the other summary columns: listing never scans the log, and no event payload changes. Engine-side payload durations would need engine changes and make crashed attempts harder. |
| Open stretch | Stored totals + `active_since` / `waiting_since`; the API adds the open stretch up to now | Totals change only on boundary events, so no write per tick; the API answer is current. |
| Queue time after a decision | Counted as waiting | The run is not working; the gap is usually under a second, and `run_resumed` is the only event that ends it (`gate_decided` is written by the gate node after the resume). |
| Wall-time limit | Reads the projected columns | One definition of active time for the limit and the UI, and no log scan when a worker claims a run. |
| Old runs | Backfill live runs only; ended ones show "—" | Runs in flight at deploy must keep a correct limit and console; history before 11.2 is not worth a full log replay. |
| `duration_ms` | Kept, deprecated, documented as wall clock | No breaking change for API clients; the web stops reading it. |
| Waiting display | A new `WaitingTime` display component | `CLAUDE.md` rule 3: each kind of value has one component. |

## Open questions
- None
