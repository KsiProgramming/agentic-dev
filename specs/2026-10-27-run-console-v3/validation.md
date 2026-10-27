# Validation: Run console v3

## Done when (from roadmap)
> From the runs list, one click shows an agent's output; a failed run names its failing step and reason without scrolling; no JSON is shown inside a table cell

- "One click": clicking a finished run in `/runs` opens the console with the last agent step selected, and its Output tab shows the final message.
- "Without scrolling": the failure banner, with the step and the reason, is inside the first viewport at 375 and 1440 px.
- "No JSON in a cell": no `td` in the console parses as a JSON object or array. Payloads open in the drawer.

## Automated checks
- [ ] Web unit (Vitest), helpers:
  - `stepKey` / `findStep` across map items, iterations and branches;
  - `defaultStep`: running, waiting, failing, last answer, and the URL wins over all of them;
  - the step outlines;
  - `writtenFiles` keeps the last write per path;
  - steps done of total agrees with `nodeStatuses`;
  - raw row summaries are one line
- [ ] Web unit (Vitest), console:
  - the header (trigger, branch, PR as the primary action, "⋯" with Copy link and Download events);
  - the five tiles, with the budget and the tokens tooltip;
  - the banner for failed, waiting and expired runs, with "Go to step";
  - two panes, List | Graph, `?step=` and `?tab=`, and old `?tab=` links;
  - Output capped, with Show full; file cards and their sheet; the Input, Usage and Events tabs; the event drawer;
  - loading, empty and error states;
  - the existing dock and gate decision tests still pass
- [ ] e2e (Playwright):
  - `console.spec.ts` checks the Done when above;
  - `monitor.spec.ts`, `graph.spec.ts`, `gate-edits.spec.ts`, `expiry.spec.ts`, `journey.spec.ts` and `inbox.spec.ts` are green on the new layout;
  - the console (List, Graph, event drawer) is covered by `a11y.spec.ts` (no serious axe issue) and `layout.spec.ts` (375, 768 and 1440 px, no horizontal page scroll)
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`. The backend checks are untouched and green in CI

## Manual / demo checks
- [ ] On the dev stack, start a docs run and watch it live:
  - the running step is selected and followed, and the live line ticks;
  - at the gate, the waiting banner and the dock show;
  - after approval, the PR becomes the primary action and fills the Output tile
- [ ] Open a finished run from `/runs`: the agent's answer shows, capped with "Show full output", and the written files show as cards
- [ ] Open a failed run (for example, one stopped by its budget): the banner names the step and the reason, and "Go to step" selects that step
- [ ] Look at the console at 375 and 1440 px, in light and dark: two panes at 1440, stacked at 375, no horizontal page scroll

## Merge criteria
- [ ] Every check above passes in CI
- [ ] No palette colours, raw JSON in cells, hand-made `Intl` formats or `duration_ms` reads (CLAUDE.md rules 1–4)
- [ ] tech-stack (the "Run console" section, the trimmed UI v2 part, the decisions log) and `CHANGELOG.md` are updated in the same PR
