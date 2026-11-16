# Rerun from a step

Roadmap phase: 12.4
Branch: plan/12.4-rerun-from-step

## Context
Milestone 12 ("Nothing is lost", mission principle 9) closes the gap between what the graph keeps (AC-8, the Postgres checkpointer) and what the code keeps. 12.1 recovers runs lost before a worker claims them, 12.2 saves each writer's and integration branch as a git bundle in `run_branches` when its step completes, and 12.3 keeps a failed, cancelled or expired run's sandbox and shows its writers' changes, including uncommitted work as a `wip` version. Today a rerun (`POST /runs/{id}/rerun`, 2.6) starts from scratch: a run that failed at its last step pays again for every step before it.

12.4 lets a person rerun from one step: a **new** run (tech-stack decisions log: "Rerun: a new run linked by `rerun_of`"; the original's log stays append-only) that starts from the original's checkpoint taken before that step, with its branches restored from the bundles saved up to that step, and optionally the step's parameters edited. It finishes Milestone 12 and is the last phase before Milestone 7. It depends on 12.2 (bundles) and 12.3 (`wip`, retention), both done. 12.3's decisions log left "whether a rerun uses `wip`" to this phase.

Because the edited step's instructions change what an agent receives, `lessons.md` rule 1 applies: the phase is done only after a real Claude run is read step by step in the console.

## Scope
### In scope
- **Top-level steps only.** "Rerun from here" on a step of the run's top-level sequence: an `agent`, `tool` or `gate` step, or a whole container (`loop`, `map`, `parallel`, `orchestrator`, `router`, `subflow`) as one step, which then runs whole again.
- **Any ended run** (failed, cancelled, expired, completed) whose needed bundles are still kept. Past `branch_retention_days` (12.3) the bundles are gone and the API answers `409` naming why.
- **API:** `POST /runs/{id}/rerun` takes an optional `from` `{node_id, set_params?, use_wip?}`. Without `from` it behaves as today.
- **Checkpoint seeding:** the new run's thread (its own run id) is seeded with a copy of the original's latest checkpoint whose `next` is the chosen step; pending writes are not copied, so the step runs whole. Earlier steps are neither run nor charged again.
- **Code restore:** each `run_branches` version records the top-level step it was saved in; the new run's sandbox restores, under its own `agent/<new run>/*` names, the latest version of each branch saved by the steps before the chosen one. The new run records its base commit from the original (`runs.base_sha`).
- **Use the `wip` snapshot (optional):** when the chosen step is the one the run ended in and it left `wip` versions, `use_wip: true` restores each as one commit on top of its writer's branch ("Uncommitted work from run <id8>"), so the agent starts from where it was cut off.
- **Edit the step's parameters:** `set_params` are `setParam` graph operations (5.1, principle 1) on the chosen node only, applied to the original's spec to make the new run's spec; any other op, or a node other than the chosen one, is `422`. The stored workflow is not changed and gets no new version.
- **Carried state:** the new run's state keeps the earlier steps' results, artifacts (rows copied to the new run), router choices and plans; its spend starts at zero, so the earlier steps count neither in its cost nor against its budget.
- **Links and history:** `runs.rerun_of` plus `runs.rerun_from_node`; the summary's `trigger` stays `rerun` and gains `rerun_from {run_id, node_id}`; an audit entry `run.rerun` with `from_node`, `use_wip` and the edited paths.
- **Console:** "Rerun from here" on a top-level step of an ended run, opening a sheet with that step's parameter form (5.4's schema form, that node only), the `wip` option when it applies, an optional budget and Start. The new run's header says "Rerun of <id8> from <step>"; the steps it carried are listed as carried over, linking to the original's step, with no cost.

### Out of scope
- Rerunning from a step inside a map item, parallel branch, loop iteration or orchestrator task (a later phase if asked; would need per-task checkpoint surgery).
- Structural edits (add, remove, connect) in a rerun: that is a new workflow version (5.7) and a plain rerun.
- Resuming the original run in place (same thread, same run): never; the log stays append-only.
- A new e2e spec for the flow (the user chose engine/store tests and a real run; the repo's existing e2e, axe and layout checks still run before merge).
- Pushing anything to GitHub: nothing new is pushed (principle 3).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| How the new run starts | Copy the original's checkpoint (the latest one whose `next` is the step) into the new run's own thread; drop pending writes | One run is one thread and one append-only log; `update_state(as_node=…)` is awkward for the first step and container entries; forking in the original's thread would mix two runs' histories. |
| Which code is restored | The latest version of each branch saved in the top-level steps before the chosen one, by a new `run_branches.step` column | The save happens before the checkpoint, so a checkpoint id is not known then; the top-level step it ran in is, and orders cleanly against the chosen step without wall clocks. |
| Branch names | Restored under `agent/<new run>/<key>` from the original's bundles | Branch names carry the run id; a rerun's branches are its own. |
| Runs saved before 12.4 | A run that has branches with no `step` cannot be rerun from a step that needs them (`409` "saved before rerun from a step existed"); a plain rerun still works | No guessing which commit a step saw. |
| `wip` | Optional (`use_wip`, default off), only for the step the run ended in; applied as one commit on the writer's branch | Answers 12.3's open decision. A commit is visible in the step's changes and needs no change to how worktrees are created; default off because a rerun with changed instructions usually wants a clean start. |
| Parameter edits | `setParam` ops on the chosen node only, recorded on the new run; the stored workflow is untouched | Principle 1 (one spec, graph operations); a structural change would invalidate the copied checkpoint. |
| Spend | The new run's usage starts at zero; carried steps show no cost | Done when: earlier steps are not charged again; budgets cover the new run only, as for a plain rerun. |
| API shape | `from` on the existing `POST /runs/{id}/rerun` | One rerun endpoint; `rerun_of` already links them. |

## Open questions
- Which `RunState` fields carry spend or the run id (usage totals, branch names in results) and must be reset or rewritten when the checkpoint is copied: confirmed in plan group 2 with a test, before the API exposes `from`.
