# Plan: Rerun from a step

Engine and store first, then the API, then the console. Read `specs/lessons.md` before group 2 (it changes what agents receive). The project stays working after each group: until group 4, `from` is not accepted and rerun behaves as today.

## 1. Record which step saved each branch version
- [x] Alembic `0032_rerun_from_step`: `run_branches.step` (nullable `String(128)`, the top-level step id the save ran in); `runs.rerun_from` (JSONB `{node_id, use_wip, edited}`); up and down tested.
- [x] `agentic_engine.branches.BranchSaver`: the save call takes the top-level step id; every caller passes it (agent, tool and gate steps, map items, parallel branches, orchestrator tasks and `<id>.integrate`), from the compiler's knowledge of which top-level step a node sits in.
- [x] `agentic_worker.branches.SandboxBranchSaver` and `agentic_store.save_branch` store it; `wip` versions record the step the run ended in.
- [x] `agentic_store.branches_before(run_id, step_ids)`: the latest version of each `writer`/`integration` branch whose `step` is in `step_ids`, with its bundle; and `wip_versions(run_id, step)`. Store tests (Testcontainers).

## 2. Seed a new run from a checkpoint (engine)
- [x] `agentic_engine.graph.fork`: `checkpoint_before(checkpointer, run_id, node_id)` (the latest checkpoint whose `next` is the step, `StepNotReachedError` if none) and `seed_thread(checkpointer, source_run, target_run, checkpoint)`: copy the checkpoint and metadata into the target's thread with `aput`, without pending writes.
- [x] Audit `RunState` for spend and run-id-bearing fields (usage totals, budget counters, branch names in `AgentNodeResult`, artifact refs); reset spend and rewrite run ids on copy. Answer the requirements' open question in tech-stack.
- [x] `top_level_steps(spec)` and `steps_before(spec, node_id)` helpers; reject a node that is not top-level.
- [x] Engine tests on the fake runtime: a 3-step sequence rerun from step 3 runs only step 3; no usage events for steps 1 and 2; a container step (loop, orchestrator) reruns whole; router choices and orchestrator plans before the step are kept; the rerun of a gate step pauses again.
- [x] "What the agent receives" test (lessons rule 1): the rerun step's request carries the edited instructions, the earlier steps' outputs as its input, the run's request and repo context, and its tools read the restored branch.

## 3. Restore the code (worker and sandbox)
- [x] Worker: a run with `rerun_from` seeds its thread on its first attempt (once; a resumed attempt finds its own checkpoint), then resumes with `resume_workflow`.
- [x] Sandbox `open(..., restore=...)`: restore bundles from the original run under `agent/<new run>/<key>` (fetch refspec renames); the new run's `base_sha` copied from the original.
- [x] `use_wip`: restore the step's `wip` bundle as its writer's branch (its commits plus 12.3's snapshot commit).
- [x] Copy the artifact rows the copied state references into the new run's `run_artifacts`.
- [ ] Worker tests (fake sandbox; one Docker test, never all of `packages/sandbox/tests`): the new run's branches hold the original's commits as of the step, not later ones; `use_wip` adds the snapshot commit; a killed worker of a seeded run resumes from its own checkpoint, not re-seeding. (Engine test covers the resume; the worker test needs Docker.)

## 4. API
- [x] `agentic_store.create_rerun(..., from_step=...)`: checks the run ended, the node is top-level and was reached, the needed bundles exist and are not dropped, `use_wip` applies; applies `set_params` with the 5.1 graph-operations code, refusing other ops or nodes; sets `rerun_from_node`; audit `run.rerun` gains `from_node`, `use_wip`, `edited` (paths only, no values).
- [x] `POST /runs/{id}/rerun` body `from {node_id, set_params?, use_wip?}`: `422` for a node that is not a top-level step (unknown included) or a disallowed op or policy limits, `409` not reached / bundles dropped / saved before 12.4 / run not ended / no `wip`. Summaries gain `rerun_from {run_id, node_id}`.
- [x] API tests for each answer; OpenAPI and the web's generated types updated.

## 5. Console
- [x] "Rerun from here" in the selected step's pane actions, for top-level steps of an ended run (disabled with a reason when bundles were dropped).
- [x] `RerunFromStepSheet`: the step's parameter form (5.4's schema form for that node only), "Start from its uncommitted work" when `wip` applies, Start; three states; navigates to the new run. (No budget field, as for the plain Rerun.)
- [x] New run: header and runs-list trigger "Rerun of <id8> from <step>"; carried steps listed as carried over, linking to the original's step, no cost shown.
- [x] Vitest for the action's visibility, the sheet and its request body.

## 6. Specs, docs and the real run
- [x] `tech-stack.md`: run history and rerun contract (`from`, `rerun_from`), Saved branches (`step`, restore under new names, `wip` as a commit), Run console (action, sheet, carried steps), audit table, decisions-log rows from requirements.
- [ ] `lessons.md` entry if the real run shows something tests missed.
- [x] `CHANGELOG.md` under `## [Unreleased]`.
- [ ] Real run with `AGENTIC_RUNTIME=claude` (see validation.md), read step by step in Activity.
