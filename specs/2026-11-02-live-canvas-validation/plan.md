# Plan: Live validation on canvas

## 1. Shared fixture and engine test
- [x] `schemas/fixtures/port-checks.json`: `{$comment, cases: [{name, spec, mismatches: [node_id, …]}]}`, hand-written like `graph-ops.json`. Cases: typed pair that fits; missing required property; wrong top-level type; `integer` into `number`; gate looked through; nested sequence flattened; container breaking the edge; artifact read from its last writer (and a node reading two artifacts: no producer); merging reduce feeding a consumer; a merge source with no `findings` array; an untyped node on either side; a schema that is not an object skipped.
- [x] `packages/engine/tests/test_port_check_fixtures.py`: for each case, the `port_mismatch` issues of `port_issues(WorkflowSpec(...).root)` have exactly the fixture's node ids, in order.

## 2. Browser mirror (`web/src/workflows/ports.ts`)
- [x] `portEdges(spec)`, `mergeSources(spec)` and the artifact writer walk they need, mirroring `port_edges`, `merge_sources` and `_walk_artifacts`'s writers (reads only; no artifact issues).
- [x] `mismatch(out, wanted, producer)`, as `_port_mismatch`; `FINDINGS_PROPERTIES` (top-level property types of the findings report).
- [x] `portMismatches(spec): {producer, consumer, message}[]` in run order, messages worded as the engine's.
- [x] `ports.test.ts`: every fixture case gives its node ids; `FINDINGS_PROPERTIES` matches `schemas/findings.v1.json`'s top-level `properties` types.

## 3. Blocked connections (`web/src/workflows/edits.ts`, `builder.tsx`)
- [x] `newMismatches(spec, edit)`: the edit applied with `applyOps`, its `portMismatches` minus the spec's (keyed by producer → consumer); `[]` when the edit does not apply.
- [x] `blockReason(spec, edit)`: the first new mismatch as a sentence ("`report` needs `findings`, which `scan` does not give"), else `null`.
- [x] `StepMenu` computes, when open, each item's edit and its block reason: Move up/down, every Move to… target, Remove, Remove a branch, each palette kind under Add a step after, Add a branch and Replace with…. A blocked item uses `Unavailable` with the reason (palette items keep their icon and name).
- [x] The "Add first step" menu does the same for its palette.
- [x] `apply` refuses an edit with a new mismatch (refusal on the consumer's card, toast), as a last guard.
- [x] Tests: `edits.test.ts` (each kind of structural edit blocked on a typed spec; an edit that removes or keeps an existing mismatch allowed); `builder.test.tsx` (a Move to… target and a Remove disabled with the reason; a palette kind disabled under Replace with…).

## 4. Live issues (`web/src/workflows/api.ts`)
- [x] `useValidation(workspaceId, version, spec, dirty)`: no edits → the version's `issues`; edits → `POST /workflows/{id}/validate {workflow: spec, workspace_id}` 400 ms after the last change, query keyed by the spec, `placeholderData` keeping the previous answer; `{issues, checking, error, retry}`.
- [x] Tests with a mocked fetch (in `builder.test.tsx`): debounce (one call for quick edits), no call with no edits, the error state.

## 5. Issues on the canvas (`builder.tsx`, `side-panel.tsx`)
- [x] Group issues by `node_id`. On a card: failed edge, `CircleAlertIcon` + the first message (truncated, full text in `title`), "+N more"; a refusal still wins.
- [x] Status line: "Checking…", "Ready to run", or "N issues · runs refuse it until they are fixed" as a button opening the issues list (`Popover` from `md`, bottom `Sheet` below): each message as text, its node id in mono as a button that selects the node and focuses its card; node-less issues listed too. "Could not check the workflow." with Retry on error.
- [x] `NodePanel` takes the node's issues and shows them at the top, under a refusal.
- [x] Tests in `builder.test.tsx`: an edit with a mocked `validate` answer puts its issue on the right card and in the count; the list's node button selects the node; error with Retry; no call before the first edit.

## 6. Specs and checks
- [x] `specs/tech-stack.md`: Builder canvas (status line, issues list, issues on cards and in the panel, blocked edits); Typed ports (browser mirror, `port-checks.json`); Node manifests "Not yet" (drop the 5.6 port contracts); decisions log row "Live validation (5.6)".
- [x] `CHANGELOG.md` under `## [Unreleased]`.
- [x] `uv run pytest packages/engine/tests/test_port_check_fixtures.py`; `cd web && pnpm lint && pnpm typecheck && pnpm test`.
- [ ] `pnpm test:e2e` (axe and layout): no new failures against `main`; builder screenshots updated if the status line changes them.
