# Plan: `parallel` primitive with join policies (all/any/quorum)

The work goes in this order: spec first, then the engine with `all`, then early joins and cancellation, then the UI, then docs (user choice). Each group leaves the project working and CI green.

## 1. Spec model and validator
- [x] `spec/models.py`:
  - Add `ParallelNode`: `branches: list[Node]` with 2 to `MAX_AGENTS_ALIVE` entries, `join: Literal["all", "any", "quorum"]`, and `quorum: int | None`.
  - A model validator makes `quorum` required for `join: "quorum"`, forbidden otherwise, and between 1 and `len(branches)`.
  - Add the node to the `Node` union. `iter_nodes` recurses into `branches[i]` (path `root.steps[1].branches[0]`), and `node_tools` returns `[]` for it.
- [x] Add `parallel_issues(root)` with the new code `not_allowed_in_parallel` (via `_not_in_parallel`, which reuses the map rule).
  - `_not_in_loop` and `_not_in_map` reject `parallel`.
  - `map_issues` keeps refusing a `reduce.from` that is not a map.
  - Wire it into `structure_issues` and `IssueCode`.
- [x] `policy_issues`:
  - Raise `agents_alive` when there are more branches than `policy.agents_alive`.
  - Count a parallel as one level of depth.
  - Update the `Policy.max_depth` description.
- [x] `duplicate_id_issues` and `publish_gate_issues` / `create_repo_issues` walk branches. Check that a writer before the parallel and a gate after it still pair correctly.
- [x] Fixtures:
  - `valid/parallel-three-reviewers.json`, `valid/parallel-any.json`, `valid/parallel-quorum.json`.
  - The invalid fixtures listed in requirements.md.
- [x] `test_spec.py` and `test_validate.py`:
  - Each rejection names its code, its node and its path.
  - The schema contains `parallel` with `branches` `minItems: 2` and `maxItems: 8`.
  - `/validate` returns `not_allowed_in_parallel`.
- [x] Re-export the JSON Schema, the OpenAPI spec and the web client (`schema.d.ts`). The compiler temporarily raises `CompileError` for parallel until group 2 lands, or groups 1 and 2 land together.

## 2. Engine: fan-out and the `all` join
- [x] `graph/state.py`:
  - Add `parallel_results: Annotated[dict[str, dict[str, AgentNodeResult]], merge_map_results]` (the same merge by container id, then by key) to `RunState`, `RunUpdate` and `initial_state`. Old checkpoints have none, which reads as `{}`.
  - Add the `ParallelBranch` `Send` payload (`index`).
- [x] `events.py`:
  - Add `PARALLEL_BRANCH_STARTED` and `PARALLEL_BRANCH_COMPLETED`.
  - `emit` and `agent_event` take an optional `branch: int`, which is written into the payload. Update the docstring on what tags a body event.
- [x] `graph/compile.py`:
  - Add `branch_node_id` and `parallel_join_node_id` helpers.
  - Entry `_parallel_entry`: counts the agents in the branches, calls `_refuse_spawn` (which ends the parallel with `END`), logs `node_started` with `branches`, `join` and `quorum`, and returns `spawned`.
  - Fan-out `_fan_out_branches`: one `Send` for each branch index.
  - Worker `_parallel_branch`:
    - Logs `parallel_branch_started`.
    - Runs `step_nodes(branch)` through `_run_step(..., branch=index)`, stopping at the first step that does not complete.
    - Returns `results` for its nodes (not `order`, see requirements.md), its `usage`, and `parallel_results[pid][branch_id]`. It does not write `last_text`.
    - Logs `parallel_branch_completed`.
  - Join `_parallel_join`:
    - A pure `join_outcome(join, quorum, statuses)` returns completed, failed or undecided.
    - The join builds the output text and `data` in branch order, logs `node_completed` or `node_failed` with the lists, sets `last_text`, `results[pid]` and `order`, and routes with `_continue_if_completed`.
  - The `add()` case wires entry, workers and join. `step_nodes` walks the branches, and `recursion_limit` counts a parallel as 3 steps, like a map: its workers share one superstep.
  - `_run_step` gains a `branch` parameter next to `item`, and the event log a `branch` tag.
- [x] `packages/engine/tests/test_parallel.py` (fake runtime, `InMemorySaver`):
  - Done when: three single-agent branches overlap (the fake runtime's peak in flight is 3), and the join `all` completes with outputs in branch order even when they finish in reverse.
  - A sequence branch runs its steps in order.
  - Each branch gets the parallel's input.
  - A later node reads `results.<branch node>` in CEL.
  - Usage from every branch is summed.
  - Events: one `node_started` and one end for the parallel, start and complete markers for each branch, a `branch` tag on body events, and `seq` running 1..n with no gaps.
  - Spawn limit: a parallel whose agents would pass `agents_spawned` fails before any branch starts.

## 3. Early join and cancellation (`any`, `quorum`, fail fast)
- [x] An in-process `_JoinCoordinator` for each parallel and attempt:
  - Each branch's outcome is recorded as it finishes.
  - Once `join_outcome` is decided, it cancels the other branches' running step tasks. `_run_step` already logs `node_cancelled` on `CancelledError`.
  - A cancelled branch returns `status: "cancelled"` and is logged in `parallel_branch_completed`.
  - The worker runs its steps in a task it can cancel, and tells a sibling cancel apart from a real cancellation of the run or a `PolicyLimitExceeded` from the budget. Both of those still propagate.
- [x] The join treats cancelled branches as neither completed nor failed. The decision comes from the stored results only.
- [x] `test_parallel.py`:
  - `any`: the fast branch wins, the others end `node_cancelled`, and the output is the winner's.
  - `any`: all branches fail, so it fails.
  - `quorum: 2` of 3: completes at 2 and cancels the third. With 2 failures it fails at once and cancels the rest.
  - `all`: one fails, the others are cancelled, and the parallel fails naming the branch.
  - A budget stop inside a branch still ends the run with `policy_limit_exceeded`, not as a sibling cancel.
  - Agents alive: with the run's `agents_alive` at 2, 3 branches still finish, and the peak is 2.
  - Resume mid-parallel: after a cut-off once branch 0 has finished, only branches 1 and 2 run again, and the join is correct (AC-8).

## 4. Console: timeline and graph tab
- [x] `web/src/runs/types.ts` and `timeline.ts`:
  - A parallel step holds `branches` entries (`index`, `id`, `status`, steps), built from `parallel_branch_*` events. `scopeFor` places events tagged `branch` in their branch.
  - Usage totals include the branches.
  - The step view renders branches on a nested rail, like map items.
- [x] `web/src/runs/graph/spec-graph.ts`: a `parallel` is a container group with its branches side by side, top aligned, in the hand-written layout. ELK was dropped for this phase (see requirements.md).
- [x] `node-status.ts`: the parallel summary ("2 of 3 branches · any", "· 1 failed"). Branch nodes take their own status; a cancelled branch shows "Cancelled". `graph-nodes.tsx` gets the parallel icon and detail line.
- [x] Add parallel cases to `spec-graph.test.ts`, `node-status.test.ts` and `timeline.test.ts`.

## 5. Docs and demo
- [x] README: a "Parallel" section covering the spec shape, the join policies, cancellation, limits, events and restrictions. Update the primitives list.
- [x] tech-stack.md:
  - The run console timeline and graph tab rules (branches, ELK).
  - Add `not_allowed_in_parallel` to the validation codes.
  - A decisions log row: parallel through `Send`, with an early join and cancellation.
- [x] CHANGELOG entry under [Unreleased].
- [ ] Live demo on docker compose: a 3-branch `all` run and an `any` run on Claude, watched in the console. See validation.md.
- [x] Tick this plan, and record answers to the open questions in `requirements.md`.
