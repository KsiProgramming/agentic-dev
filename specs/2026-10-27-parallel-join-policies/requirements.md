# `parallel` primitive with join policies (all/any/quorum)

Roadmap phase: 4.1
Branch: plan/4.1-parallel-join-policies

## Context
Today a run can only branch over data: `map` runs one body for each item. Milestone 4 (Audit) needs different specialists working side by side on the same input, for example a security reviewer, a dependency reviewer and a style reviewer. `parallel` runs a fixed set of different branches at the same time and joins them under a policy:
- `all`: every branch must complete.
- `any`: the first branch to complete is enough.
- `quorum`: k branches must complete.

It depends on these phases, all done:
- 1.10: map's `Send` fan-out, the shared step runner `_run_step`, and per-item checkpointing. Parallel reuses all three.
- 3.2 and 3.3: the policy limits (agents alive and spawned, depth) and the budget meter. Branch agents count against them.
- 3.4: the one engine validator behind `POST /workflows/{id}/validate`.
- 3.5: the graph tab. Its decision log said ELK (`elkjs`) would replace the hand-written layout when branches arrive (4.1 or 4.6). See the layout decision below.

It unblocks:
- 4.4 and 4.7: deterministic tool nodes and specialist agents running side by side in the audit template.
- 4.5: the `dedupe` and `vote` reduce strategies over several sources.
- 5.5: container nodes on the canvas.
- 6.8: AC-2 (a canvas flow with `parallel`).

Principles that apply:
- **Open, but safe by construction (2):** the number of branches is capped by agents alive, checked at validation. Every agent in the branches is counted against agents spawned when the parallel starts. The budget and the run-wide alive slots apply to branch agents as they do everywhere else.
- **Humans approve irreversible actions (3):** a branch holds no gates, writers or publishers. A gate stays a step of a sequence, and only one gate waits at a time.
- **Transparency (6):** each branch's start and end are logged. Every branch event carries its branch index. Cancelled branches end `node_cancelled`, so the log explains every branch.
- **Small, verifiable steps (7):** branches hold `agent`, `tool` and `sequence` nodes only, the same rule as a map body. Containers inside branches come later.
- **One spec, many views (1):** the graph tab draws the parallel from the stored spec.

Tech-stack choices that apply:
- LangGraph `Send` for the fan-out, as for `map`.
- The Postgres checkpointer: finished branches survive a restart.
- React Flow, with the hand-written layout extended (see the layout decision).
- Pydantic models exported as JSON Schema.

## Scope
### In scope
- **Spec:** `ParallelNode` is `{"type": "parallel", "id", "branches": [Node, …], "join": "all" | "any" | "quorum", "quorum"?: int}`.
  - `branches` holds 2 to 8 nodes (8 is `MAX_AGENTS_ALIVE`). A branch is one node: an `agent`, a `tool` or a `sequence`. Its id names the branch.
  - `quorum` is required for `join: "quorum"` and forbidden otherwise. It must be between 1 and the number of branches. A model validator enforces this, so a breach is a `schema` issue.
  - It joins the `Node` union. `iter_nodes` recurses into each branch, and `node_tools` returns `[]` for it.
- **Validation** (one validator, so `POST /runs` and `/validate` agree):
  - A new code, `not_allowed_in_parallel`, covers a branch that holds a gate, a writer, a publisher, a loop, a map, a reduce or a parallel.
  - A parallel is not allowed inside a loop or a map. This reuses `not_allowed_in_loop` and `not_allowed_in_map`.
  - `policy_limit` (`agents_alive`) is raised when there are more branches than the workspace's agents alive.
  - A parallel counts as one level of nesting for `max_depth`. The `Policy` field description changes from "loops and maps" to "containers".
  - A `reduce.from` that names a parallel is still a `reference` issue. Reducing branches comes with 4.5.
- **Engine:**
  - A parallel compiles to three LangGraph nodes:
    - **Entry `<id>`:** logs `node_started` (`branches`, `join`, `quorum`) and counts every agent node in every branch on `agents_spawned` at once, or refuses the parallel as a map does. It then sends `Send("<id>.branch", {index})` once per branch.
    - **Worker `<id>.branch`:** runs one branch's steps in order on the parallel's input, through `_run_step` with a `branch` tag.
    - **Join `<id>.join`:** applies the join policy to the stored branch results and routes on.
  - Every branch gets the parallel's input. Branch node ids are unique, so their results go into `RunState.results`, and later CEL can read `results.<branch node>`. They do not go into `order`, which is the run's path: a branch can fail while its parallel completes, and the runner ends a run at the first node in `order` that did not complete. `WorkflowRunResult.results` lists them after the path. The workers never write `last_text`. The branch outcomes go into a new `RunState.parallel_results[parallel_id][branch_id]` through a merging reducer, so they are checkpointed per branch.
  - **Join policies:** each one decides as soon as the outcome is known, then cancels the branches still running. Those branches end `node_cancelled`.
    - `all` completes when every branch has completed. It fails on the first branch that fails.
    - `any` completes on the first branch to complete. It fails only when every branch has failed.
    - `quorum` completes when k branches have completed. It fails once k can no longer be reached.
  - Early cancellation uses an in-process coordinator for each parallel within one attempt. The join node decides from the stored results, so a resumed run stays correct even when it cannot cancel early. A budget stop (`PolicyLimitExceeded`) is never mistaken for a sibling cancel.
  - The output text is the outputs of the completed branches in branch order, joined by `"\n\n"`. `data` is `{"outputs": {branch_id: text}, "completed": [...], "failed": [...], "cancelled": [...]}`.
  - A failed parallel ends the run, like any node that does not complete. Its error names the policy and the branches that failed.
  - `recursion_limit` and `step_nodes` cover parallel.
- **Events:**
  - `node_started(parallel)`, with `branches`, `join` and `quorum`.
  - `parallel_branch_started` (`index`, `branch_id`) and `parallel_branch_completed` (`index`, `branch_id`, `status`, `error`?) around each branch.
  - Branch body events carry `payload.branch`.
  - Then `node_completed` or `node_failed` for the parallel, with `completed`, `failed` and `cancelled`.
- **API:**
  - The JSON Schema, the OpenAPI spec and `web/src/api/schema.d.ts` are re-exported.
  - The `/validate` codes list in tech-stack.md gains `not_allowed_in_parallel`.
- **Web:**
  - **Timeline:** the parallel step has one entry per branch, named by the branch id with its status, nested on its own rail like map items. Events are scoped by `branch`.
  - **Graph tab:** the parallel is a box whose branches are side by side, with fan-out and fan-in edges. The box header reads, for example, "2 of 3 branches · any". Cancelled branches show "Cancelled".
    - `specToGraph` keeps its hand-written layout and places the branches side by side inside the box. The rest of the graph keeps its look.
- **Fixtures:**
  - Valid: `valid/parallel-three-reviewers.json` (join `all`), `valid/parallel-any.json`, `valid/parallel-quorum.json`.
  - Invalid: `parallel-one-branch`, `parallel-quorum-too-high`, `parallel-quorum-without-join`, `parallel-with-gate`, `parallel-with-writer`, `parallel-with-loop`, `parallel-in-map`, `parallel-in-loop`, `parallel-too-many-branches` (policy).
- **Docs:**
  - A README "Parallel" section.
  - A CHANGELOG entry.
  - tech-stack.md: the run console rules (timeline and graph tab), the validation codes, and a decisions log row.

### Out of scope
- Gates, writers and publishers inside branches. Parallel writers need the integration branch (6.3), and branch gates need several gates waiting at once.
- Loops, maps, reduces and nested parallels inside branches, and a parallel inside a loop or a map. This needs container nodes on the canvas (5.5) and a branch worker that runs subgraphs.
- `reduce` over a parallel's branches: 4.5 (dedupe and vote).
- Weighted or per-branch quorums, branch timeouts, and a "best of" pick by an agent.
- Refunding the spawned count of agents in cancelled branches that never started.
- Dedicated web unit and Playwright tests for the new UI (not chosen for this phase). The existing web suites are updated where shapes change.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Engine, validator, timeline and graph tab | User choice. "Done when" is an engine fact, but the console must explain a branching run (mission 6 and 8). |
| Branch body | `agent`, `tool` and `sequence` only | User choice. A `Send` worker runs leaf steps inline, as a map body does. Containers would need subgraphs inside a worker. |
| Fan-out | One `Send` to `<id>.branch` per branch, then `<id>.join` | User choice. It reuses the map machinery and per-task checkpointing, and an early join is possible because every branch is one task. |
| Failure handling | Decide as soon as the outcome is known, then cancel the rest | User choice. It wastes the fewest tokens, and the result is the same for each policy. |
| Cancellation | An in-process coordinator per attempt. The join decides from stored results | Cancelling is an optimisation, and correctness lives in the checkpointed results. A resumed run therefore joins correctly. |
| Agents spawned | Every agent in every branch is counted when the parallel starts | Concurrent branches all see the same state snapshot, so counting as they go could overshoot. This is the same rule as map. |
| Branch cap | 2 to 8 in the schema, and no more than the workspace's agents alive (policy) | All branches can then really run at once. 8 is the platform ceiling (`MAX_AGENTS_ALIVE`). |
| Output | Completed branches' texts in branch order. `data.outputs` is keyed by branch id | Deterministic whatever order the branches finish in, so tests and later reduces are stable. |
| Branch input | Every branch gets the parallel's input | Specialists review the same thing. Per-branch input mapping waits for typed ports (4.2). |
| Graph layout | Hand-written: the branches side by side, top aligned, inside the parallel's box. ELK waits for 4.6 | Changed during implementation (the plan said ELK). Branches inside a box need no edge that leaves it, like a map's or a loop's body, so routing is not needed yet. ELK would make the layout async and add a lazy-loaded dependency for no visible gain. ELK comes when edges cross boxes (`router`, 4.6). |
| Branch nodes in `order` | In `results`, not in `order` | Found during implementation: the runner stops a run at the first node in `order` that did not complete, and a cancelled or failed branch must not stop a parallel that completed. |
| Internal node names | `<id>.branch` and `<id>.join` | `NodeId` forbids `.`, as with `<map>.item` and `<loop>.check`. |

## Open questions
- On a resume, branches that had not finished run again even if the policy was already met before the crash, because the coordinator only sees the current attempt. Seeding the coordinator from the checkpoint can fix this if it matters. Accepted for 4.1.
- ~~`elkjs` layout is asynchronous.~~ Resolved: no ELK in 4.1 (see the layout decision).
