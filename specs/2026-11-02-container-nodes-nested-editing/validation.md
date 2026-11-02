# Validation: Container nodes drawn with children inside

## Done when (from roadmap)
> Nested flow is editable visually

## Automated checks
- [ ] `edits.test.ts`: `placeOf` for every slot kind; `addStep` after a sequence step (one `addNode`) and after a lone body (detached `addNode` + `connect` with a fresh `sequence_<n>`); `moveStep` in a nested sequence; `moveTo` after a node in another chain and as a new parallel branch; `replaceNode` on a loop body and a route; `addBranch`; every produced edit applies through `applyOps`, and none is produced for a move or remove that would empty a slot or leave a parallel with one branch.
- [ ] `builder.test.tsx`: nested cards have the "⋯" menu; an add inside a map body, a move out of a parallel branch and a Replace show in the canvas and are one undo step each; Remove is disabled with its reason on one of two branches and on a lone body; Save sends one `PATCH` with the batch.
- [ ] `pnpm lint && pnpm typecheck && pnpm test` green.
- [ ] `pnpm test:e2e` (axe and layout suites) shows no new failures against `main` (see the known stale console specs), builder screenshots updated if needed.
- [ ] CI green.

## Manual / demo checks
- [ ] Open the audit template in the builder (`/templates` → Edit in builder). Inside the `checks` parallel: add an agent after one reviewer, move a scanner up, add a branch, move a step out to the root chain, replace the body of a loop or map from the docs template. Save; reload the page; the nested flow is as edited and the version number went up by one.
- [ ] Try to remove one of two branches and the only body of a map: the item is disabled and says why.
- [ ] Undo each edit in turn back to the saved version; Discard after a few edits.
- [ ] Do it all from the keyboard (Tab to a nested card's "⋯", arrow keys in the menus); focus lands on the changed card.
- [ ] Look at the builder at 375 and 1440 px, light and dark: no horizontal page scroll, menus fit.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `specs/tech-stack.md` (Builder canvas, decisions log) and `CHANGELOG.md` updated in the PR
- [ ] No engine, API or schema change in the diff
