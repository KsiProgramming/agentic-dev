# Validation: Side panel from parameter JSON Schema

## Done when (from roadmap)

> Role, instructions, provider, tools, budget (optional) are editable

## Automated checks

### Engine (`uv run pytest packages/engine`)

- [ ] `WorkflowSpec.budget_usd` is optional, accepts $0.01 to $1,000,000 and rejects 0 and negatives.
- [ ] `setParam` without `node_id` sets and unsets `budget_usd`; the engine and TS mirror agree on the new `graph-ops.json` cases.
- [ ] No manifest's `parameters` has a nullable `anyOf`; titles are sentence case.
- [ ] Agent `tools` enum is `PLATFORM_TOOLS` minus publish and create tools; a tool node's `tool` enum is `PLATFORM_TOOLS`. The spec schema still accepts an unknown tool (an `unknown_tool` issue, not `schema`).
- [ ] Every manifest's `ui` keys name fields of its `parameters`, and widgets are from the closed set.
- [ ] `schemas/workflow.v0.json`, `schemas/graph-ops.v1.json` and `schemas/fixtures/*.json` are fresh (the staleness tests pass).

### API (`uv run pytest packages/api`)

- [ ] Budget resolution: the run's budget wins over the workflow's, which wins over the workspace default, on `POST /runs`, rerun and `POST /workflows/{id}/validate`; `runs.policy.budget_usd` holds the resolved value.
- [ ] A workflow budget with an unpriced model is refused with `budget_unpriced_model`.
- [ ] `GET /node-types` returns `ui` for each manifest. `web/openapi.json` and `src/api/schema.d.ts` are regenerated; the OpenAPI drift check is green.

### Web (`cd web && pnpm lint && pnpm typecheck && pnpm test`)

- [ ] `params.test.ts`: leaf paths for scalars, scalar lists, nested objects, object lists; unset object set whole; clear → `null`; unchanged → no op.
- [ ] `ops.test.ts`: the document `budget_usd` parity cases.
- [ ] `side-panel.test.tsx`:
  - every manifest in `node-types.json` renders a form
  - a fake `echo` kind renders from its schema with no web change
  - role, instructions, provider and tools each commit one `setParam`
  - an invalid value is shown inline and not committed; the JSON widget refuses text that does not parse
  - manifest loading, error and no-manifest states
- [ ] `builder.test.tsx`:
  - select a nested agent, edit its instructions, Undo restores them, Save sends the `setParam`
  - set and clear the workflow budget from "Edit details"
  - the selection clears when its node is removed or undone away
- [ ] `pnpm lint` passes (`agentic-ui/no-raw-colors`, no arbitrary text sizes); no rjsf stylesheet is imported.
- [ ] The existing `pnpm test:e2e` suites (layout screenshots, axe) still pass for `/workflows/[id]`, updated screenshots reviewed.

### Lint and types

- [ ] `uv run ruff check`, `uv run ruff format --check` and the strict type check are clean.

## Manual / demo checks

- [ ] **Done-when demo:**
  1. From `/templates`, "Edit in builder" on the docs template.
  2. Select an agent (one inside a container too). Change its role and instructions, set provider to `claude`, tick two tools, untick one. Each change shows on the card or in "N unsaved changes".
  3. "Edit details": set a budget of $2.00. Save. Reload: version N+1 shows every value in the panel.
  4. Undo-before-save check: change the role, Undo, and the panel shows the old role.
  5. Clear the budget, Save, reload: the budget field is empty.
  6. Start a run with the saved spec (`POST /runs` with its JSON and no `budget_usd`): the run console's Cost tile reads "of $2.00 budget".
- [ ] Select a router, a loop and a reduce: their fields render (routes cannot be added or removed), and edits save.
- [ ] Keyboard only: open "⋯", "Edit parameters", tab through the form, commit with Enter, close with Escape; focus returns to the card.
- [ ] 375 px (panel as a sheet) and 1440 px (panel beside the canvas), light and dark: no horizontal page scroll, labels and help readable, errors show icon and text.

## Merge criteria

- [ ] All automated checks above pass in CI.
- [ ] tech-stack updated (side panel, manifest `ui`, document `budget_usd`, budget resolution, Frontend row, decisions rows); `CHANGELOG.md` has an `[Unreleased]` entry.
- [ ] The "Edit details" dialog is gone; no kind-specific form code in `web/src/workflows` (a `switch` on `node.type` in the panel fails review).
- [ ] The demo above was run and noted in the PR description.
