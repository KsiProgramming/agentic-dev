# Validation: Canvas renders a spec; edits emit graph operations

## Done when (from roadmap)
> Editing on canvas round-trips to the stored spec

## Automated checks
- [x] **E2E round trip** (`web/e2e/builder.spec.ts`, the Done-when test): a workflow created through the API opens on `/workflows/<id>`; adding an agent after the first step, moving it down, removing a step and renaming the workflow, then Save, gives version 2; after a reload the canvas shows the edited tree, and `GET /workflows/{id}` returns that spec with `base_version: 1` and the ops sent; `GET ?version=1` is unchanged.
- [x] E2E entry: "Edit in builder" on a template opens its workflow; a second click opens the same one (no duplicate).
- [x] API: `test_workflows.py` cases for `POST /workflows {template}` (201 per template, 409 with `workflow_id`, 422 for an unknown template, a bad parameter, both bodies or neither).
- [x] Ops parity: the shared fixtures in `schemas/fixtures/graph-ops.json` pass in both `test_graph_ops_fixtures.py` and `ops.test.ts`.
- [x] Unit: `edits.test.ts`, `builder.test.tsx` (menu items → ops, undo, `409` rebase, `422` on the card); `run-map.test.tsx` unchanged after the `SpecTree` extraction.
- [x] Repo checks: `uv run ruff check`, `uv run pyright`, `uv run pytest`; `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e` (includes `a11y.spec.ts` and `layout.spec.ts` with the builder page).

## Manual / demo checks
- [ ] `docker compose up`, open Templates → "Edit in builder" on Generate docs; make each edit with the keyboard only (Tab to a card's "⋯", arrows, Enter); Save; reload: the edits are there and "Version 2" shows.
- [ ] Look at the builder at 375 and 1440 px, light and dark: cards as in the run map, no horizontal page scroll, the header's actions stack on a phone.
- [ ] Two tabs on the same workflow: save in one, then save in the other: the second says it updated to the latest version and keeps its edits (or drops them with the reason).
- [ ] Leave the page with unsaved edits: it asks first.

## Merge criteria
- [ ] All checks above pass (locally; CI minutes are limited, so the e2e job is run locally before pushing).
- [ ] `tech-stack.md` updated (Canvas row, Builder canvas section, the `POST /workflows` template body, decisions rows) and `CHANGELOG.md` has an entry under `[Unreleased]`.
- [ ] The run map looks and behaves as before (layout screenshots unchanged).
- [ ] No raw colours, arbitrary sizes or hand-rolled status pills (`pnpm lint`).
