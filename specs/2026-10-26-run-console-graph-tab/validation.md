# Validation: Graph tab in the run console

## Done when (from roadmap)
> Clicking a node in the graph shows what the agent did

Checkable as: on the Graph tab of a docs run, every node of the run's spec is drawn with its current status; clicking an agent node opens a sheet with that agent's messages, tool calls and usage, the same content as its step on the Timeline tab.

## Automated checks
### API (`packages/api/tests/test_runs.py`, Testcontainers Postgres)
- [ ] `GET /runs/{id}` returns `spec` equal to the spec posted to `POST /runs`.
- [ ] A rerun's detail returns the same spec as the original.
- [ ] `GET /runs` items do not include `spec`.

### Mapping and status (Vitest, no DOM)
- [ ] `specToGraph` on the docs template spec: one node per spec node, the map drawn as a container holding its body, `reduce` with a dashed edge from the map, edges in sequence order.
- [ ] Specs with a loop (with a nested sequence body), a gate and a tool node give the expected nodes, parents and edges; the layout is deterministic (same input → same positions) and no two sibling nodes overlap.
- [ ] `nodeStatuses`: nodes with no events are "Not started"; running, waiting, completed, failed and cancelled steps map to the right status; a map body node with one failed item is "Failed"; map and loop summaries read "3 of 5 items · 1 failed" and "iteration 2 of 5".
- [ ] `stepsForNode` returns one step per map item and per loop iteration for body nodes.

### Components (Vitest + Testing Library)
- [ ] The Graph tab renders a node per spec node, each with its status label (text, not colour alone).
- [ ] Clicking an agent node opens the detail sheet with its merged message and tool call lines; a not-started node shows "This step has not run yet".
- [ ] New events (SSE) change a node's status without re-laying out the graph.
- [ ] `?tab=graph` opens the Graph tab; switching tabs updates the URL.
- [ ] Keyboard: every node is reachable with Tab and has an accessible name ("writer, agent, Completed"); Enter or Space on a focused node opens its detail sheet; Escape closes it and focus returns to the node.

### End to end (Playwright, CI "Compose smoke test + e2e")
- [ ] `graph.spec.ts`: on the docs fixture run, open Graph, click a map worker, see what it did per item; the waiting gate node shows "Needs approval" and the approval dock is still visible.
- [ ] axe finds no serious issues on the Graph tab, light and dark.
- [ ] Keyboard only: from the Graph tab trigger, Tab to a map worker node, press Enter, and the detail sheet opens with what it did; the approval dock's `A` / `R` shortcuts still work while the graph has focus but not while the sheet is open.
- [ ] Screenshots at 375, 768 and 1440 px show the graph in its own box with no horizontal page scroll.

### CI
- [ ] `ruff`, strict type check and `pytest` green for every package.
- [ ] Web lint, typecheck (with the regenerated `schema.d.ts`), Vitest and Playwright green.

## Manual / demo checks
- [ ] `docker compose up`, connect Claude and GitHub, start a "Generate docs" run on a small repo from `/templates`.
- [ ] Open the run console, switch to Graph: every node is drawn; nodes not reached yet are "Not started".
- [ ] Watch nodes turn running, then completed, live; the map container shows its item count growing.
- [ ] Click a map worker: the sheet lists each module with what the agent read and wrote. Click the reducer: its merged output.
- [ ] When the run waits at the gate, the gate node says "Needs approval" and the dock is above the graph; approve, and the publisher node completes with the PR link visible in its detail.
- [ ] Unplug the mouse (or don't use it): Tab through the graph's nodes, see a visible focus ring on each, open and close a node's detail with Enter and Escape.
- [ ] Toggle dark mode and resize to a phone width: the graph stays readable and pannable, the page does not scroll sideways.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] Roadmap row 3.5 marked done (CI or `complete-phase`), and a CHANGELOG entry under `[Unreleased]`.
- [ ] `specs/tech-stack.md` describes the Graph tab and has the decision row.
- [ ] Only `@xyflow/react` is added as a dependency; no raw palette colour classes in the new components.
