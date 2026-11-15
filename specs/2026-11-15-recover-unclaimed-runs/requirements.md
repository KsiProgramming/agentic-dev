# Recover runs lost before a worker claims them

Roadmap phase: 12.1
Branch: plan/12.1-recover-unclaimed-runs

## Context

First phase of Milestone 12 (Nothing is lost), which the roadmap's "Next up" line puts after Milestone 6, now fully done. Promoted from the idea "Recover runs lost between the queue and the worker" (`ideas.md`, seen on 2026-11-02).

Today a run is announced on a Redis list (`agentic_store.queue`) and owned through its lease in Postgres (`agentic_store.lease`). Popping the id removes it from Redis, so two gaps lose a run:

- **A worker dies between `dequeue_run` and `claim_run`.** The id is gone and the run is `queued` with no lease, so `reclaim_expired_run` (1.3) never sees it. The run stays "Queued" for good, and the console shows "Waiting for the run to start…" without saying why.
- **The stored spec cannot be parsed by this worker** (2026-11-02: a worker older than 5.4 could not parse `budget_usd`). `stored_run()` parses the spec inside `_claimed`'s transaction, so the claim rolls back, the id is already gone, and the exception goes up through `_next_run` and stops the worker loop. The reclaim path has the same flaw: a run with a spec no worker can parse would stop every worker that reclaims it, one after the other.

Runs that a gate decision (`approvals`) or an expiry (`expiry`) queues again are also `queued` with no lease, so they fall into the same gap.

Principles: **9. Nothing is lost** (every run reaches an outcome), **6. Transparency** (a stuck run says why) and **8. Calm UI** (what needs the user is visible). Tech stack: workers pull from a Redis-backed queue, and Postgres holds run state (Backend → Run workers). The sweep has the same shape as 11.3's gate sweep (decisions log → "Expiry mechanics").

The phase does not change what agents receive, so lessons.md rule 1's real Claude run does not apply. It unblocks nothing directly. 12.2–12.4 build on the same worker loop.

## Scope

### In scope
- **Postgres is the queue's source of truth.** A new `queued_at` column (set whenever a run becomes `queued`: on creation, after a gate decision, a cancel or an expiry while waiting) and `enqueued_at` (the last time the sweep pushed it; the API's own pushes need not write it, since staleness is `GREATEST(queued_at, enqueued_at)`).
- **A queue sweep in every worker,** beside `_sweep_gates`: when the worker starts and every `QUEUE_SWEEP_S` (default 15 s), the runs that are `queued` with no lease, `queued_at` older than `QUEUE_STALE_S` (default 60 s) and `enqueued_at` older than the same threshold are locked (`SKIP LOCKED`), given a new `enqueued_at`, and pushed to Redis again. Pushing an id twice is harmless: `claim_run` takes it only once and skips the rest.
- **A spec this worker cannot load fails the run, not the worker.** The claim commits first; the spec is parsed after it. A parse error (a new claim or a reclaim) ends the run `failed` with `failure_reason = "this worker cannot load the run's spec: <error>"`, releases it, and the worker goes on to the next run. The `run_started` written first uses the raw spec's `id` and `name` where present.
- **API:** `GET /runs/{id}` (and the summaries in `GET /runs`) return `queued_at` and `queue_stalled_at` (while queued with no live lease, `queued_at` plus `QUEUE_STALE_S`, read from the same setting as the worker; else `null`). A timestamp rather than the planned `queue_stalled` boolean: nothing is written when a run becomes stalled, so the runs stream would never push the change, and the client compares the time with its own clock.
- **Console:** a queued run's empty state shows "Queued <RelativeTime>" in place of "Waiting for the run to start…", and, once past `queue_stalled_at`, a hint: "No worker has picked this run up yet. Check that a worker is running."
- Specs: tech-stack (queue and lease rules, run history contract, decisions-log row), `ideas.md` entry's open questions answered, CHANGELOG.

### Out of scope
- **A spec schema version check** (a worker refusing a newer spec and leaving it to a newer worker instead of failing it). It stays an open question in `ideas.md`. Failing with a clear reason and rerunning from a current worker (2.6) covers it for now.
- **The sweep in the API.** Only workers write run state that drives the queue, as for 11.3.
- Saving writers' code outside the sandbox: 12.2. Keeping a failed run's sandbox: 12.3. Rerun from a step: 12.4.
- Replacing Redis with a Postgres queue (`LISTEN/NOTIFY`, `SKIP LOCKED` polling). Redis stays the fast path; the sweep is the safety net.
- New e2e or layout specs. The console change reuses `EmptyState` and `RelativeTime`.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Who sweeps | Every worker, a task beside `_sweep_gates`, rows locked `SKIP LOCKED` | Same model as 11.3. With no worker, nothing can run anyway, and the console hint says so. |
| Source of truth | Postgres (`status = 'queued' AND lease_expires_at IS NULL`), Redis only announces | `claim_run` already decides by the lease; the sweep makes "announced" recoverable. |
| When a run is stale | `queued_at` and `enqueued_at` both older than `QUEUE_STALE_S` (60 s) | Well above `queue_poll_s` (1 s) and a claim's round trip, so a run a live worker is about to claim is rarely pushed twice. A double push is harmless anyway, and `enqueued_at` stops the sweep from pushing the same id every tick. |
| Two columns, not one | `queued_at` for people (the console), `enqueued_at` for the sweep | Pushing an id again must not reset "Queued 4 min ago". |
| Unloadable spec | Parse after the claim commits; fail the run with a fixed-prefix reason and release it | The run reaches an outcome (principle 9) and one bad row cannot stop every worker. A rerun from a current worker recovers it. |
| Stalled flag | `queue_stalled_at`, computed by the API from `QUEUE_STALE_S`; the browser compares it with its clock | One threshold, read by both processes from one env var; the web never guesses it, and the hint appears on time without a write to push it. |
| Upgrade order | The deployment guide rolls workers out before the API | A newer worker reads an older API's specs; an older worker now fails a run whose spec a newer API wrote. |

## Open questions
- None. The idea's version-check question stays open in `ideas.md` (out of scope above).
