# Canvas renders a spec; edits emit graph operations

Roadmap phase: 5.2
Branch: plan/5.2-canvas-graph-ops

## Context

Done when: **editing on canvas round-trips to the stored spec.**

5.1 stored workflows as immutable versions and made graph operations (`addNode`, `removeNode`, `connect`, `disconnect`, `setParam`) the one way to change them (tech-stack → "Workflows and graph operations"). Nothing in the web app reads or writes a stored workflow yet. This phase adds the first editor: a page that draws a stored workflow and turns each edit into graph ops, saved as one `PATCH /workflows/{id}`.

Mission principle 1 (**one spec, many views**) drives it: the canvas never holds a second model of the graph; it holds the base version's spec plus a list of ops, and what it shows is those ops applied to that spec. Principle 8 (calm UI) and the 11.9 decision "Run graph: a tree of cards, no React Flow or ELK" drive the look: the canvas is the run map's card tree made editable, not a pan-and-zoom box.

Note: the roadmap's "Next up" line names 4.8, which is not planned. 5.2 was picked on purpose by the user; it depends only on 5.1 (done) and the run map (11.9, done).

It unblocks 5.3 (the palette fills the "Add step" menu from manifests), 5.4 (the side panel emits `setParam` for a selected card), 5.5 (editing inside containers), 5.6 (issues and blocked connections on cards) and 5.7 (history and restore on the same page).

## Scope

### In scope

- **Page `/workflows/[id]`** (the browser's workspace): `PageHeader` with the workflow's name and description, its id in full (mono: workflow ids are readable slugs, so not an 8-character `IdChip`), and the actions Edit details, Undo, Discard and Save; under it one line with "Version N", the issue count from the stored version ("3 issues · runs refuse it until they are fixed", text only; per-node issues are 5.6) and the unsaved changes. Loading, empty (unknown workflow → `EmptyState` with "Go to templates") and error states.
- **Canvas = the run map's card tree, editable.** The chain-of-cards layout of `RunMap` is extracted into one shared presentational tree (`SpecTree`) used by the run map (with statuses) and the canvas (with edit actions). Same cards, same widths, same phone layout; no status dots on the canvas.
- **Edits (each a keyboard-reachable item in the card's "⋯" menu, `aria-label` on the icon button):**
  - *Add step after* (and "Add first step" above the first): a small hard-coded kind menu, **agent**, **tool**, **gate**, each with schema-valid defaults (agent: role "Agent", instructions "Describe what this agent does."; tool: `repo.list_files`; gate: title "Approve"), id `<kind>_<n>` unique in the spec → `addNode {node, at: {after}}` (or `{parent: root, index: 0}`). Replaced by the manifest palette in 5.3.
  - *Move up / Move down* → one `connect` that moves the step (moving the first step down is `connect {from: second, to: first}`; any order is reachable this way).
  - *Remove* → `removeNode`, confirmed in a dialog that names the node and how many nodes under it go with it.
  - *Edit details* (a dialog with name and description) → `setParam` with no `node_id` (`name`, `description`), one edit.
  - Edits apply to **steps of the root sequence** (any kind, containers moved and removed whole). Inside a container the cards are drawn but read-only (5.5).
- **Local op buffer and explicit Save.** Edits append to a buffer; the canvas shows `applyOps(baseSpec, buffer)`. Undo pops the last edit (an edit may be several ops); Discard (with a confirm) empties it. Save sends the buffer as one `PATCH {base_version, ops}`, then shows the new version and empties the buffer. "N unsaved changes" shows under the header; leaving the page with changes asks first (`beforeunload`, as the gate review's edits do).
- **TS `applyOps` mirror** (`@/workflows/ops`): the five ops, placement rules and every error code except `schema` (the server's), typed from the generated `GraphOp` schema. It is a preview only; the server's answer is the truth.
- **Conflicts and refusals:** `409 version_conflict` → reload the latest version and re-apply the buffer on it locally; if it applies, keep the edits and say "Updated to version N, your edits were kept"; else drop them with the op error. `422` op error → toast with the message, the named node's card marked with an error line until the buffer changes.
- **Entry point:** "Edit in builder" on each template card of the gallery: `POST /workflows {template, parameters}` builds the spec from the template's defaults and stores version 1; `409 workflow_exists` opens the existing workflow. Navigates to `/workflows/<id>`.
- **API addition:** `POST /workflows` also takes `{template: {id, parameters?}}` instead of `{spec}` (exactly one of them). An unknown template, bad parameters or both bodies are `422`, as `POST /runs` answers them. `409 workflow_exists` carries `workflow_id`.
- Breadcrumbs from the shell: "Workflows › <id>" (no Workflows list page yet: the segment is not a link).
- Specs: tech-stack "Builder canvas" UI section, the Frontend "Canvas" row (no React Flow), the `POST /workflows` template body, decisions rows; `CHANGELOG.md`.

### Out of scope

- Drag and drop, drawing edges with handles, pan and zoom (a later phase may add drag beside the menu; never drag only).
- The manifest-driven palette (5.3); editing node parameters in a side panel (5.4).
- Adding, moving or removing nodes inside containers, and adding containers (5.5).
- Issues on cards and blocking invalid connections (5.6).
- Version history, diff, restore, running a stored version (5.7); a Workflows list page and "Blank canvas" (5.8).
- Redo, autosave, multi-user presence.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Canvas technology | The run map's card tree made editable (`SpecTree` shared by both); no React Flow | 11.9 dropped React Flow and ELK because pan and zoom inside a box was hard to handle; the tree is the spec's own shape (5.1's edge model), works on a phone and needs no layout engine. Supersedes tech-stack's "React Flow added back with Milestone 5". |
| Edit gestures | A "⋯" menu per card (add after, move up/down, remove), no drag | Every edit reachable by keyboard (CLAUDE rule 10) with one code path; each item maps to one known op. |
| Where edits apply | The root sequence's steps; containers drawn read-only | 5.5 owns nested editing; the ops already support it, so 5.5 is UI only. |
| Save model | Local op buffer, one `PATCH` per Save, undo by popping the buffer | One version per intent, not per click; undo is free (the ops are the history); matches 5.1's `base_version` concurrency. |
| Client apply | A TS mirror of `apply_ops` for preview, with parity fixtures shared with the engine tests | The canvas shows edits before Save and rebases them after a `409`; shared fixtures keep the two from drifting. The server stays the authority (`schema` is checked only there). |
| Node defaults | Hard-coded agent, tool and gate with schema-valid defaults | Enough to prove the round trip; 5.3 replaces the menu with manifests. |
| Entry point | `POST /workflows {template, parameters?}` from a template; existing → open it | No list page until 5.8, and templates are the only specs users have. Building the spec on the server keeps templates in Python. |

## Open questions

- None
