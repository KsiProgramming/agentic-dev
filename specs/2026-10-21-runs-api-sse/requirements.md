# POST /runs + GET /runs/{id}/events (SSE)

Roadmap phase: 0.6
Branch: plan/0.6-runs-api-sse

## Context
Phase 0.5 writes every run step to the append-only `run_events` table, but a run can only be started from a test, and nobody outside Postgres can see it. This phase puts the run behind the HTTP API: a client starts a run and watches its events arrive live.

It depends on 0.4 (`run_workflow`) and 0.5 (`runs` / `run_events`, `PostgresEventSink`, `list_run_events`), both done. It unblocks 0.7 (a Claude run is started and watched the same way), 0.8 (the monitor page consumes this stream) and 1.3 (durable worker execution).

The tech stack fixes the shape: **API and workers are separate processes**, workers pull from a **Redis-backed queue**, and SSE fan-out uses **Postgres `LISTEN/NOTIFY`** on top of `run_events`. Principle **Transparency** (every action visible live) is the reason this phase exists; principle **Small, verifiable steps** keeps it to one endpoint pair on the fake runtime.

## Scope
### In scope
- `POST /runs` with body `{ "workflow": <WorkflowSpec>, "input": "<str>" }`. It validates the spec (422 on error), inserts a `runs` row with status `queued`, enqueues the run id on Redis and returns `202 { run_id, status, events_url }`.
- Migration `0003`: `runs.spec` (JSONB) and `runs.input` (text) so the worker loads the run from Postgres, and `queued` as a valid status. `PostgresEventSink` now moves an existing row to `running` on `run_started` instead of inserting it.
- `pg_notify('run_events', '<run_id>:<seq>')` in the same transaction as each event insert.
- Worker: a loop that takes run ids from the Redis queue (`BRPOP`), loads spec + input, runs `run_workflow` with a `PostgresEventSink` and handles one run at a time.
- The worker moves to a new `packages/worker` (`agentic_worker`) package that depends on engine + store, since store already depends on engine. Compose's `worker` command is updated.
- Worker runtime: `FakeRuntime` only. A worker setting `FAKE_STEP_DELAY_S` (default 0.5 s in compose, 0 in tests) puts a `Delay` between scripted events and streams the echo reply as several `text_delta`s, so a run is visibly live.
- `GET /runs/{id}/events`, using FastAPI's built-in `fastapi.sse.EventSourceResponse` / `ServerSentEvent`:
  - Each frame has `id: <seq>`, `event: <type>` and `data: <RunEvent JSON>`.
  - It replays stored events after `Last-Event-ID` (header) or `?after=<seq>`, then tails new ones.
  - The stream closes after the run's terminal event (`run_completed` / `run_failed` / `run_cancelled`), or right away after replay if the run has already finished.
  - 404 for an unknown run id. FastAPI sends a `: ping` keep-alive comment every 15 s.
- One `LISTEN` connection per API process (opened in the lifespan) that wakes per-run subscribers. On a wake-up the subscriber re-reads `run_events` after its last seq, so a missed or merged notification never loses an event.

### Out of scope
- `GET /runs` (list) and `GET /runs/{id}` (summary): the monitor (0.8) adds what it needs.
- Real providers / Claude (0.7). Choosing a runtime per request.
- Cancelling a run over HTTP. Retries, a dead-letter queue, worker concurrency > 1.
- Resuming a run after a worker crash (1.3). A run whose worker dies stays `running`.
- Auth, workspaces and tenancy (1.4).
- Stored, versioned workflows (`/workflows`, 4.1): the spec is sent inline.
- Batching or dropping `text_delta` rows.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Run execution | Redis queue → separate worker process | Tech stack: API and workers are separate and workers are stateless. An in-process task would be thrown away by 1.3. |
| Queue mechanics | Redis list, `LPUSH` / `BRPOP`, payload = run id only | Smallest thing that works. Spec and input live in Postgres, the single source of truth. A durable queue is for 1.3. |
| Who creates the `runs` row | API, status `queued` | `POST` can return an id the client streams right away. A run that never starts is still visible. |
| Worker package | New `packages/worker` | `store` → `engine`, so a worker inside `engine` cannot use `PostgresEventSink` without a cycle. |
| SSE implementation | `fastapi.sse.EventSourceResponse` (FastAPI 0.156, already locked) | Built in. No extra dependency such as `sse-starlette`. Supports `id` / `event` / comment frames. |
| Live fan-out | `LISTEN/NOTIFY` with one listener per API process, then re-query by seq | Tech-stack choice. The notification is only a wake-up and Postgres stays the source, so ordering and no-duplicates come from `seq`. |
| Resume | `Last-Event-ID` = seq, or `?after=` for curl | Standard SSE reconnect. `seq` is already unique and ordered per run. |
| Live demo on the fake runtime | `FAKE_STEP_DELAY_S` worker setting | "Done when" needs a run that streams over time. A setting keeps tests instant. |

## Open questions
- None.
