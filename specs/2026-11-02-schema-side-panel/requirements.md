# Side panel from parameter JSON Schema

Roadmap phase: 5.4
Branch: plan/5.4-schema-side-panel

## Context

Done when: **role, instructions, provider, tools, budget (optional) are editable.**

5.2 made the stored spec editable as a card tree, but only its structure: add, move and remove steps. Every parameter of a node (an agent's role and instructions, a gate's title, a loop's `until`) still has to be written in JSON. 5.3 gave each primitive a manifest whose `parameters` is the node's JSON Schema, and said "the side panel (5.4) renders it". This phase adds that panel: select a node, edit its parameters in a form drawn from its manifest, and each change is a `setParam` op in the 5.2 edit buffer, saved as a new version like any other edit.

What drives it:
- **Mission principle 1 (one spec, many views):** the panel holds no model of its own. It reads the node from the spec shown (base version plus the buffer) and writes only `setParam` ops, so undo, Save, `409` rebase and the audit entry work as they do for the canvas.
- **Mission, "Open orchestration":** the form comes from `parameters`, so a primitive the engine adds (or a composite in 6.6, a plugin in 10.1) gets a panel with no web change, as 5.3 did for the palette.
- **Mission v1 decision "Budget is optional":** "a workspace, workflow or run *may* set a USD budget". Workspace and run budgets exist (3.3); a workflow's does not, since the spec has no field for it. This phase adds it, so "budget (optional)" in the Done-when is the workflow's budget.
- **Tech-stack:** "Side panels: JSON-Schema forms (`@rjsf/core`), rendered from node manifests"; "tools granted per node through the node manifest" (5.3 left the per-node grant to 5.4). The panel follows the design language (surfaces, three text levels, type scale) and CLAUDE rules 1 to 11.

Note: the roadmap's "Next up" line names 4.8, which is not planned. The user picked 5.4 on purpose. It depends on 5.1, 5.2 and 5.3, all done.

It unblocks 5.5 (a node added inside a container is configured in the same panel), 5.6 (a node's issues show in its panel), 5.8 (a canvas workflow is set up without JSON) and 9.x (the Architect's `setParam` ops land in the fields people already see).

## Scope

### In scope

- **Manifest additions (engine):**
  - `parameters` is normalised for forms: an optional field's `anyOf: [X, {type: null}]` becomes `X` (not required means it may be unset), and titles are sentence case ("Input schema", not "Input Schema"). The spec's own JSON Schema (`schemas/workflow.v0.json`) does not change.
  - Choices the spec checks in validation, not in its schema, become `enum`s in `parameters` only: an agent's `tools` items are the tools an agent may be granted (`PLATFORM_TOOLS` minus publish and create tools, which only a tool node may call); a tool node's `tool` is one of `PLATFORM_TOOLS`. The spec still takes any string, so an unknown tool stays an `unknown_tool` issue, not a `schema` error.
  - A new manifest field `ui`: a small, kind-agnostic subset of an rjsf `uiSchema` keyed by field: `ui:widget` (`textarea`, `json`, `checkboxes`), `ui:order`, `ui:placeholder` and `ui:options` (`advanced: true` puts a field in a collapsed "Advanced" group; `addable`, `removable`, `orderable: false` for a list whose length is structure, like a router's `routes`). Every manifest gets one; a test checks each key names a field in `parameters`.
- **Workflow budget (engine, API):**
  - `WorkflowSpec.budget_usd: float | None` (optional, $0.01 to $1,000,000, as elsewhere). Adding an optional field keeps `spec_version: "0"`.
  - `setParam` without `node_id` takes `budget_usd` as well as `name` and `description` (engine and the TS mirror, with a parity fixture).
  - A run's budget is the first set of: the run's own (`budget_usd` on `POST /runs`, rerun), the workflow's (`spec.budget_usd`), the workspace default. `POST /workflows/{id}/validate` resolves it the same way. Frozen in `runs.policy` as today; `budget_unpriced_model` applies to it like any budget.
  - The OpenAPI spec, the generated client and the schema fixtures are regenerated.
- **Side panel (web):**
  - **Selecting:** clicking a card, or "Edit parameters" (first item of its "⋯" menu), selects that node. Any card can be selected, including those inside containers: parameters are not structure, so a nested agent's instructions are editable now; adding, moving and removing inside containers stays 5.5. The selected card has the selected edge from design-language. Escape or the panel's close button clears it.
  - **Where it sits:** from 1024 px, a pane to the right of the canvas (the canvas narrows; no horizontal scroll); below that, a `Sheet` from the right. Header: the node's kind icon and label, its id (mono, full), and the manifest's description in `muted-foreground`.
  - **Form:** `@rjsf/core` with `@rjsf/validator-ajv8`, themed with our own templates and widgets built from `web/src/components/ui` (`field`, `input`, `textarea`, `native-select`, `checkbox`, `collapsible`): text, number, boolean, enum select, multi-select checkboxes (tools), object fields grouped, an "Advanced" collapsible, and a JSON widget for object-valued fields (`input_schema`, `output_schema`, `args`) that checks the text parses before it commits. Help text is the field's `description`. No rjsf default markup or styles reach the page.
  - **Commit model:** every change the form's validator accepts becomes a `setParam {node_id, path, value}` edit; consecutive changes to the same fields of the same node replace the last edit, so typing in one field is one undo step. Clearing an optional field sends `null`. (Planned as commit on blur; changed while building, since rjsf's change and blur events do not give a reliable order to commit on.) Paths are leaf-level: a scalar or a list of scalars is set whole (`tools`), an object is entered (`classifier.instructions`), a list of objects is set per item field (`routes[1].when`). Setting a field of an unset object sets the whole object. A value the form's validator rejects is shown inline and not committed.
  - **Workflow settings:** with no node selected (and from the header's "Edit details", which now opens it), the panel shows the workflow: name, description and budget. Budget is a USD field with the hint "Unset: the workspace's default (or none)"; the 5.2 "Edit details" dialog is removed.
  - The panel follows the spec shown: undo, Discard and a `409` rebase update it; if the selected node disappears, the selection is cleared. A `422` that names the selected node shows its message at the top of the panel.
  - States: the manifests' loading and error (from `useNodeTypes`) show `LoadingState` and `ErrorState` in the panel; a kind with no manifest shows "No editable parameters for this kind" and the node's JSON (`JsonView`).
- **Specs:** tech-stack "Builder canvas" (side panel bullet), "Node manifests" (`ui`, the normalised `parameters`, tool enums), "Workflows and graph operations" (document `budget_usd`), the budget policy bullet (resolution order), Frontend row (rjsf themed by us), decisions rows. `CHANGELOG.md` entry.

### Out of scope

- Adding, moving or removing nodes inside containers, and adding or removing router routes (5.5, 6.6).
- Live validation issues on cards and fields from the validator, and blocking bad connections (5.6). The header's version issue count stays as it is.
- A per-node budget, model pickers from the price table, and a provider other than `claude` (the enum is what the spec allows).
- Per-tool argument forms for a tool node's `args` (a JSON field now; 10.1 plugins may describe theirs).
- Running a stored workflow from the builder, history and restore (5.7).
- Monaco in the panel (the JSON widget is a textarea with a parse check; Monaco stays for diffs).
- Playwright e2e for the panel (the user chose unit tests and a manual demo; the existing layout and axe suites still run).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Which budget | An optional `budget_usd` on the workflow spec, between the run's and the workspace's in precedence | The mission already lists a workflow budget; it fits the existing hard-stop meter with no engine change, and a per-node cap would need a new meter. |
| Form library | `@rjsf/core` + `@rjsf/validator-ajv8` with our own templates and widgets | The tech stack chose rjsf; theming it with our primitives keeps the design rules (tokens, type scale, a11y) and lets any schema render, which a hand-written renderer would have to re-earn. The shadcn theme package ships its own copies of primitives we already own. |
| Form-friendly schema | Normalised in the manifest's `parameters` (nullable `anyOf` collapsed, sentence-case titles, tool enums), not in the spec schema | rjsf renders `anyOf` as a type switcher; fixing it once in the engine keeps the web kind-agnostic. The spec schema keeps accepting any tool name so validation still explains it (`unknown_tool`). |
| Layout hints | A manifest `ui` field, a subset of rjsf's `uiSchema` | Widgets, order and the "Advanced" group come from the engine with each primitive, so a new primitive needs no web change for a good form either. |
| Commit granularity | One `setParam` per accepted change at leaf paths, consecutive changes to one field coalesced | One undo step per intent, not per keystroke, and the canvas updates as you type; leaf paths keep the audit and the diff (5.7) readable. |
| Nested nodes | Parameters of any node are editable; structure stays root-only until 5.5 | `setParam` already addresses any node by id; template agents are mostly inside containers, so the Done-when would be hollow otherwise. |
| Workflow details | The panel with no selection replaces the "Edit details" dialog | One place for the workflow's own fields, budget included. |

## Open questions

- None
