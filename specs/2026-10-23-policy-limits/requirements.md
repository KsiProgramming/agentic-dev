# Policy limits: agents alive/spawned, depth, iterations, wall time

Roadmap phase: 3.2
Branch: plan/3.2-policy-limits

## Context
Milestone 3 adds the controls a platform admin needs. 3.1 made cost visible. 3.2 makes the non-cost limits real, and 3.3 adds the optional budget on top. Together they cover AC-7 (clean stop on limits). Today:
- Loop iterations (≤ 5) and map concurrency (≤ 8) are hard-coded caps in the spec schema (`spec/models.py`). Their docstrings already say "Phase 3.2 makes it configurable".
- The 40-agent spawn cap is checked **per map**, not per run. Going over it raises a bare `ValueError`, so the run ends `failed` with `ValueError: 41 items is more than…`.
- Nesting depth and wall time are not enforced at all.

Principles that drive it:
- **Mission 2 (safe by construction):** the engine enforces limits, not the graph. Limits are checked at validation time and again at runtime.
- **Mission v1 decision "Budget is optional":** budget is optional, but the other limits always apply (agents alive, agents spawned, nesting depth, loop iterations, wall time).
- **Mission persona, platform admin:** admins control cost, tools and limits per workspace.
- **Tech stack, security:** the defaults are agents alive 8, agents spawned 40, nesting depth 2, loop iterations 5, wall time 2 h.
- **Tech stack, cost decision:** a run's numbers are frozen when it starts and never recomputed. Limits follow the same rule.

Depends on: 1.9 (loop), 1.10 (map/reduce), 2.3 (run summaries, `failure_reason`), 2.6 (settings cards, cancel watcher pattern). All are done.
Unblocks: 3.3 (budget reuses the policy model and the limit-stop event), 3.4 (validation endpoint reuses the policy checks), 4.1 and 6.1 (`parallel` and `orchestrator` share the run-wide alive and spawned counters).

## Scope
### In scope
- **Policy model** `agentic_engine.policy`:
  - `Policy(agents_alive, agents_spawned, max_depth, loop_iterations, wall_time_s)`;
  - `PLATFORM_POLICY` holds the tech-stack defaults, which are also the ceilings;
  - `effective_policy(workspace_overrides)` returns the platform values lowered by the workspace's.
- **Workspace policy:**
  - stored per workspace, each field nullable (null means the platform default);
  - `GET /workspaces/{id}/policy` returns the defaults, the overrides and the effective values;
  - `PUT /workspaces/{id}/policy` replaces the overrides. Values must be ≥ 1 and ≤ the platform ceiling, else 422;
  - a "Run limits" card in Settings shows the defaults, lets the user lower each one, and has a reset.
- **Policy frozen per run:** `POST /runs` (and rerun) copies the effective policy onto `runs.policy`. The worker runs with that copy, resumes included, so changing the workspace policy never changes a running run.
- **Validation-time checks** (on `POST /runs` and rerun, 422 with one actionable message per problem naming the node path, the limit and the value):
  - each `loop.max_iterations` ≤ `loop_iterations`;
  - each `map.max_concurrency` ≤ `agents_alive`;
  - container nesting (loop, map) ≤ `max_depth`.
- **Runtime enforcement** (in the engine and the worker):
  - **agents spawned:** a per-run count of agent starts (agent nodes, map item agents, reduce agents, every loop iteration) kept in `RunState`, so it survives a resume. A map checks `spawned + agents in its items` before it fans out and fails fast. Otherwise the check happens before each agent start;
  - **agents alive:** one run-wide semaphore of size `agents_alive` around every agent call. Going over it waits, it does not fail. The spec check above already rejects concurrency above the limit;
  - **wall time:** a worker watchdog next to `_watch_cancel`. Active time is time spent executing: from `run_started` or `run_resumed` to `gate_waiting` or the run's end, summed from the event log when an attempt starts. Time waiting at a gate does not count;
  - **depth:** a validation check only for now, since no primitive nests at runtime yet (the `orchestrator` in 6.1 and `subflow` in 6.5 will add the runtime check).
- **Clean stop with a reason:**
  - a new `policy_limit_exceeded` event (`limit`, `value`, `observed`, plus `node_id` when a node hit it);
  - running nodes end with `node_cancelled`;
  - `run_failed` with `error` = a readable reason, e.g. "policy limit: wall time 2h 0m exceeded", which becomes `runs.failure_reason`;
  - the sandbox is released as for any failed run;
  - the console header and the runs list show that reason as they do any failure reason. The raw events tab shows the structured event.

### Out of scope
- Budget (USD) limit and its hard stop: 3.3.
- A `policy` block in the workflow spec (a per-workflow tightening): later, with the canvas side panel (5.4).
- `POST /workflows/{id}/validate`: 3.4. It will call the same check functions.
- Raising limits above the platform ceilings, and per-plan or per-tenant ceilings: 10.5.
- Runtime depth enforcement: 6.1 and 6.5.
- RBAC on who may edit the policy, and an audit of changes: 3.7.
- Playwright end-to-end coverage of the stop reason and the card (the user chose engine and integration tests. Component tests still cover the card).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where limits are set | Platform defaults are the ceilings. A workspace may only lower them | Mission 2: safe by construction. An admin can tighten, never loosen past what the platform supports. |
| Storage | `workspace_policies(workspace_id PK, agents_alive, agents_spawned, max_depth, loop_iterations, wall_time_s, updated_at)`, nullable columns | One row per workspace. Null means "platform default", so changing a default later reaches every workspace that did not override it. |
| Frozen per run | `runs.policy JSONB NOT NULL`, set at creation. Existing rows are backfilled with `PLATFORM_POLICY` | Same rule as cost: a stop can always be explained by what the run was given, and resume is deterministic. |
| Run outcome | `failed`, not a new status | Keeps the `RunStatus` set and every UI filter unchanged. The structured event and `failure_reason` say which limit was hit. |
| Stop event | `policy_limit_exceeded` before `run_failed` | The append-only log records which limit, its value and what was observed (mission 6). 3.3 reuses it with `limit: "budget_usd"`. |
| Wall time clock | Active time only, which excludes gate waits, summed from event timestamps | A slow approver must not kill a run, and a waiting run holds no worker. Event timestamps survive a worker restart. A crash gap counts up to the last event. |
| Wall-time enforcement point | Worker watchdog (polled like cancel), then cancel the attempt and write the stop | The engine cannot see the time spent on earlier attempts. The worker already owns cancel. |
| Agents alive at runtime | Throttle with a run-wide semaphore, do not fail | "Alive" is a concurrency cap. Queuing is the clean behaviour, and the spec check stops impossible specs early. |
| Agents spawned | Counted per run (not per map), every agent start, and checkpointed in `RunState` | It matches the tech-stack meaning and holds across a resume. The current per-map check is replaced. |
| Loop at `max_iterations` | Still ends normally (1.9 behaviour). Only a spec above the policy is rejected | Reaching a declared bound is not a violation. Exceeding the policy is caught before the run starts. |
| Validation messages | One per problem: `loop 'review' at steps[2]: max_iterations 8 is above the workspace limit of 5` | Actionable, the same format as the existing spec checks, and reused by 3.4. |
| Units | `wall_time_s` in seconds (≥ 1) in the API, shown as hours and minutes in the UI | Seconds let tests use a short limit. |

## Open questions
None. Settled during implementation:
- **Docs template and 40 spawned agents:** it did not fit (up to 40 modules plus the writer). `repo.list_modules` now takes a `limit`, and the template asks for `agents_spawned - 1` modules.
