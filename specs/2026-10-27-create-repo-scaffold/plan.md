# Plan: Create new repo (behind a gate) + scaffold commit

## 1. GitHub client
- [x] `packages/github/src/agentic_github/app.py`: `create_org_repo(...)` (`POST /orgs/{org}/repos`, `auto_init: true`, optional `gitignore_template` / `license_template`) and `get_repo(installation_id, full_name) -> RepoInfo | None`. Map 422 "name already exists" to `RepoExistsError` and 403 to `RepoCreationNotAllowedError`, with no token or headers in the message.
- [x] `errors.py`, `models.py` (`RepoInfo.created_at`), `platform.py` (`GithubPlatform` gains both methods), `__init__.py` exports.
- [x] `fake.py`: `create_org_repo` makes `<fixtures>/<org>/<name>.git` with one scaffold commit on `main` (README, optional `.gitignore`/LICENSE) using host git; `get_repo` and `list_repos` include created repos.
- [x] `packages/github/tests/test_app.py` (respx): 201, name taken, 403, unknown installation, `get_repo` 404 → `None`, templates passed through. `test_fake.py`: the created bare repo clones and has one commit.

## 2. `createRepo` tool and the validator rule
- [x] `packages/tools/src/agentic_tools/github/server.py`: `createRepo` (owner fixed to the target org; idempotent on `RepoExistsError` when the repo's `created_at` ≥ the run's `created_at`); `build_github_server` takes `sandbox: Sandbox | None` and registers `openPR` only with a sandbox. `GithubTarget` gains `run_created_at`.
- [x] `packages/engine/src/agentic_engine/spec/models.py`: `CREATE_TOOLS`, added to `PLATFORM_TOOLS`; `create_repo_issues(root)` with codes `create_not_tool_node`, `create_without_gate`, `create_not_first`; wired into `validate_workflow`.
- [x] Keep the "tool servers register exactly `PLATFORM_TOOLS`" test green.
- [x] Tests: `packages/tools/tests/test_github_server.py` (create, retry returns `created: false`, older repo refused, no-sandbox server lists only `createRepo`); `packages/engine/tests/test_validate.py` (each new code, valid wrapped spec).

## 3. Engine and worker: `repo_created` and the requeue
- [x] `agentic_engine/events.py`: `RepoCreated` event. `tool.py`: a `github.createRepo` result emits `repo_created` before `node_completed`.
- [x] `graph/compile.py`: after a create tool node, a `repo_ready` step calls `interrupt({"kind": "repo_ready"})`. The run result reports it as `requeue`, not `waiting`.
- [x] `agentic_store`: `repo_created_for(run_id)`; the sink writes the `repo.created` audit row on `repo_created`. A requeue goes back to the queue with no status change.
- [x] `packages/worker/src/agentic_worker/main.py` `_attempt`:
  - a run with a create node and no `repo_created` opens no sandbox, only `open_github_tools(..., sandbox=None)`;
  - on `suspended` it starts the next attempt at once (`_attempts`), without going back through the queue;
  - the resume path passes `Command(resume=None)` for `repo_ready`.
- [x] Tests: `packages/engine/tests/test_compile.py` (interrupt after create, resume continues); `packages/worker/tests/test_worker.py::test_done_when_a_docs_run_works_on_a_new_repo[approve|reject]` (see validation.md); store test for the audit row.

## 4. Run API
- [x] `runs/models.py`: `NewRepo` (name pattern, `private=True`, description ≤ 350, gitignore/license from fixed lists); `CreateRunRequest.new_repo`, exclusive with `repo`; relax `_repo_for_repo_tools` for it.
- [x] `runs/routes.py`: resolve the installation's account (`409 personal_account`, `409` no GitHub connection), pre-check with `get_repo` (`409 repo_exists`), set `repo`, wrap the root (`wrap_with_create_repo(spec, new_repo, owner)` in `agentic_engine.templates`), then the existing validation. Rerun of a created-repo run → `409 repo_exists`.
- [x] `workspaces` (or `github`) routes: `GET /workspaces/{id}/repos/new-repo-options`.
- [x] Audit: the formatter's action list gains `repo.created`. (`run.created` details unchanged: `repo_url` names the new repo.)
- [x] Tests in `packages/api/tests/test_runs.py` and `test_repos.py`; re-export `web/openapi.json` and `web/src/api/schema.d.ts`.

## 5. Docs template on an empty scaffold
- [x] Confirmed not needed: on a scaffold, `repo.list_modules` falls back to the repo root (`.`), so the map has one item (asserted in the worker e2e test).
- [x] `packages/engine/tests/test_new_repo.py`: the wrapped docs spec validates; prompt text; bad `NewRepo` values.

## 6. Web: "New repo" in the New run sheet
- [x] `web/src/runs/new-run/new-run-sheet.tsx`: Existing / New toggle (radio group, keyboard reachable); `new-repo-fields.tsx` with owner, name (client rules mirror the schema), Private switch, description, .gitignore and license selects from `new-repo-options`; disabled option with its reason when `can_create` is false.
- [x] Submit sends `new_repo` instead of `repo`; `409 repo_exists` is shown on the name field and other 409s in the form `Alert`.
- [x] Timeline and graph: `repo_created` summarised as a quiet line ("Created `acme/docs-demo`" linking to GitHub); `web/src/runs/types.ts` listens for it.
- [x] Audit formatter: `repo.created`.
- [x] Vitest: toggle, validation, request body, disabled state, 409 on the name field, timeline line, audit line. axe stays clean.

## 7. Docs and demo
- [x] README "Create a new repo" section (App permission, org install, personal accounts unsupported, demo steps); `.env.example` unchanged.
- [x] `specs/tech-stack.md`: create rule and issue codes in "Workflow validation", `repo_ready` / `new_repo` in a short "New repos (API contract)" section, `repo.created` in the audit table, decisions-log row.
- [ ] CHANGELOG entry.
- [ ] Manual demo on a real org (validation.md); record the repo and PR links in the PR description; resolve the open questions in requirements.md.
