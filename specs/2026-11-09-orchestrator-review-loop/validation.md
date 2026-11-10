# Validation: Orchestrator in a loop

## Done when (from roadmap)
> A reviewer's rejection inside a loop makes the orchestrator plan again on top of the merged work, and an approval goes on to one PR

Made checkable: in a loop of orchestrator → synthesizer → reviewer, a "changes" verdict starts iteration 2, whose hub gets the review as data and whose tasks start from the integration branch; an "ok" verdict ends the loop, and the publish after it opens one pull request holding every iteration's merged work.

## Automated checks
- [ ] Validation: an orchestrator in a loop is valid; in a map, a parallel branch or another orchestrator it is still refused; a plain writer, gate or publisher in the loop is still refused.
- [ ] Engine (fake runtime): reject-then-approve runs two iterations; iteration 2's hub input holds the review and iteration 1's tasks; iteration 2's task branches start from the integration branch's head; the integration branch holds both iterations' merges; a repeated task id is refused; `max_iterations` stops the loop; every iteration's agents count on `agents_spawned`.
- [ ] Resume: a run cut off in iteration 2 resumes there without asking the hub again for a planned iteration (AC-8).
- [ ] Fixture: `orchestrator-loop-run.json` recorded and checked; Vitest folds it into iterations, each with its tasks and rounds.
- [ ] `team-review-pr` v2's spec validates (engine test).
- [ ] `uv run pytest packages/engine packages/sandbox` (sandbox tests only with the user's OK: they sweep dev sandboxes) and `cd web && pnpm lint && pnpm typecheck && pnpm test`.

## Manual / demo checks
- [ ] A real run of `team-review-pr` v2 on a test repo with Claude: the reviewer asks for changes once, iteration 2 reworks on top of iteration 1, the reviewer approves, the gate shows one diff with both iterations' changes, and one pull request opens.

## Merge criteria
- [ ] All automated checks above pass locally (CI minutes are limited: CI runs on the PR, not watched step by step).
- [ ] tech-stack (Orchestrator contract, loop rules, decisions), roadmap `[Plan]` link and `CHANGELOG.md` updated in the same PR.
- [ ] The publish stays behind a gate after the loop; review text reaches the hub only as data.
