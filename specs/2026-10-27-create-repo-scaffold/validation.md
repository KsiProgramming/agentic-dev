# Validation: Create new repo (behind a gate) + scaffold commit

## Done when (from roadmap)
> Docs run works on a newly created repo

## Automated checks
- [ ] `packages/github/tests/test_app.py` (respx): `create_org_repo` sends `auto_init` and the templates and returns `RepoInfo`. A taken name raises `RepoExistsError`, a 403 `RepoCreationNotAllowedError` and an unknown installation `InstallationNotFoundError`. No error message holds the token. `get_repo` returns `None` on 404.
- [ ] `packages/github/tests/test_fake.py`: the fake creates a bare repo with exactly one commit (README, plus `.gitignore`/LICENSE when asked) that clones.
- [ ] `packages/tools/tests/test_github_server.py`:
  - `createRepo` creates in the target org.
  - A retry after a crash returns `created: false`, but a repo older than the run is refused.
  - A server with no sandbox offers only `createRepo`.
  - The registered tools still equal `PLATFORM_TOOLS`.
- [ ] `packages/engine/tests/test_validate.py`: `create_not_tool_node`, `create_without_gate`, `create_not_first` (a `repo.*` node before it, the node inside a map, two create nodes); the wrapped docs spec is valid.
- [ ] `packages/engine/tests/test_compile.py`: the run interrupts with `repo_ready` right after the create node and resumes into the next node with no decision. A `map` over zero items completes.
- [ ] `packages/worker/tests/test_worker.py::test_done_when_a_docs_run_works_on_a_new_repo[approve]` (fakes only, no network):
  - the run pauses at `create_repo` with no sandbox and nothing created;
  - approval creates `e2e-org/<name>` with the scaffold commit and logs `repo_created`, and the run is requeued, not `waiting`;
  - the next attempt clones the new repo, and the docs flow commits `docs/README.md` on `agent/<run>/writer`;
  - the run pauses at `approve`, and approval opens a PR on the new repo.
  - One `repo.created` audit row.
- [ ] Same test, `[reject]`: no repo is created and the run ends `cancelled`.
- [ ] Worker crash test: kill the worker after `createRepo` returns but before the node completes. The resumed run reuses the repo (`created: false`) and goes on (AC-8).
- [ ] `packages/api/tests/test_runs.py`:
  - `new_repo` with `repo` → 422; a bad name → 422 with the field path.
  - A personal-account installation → `409 personal_account`; no GitHub connection → 409; a taken name → `409 repo_exists`.
  - Success stores `repo` as the target URL and a spec starting with gate + `createRepo`.
  - Rerun of a created-repo run → `409 repo_exists`.
- [ ] `packages/api/tests/test_repos.py`: `new-repo-options` for an org, a personal account and no installation.
- [ ] Vitest:
  - New-repo toggle and fields, name rules, request body, the disabled state with its reason, `409 repo_exists` on the name field.
  - The "Created repo" timeline line.
  - The `repo.created` audit line.
  - axe finds no serious issues in the sheet.
- [ ] OpenAPI and the web client re-exported with no diff.
- [ ] CI green: `ruff`, `pyright`/`mypy` strict, `pytest`, ESLint, Prettier, `tsc`, Vitest, Playwright screenshots, roadmap check.

## Manual / demo checks
- [ ] The dev GitHub App has **Administration: write** and is installed on a test organisation. `docker compose up` with a Claude key saved.
- [ ] `/templates` → Generate docs → **New repo**: the owner shows the org. Enter `docs-new-<date>`, keep Private, pick the Python .gitignore and MIT, then Start run.
- [ ] The console shows the `create_repo` gate with its prompt naming the repo, and the dock is visible without scrolling at 375 and 1440 px. Nothing exists on GitHub yet.
- [ ] Approve: a "Created `org/docs-new-…`" line appears, then the docs nodes run, and the run waits at `approve`.
- [ ] On GitHub, the repo is private with one commit (README, `.gitignore`, LICENSE).
- [ ] Approve the PR gate: the console links the PR; on GitHub it targets `main` of the new repo and adds `docs/README.md`.
- [ ] `/audit` lists `run.created`, `gate.approved` ×2, `repo.created` and `run.ended` for the run.
- [ ] Start the same name again: the name field shows "already exists" before any gate.
- [ ] A personal-account installation (if one is available): "New repo" is disabled with its reason.
- [ ] Record the answers to the open questions (selected-repositories installs, "Repository creation" permission).
- [ ] Logs from the API, worker and tool servers contain no installation token or Claude key.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] Manual demo done; repo URL and PR link recorded in the PR description
- [ ] README section, tech-stack.md contract updates and CHANGELOG entry added
- [ ] Open questions in requirements.md answered or moved to a later phase
- [ ] Roadmap phase 1.12 marked done (by CI on the PR branch)
