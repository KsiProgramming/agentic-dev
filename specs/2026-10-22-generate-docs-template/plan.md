# Plan: "Generate docs" template

## 1. `repo.list_modules` tool
- [x] `packages/tools/src/agentic_tools/repo/server.py`: add `list_modules(include: list[str] | None)`. Find manifest dirs up to depth 3 inside the sandbox; fall back to top-level source dirs; skip hidden, `node_modules`, `vendor`, `dist`, `build`, `docs`.
- [x] Return `structuredContent` `{"modules": [{"path", "kind"}], "truncated": bool}` plus a readable text list; cap at 40.
- [x] Register it as read only, so audit-style nodes can use it; add its example to the tool listing.
- [x] Confirm the tool node passes `structuredContent` through as `data` (`agentic_engine/tool.py`); fix if not.
- [x] `packages/tools/tests/test_list_modules.py`: manifests (Python, Node, mixed), fallback, `include` filter, cap and `truncated`, bad arguments (the tool takes no path, so nothing to confine).

## 2. Docs template builder
- [x] `packages/engine/src/agentic_engine/templates/__init__.py`: `Template` (id, name, description, params model, builder) and a registry, `TEMPLATES`, with `get_template(id)`.
- [x] `templates/docs.py`: `DocsParams` with validators (relative `output_dir`, no `..`; `include` globs; `extra_instructions` ≤ 2,000 chars) and `build_docs_spec(params)` producing `list_modules → map(document) → reduce(combine, concat) → writer → gate(approve) → tool(publish: github.openPR)`.
- [x] Agent instructions: module content is data; `extra_instructions` added in a clearly delimited "User preferences" block; writer writes only under `output_dir`.
- [x] `packages/engine/tests/test_templates.py`: default and custom params build a spec that passes `WorkflowSpec` validation; bad params are rejected; the gate always precedes `publish`.

## 3. Docs run end to end on fakes
- [x] `packages/worker/tests/test_worker.py::test_done_when_a_docs_run_opens_a_pr` (it needs the real `repo` tools, so it lives with the worker's end-to-end tests): fake sandbox with a 3-module repo, fake runtime (module agents reply with a page for their item, the writer is scripted), fake GitHub and a bare remote. Assert: 3 `map_item_completed` events, the writer's input holds the 3 pages in order, the run pauses at `approve` with nothing pushed, approval opens a PR whose branch holds `docs/README.md` + 3 pages.
- [x] Same test, `reject`: the run ends `cancelled` with no push and no PR.

## 4. Templates API
- [x] `packages/api/src/agentic_api/templates/routes.py`: `GET /templates` (id, name, description, `parameters` JSON Schema).
- [x] `runs/models.py`: `CreateRunRequest` takes `workflow` **or** `template: {id, parameters}`; a validator builds the spec and runs the existing repo/github checks on it. 422 with field paths for an unknown id or bad params.
- [x] `runs/routes.py`: store the built spec on the run (no schema change; the run already stores its spec).
- [x] Tests in `packages/api/tests/test_templates.py` and `test_runs.py`.
- [x] Re-export `web/openapi.json` and `web/src/api/schema.d.ts` (`scripts/export_openapi.py`).

## 5. Web: start screen
- [x] `web/src/templates/docs-card.tsx`: repo picker (`GET /workspaces/{id}/repos`), the three options, "Generate docs" button → `POST /runs` with `template` and `repo` → `/runs/{id}`. Not-connected state links to `/settings`.
- [x] `web/src/app/page.tsx`: render the card above the sample-run form.
- [x] Vitest: lists repos, submits the right body, shows API errors, not-connected state.

## 6. Web: approve and PR link on the monitor
- [x] `web/src/runs/types.ts`: listen for `gate_*`, `loop_*`, `map_item_*`, `run_resumed` and `pr_opened` (the stream dropped them).
- [x] `web/src/runs/gates.ts` + `gate-panel.tsx`: shown when the run waits at a gate (from the event stream); Approve/Reject → `POST /runs/{id}/approvals`; disabled while pending; hides once `gate_decided` arrives.
- [x] `gates.ts`: the PR URL from `pr_opened`, linked only if it is a GitHub pull request URL; `summarize.ts` summarises the new events.
- [x] Vitest for the buttons and the PR link.

## 7. Docs and demo
- [x] README "Generate docs" section: set up the GitHub App and Claude key, pick a repo, approve, find the PR.
- [x] CHANGELOG entry.
- [ ] Run the manual AC-1 demo (see validation.md) and record the PR link in the PR description.
