# Plan: Side panel from parameter JSON Schema

Order: engine, then API, then web. The app keeps working after each group: the panel arrives last, and the "Edit details" dialog stays until group 5 replaces it.

## 1. Workflow budget (engine)

- [x] `spec/models.py`: `WorkflowSpec.budget_usd: float | None` (`ge=0.01`, `le=1_000_000`, a description naming the precedence). `spec_version` stays `"0"`.
- [x] `spec/ops.py`: `_DOCUMENT_PARAMS` gains `budget_usd`; the `setParam` docstring and `schemas/graph-ops.v1.json` say so.
- [x] `scripts/export_workflow_schema.py`: regenerate `schemas/workflow.v0.json`, `schemas/graph-ops.v1.json` and the fixtures (`graph-ops.json` gains a document `budget_usd` case, set and unset).
- [x] Tests (`test_spec.py`, `test_ops.py`): the field validates and bounds; `setParam {path: "budget_usd"}` sets and unsets; a node path named `budget_usd` is still `not_a_param` where the node has none.

## 2. Budget resolution (API)

- [x] One helper (`agentic_api.runs` or `agentic_store.policy`): `run budget → spec.budget_usd → workspace default`, used by `POST /runs`, rerun (the stored spec's budget when the rerun sets none) and `POST /workflows/{id}/validate`.
- [x] Tests: each level wins over the ones after it; `budget_unpriced_model` fires for a workflow budget; `runs.policy.budget_usd` is the resolved value.

## 3. Form-ready manifests (engine)

- [x] `nodes.py`:
  - `parameters_schema` collapses `anyOf: [X, {type: "null"}]` to `X` (keeping `default`, `description`, `title`), and makes `title`s sentence case.
  - `AGENT_TOOLS = PLATFORM_TOOLS - PUBLISH_TOOLS - CREATE_TOOLS` (sorted); agent `tools.items.enum` and `uniqueItems: true`; tool node `tool.enum = sorted(PLATFORM_TOOLS)`; reduce's agent `tools` likewise if it has them.
  - `NodeManifest.ui: dict[str, JsonValue]` (default `{}`), and a `ui` per manifest. Agent: `ui:order` role, instructions, provider, model, tools, then the rest; `instructions` textarea; `tools` checkboxes; `input_schema`, `output_schema` json and advanced; `reads`, `writes` advanced. Tool: `args` json. Gate: `prompt` textarea. Router: `routes` not addable, removable or orderable; `classifier.instructions` textarea. Loop, map, reduce, parallel: their CEL and strategy fields with placeholders.
- [x] `tests/test_nodes.py`:
  - no `anyOf` with a null member left in any `parameters`
  - titles are sentence case
  - agent `tools` enum equals `AGENT_TOOLS`, and an agent naming each one validates with no `publish_not_tool_node` issue
  - every `ui` key names a property (or `a.b` nested property) of `parameters`; widgets are from the closed set
- [x] Regenerate `schemas/fixtures/node-types.json`; `GET /node-types` test checks `ui` is present and the agent's `provider` has no `anyOf`.
- [x] `uv run python scripts/export_openapi.py`, then `cd web && pnpm gen:api`.

## 4. Web: ops mirror and path helpers

- [x] `ops.ts`: `DOCUMENT_PARAMS` gains `budget_usd`; `ops.test.ts` runs the new parity fixture cases.
- [x] `web/src/workflows/params.ts` (pure, no React):
  - `paramOps` / `paramEdit(nodeId, before, after, schema)`: the leaf `setParam` ops between two form values (rules from requirements: scalars and scalar lists whole, objects entered, object lists per item field, an unset object set whole, empty optional → `null`), as an edit keyed by node and paths
  - `nodeParams(node, manifest)`: the node's values without `type`, `id` and slots
- [x] `params.test.ts`: agent role, tools list, `classifier.instructions` on a router with and without a classifier, `routes[1].when`, clearing `model` → `null`, no op when the value is unchanged.

## 5. Web: panel and theme

- [x] `pnpm add @rjsf/core @rjsf/utils @rjsf/validator-ajv8` (check the current major with ctx7 first; it must support React 19).
- [x] `web/src/workflows/form/` (our rjsf theme):
  - templates: `FieldTemplate` (label, help, error with `text-status-failed` and icon), `ObjectFieldTemplate` (groups, "Advanced" `Collapsible` from `ui:options.advanced`), `ArrayFieldTemplate` (honours addable, removable, orderable), `ErrorListTemplate` (none: errors are inline)
  - widgets: text, textarea, number (USD for `budget_usd`), select (`native-select`), checkboxes, checkbox, json (textarea, mono, parse check)
  - no rjsf CSS imported; tokens and type scale only
- [x] `web/src/workflows/side-panel.tsx`:
  - `NodePanel` (header: `KindIcon`, label, `IdChip`-style full id, description; the form; the `422` message when it names this node; manifest loading, error, no-manifest states)
  - `WorkflowPanel` (name, description, budget)
  - commits through `paramEdits` into the builder's edit buffer as one edit
- [x] `builder.tsx` and `SpecTree`:
  - selection state (`selectedId`); a card is selectable (a real button covering the title row, `aria-pressed`) in the builder only; "Edit parameters" first in the "⋯" menu; Escape clears
  - layout: two columns from `lg` (canvas, panel `w-96` in a bordered pane), `Sheet` below
  - selection cleared when the node is gone after undo, Discard, Remove or a rebase
  - "Edit details" opens `WorkflowPanel`; the old dialog is removed
- [x] Tests:
  - `side-panel.test.tsx`: every manifest in `node-types.json` renders a form without errors; an `echo` kind from a fake manifest renders from its schema alone; editing role, instructions, provider, tools commits one `setParam` each; an invalid value shows inline and commits nothing; JSON widget parse error
  - `builder.test.tsx`: select a nested agent, edit instructions, Undo restores it, Save sends the `setParam`; set and clear the budget (`setParam` without `node_id`); the selection clears when the node is removed

## 6. Specs, changelog, demo

- [x] `specs/tech-stack.md`:
  - Builder canvas: a "Side panel" bullet (selection, layout, commit model, workflow settings)
  - Node manifests: `ui`, the normalised `parameters`, the tool enums
  - Workflows and graph operations: the document's `budget_usd`
  - Policy limits, Budget: the resolution order
  - Frontend "Side panels" row: rjsf with our theme
  - decisions rows from requirements.md
- [x] `specs/mission.md` unchanged (the workflow budget is already there).
- [x] `CHANGELOG.md` under `## [Unreleased]`.
- [ ] Manual demo from validation.md, noted in the PR.
