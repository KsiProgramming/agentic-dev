# Durable execution with the Postgres checkpointer

Roadmap phase: 1.3
Branch: plan/1.3-durable-execution-checkpointer

## Context
Today a run lives only in its worker's memory. The worker pops the run id off the Redis list (`BRPOP`). It compiles the graph with no checkpointer and runs it to the end. If the worker dies, three things happen:
- The job is gone.
- The run stays `running` forever.
- The next worker's startup sweep deletes the run's sandbox as an orphan.

The queue module and the sandbox sweep both say "durable execution comes later". This phase is that later. It covers AC-8 and the mission's reliability goal: "a worker restart mid-run loses no completed nodes".

It depends on these phases, all done:
- 0.4: the compiled LangGraph graph and `RunState`.
- 0.5/0.6: the `run_events` log and `runs` table.
- 1.1/1.2: the per-run sandbox and its `repo` tools.

It unblocks:
- 1.7: `gate` uses `interrupt()`, which needs a checkpointer to pause and resume.
- 1.9/1.10: loops and map, which are longer runs where a lost worker costs more.
- 5.x: dynamic fan-out with `Send`, which checkpoints each step.

Principles and stack choices that apply:
- **Tech stack, "Durable state":** the LangGraph Postgres checkpointer (`langgraph-checkpoint-postgres`, `AsyncPostgresSaver`). We don't build our own snapshot format.
- **Tech stack, "Run workers":** workers are "stateless apart from checkpoints". Any worker can pick up any run.
- **Transparency (6):** a resume is visible in the append-only log. Events from the lost attempt are never rewritten.
- **Small, verifiable steps (7):** resume works at node granularity. A node that was cut off runs again from its start. Nothing is resumed inside an agent's tool loop.

## Scope
### In scope
- **Engine (no database):**
  - `compile_workflow` takes an optional LangGraph `BaseCheckpointSaver`.
  - `run_workflow` runs with `thread_id = run_id`.
  - A new `resume_workflow(spec, runtime, run_id, checkpointer, sink, next_seq, attempt)` continues with `ainvoke(None, config)`. A node that already completed is not run again.
  - It emits a new `run_resumed` event (payload: `attempt`, `completed_nodes`) and then carries on with the usual node and run events.
  - `RunEventLog` can start at a given `seq`, so the log stays gap-free across attempts.
  - `agentic_engine` still does not depend on Postgres (`test_no_database.py` stays green).
- **Store:**
  - Add `langgraph-checkpoint-postgres` and `psycopg[binary,pool]`.
  - `open_checkpointer(database_url)` builds an `AsyncPostgresSaver` from the same `DATABASE_URL`, turning `postgresql+asyncpg://` into `postgresql://`.
  - `max_event_seq(run_id)`.
  - Lease functions: `claim_run`, `renew_lease`, `release_run`, `reclaim_expired_run`.
- **Schema (Alembic):**
  - `runs` gets `worker_id`, `lease_expires_at` and `attempt`.
  - A separate migration creates the checkpointer's tables by calling the saver's `setup()`, so Alembic owns the whole schema.
- **Worker, lease and reclaim:**
  - Claim a run atomically (`UPDATE … WHERE … RETURNING`), keep the lease alive with a heartbeat, and release it when the run ends.
  - At startup and on every idle poll, reclaim one `queued` or `running` run whose lease has expired (`FOR UPDATE SKIP LOCKED`), then resume it.
  - Redis stays the "new run" notification. Postgres is the truth about who owns a run.
- **Graceful stop:** on SIGTERM the worker releases its lease, and the run is left to resume. It no longer writes `run_cancelled`. A `docker compose stop` is now a drain, not a cancellation.
- **Attempt cap:** a run reclaimed more than `max_attempts` times (default 3) ends `run_failed` with a clear reason, so a run that crashes the worker every time can't loop forever.
- **Sandbox on resume:** the reclaiming worker removes the run's old container, if any, and opens a fresh clone. Phase 1.2 tools are read only, so no work is lost. The blanket startup `sweep_orphans` is narrowed to sandboxes whose run is not leased by a live worker.
- A 3-node fake fixture (`three-step-sequence.json`) and a README section for the kill/restart demo.

### Out of scope
- Resuming inside a node (mid tool loop, partial agent output): a node that was cut off reruns in full. Its tokens are spent twice. That is acceptable until cost tracking (2.1) makes it visible.
- User-initiated cancel (`POST /runs/{id}/cancel`): not on the roadmap yet. A graceful stop no longer cancels.
- Keeping a writer's worktree or branch across a resume: 1.6 decides that once there are writes to keep.
- Checkpoint retention and cleanup: later (with 2.7 audit or ops work).
- Gates and `interrupt()`: 1.7. This phase only provides the checkpointer they need.
- A Testcontainers kill-worker integration test: not chosen for this phase (see Open questions).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Detecting a dead worker | Lease plus heartbeat on `runs` (`worker_id`, `lease_expires_at`) and reclaim from Postgres | This was the user's choice. It works with N workers, doesn't depend on Redis keeping in-flight state, and keeps Postgres as the one source of truth. |
| Lease timing | TTL 30 s, heartbeat every 10 s, both set in `WorkerSettings` | A killed worker's run is picked up within about 30 s locally. Tests can shorten both. |
| Checkpointer | `AsyncPostgresSaver` from `langgraph-checkpoint-postgres`, `thread_id = run_id` | The tech stack fixes it. Resuming is `ainvoke(None, config)` on the same thread (LangGraph docs, "Resuming after an error"). |
| Driver | psycopg for the saver, next to asyncpg for SQLAlchemy | The saver needs psycopg. Both read the same `DATABASE_URL`, so there is no new setting. |
| Checkpoint schema | Alembic migration that replays the saver's versioned `MIGRATIONS` (what `setup()` runs), frozen at the saver version | This was the user's choice. One `alembic upgrade head` creates everything, and workers never run DDL. A test flags a saver upgrade that needs a new revision. |
| Engine API | Checkpointer is injected. The engine imports only `langgraph.checkpoint.base` | This was the user's choice. Engine tests use `InMemorySaver`, and the engine stays free of Postgres. |
| Event log across attempts | Append only. `seq` continues from the max stored `seq`. `run_resumed` marks the boundary. The interrupted node's events from the first attempt stay | Transparency (6). The monitor (0.8) shows what really happened. |
| Granularity | Per node (LangGraph super-step) | It meets AC-8 ("resumes after the last completed node") with no changes to the runtime. |
| Graceful stop | Release the lease, don't cancel | With durability, a restart shouldn't throw away a run. Cancelling becomes an explicit user action later. |
| Sandbox | Recreate on resume | The tools are read only (1.2), so a fresh clone is equivalent. Reattaching would tie a run to one host. |
| Crash loops | `max_attempts = 3`, then `run_failed` | This is safe by construction (2). |

## Open questions
- ~~**Serializing `RunState`:** the state holds `AgentNodeResult` Pydantic models. Check that LangGraph's `JsonPlusSerializer` round-trips them in the installed version, including any allow-list for msgpack types.~~ Resolved in group 1: it round-trips them, but logs that unregistered types "will be blocked in a future version". `agentic_engine.graph.checkpoint_serde()` lists `AgentNodeResult` in `allowed_msgpack_modules`, which also works under `LANGGRAPH_STRICT_MSGPACK=true`. Every saver is built with it.
- **Coverage of lease and reclaim:** the user chose engine unit tests plus the manual compose demo. The worker drain test covers claim, release and reclaim end to end, but heartbeat renewal and concurrent reclaim (`SKIP LOCKED`) are proven only by the demo. Small store tests can be added later if they regress.
- ~~**Downgrading the checkpoint migration:**~~ Resolved in group 2: the downgrade drops the four tables of saver 3.2, and `test_migrations` checks the downgrade and upgrade round trip.
- **Windows:** psycopg's async driver can't use the Proactor loop that Windows tests and the fake sandbox's subprocesses use. Native Windows workers run on a selector loop, worker and API tests use an in-memory saver, and the Postgres saver test runs only on Linux (CI).
