# Integration branch: merge worker branches before the final PR

Roadmap phase: 6.3
Branch: plan/6.3-integration-branch-merge

## Context

6.1 (#157) gave each orchestrator task its own writer key, worktree and branch, `agent/<run>/<orchestrator>.<task>`. A gate after the orchestrator already shows and edits each task's changes. Publishing them is refused, though: `github.openPR` with an orchestrator (or a node in its body) as `from_node` is a `reference` issue ("whose task branches cannot be published yet", tech-stack decisions log, "Task writers (6.1)"). One PR cannot hold several tasks without one branch that holds them all.

6.2 (#159) added the replan policy. A task that fails can be planned again in a later round with a new id and a new branch.

6.3 adds that one branch. Once the orchestrator's tasks have run, the engine merges the completed tasks' branches into an **integration branch**, `agent/<run>/<orchestrator>`. That branch is what a gate shows and edits and what `openPR` publishes. 6.3 depends on 6.1 and 6.2 (both done). It unblocks 6.7 ("fix selected findings" as fix PRs) and AC-2 (6.8).

Principles that drive it:
- **Humans approve irreversible actions** (mission 3): the integration branch is published only by `openPR` behind a gate, as any writer's branch is.
- **Nothing is lost** (mission 9): a merge never rewrites a task's branch. A task that conflicts keeps its branch as it was, and work that merged is never merged twice.
- **Transparency** (mission 6): every merge, and every conflict with the paths it hit, is in the event log.
- **Open, but safe by construction** (mission 2): validation still requires a gate between the orchestrator and its publisher.
- Tech stack: the engine never runs git. It goes through a protocol that the worker implements over the sandbox, as `GateReview` does ("Gate review (API contract)").

## Scope

### In scope
- **The integration branch:** `agent/<run>/<orchestrator>` (the `branch_name` of the orchestrator's id), created from the clone's `HEAD`, the same base as the task branches. It has its own worktree in the sandbox.
- **When it merges:** after each round settles (the join), before a replan (6.2) or the orchestrator's end. The completed tasks of that round are merged in plan order, one `git merge --no-ff` each, by the agent identity, with the message `Merge task '<id>': <title>`. A task with no commits on its branch, or no branch (its body did not write), is skipped. An orchestrator whose body holds no writer has no integration step.
- **Conflicts:** the user chose that a conflict counts as that task failing. The merge is aborted, so the integration branch keeps every task merged before it. The task's outcome becomes `failed` with ``merge conflict with earlier tasks on src/app.py, src/util.py`` (at most 10 paths, then "and N more"). The remaining tasks of the round are still merged. With replan rounds left, 6.2's replan runs, and the hub sees the conflict as that task's error (data, mission 5). With no rounds left, the orchestrator fails like any failed task: ``task 'c' failed: merge conflict …``.
- **Idempotent and resumable:** the tasks merged are checkpointed in `RunState.integrated` (orchestrator id → task ids). The sandbox also skips a branch that is already an ancestor of the integration branch, so a crash between a merge and its checkpoint never merges twice.
- **The orchestrator as a writer:** when its integration branch has commits, `data.writers` is `[<orchestrator id>]`. The per-task keys stay in `data.plan`, and `data` gains `branch` (the integration branch) and `merged` (task ids). A gate after it shows the integration branch's files as one writer, and approve-time edits commit to it. When nothing was merged, `writers` is empty.
- **Publishing:** `openPR` with `from_node` set to the orchestrator is allowed when a gate lies between them. A node inside the orchestrator's body is still refused, with a message that names the orchestrator to publish instead. The `github` server's writers include the orchestrator's id.
- **Events:** a new `branch_integrated` event per round (`round`, `branch`, `merged: [ids]`, `skipped: [ids]`, `conflicts: [{id, paths}]`, `head`). `task_completed` for a task that conflicts is emitted with `status: "failed"` and its error. `node_completed` gains `branch` and `merged`.
- **Contract:** tech-stack "Orchestrator (API contract)" and "Gate review (API contract)" updated, plus decision-log rows. Also the `schemas/` export, the regenerated fixtures and API types, and a `[Plan]` link on the roadmap row.

### Out of scope
- An integration branch for `parallel` writers. Branches still hold no writers. A later phase or 6.8 can reuse the same integrator.
- An agent that resolves conflicts. A conflict is a task failure, and a 6.2 replan is how it is retried.
- Rebasing or squashing task branches, and choosing a merge order other than plan order.
- Git trailers on merge commits (`Agentic-Run`, …): an idea in `ideas.md`, not this phase.
- Showing the integration branch or the conflicts in the console beyond the gate review and the existing step rows. That is 6.4.
- Merging into the base branch: that stays a human's decision on the PR (mission non-goal).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where it merges | An engine step, `<id>.integrate`, after each round's join, through an `Integrator` protocol that the worker implements over the sandbox | It is checkpointed like the join, so a resumed run continues from it. The engine never runs git, as with `GateReview`. Merging inside `openPR` would leave the gate showing per-task branches rather than what is published. |
| A merge conflict | That task fails; the round's other tasks still merge; a 6.2 replan retries it, otherwise the orchestrator fails | The user's choice. One conflicting task never throws away the work that merged, and the replan policy already handles a failed task. |
| Merge style | `--no-ff` per task in plan order, from the clone's `HEAD` | Each task stays one visible merge commit in the PR's history. Plan order is the order the hub gave and is stable across resumes. |
| What a gate shows | The integration branch, as the orchestrator's single writer | What the approver reviews and edits is exactly what `openPR` pushes ("Gate edits" decision). |
| Branch name | `agent/<run>/<orchestrator>` | Matches the per-node convention. Task branches (`<orch>.<task>`) can never collide with it because node ids hold no `.`. |
| Merge state | `RunState.integrated`, plus an ancestry check in the sandbox | The checkpoint keeps resume cheap. The ancestry check covers a crash between the merge and the checkpoint. |

## Open questions
- None for 6.3. Separately, the roadmap's "Next up" line still names Milestone 4 at 4.8 (done in #156). It should name Milestone 6, in its own PR with a changelog entry.
