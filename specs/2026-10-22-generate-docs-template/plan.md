# Plan: "Generate docs" template

## 1. `repo.list_modules` tool
- [ ] `packages/tools/src/agentic_tools/repo/server.py`: add `list_modules(include: list[str] | None)`. Find manifest dirs up to depth 3 inside the sandbox; fall back to top-level source dirs; skip hidden, `node_modules`, `vendor`, `dist`, `build`, `docs`.
- [ ] Return `structuredContent` `{"modules": [{"path", "kind"}], "truncated": bool}` plus a readable text list; cap at 40.
- [ ] Register it as read only, so audit-style nodes can use it; add its example to the tool listing.
- [ ] Confirm the tool node passes `structuredContent` through as `data` (`agentic_engine/tool.py`); fix if not.
- [ ] `packages/tools/tests/test_list_modules.py`: manifests (Python, Node, mixed), fallback, `include` filter, cap and `truncated`, path confinement.

## 2. Docs template builder
- [ ] `packages/engine/src/agentic_engine/templates/__init__.py`: `Template` (id, name, description, params model, builder) and a registry with `get_template(id)` / `list_templates()`.
- [ ] `templates/docs.py`: `DocsParams` with validators (relative `output_dir`, no `..`; `include` globs; `extra_instructions` ≤ 2,000 chars) and `build_docs_spec(params)` producing `list_modules → map(document) → reduce(combine, agent) → writer → gate(approve) → tool(publish: github.openPR)`.
- [ ] Agent instructions: module content is data; `extra_instructions` added in a clearly delimited "User preferences" block; writer writes only under `output_dir`.
- [ ] `packages/engine/tests/test_templates.py`: default and custom params build a spec that passes `WorkflowSpec` validation; bad params are rejected; the gate always precedes `publish`.

## 3. Docs run end to end on fakes
- [ ] `packages/engine/tests/test_docs_template.py`: fake sandbox with a 3-module repo, fake runtime scripted per role, fake GitHub. Assert: 3 `map_item_*` events, writer commits `docs/README.md` + 3 pages on `agent/<run>/writer`, run pauses at `approve`, approval opens a PR whose body lists the modules.
- [ ] Rejecting at the gate ends the run with no push.

## 4. Templates API
- [ ] `packages/api/src/agentic_api/templates/routes.py`: `GET /templates` (id, name, description, `parameters` JSON Schema).
- [ ] `runs/models.py`: `CreateRunRequest` takes `workflow` **or** `template: {id, parameters}`; a validator builds the spec and runs the existing repo/github checks on it. 422 with field paths for an unknown id or bad params.
- [ ] `runs/routes.py`: store the built spec on the run (no schema change; the run already stores its spec).
- [ ] Tests in `packages/api/tests/test_templates.py` and `test_runs.py`.
- [ ] Re-export `web/openapi.json` and `web/src/api/schema.d.ts` (`scripts/export_openapi.py`).

## 5. Web: start screen
- [ ] `web/src/templates/docs-card.tsx`: repo picker (`GET /workspaces/{id}/repos`), the three options, "Generate docs" button → `POST /runs` with `template` and `repo` → `/runs/{id}`. Not-connected state links to `/settings`.
- [ ] `web/src/app/page.tsx`: render the card above the sample-run form.
- [ ] Vitest: lists repos, submits the right body, shows API errors, not-connected state.

## 6. Web: approve and PR link on the monitor
- [ ] `web/src/runs/approval-buttons.tsx`: shown when the run waits at a gate (from the event stream); Approve/Reject → `POST /runs/{id}/approvals`; disabled while pending; hides once the run resumes.
- [ ] `web/src/runs/summarize.ts`: extract the PR URL from the `openPR` result event and show it as a link.
- [ ] Vitest for the buttons and the PR link.

## 7. Docs and demo
- [ ] README "Generate docs" section: set up the GitHub App and Claude key, pick a repo, approve, find the PR.
- [ ] CHANGELOG entry.
- [ ] Run the manual AC-1 demo (see validation.md) and record the PR link in the PR description.
