# Validation: Node manifests and a palette generated from them

## Done when (from roadmap)

> A new primitive appears in the palette with no frontend change

## Automated checks

### Engine (`uv run pytest packages/engine/tests/test_nodes.py`)

- [ ] Every member of the `Node` union has exactly one manifest, and a kind without one fails the test.
- [ ] Every manifest's `default` validates as a `Node`, alone and as the only step of a root `sequence`.
- [ ] `parameters` never contains `type`, `id` or a slot field. Agent's has `role`, `instructions`, `provider`, `model`, `tools`, `input_schema`, `output_schema`, `reads` and `writes`.
- [ ] Each `slots` entry names a node-holding field of the model. Leaves have none.
- [ ] Each `fill` target is a key of `parameters` (reduce: `previous_step → from`).

### API (`uv run pytest packages/api/tests/test_node_types.py`)

- [ ] `GET /node-types` returns `200` with the 9 manifests in palette order. The response matches the registry and the OpenAPI schema.
- [ ] `web/openapi.json` and `web/src/api/schema.d.ts` are regenerated and committed. The OpenAPI drift check in CI is green.

### Web (`cd web && pnpm lint && pnpm typecheck && pnpm test`)

- [ ] `edits.test.ts`:
  - a default with nested nodes (parallel, router, loop) gets fresh, unique ids
  - route ids are unchanged
  - `previous_step` sets reduce's `from`
  - a fake manifest kind `echo` becomes one valid `addNode`
- [ ] `node-types.test.tsx`: groups in category order, an unknown category last, an unknown icon name renders `BoxIcon`.
- [ ] `builder.test.tsx`:
  - the palette lists the mocked manifests grouped (Steps, Flow, Combine) with the fake `echo`
  - choosing `echo` adds `echo_1` and Save sends the `addNode`
  - loading, error with Retry, and empty rows render
  - the menu works from the keyboard
- [ ] `run-map.test.tsx` and `spec-graph.test.ts`: a spec with an unknown kind renders a card (fallback icon and label) and does not throw.
- [ ] `pnpm lint` passes (`agentic-ui/no-raw-colors`, no arbitrary text sizes).

### Lint and types

- [ ] `uv run ruff check`, `uv run ruff format --check` and pyright/mypy strict are clean.

## Manual / demo checks

- [ ] **Done-when demo**, on a scratch branch, not committed:
  1. Add a throwaway leaf primitive `EchoNode` (`type: "echo"`, `id`, `text`) to the `Node` union with a manifest (`label: "Echo"`, `category: "step"`, `icon: "megaphone"`, default `text: "hello"`).
  2. Restart the API only (`docker compose restart api`, or rerun uvicorn). Do not touch or rebuild `web/`.
  3. Open `/workflows/<id>`, then "⋯" → Add a step after. **Echo** is listed under Steps with the fallback icon and its description.
  4. Choose it. An `echo_1` card appears with the label "Echo". Save, reload, and the card is still there (stored in a new version).

  Then revert the engine change.
- [ ] Add a parallel and a router from the palette, Save, and reload. Their default children are drawn inside them (read-only) with fresh ids. The header shows the version's issue count, if any.
- [ ] Add a reduce after a parallel, and its detail line reads "Concat of <parallel id>".
- [ ] Check the palette at 375 and 1440 px, in light and dark: groups are readable, there is no horizontal scroll, and the descriptions are truncated rather than wrapped off-screen.

## Merge criteria

- [ ] All automated checks above pass in CI.
- [ ] tech-stack has the "Node manifests (API contract)" section, the updated Builder canvas and Database rows, and decisions rows. `CHANGELOG.md` has an `[Unreleased]` entry.
- [ ] No hard-coded node kind list remains in `web/src/workflows` (`NEW_KINDS` is gone).
- [ ] The demo above was run and noted in the PR description.
