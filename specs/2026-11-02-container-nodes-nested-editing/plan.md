# Plan: Container nodes drawn with children inside

## 1. Where a node sits (`web/src/workflows/edits.ts`)
- [x] `placeOf(spec, nodeId)`: the node's parent (`null` for the root), the slot it is in (`steps`, `branches`, `body`, `then` with its route id, `default`, `root`), its index in a list slot, and its chain (the ids of its sequence's steps, or `[nodeId]` when it is alone).
- [x] `freeId(spec, kind)`: the first free `<kind>_<n>`, shared with `newNode` (which keeps its behaviour).
- [x] `stayReason(place)` (planned as `canEmpty`): whether the node may leave its slot (not the only step of a sequence, a body, a route's `then`, one of two branches, or the root), with the reason as a sentence for the menu.
- [x] Unit tests in `edits.test.ts` on the audit and docs template specs from `schemas/fixtures` (or small inline specs): every slot kind, nested sequences, a router route.

## 2. Nested edits (`edits.ts`)
- [x] Generalise `addStep(spec, afterId, kind, manifests)`: `addNode {after}` for a sequence step, else detached `addNode` + `connect {from, to, sequence_id: freeId("sequence")}`.
- [x] Generalise `moveStep` to the node's own chain (any sequence); `null` for a lone node.
- [x] `moveTargets(spec, nodeId)` and `moveTo(spec, nodeId, target)`: "after <id>" (`connect`, wrapping when needed) and "new branch of <parallel>" (`removeNode` + `addNode {parent, index}` of the same subtree); excludes the node, its subtree, the no-op target, and everything when `canEmpty` is false.
- [x] `replaceNode(spec, nodeId, kind, manifests)`: `removeNode` + `addNode {at: {parent, index?, route?}}`; `null` for the root.
- [x] `addBranch(spec, parallelId, kind, manifests)`: `addNode {at: {parent, index: branches.length}}`.
- [x] `removeStep` unchanged; `rootSteps` replaced by `placeOf` in callers.
- [x] Tests: each edit's ops apply through `applyOps` to the expected tree, and the guards hold (no edit produced for an emptying move or remove). Undo of a wrap restores the original spec.

## 3. Menus on every card (`web/src/workflows/builder.tsx`)
- [x] `renderCard`: every node card (not route cards) gets `StepMenu`; the root-only `rootIds` check goes.
- [x] `StepMenu`: Edit parameters, Add a step after, Add a branch (parallel only), Move up, Move down, Move to… (submenu of targets, "After `lint`" / "New branch of `checks`", ids in mono; where each one is was left out), Replace with… (palette, on every node but the root), Remove a branch (a parallel's sequence branches), Remove; disabled items carry the guard's reason.
- [x] The Replace confirm reuses `RemoveDialog` with its title and button changed ("Replace `x`?", the count of nodes going with it).
- [x] The "Only a workflow whose root is a sequence…" note goes; "Add first step" stays for a root sequence.
- [x] Focus: after an edit from a menu the focus goes to the moved, added or replacing node's card (`data-select`), so keyboard users do not lose their place.
- [x] Tests in `builder.test.tsx`: a nested card has the menu; adding inside a map body wraps it; moving a branch step to the root; Replace on a loop body; Remove disabled with its reason on one of two branches; Save sends the batch.

## 4. Specs and changelog
- [x] `specs/tech-stack.md` → Builder canvas: the canvas bullet (menu on every card, the new items, guards), the side panel bullet (drop "stays 5.5"); decisions log row "Nested editing (5.5)".
- [x] `CHANGELOG.md` under `## [Unreleased]`.
- [x] Run `pnpm lint && pnpm typecheck && pnpm test`.
- [ ] Run `pnpm test:e2e`; update builder layout screenshots if the menus change them.
