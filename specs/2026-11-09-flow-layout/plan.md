# Plan: Flow layout for the canvas and the run map

Layout model first, then the run map, then the builder (interview choice).

**Changed while building:** the root sequence wraps into rows to fit the pane (`flowLayout(spec, maxCols)`, a `wrap` edge), the flow is drawn from 560 px of pane width, and a route's name sits over its first card. One `SpecView` picks flow or tree for both views. The repo stays green after each group: the old `SpecTree` drawing stays until the new one replaces it in each view.

## 1. Layout model
- [x] `web/src/runs/graph/flow-layout.ts`: `flowLayout(spec, options)` → `{cards: [{id, kind, x, y, lane}], edges: [{from, to, label?, kind: "flow" | "fork" | "join" | "back"}], width, height}`. Cards are the same size as today (208 × 56 px); gaps from tokens (one column gap, one lane gap).
- [x] Rules: sequence left to right; parallel, map, orchestrator: fork → lanes → join (map and orchestrator: one lane with its "× each" marker); router: lanes with labelled edges, `default` last; loop: body plus a back edge labelled with `until`; subflow: a framed lane of its called root on the run map (`calledRoot`), a leaf card on the canvas.
- [x] Vitest (`flow-layout.test.ts`) over every spec in `schemas/fixtures` and `packages/engine/tests/fixtures/specs/valid`, plus `team-review-pr`: no two cards overlap; every edge joins two cards; run order reads left to right (each sequence step right of the one before); a loop has exactly one back edge; the layout is the same for the same spec.

## 2. Renderer and the run map
- [x] `web/src/runs/graph/flow-view.tsx`: absolutely positioned cards (the existing card components) over an SVG of the edges, in a box that scrolls on its own from 768 px; edge labels as text; back edges as curves under the lanes.
- [x] `run-map.tsx`: draws `FlowView` from 768 px of pane width (a container query), `SpecTree` below. Status dots, the selected ring, task cards (6.4), skipped routes (dashed edge and card), the footer, keyboard order (run order) unchanged.
- [x] Update `run-map.test.tsx`, `run-map-orchestrator.test.tsx`, `timeline-subflow.test.tsx` for the new drawing; keep their behaviour checks.

## 3. The builder
- [x] `builder.tsx`: the canvas draws `FlowView` with its cards (menus, issues, diff badges, selection) from 768 px, `SpecTree` below.
- [x] Focus after an edit, blocked items, "Add first step", the side panel and history work unchanged; `builder.test.tsx` and `edits.test.ts` keep passing.

## 4. Specs, design language, screenshots
- [x] `specs/design-language.md` → Run map: the flow (lanes, forks and joins, edge labels, back edges, the narrow fallback).
- [x] `specs/tech-stack.md`: Frontend → Canvas; UI design system → Run console → Run map, Builder canvas; decisions log row superseding the "card tree" rows (11.9, 5.2).
- [ ] Layout screenshots (`layout.spec.ts`, not run yet: e2e needs the fake-runtime stack) and axe (`a11y.spec.ts`) for the builder and the run map with `team-review-pr`-like and router/loop workflows at 375, 768, 1440 px, light and dark.
- [x] `specs/roadmap.md` `[Plan]` link; `CHANGELOG.md` entry.
