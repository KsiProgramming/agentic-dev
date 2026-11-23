# Circuit breakers

Roadmap phase: 13.7
Branch: plan/13.7-circuit-breakers

## Context

13.3 to 13.6 check a writer's work before a person sees it. Nothing yet watches how an agent works while it runs. An agent can call the same failing tool again and again, spend many times what its step usually costs, write outside the area it was given, or rewrite a file back and forth. Today the only stops are the policy limits (3.2, 3.3). They end the run as `failed`, and they come late: the wall time is 2 h and the budget is optional. 13.7 adds four breakers. The engine watches each step's events, and when a breaker trips it pauses the run with the reason. A person reads why, then resumes or cancels.

It builds on:
- **3.2 and 3.3 policy limits and the budget meter.** The breakers see the same per-event hook (`limits.budget.add` in `graph/compile.py`) and stop running steps the same way. Their thresholds are frozen on the run like its policy.
- **1.7, 11.3 and 7.9 the waiting state.** A pause uses the gate's way of waiting: the worker is released, the time counts as waiting time, the pause expires and shows in the Inbox. 7.9 already announced a wait that is not a gate (`gate_waiting` with `wait_for`), and a pause follows that precedent.
- **1.3 and 12.2 resume after a restart.** A resumed run goes on from its last checkpoint with its saved branches, exactly as after a worker restart (AC-8).
- **13.5 protected paths.** The same path matcher (`agentic_runtime.paths`), and the same way of passing rules to the repo write tools for each step (`ProtectedPaths`), serve a node's declared paths.

What drives the design:
- **Principle 2 (safe by construction).** The engine trips a breaker, not the flow's author. A cap refuses, it does not warn: a write outside the declared paths never lands. A workspace or workflow can tune a breaker within a range but cannot turn it off.
- **Principle 3 and principle 8.** What needs a person is always visible: banner, dock, Inbox, page title. A pause nobody answers expires, as an approval does.
- **Principle 9.** A pause loses nothing. The steps that completed stay done, and the branches are saved (12.2).
- **Principle 5.** The breaker's details include tool arguments, error text and paths. These are model and repo output, so the console shows them as text and the resumed agent gets them as data.
- **Lessons 1 and 13.** The resumed agent is told why it was paused, so what agents receive changes, and the phase needs a real Claude run read step by step. A pause is not a send-back, so it uses no loop pass.

## Scope

### In scope

- **The watcher** (`agentic_engine.breakers`). There is one watch per step execution, fed every agent event of the step. It watches agents, review lenses (13.6), a router's classifier, an orchestrator's hub, and an orchestrator's tasks. It does not watch tool nodes or gates, which are deterministic. Each map item, branch, task and loop pass has its own watch. Counters start fresh each time the step starts.
- **Four breakers** (default thresholds in brackets):
  1. **Repeat.** The same tool with the same arguments (canonical JSON, with `description` left out) `repeat_calls` times in one step [5]. Or tool results marked as errors, from the same tool and with the same text (whitespace collapsed, first 500 characters), `repeat_errors` times [3].
  2. **Cost.** The step's cost reaches `cost_multiple` times its node's average [3] **and** is at least `cost_floor_usd` above that average [$0.50]. The average is the mean cost of one execution of the same node id in the last 20 completed runs of the same workflow (the template id, or the stored workflow id at any version). It counts only once there are 5 such runs; until then this breaker does not watch the node. The baselines are worked out when the run is created and stored on it (`runs.cost_baselines`). The breaker trips as soon as the cost is crossed, not at the end of the step.
  3. **Paths.** A new optional field, `paths: [glob]`, on an agent node that has write tools. A `repo.write_file` outside those globs trips the breaker on its `tool_call`, before the tool runs. The repo write tools also refuse such a write: `repo.write_file` before it writes, and `repo.commit` for any staged path, both sides of a rename included. This is the pattern of 13.5's `ProtectedPaths` (a `DeclaredPaths` object per step), so no provider's event order can let the write land. A node with no `paths` has no limit. Matching uses 13.5's matcher.
  4. **Flip-flop.** Within one step, a `repo.write_file` whose content (sha256) equals an earlier content of that path, other than its latest, counts as one flip. The breaker trips at `flip_flops` flips on one path [2].
- **Pause.** When a breaker trips, the steps that are running end `node_cancelled`, as in a budget stop. Then come `breaker_tripped` (on the tripped node) and `gate_waiting`, which carries `breaker` and the approval time to live. The attempt ends `waiting` and the worker releases the run. If several breakers trip at once, the first one wins and the others are cancelled with it. Waiting time is not active time (11.2). A pause expires after `approval_ttl_s`: the run is cancelled with the reason "Breaker pause expired" and `expired: true`.
- **Resume and cancel** use `POST /runs/{id}/approvals` with the tripped node's id.
  - **`approve` (Resume).** The worker resumes the run from its last checkpoint. The engine writes `gate_decided` with `source: "breaker"`. The tripped step runs again from its start; its earlier conversation is not kept. Steps that completed beside it are not run again.
  - **`reject` (Cancel).** The run ends `cancelled` with the reason "Cancelled after a circuit breaker", and its sandbox is kept (12.3).
  - Edits, selections and dismissals on a breaker decision are refused with `422 breaker_decision_invalid`.
- **The resumed agent is told why.** Its system prompt gets a "# Paused before" section after "# Protected paths". The section names the breaker, the threshold and what was seen, and quotes the call, error, path or cost between tags as data. It is built from the `breaker_tripped` event, never from instructions. `node_started` carries `resumed_after: {breaker, reason}`. A person's comment on Resume goes to the audit log only; it is not passed to the agent (that is 20.1).
- **Thresholds.**
  - A `BreakerPolicy` sits in `Policy.breakers`, with defaults so that runs frozen before 13.7 still load.
  - A workspace sets the thresholds through `PUT /workspaces/{id}/policy`'s `breakers`. A workflow sets per-field overrides in its spec's `breakers`.
  - They are resolved in this order: workflow, then workspace, then platform. Each is clamped to a platform range: `repeat_calls` and `repeat_errors` 2–50, `cost_multiple` 1.5–20, `cost_floor_usd` 0–1,000, `flip_flops` 1–10.
  - The resolved thresholds are frozen on the run when it is created.
  - `POST /workflows/{id}/validate` reports a value outside its range, and `paths` on a node with no write tools (`paths_without_writes`).
- **Store and API.**
  - `runs.breaker_trips` is a count, like `protected_attempts`. `runs.cost_baselines` holds the baselines. Both come in Alembic `0043_circuit_breakers`.
  - `waiting_gate.breaker` appears in the summaries, and `GET /runs/{id}/gate` returns the breaker details.
  - The audit log gains `breaker.tripped` (System), `breaker.resumed`, `breaker.cancelled` and `breaker.expired`.
- **UI** (full UI):
  - **Console.**
    - A banner, "Paused by a circuit breaker: <reason>", with `ExpiresIn`, "Go to step", Resume and Cancel run.
    - The approval dock shows the pause with Resume and Cancel run, through the shared `useGateDecision`. `A` resumes and `R` opens the Cancel dialog.
    - The tripped step's status reads "Paused" (a `StatusBadge` in the waiting colour). Its Output shows `BreakerDetails`: the breaker, the threshold, what was seen, and the call, error, path or cost through the display components.
    - A resumed step's Input tab shows "Paused before".
    - A "Breakers" tile appears in the header once it is above zero, like Protected files.
  - **Inbox.** Paused runs are listed with the gates. A pause's review shows `BreakerDetails`, Resume and Cancel run.
  - **Runs list.** A paused run's badge reads "Paused" (through `badgeStatus` and `statusLabel`) and counts in the "Needs approval" view. The page title gets a "● Paused" prefix.
  - **Settings.** A "Circuit breakers" card on Limits and budgets shows each threshold with its unit and its range in the help text, and saves from the existing sticky bar.
  - **Builder.** `paths` on agent nodes and `breakers` on the workflow panel come from the manifests' JSON Schema (Advanced). No hand-written form.

### Out of scope

- Keeping the agent's conversation across a pause (holding it in place inside the worker). This was considered and not chosen; see Decisions.
- A person's message to the agent on Resume, and steering a running agent (20.1).
- A manual "Pause" button, and pausing from mission control (20.2).
- Counting breakers in workspace metrics (20.6). `runs.breaker_trips` is what 20.6 will read.
- Flip-flops across loop passes or across steps. A loop's `max_iterations` already bounds those, and 13.12's send-back choice covers the reviewer side.
- A cost baseline within one run (map items, loop passes). The baseline comes from history only.
- Raising a threshold for the rest of a run on Resume, or turning a breaker off.
- Breakers for a vendor's agent (10.6, which lists 13.7 as a dependency).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How a trip pauses | Stop at the last checkpoint and wait as at a gate: `gate_waiting` with `breaker`, decided through `POST /runs/{id}/approvals` | Chosen by the user. Status, waiting time, expiry, the Inbox count and the worker's release then need no new path, and 7.9's `wait_for` set the precedent. Holding the agent in place would keep its conversation, but it ties up a worker slot for as long as nobody answers and still falls back to a rerun after a restart. |
| What Resume runs | The tripped step again from its start, with fresh counters; steps that completed are kept | This is the tested resume-after-restart path (AC-8, 12.2). A second trip pauses again, and each pause needs a person, bounded by the approval TTL and the wall time. |
| Telling the resumed agent | A "# Paused before" section built from the event, as data | Without it, a step that restarts with the same input is likely to repeat itself. It changes what agents receive, so it needs a real run (lessons 1). |
| Declared paths | `paths` on writer agent nodes, opt-in. Enforced by the watcher on `tool_call` and refused by the repo write tools | "A cap refuses." The tool-layer refusal makes the guarantee hold on Copilot too, whatever order its events arrive in. |
| Cost baseline | The mean per execution of the same node over the last 20 completed runs of the same workflow, from 5 runs, frozen at run creation | "Its node's average" is the node's usual cost. Freezing it means a resume never moves the line. The floor keeps it from tripping over a few cents. |
| Tuning | Workflow, then workspace, then platform, clamped to ranges. No off switch | Principle 2. A workflow whose agent really does re-read a file often can raise `repeat_calls`, but it cannot remove the breaker. |
| Order of work | One breaker (repeat) end to end first, then the other three, then thresholds and settings | Chosen by the user. The second half of Done when works early, and the pause path is proved before more detectors depend on it. |
| Validation | Engine tests per breaker, API and store tests, the e2e suite with axe, and one real Claude run | Chosen by the user, with the checks that CLAUDE.md (UI) and lessons rule 1 require. |

## Open questions

- The default thresholds (5 calls, 3 errors, 3× with a $0.50 floor over 5 of the last 20 runs, 2 flips) are first guesses. The real run, and the first weeks of use, may tune them. Any change goes into tech-stack with the reason.
- "Needs approval" now also holds paused runs. The view keeps its name in 13.7; renaming it ("Needs you") is left until users and sign-in exist.
- Whether the Copilot adapter emits `tool_call` before it runs the tool. The tool-layer refusal makes the paths breaker safe either way. The plan checks it, and tech-stack records the answer.
