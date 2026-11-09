# Flow layout for the canvas and the run map

Roadmap phase: 5.9
Branch: plan/5.9-flow-layout

## Context

The builder canvas (5.2) and the run map (11.9) share one drawing, `SpecTree`: a tree of cards with the run order top to bottom and each container's body, branches or routes hanging off to the right. It needs no layout engine and works on a phone, but it draws the spec's *structure*, not its *flow*. On a real team workflow (`team-review-pr`: an orchestrator with two workers, a synthesizer, a reviewer and a router) it reads oddly:

- the orchestrator's workers hang off to the side, with no line back into the next step, so the fan-out and the join are invisible;
- the reading order zigzags: down for steps, right for a container's insides, then back left;
- a router's routes are dashed cards that read like steps, though they are labels on edges;
- a loop has no back edge, so "go round again" is not drawn.

A user drew the shape they expected: left to right, the workers side by side between a fork and a join, the reviewer looping back. This phase draws that.

Mission principles: **Enterprise-grade, calm UI (8)** (a workflow should read the way people think about it), **One spec, many views (1)** (the layout is computed from the spec, and edits still go through graph operations). It changes the UI design system rule "Canvas: plain HTML card tree" and the 11.9/5.2 decisions in tech-stack. It builds on 5.2–5.6 (canvas, palette, side panel, containers, live validation), 6.4 (orchestrator tasks on the map) and 6.5 (a subflow's call on the run map). It unblocks 6.9 (a loop around an orchestrator needs a back edge to read).

## Scope

### In scope
- **A flow layout model** (`flowLayout(spec)`, pure, in `@/runs/graph`): from the spec tree, card positions and edges, with no layout library. Workflows are series-parallel, so the layout is recursive:
  - a sequence is its steps left to right;
  - a parallel, map or orchestrator is a fork, one lane per branch (a map's and an orchestrator's body as one lane, marked "× each item" / "× each task"), and a join;
  - a router's routes are lanes whose edges carry the route's name (`ok`, `default`); a route not taken is dashed on the run map;
  - a loop is its body with a back edge from its end to its start, labelled with its `until`;
  - a subflow on the run map is its called workflow inline in a framed lane (6.5); on the canvas it stays one card.
- **One renderer for both views**: the cards as today (`CARD`, status dot, menus, selection, accessible names), positioned by the model, with edges drawn in SVG (`border-strong`, 1 px, arrowheads; status colours never on edges). It replaces `SpecTree` as the drawing of the canvas and the run map.
- **Run map**: orchestrator task cards (6.4) sit in the orchestrator's lane; statuses, the selection and "Go to step" work as now.
- **Builder**: every edit menu, the palette, the side panel, live issues on cards, blocked edits, the version diff badges and keyboard focus after an edit work as now; only positions change. "Add first step" stays in the pane header.
- **Narrow screens**: below 768 px of pane width, both views keep today's vertical tree (the current `SpecTree` drawing), so a phone scrolls down, not sideways. From 768 px the flow scrolls inside its own box when wider than the pane (the page never scrolls sideways).
- **Specs**: tech-stack (UI design system → Canvas, Run map, Builder canvas; a decisions-log row superseding "card tree"), design-language (Run map → flow: lanes, joins, edge labels, back edges), roadmap `[Plan]` link, changelog.

### Out of scope
- Zoom, pan, a minimap, dragging cards or drawing edges by hand (edits stay menu items, 5.2).
- A layout library (React Flow, ELK, dagre).
- Running anything new: the loop around an orchestrator is 6.9; this phase only draws what the spec says.
- Collapsing a container to one card (can follow if large workflows need it; 10.4's 200-node target is measured there).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| What changes | Both the canvas and the run map, in one phase | They share one drawing today; splitting them would leave two layouts to keep alike (interview). |
| Layout | Computed from the spec tree, no library | Workflows are series-parallel (sequences, forks and joins, routes, loops), so positions follow from the tree in one recursive pass; no new dependency, no reversal of 11.9's "no layout engine" reason (interview). |
| Edges | SVG lines under the cards, from the model's edge list | Elbow lines in CSS cannot draw a join or a back edge; SVG can, and stays inside the pane's own scroll box. |
| Narrow screens | Keep today's vertical tree below 768 px | A flow read left to right does not fit 375 px; the vertical tree already passes the layout and axe checks there. |
| Order of work | Layout model first, then the run map, then the builder | The model is unit-tested on every fixture before anything is drawn (interview). |

## Open questions
- How a map's or an orchestrator's lane says it runs per item or per task: a "× each" badge on the lane, or stacked "shadow" cards. To settle with the first screenshots.
- Whether the run map's orchestrator task cards stack inside the lane or beside the worker; decided when the renderer is built, with the 6.4 tests as the guard.
