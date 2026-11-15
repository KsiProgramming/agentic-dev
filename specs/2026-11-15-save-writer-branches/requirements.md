# Writers' commits saved outside the sandbox

Roadmap phase: 12.2
Branch: plan/12.2-save-writer-branches

## Context

Principle 9 ("Nothing is lost") and AC-8 hold for the graph but not for the code. The code agents write lives only in the run's sandbox volume until the gated `github.openPR` pushes it. When a worker dies, the next attempt resumes after the last completed node, but `DockerSandboxManager.open` gives it a **fresh** sandbox (`packages/sandbox/src/agentic_sandbox/docker_backend.py`): a new clone, with none of the commits the completed writers made. The checkpoint says "writer done", and its branch is gone. The same happens when a gate's kept sandbox is missing on approval (`open(..., reuse=True)` falls back to a fresh one).

A second gap: a fresh clone takes the default branch as it is **now**. Nothing records the commit the run started from, so a resumed agent can read different code than before, and a saved branch's base may not be in the new shallow clone.

12.1 (recover runs lost before a worker claims them) is done. 12.2 is what 12.3 (a failed run keeps its code, shown from its saved bundles) and 12.4 (rerun from a step, code restored) build on.

Specs it follows:
- Mission principle 3: saving is **not** a push. Bundles stay in our Postgres; nothing leaves for GitHub without a gate. Pushing work-in-progress branches is out (roadmap, Milestone 12 intro).
- Mission principle 6: every save is an event in the append-only log.
- Tech stack, Sandbox and Run artifacts (4.3): Postgres is the source of truth, the sandbox a working copy. Bundles follow the same model as `run_artifacts`.
- Tech stack, Durable state: the LangGraph Postgres checkpointer. A step's commits are saved **before** the checkpoint that records the step as done, so no crash lands between the two.
- Existing code: `agentic_sandbox.bundle` already exports `<base>..<branch>` as a bundle (for the push). `worktree.py` and `integrate.py` already reopen a worktree on a branch that exists.

## Scope

### In scope
- **Pinned base commit.** At a run's first clone, the clone's `HEAD` SHA is recorded on the run (`runs.base_sha`). Every later sandbox for the run (a resumed attempt, a missing kept sandbox, the attempt after `repo_created`) clones that SHA, not the branch tip. A run started before 12.2 has no `base_sha` and clones as it does today.
- **Save when a step completes:**
  - each writer's branch (`agent/<run>/<node>`, and `agent/<run>/<orchestrator>.<task>` for task writers), when its writer node, map item, parallel branch or orchestrator task completes;
  - each integration branch (`agent/<run>/<orchestrator>`) after `<id>.integrate`;
  - each edited writer's branch again after a gate commits the approver's edits (`Edit at gate <id>`).
  The save happens inside the step, before it returns its update, so the checkpoint never records a step whose commits are not saved. One hook at the end of each step that may commit saves every branch of the run whose tip moved, which covers all three cases above. A branch with no commits beyond the base is not saved. A save whose head is unchanged adds no version.
- **Storage:** an append-only `run_branches` table (migration 0030): one row per saved version of a branch, with the run, branch, node key, kind (`writer` or `integration`), version, `base_sha`, `head_sha`, commit count, size and the bundle bytes. The latest version per branch is the one restored.
- **Restore** when an attempt starts with a fresh sandbox (a killed worker's run, a missing kept sandbox): the worker fetches each branch's latest bundle into the new clone, on the worker, before the clone is copied into the sandbox (`put_file`'s 1 MB cap rules out going through the sandbox). Worktrees then reopen on those branches on first use, as today. A reused kept sandbox is not restored over.
- **Events:** `branch_saved` `{key, branch, kind, version, head, commits, size}` on each new version, its `node_id` the node the key belongs to (a task writer's orchestrator); `branch_save_failed` `{key, branch, error}` when a save fails (over the size cap, git failed); `branches_restored` `{branches: [{branch, head}]}`, run-level, once per attempt that restored, before `run_resumed`.
- **Console marker:** a writer step and an orchestrator show "Commits saved" with each branch, its commit count, its tip (`IdChip`) and when it was saved (`RelativeTime`); a failed save shows its reason as an error line on the step. The three events read as one line in Raw events (the Activity tab is per step, and `branches_restored` belongs to the run).
- **Live stream:** `EVENT_TYPES` in the web gains the three events, and the 6.x events it was missing (`route_chosen`, `plan_made`, `replan_started`, `task_started`, `task_completed`, `branch_integrated`), which the live console never received: `EventSource` delivers only the event names it listens for.

### Out of scope
- Keeping a failed or cancelled run's sandbox for a time to live, and showing a writer's changes from its bundle: **12.3**.
- Rerun from a step with the code restored: **12.4** (it reads what 12.2 saves).
- Pushing work-in-progress branches to GitHub: never, by principle 3.
- Deleting or expiring saved bundles. They live as long as the run; retention is decided with 12.3.
- Showing `base_sha` in the runs API or the console. It is stored for the engine only in 12.2.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where bundles live | Postgres `bytea`, append-only `run_branches`, latest per branch restored | Postgres is already the source of truth for artifacts and checkpoints; no object store to add. The size cap keeps rows bounded. |
| What a bundle holds | `<base_sha>..<branch>`, the existing `agentic_sandbox.bundle` export | It already exists for the push, and the base is pinned, so its only prerequisite is always in the clone. |
| Base of a run | `runs.base_sha` recorded at first clone; later clones fetch that SHA at depth 1 | A restored bundle always applies, and a resumed agent reads the same code it started from. |
| When a branch is saved | Inside the step, before its update is checkpointed | A crash between "step done" and "commits saved" would bring back the gap this phase closes. |
| How the engine asks for a save | A `BranchSaver` protocol in `agentic_engine` that the worker implements over the sandbox and the store, as `BranchIntegrator` and `GateReview` are; the engine wraps each step that may commit and saves every moved branch | The engine never runs git and never touches the store's tables. One hook covers every kind of writer, task, integration and gate edit. |
| Where a restore happens | On the worker, into the fresh clone, before it is copied into the sandbox | The sandbox's `put_file` takes at most 1 MB; a bundle may be 64 MB. |
| Size cap | 64 MB per bundle (`MAX_TAKE_FILE_BYTES`); over it the save fails with `branch_save_failed` and the run goes on | Same bound as a pushed bundle; failing the run over a backup would lose more than it protects. The console shows the step as not saved. |
| Re-saving after gate edits | Yes, each edited writer's branch | A worker killed after an approval with edits must not push the agent's version without the reviewer's edits. |
| Real run with Claude (lessons rule 1) | Not required for this phase | Agents' instructions, inputs and tools do not change. What changes on resume, the commits on their branch, is asserted in the crash test. |

## Open questions
- Resolved during the build: a sandbox removed in the middle of a step does not end the attempt; the step's tool calls fail with "the sandbox is not available". 12.2 does not change that. The commits of every step that completed before are already in `run_branches`, which is what "loses no completed step's commit" asks; resuming such a run automatically is left for a later phase (noted in tech-stack, "Saved branches").
