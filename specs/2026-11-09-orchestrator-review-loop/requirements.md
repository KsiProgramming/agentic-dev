# Orchestrator in a loop: a team review that sends the work back

Roadmap phase: 6.9
Branch: plan/6.9-orchestrator-review-loop

## Context

A team workflow should be able to say: a lead splits the work between engineers, a synthesizer puts it together, a reviewer judges the whole, and if the reviewer says "changes" the lead plans the remaining work again, on top of what was already done, until the reviewer says "ok"; then one pull request opens. Today the engine cannot run that:

- an orchestrator may not be inside a loop (`not_allowed_in_loop`, 6.1): its plan is keyed by its id, which would repeat every iteration;
- a writer may not be inside a loop either, and an orchestrator's integration branch (6.3) is made from the clone's `HEAD`, so a second round would start from the original code and the pull request would lose the first round's work;
- the only rework is a task-level replan (6.2) on a *failed* task, with the error as its only feedback. `team-review-pr` works around this by making the per-task reviewer fail on purpose with its feedback in the error.

This phase lifts the rule for the orchestrator (chosen in the interview over a `review` option on the orchestrator and over chained orchestrators): a loop's body may hold an orchestrator, each iteration plans afresh with what the last iteration said as data, and every iteration builds on the same integration branch.

Mission principles: **Open, but safe by construction (2)** (each iteration's agents count on the run's limits, and `max_iterations` bounds the rounds); **Humans approve irreversible actions (3)** (the publish stays after the loop, behind a gate); **Repo content is data (5)** (the review reaches the hub as data, never instructions). It builds on 6.1–6.4 (orchestrator, replan, integration branch, console) and 1.9 (loop). The run map's back edge is drawn by 5.9.

## Scope

### In scope
- **Validation:** an orchestrator may be in a loop's body (it still may not be in a map, a parallel branch or another orchestrator). Its worker may write, as at the top of a run: its writes land on the integration branch, which is the only writer the loop allows. A plain writer, a gate and a publisher stay refused in a loop. `max_depth` counts the loop and the orchestrator as today.
- **Plans per iteration:** the plan is keyed by the orchestrator and the loop iteration (`RunState.plans`), so iteration 2 plans afresh; task ids stay unique across the run (a task id planned in an earlier iteration is refused, as across replan rounds), so each task's writer key and branch stay its own.
- **The hub's input in a later iteration:** `{input, iteration, previous}` as JSON: the loop body's input for this iteration (the last iteration's output, e.g. the reviewer's verdict and feedback) and every earlier task with its iteration, status and output or error. Its instructions add how to plan again from a review (`hub_iteration_instructions`). Data, never instructions.
- **One integration branch for the loop:** `agent/<run>/<orchestrator>` is made from the clone's `HEAD` in the first iteration and kept; each later iteration's task branches start from its head, and their merges add to it. A conflict fails the task as in 6.3 (replanned within the iteration if `replan` allows).
- **Limits:** each iteration's hub and tasks count on `agents_spawned` when they start (as rounds do today); the run's step limit counts `max_iterations` times the orchestrator's steps; a loop whose iterations could exceed `agents_spawned` is not refused at validation (tasks are known only at runtime), the runtime stop applies.
- **Resume:** a run cut off in iteration *n* resumes there: earlier iterations' plans and merges are kept, and the hub is not asked again for an iteration it planned.
- **Events and API:** `plan_made`, `task_*`, `replan_started` and `branch_integrated` carry `iteration` when inside a loop; nothing else changes shape.
- **Console:** the step list already nests loop iterations; each iteration's orchestrator shows its own tasks and rounds; the orchestrator's Output lists iterations, each with its plan and what the review said. The run map's back edge comes from 5.9.
- **`team-review-pr` v2:** a loop around `implement`, `synthesizer` and `reviewer` (`until: results.reviewer.data.verdict == "ok"`, `max_iterations: 3`), then the gate and `open_pr` after the loop; the per-task `verdict` trick removed. Stored as a new version of the dev stack's workflow, and its spec kept as a test fixture.
- **Specs:** tech-stack ("Orchestrator (API contract)", loop rules, decisions), roadmap `[Plan]` link, changelog.

### Out of scope
- An orchestrator in a map, a parallel branch or another orchestrator.
- Plain writers, gates or publishers inside a loop.
- Carrying an agent's conversation from one iteration to the next (each iteration's agents start fresh, with the data above).
- Drawing the back edge (5.9).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How a team review loops | An orchestrator allowed in a loop (interview) | General: any loop condition can send the work back, and the loop, its `until` and `max_iterations` already exist, are validated and are drawn. |
| Where each iteration starts | From the integration branch's head, kept across iterations | The review's "changes" must build on the merged work, and one pull request must hold all of it. |
| What the hub sees next time | The loop body's input plus every earlier task's outcome, as data | Same shape as a replan's (6.2), so the hub's instructions and the console read it alike; feedback stays data. |
| Plans and task ids | Keyed per iteration; task ids unique across the run | Keeps writer keys and branches unique (6.1) and lets a resumed run find each iteration's plan. |

## Open questions
- Whether a later iteration's hub sees the integration branch's diff (or only the tasks' outputs). Starting with the outputs; the diff can be a tool call (`repo.*` on the integration branch) if reviews need it.
