# Validation: Flow layout for the canvas and the run map

## Done when (from roadmap)
> A workflow reads left to right on the canvas and the run map: a parallel, map or orchestrator forks into lanes and joins, a router's routes are labelled edges and a loop has a back edge; below 768 px the vertical tree stays

Made checkable: `team-review-pr` shows `implement` forking into its worker lane and joining into `synthesizer`, then `reviewer`, then `decision` with `ok` and `default` edges; a loop shows one back edge labelled with its condition; no card overlaps another at any width; every existing canvas edit works as before.

## Automated checks
- [ ] Vitest `flow-layout.test.ts`: every spec fixture and `team-review-pr` lays out with no overlapping cards, every edge between two cards, steps left to right, one back edge per loop, stable output.
- [ ] Vitest: run map and builder tests (`run-map*.test.tsx`, `timeline-subflow.test.tsx`, `builder.test.tsx`, `edits.test.ts`) pass on the new drawing; the vertical tree is drawn below 768 px.
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test`.
- [ ] `pnpm test:e2e` layout screenshots and axe at 375, 768 and 1440 px, light and dark, for the builder and the run map (no serious axe issue, no horizontal page scroll).

## Manual / demo checks
- [ ] In the dev stack, open `team-review-pr` in the builder and a finished run of it: the shape matches the user's sketch (fork, join, synthesizer → reviewer → decision, labelled routes).
- [ ] Open the audit template and a subflow run on the run map: routes and the called workflow read left to right.
- [ ] Check each at 375 px (vertical tree) and 1440 px (flow), light and dark.

## Merge criteria
- [ ] All automated checks above pass locally (CI minutes are limited: CI runs on the PR, not watched step by step).
- [ ] tech-stack, design-language, roadmap `[Plan]` link and `CHANGELOG.md` updated in the same PR; the "card tree" decisions superseded in the decisions log, not deleted.
- [ ] Colours from tokens only, no status colour on edges, every card a real button with its visible text as its name.
