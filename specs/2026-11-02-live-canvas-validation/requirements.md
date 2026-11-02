# Live validation on canvas

Roadmap phase: 5.6
Branch: plan/5.6-live-canvas-validation

## Context

Done when: **invalid connections cannot be made.**

The builder (5.2 to 5.5) edits any node at any depth, but it only knows the stored version's issue count ("N issues · runs refuse it until they are fixed"). It does not say which node an issue is on, and it says nothing about unsaved edits until Save. A structural edit can wire two typed nodes together whose ports do not fit: moving a step, removing the step between two others or replacing one with a `dedupe` reduce makes a new producer → consumer edge, and the server reports `port_mismatch` (4.2) only on the saved version. 5.1 stores such a version on purpose (work in progress), so nothing stops the bad connection being made.

In this spec a **connection** is a port edge as the engine defines it (`port_edges` in `agentic_engine/spec/models.py`): consecutive steps of a sequence (nested sequences flattened, gates looked through), an artifact read taken from its last writer, and the last step of a map body or parallel branch merged by a `dedupe`/`vote` reduce. A connection is **incompatible** when the engine's light check (`_port_mismatch`) fails: the consumer's `input_schema` requires a property the producer's output does not declare, or declares with a top-level type it does not accept.

What drives it:
- **Mission principle 2 (safe by construction):** limits are checked at validation time and again at runtime. The canvas becomes the earliest validation time: an incompatible connection is refused while drawing, not after a run fails at the edge.
- **Mission principle 1 (one spec, many views):** every issue comes from the one validator (`validate_workflow`, `POST /workflows/{id}/validate`, tech-stack → Workflow validation); the browser's port check is a mirror kept alike by a shared fixture, as `applyOps` is for graph ops (decision "Builder saves (5.2)").
- **Mission principle 8 (calm UI):** problems sit on the node they are about, with one sentence; a disabled menu item says why, as 5.5's guards do.
- **Tech-stack, Builder canvas:** edits stay menu items, so a blocked edit is a disabled item with its reason (`Unavailable`), never a drag that bounces.

Note: the roadmap's "Next up" line names Milestone 4 at 4.8. The user picked 5.6 on purpose. It depends on 3.4 (validate endpoint), 4.2 (typed ports) and 5.1 to 5.5, all done.

It unblocks 5.7 (a restored or diffed version shows its issues on cards), 5.8 (a blank canvas is built with live feedback) and 9.5 (the Architect's proposed ops are shown with the same issues and blocks).

## Scope

### In scope

- **Port check in the browser** (`@/workflows/ports`): a mirror of the engine's `port_mismatch` half of `port_issues`: `port_edges` (sequence steps flattened, gates looked through, artifact reads resolved through their last writer, a container or non-merging reduce breaking the edge), `merge_sources` (a merging reduce's sources must output a `findings` array) and `_port_mismatch` (required properties declared, top-level types alike, `integer` fits `number`). It returns the mismatched connections as `{producer, consumer, message}`. A merging reduce's output is the findings report; the mirror holds its top-level property types as a constant, and a web test checks it against `schemas/findings.v1.json`.
- **Shared fixture** `schemas/fixtures/port-checks.json`: specs and the `port_mismatch` issues each must give (node id, in run order). An engine test runs `port_issues` on each, a web test runs the mirror, so the two cannot drift.
- **Blocked connections** (`@/workflows/edits`): `newMismatches(spec, edit)` applies the edit (`applyOps`) and returns the incompatible connections it adds that the spec did not have. A structural edit that adds one is not offered: its menu item is disabled with the reason under it ("`report` needs `findings`, which `scan` does not give"). This covers Move up / Move down, each Move to… target, Remove, Replace with… and Add a step after / Add a branch (each palette kind), computed when the menu opens. Edits that keep or remove existing mismatches stay allowed, so a version that already has one can be fixed step by step. As a last guard, `apply` refuses such an edit with the same message (as it does an op error).
- **Live issues** (`@/workflows/api`): `useValidation` posts the edited spec to `POST /workflows/{id}/validate` (with the workspace) 400 ms after the last edit, keyed by the spec, keeping the previous answer while the next is in flight. With no unsaved edits it uses the version's own `issues` and makes no call.
- **Issues on the canvas** (`builder.tsx`):
  - A card whose node has issues gets the failed edge and, in place of its detail line, the first issue's message (icon + text, truncated with the full text in `title`) and "+N more" when it has several. 5.2's refusal keeps priority on its card.
  - The status line counts the live issues ("3 issues · runs refuse it until they are fixed", "Checking…" while a check is in flight, "Ready to run" at zero) and opens an **issues list** (a popover from 768 px, a bottom sheet below): each issue's message, its node id in mono as a button that selects that node (focus to its card, side panel open). Issues with no node (`id_mismatch`, policy limits) are listed only there.
  - The side panel shows the selected node's issues at the top, as it shows a refusal.
  - A check that fails ("Could not check the workflow." with Retry) does not block editing or Save.
- **Specs:** tech-stack → Builder canvas (status line, issues list, issues on cards and in the panel, blocked edits), Typed ports (the browser mirror and its fixture), Node manifests (drop "port contracts in the manifest (5.6)" from "Not yet"); a decisions log row "Live validation (5.6)"; `CHANGELOG.md` entry.

### Out of scope

- Any engine, API or graph-op behaviour change; the server still stores a version with issues (decision "Version validity (5.1)"), and `PATCH` does not refuse a port mismatch (the Architect's ops get the same issues back, 9.3).
- Blocking side panel edits (an `input_schema` or `reads` change that breaks a connection): they are allowed and show as live issues, as any work in progress.
- Port contracts in node manifests: the findings schema is the only typed non-port output, and the mirror and its fixture cover it (a later phase may move it to the manifest).
- Mirroring other checks in the browser (`invalid_schema` with full 2020-12 validation, artifacts, policy): the live server check reports them.
- Full schema compatibility (subsumption, `$ref`, `anyOf`): the light check stays the engine's.
- A Playwright e2e for blocked connections (the user chose unit, component tests and a manual demo; the axe and layout suites still run).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Block incompatible connections in the menus and show live server issues on cards, the status line, an issues list and the side panel | User choice. Meets "Done when" with the blocking, and "errors on nodes" with the one validator's issues. |
| How the browser knows | A TS mirror of the engine's port check, kept alike by `schemas/fixtures/port-checks.json` run by both | User choice. A menu must know synchronously which items to disable; one server call per candidate edit would make menus slow. The same pattern keeps `applyOps` honest (5.2). |
| What is blocked | Structural edits that add a mismatched connection; never one that keeps or removes existing ones | A stored version may already have mismatches (5.1 stores work in progress); refusing every edit on such a spec would leave no way to fix it. |
| Side panel edits | Allowed, shown as live issues | Typing a schema passes through invalid states; blocking each keystroke would make the field unusable. |
| Schema shape in the mirror | A schema counts when it is an object; full 2020-12 validity is left to the server's `invalid_schema` | The engine skips nodes with an invalid schema; the browser may block slightly more on a node that already shows an `invalid_schema` issue, never less. |
| Live check timing | Debounced 400 ms after the last edit, previous answer kept meanwhile | Calm UI: issues do not flicker per keystroke, and a slow check never empties the cards. |
| Issue colour | The failed status tone with an icon, as 5.2's refusal on a card | An issue means runs refuse the workflow; colour stays status (CLAUDE.md rule 2), and the card already uses this tone for refusals. |

## Open questions

- None
