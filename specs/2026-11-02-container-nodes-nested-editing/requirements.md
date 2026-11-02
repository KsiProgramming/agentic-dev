# Container nodes drawn with children inside

Roadmap phase: 5.5
Branch: plan/5.5-container-nodes-nested-editing

## Context

Done when: **nested flow is editable visually.**

5.2 made the builder's card tree editable, but only the steps of the root sequence: everything inside a `map`, `parallel`, `loop` or router route is drawn and not edited ("Steps inside containers are drawn, not edited (5.5)", tech-stack → Builder canvas). 5.4 made the parameters of any node editable in the side panel, so structure is the only part of a nested flow still in JSON. Templates put most of their agents inside containers (the audit's `checks` parallel and its voted reviewers, the docs map), so until this phase a user cannot reshape the workflows they actually have.

The graph operations of 5.1 already address any node by id at any depth (`addNode {at: {after} | {parent, index?, route?}}`, `removeNode`, `connect {from, to, sequence_id?}`), and the browser mirror `applyOps` checks them. This phase is a web change: the builder's edits (`@/workflows/edits`) learn where a node sits, and every card gets the menu the root steps have.

What drives it:
- **Mission principle 1 (one spec, many views):** every nested edit is a list of the existing graph ops, one undo step, saved as one `PATCH` like any other edit. No new op, no model of its own in the page.
- **Mission principle 7 (small, verifiable steps):** no engine or API change; the server stays the authority (`schema` is checked only there), the browser refuses beforehand what the spec's schema would refuse (an emptied sequence, a parallel under two branches).
- **Tech-stack, Builder canvas (5.2):** the canvas stays the run map's card tree (`SpecTree`), edits stay menu items so they all work from the keyboard, and there is no drag ("drag can come later beside it, never instead").
- **Spec constraints (engine `spec/models.py`):** a sequence has at least 1 step, a parallel at least 2 branches, a loop or map exactly one body, a route exactly one node (`missing_child` otherwise).

Note: the roadmap's "Next up" line names Milestone 4 at 4.8. The user picked 5.5 on purpose. It depends on 5.1 to 5.4, all done.

It unblocks 5.6 (live validation needs edits at every depth to have something to block), 5.8 (a blank canvas grows containers) and 9.x (the Architect's nested ops show as the same edits).

## Scope

### In scope

- **Where a node sits** (`@/workflows/edits`): a helper that finds a node's place in the spec: its chain (the sequence it is a step of, or a lone node in a container's body, a parallel's branch, a route's `then` or the root) and the container slot around it. Every edit below is computed from it.
- **The step menu on every card**, at any depth (route cards excepted: they are not nodes), with the same items as 5.2's root steps:
  - **Edit parameters** (as 5.4).
  - **Add a step after** (the palette): one `addNode {at: {after}}` when the node is a sequence's step; otherwise (a lone body, branch, route or root) an `addNode` with no `at` plus a `connect {from, to, sequence_id}` that wraps the node and the new one in a new sequence, with the first free `sequence_<n>` id. One edit, one undo step.
  - **Move up / Move down** within its own chain: one `connect` each, as 5.2's `moveStep` but for any sequence. Disabled at the chain's ends and for a lone node.
  - **Move to…** (a submenu): put the node right after another node in any chain (`connect`, wrapping with a new sequence when the target is not a sequence's step), or as a new branch of a parallel (`removeNode` + `addNode {at: {parent, index}}` of the same subtree). Targets exclude the node itself, everything under it, the step right before it (a no-op) and any move that would empty its current slot (see Guards).
  - **Replace with…** (a submenu, the palette), on every node but the root: `removeNode` + `addNode {at: {parent, …}}` of the new kind in one edit, so a body, a route or a lone step is never empty. The confirm dialog names how many nodes go with the old one. (Planned only where Remove is off; offered on every node while building, as it is the one way to change a node's kind.)
  - **Remove**, with 5.2's confirm dialog.
- **Parallel branches:** a parallel's menu gets **Add a branch** (the palette): `addNode {at: {parent}}` as the last branch. A branch can be removed or moved away while the parallel keeps at least 2; a branch that is a sequence has no card of its own, so the parallel's menu has **Remove a branch** for those (named by their first step, "b2 + 1 more").
- **Guards** (computed in `edits`, shown as disabled menu items with the reason as their description, so no edit the server's schema would refuse is ever kept): Remove and Move to… are off when the node is the only step of a sequence, a loop's or map's body, a route's `then` (use Replace with…), one of only two parallel branches, or the root. The only step of the root sequence keeps 5.2's rule.
- **Drawing:** containers keep the run map's look (a container's body, branches or routes hang off it to the right as chains, joined by elbow lines; under it below 560 px), which is what "drawn with children inside" means here. The root-only note ("Only a workflow whose root is a sequence can be edited here yet") goes, as every card now has a menu. `SpecTree` keys its cards by node id instead of position (found while building: a moved card's open menu stayed with its old position); its drawing does not change. Remove's dialog and the refusal on a card work at any depth.
- **Specs:** tech-stack "Builder canvas" (menus on every card, Move to…, Replace with…, Add a branch, guards; drop "drawn, not edited (5.5)" and the 5.4 note on structure), decisions row; the edits module's comment; `CHANGELOG.md` entry.

### Out of scope

- Any engine, API or graph-op change; parity fixtures stay as they are.
- Framed boxes around containers or any change to `SpecTree`'s drawing shared with the run map (the user chose the run map's look).
- Adding, removing or renaming router routes, renaming ids, `wrap` and `extract` as ops (6.6).
- Drag and drop (a later addition beside the menus, never instead).
- Live validation issues on cards and blocked port connections (5.6).
- Playwright e2e for nested edits (the user chose unit tests and a manual demo; the existing layout and axe suites still run).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the work is | Web only: `@/workflows/edits` computes ops, `builder.tsx` draws menus | 5.1's ops already reach any depth and the browser mirror checks them; a new op would need engine, schema, fixture and client changes for nothing. |
| Adding after a lone node | `addNode` detached + `connect` with a new `sequence_<n>` | `addNode {after}` needs a sequence step; `connect`'s `sequence_id` is the documented way to grow a lone body into a chain. One edit keeps it one undo step. |
| Keeping containers non-empty | Disable Remove and Move to… where they would empty a slot; offer Replace with… (remove + add in one batch) | A batch is all or nothing and `missing_child` is checked on its result, so remove-then-add is legal; the spec's minimums (1 step, 2 branches) are schema checks only the server makes, so the browser must not keep such an edit. |
| Moving between chains | A "Move to…" submenu of targets, `connect` or remove + add | Keyboard-reachable like every other edit (tech-stack: no drag); reuses the existing ops. |
| Container look | The run map's chains to the right, not framed boxes | Keeps one `SpecTree` for the run map and the builder (5.2, 11.9 decisions) and no layout change to review. |

## Open questions

- None
