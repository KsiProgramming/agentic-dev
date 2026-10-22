# Plan: `github.openPR` tool behind a gate

The groups are ordered so the project works after each one. Every group has its own tests.

## 1. `agentic_github`: tokens, PRs, push
- [x] `models.py`: `PullRequestInfo`.
- [x] `app.py`:
  - `installation_token(installation_id) -> SecretStr`. The caller registers it for redaction while it holds it.
  - `open_pull_request(...)`: a 422 reuses a PR already open from the branch, or else raises `PullRequestError` with GitHub's reason.
- [x] `push.py`:
  - `repo_full_name(url)` accepts only `https://github.com/<owner>/<name>(.git)`.
  - `push_bundle(bundle, *, remote_url, base_sha, branch, token)` uses a temp repo: a shallow fetch of `base_sha`, a fetch of the bundle, an ancestor check, then `git push --force-with-lease=<ref>:`. The token goes through `GIT_CONFIG_*` env as an `http.extraHeader` (`auth_env`), and the temp dir is removed afterwards.
- [x] `testing.py`: `pull_payload`.
- [x] Tests:
  - respx tests for the token and the PR call, covering success, an existing PR, a refusal, 404 and 502.
  - `push_bundle` against a local bare repo (`file://`), including a base that has moved and an existing branch.
  - Error messages carry no token or temp path.

## 2. Sandbox bundle export
- [x] `protocol.py`: `staging_dir` and `take_file(path)`, the reverse of `put_file`. The base SHA travels in `BranchBundle`, not on the sandbox.
- [x] `docker_backend.py`: `take_file` reads through `get_archive` (size-capped) and removes the file. `fake.py`: the same on the host.
- [x] `bundle.py`: `export_branch(sandbox, branch)` runs `git bundle create` for `<HEAD>..<branch>` in the sandbox and takes the file out.
- [x] Tests on both backends: a round trip onto the base, nothing left behind, a branch with no commits refused, the size cap, staging-only paths. The shallow-base question is settled (see requirements.md).

## 3. `github` MCP server + routing
- [x] `agentic_tools/github/server.py`: `build_github_server(github, target, sandbox, run_id=, writers=, push=)` with the `openPR` tool, its schema `examples`, and structured output `{url, number, head, base, commit}`. `open_github_tools` connects it in memory.
- [x] `agentic_tools/routing.py`: `RunTools` routes each call to the executor offering the tool. `ToolOutput.data` carries MCP structured content. `strict_tool` is shared with `repo`.
- [x] Tests on both backends, with a bare-repo remote and `FakeGithub`:
  - A push plus a PR.
  - A chosen base.
  - Opening it again.
  - No commits.
  - A non-writer.
  - GitHub errors.
  - An existing branch not overwritten.

## 4. Engine: gate rule + `pr_opened`
- [x] `spec`: `WRITE_TOOLS`, `PUBLISH_TOOLS` and `publish_gate_errors`, checked by `WorkflowSpec`:
  - Only a tool node may publish.
  - `from_node` must be an earlier writer.
  - A gate must sit between them.
- [x] `compile.py`: a completed publishing node emits `pr_opened` before `node_completed`. `AgentNodeResult.data` carries the tool's structured result.
- [x] Fixtures: `valid/open-pr.json`, `invalid/open-pr-without-gate.json`, `invalid/open-pr-gate-before-writer.json`, `invalid/open-pr-unknown-from-node.json`, `invalid/open-pr-by-agent.json`. The exported schemas are unchanged.
- [x] Tests (fake runtime, fake publisher):
  - Pause at the gate.
  - On approve: `tool_call`, `tool_result`, `pr_opened`, `node_completed`, `run_completed`.
  - On reject: nothing published.
  - A failed publish fails the run with no `pr_opened`.
  - Unit tests of the rule.

## 5. API: GitHub checks at `POST /runs`
- [x] `runs/models.py`: `github.*` tools need a `repo` on GitHub (`422`). The gate rule comes from the spec (`422`).
- [x] `runs/routes.py`: `409` if the spec uses `github.*` and the workspace has no GitHub connection. The OpenAPI spec and the web client are re-exported.
- [x] Tests: 202 with a connection, 422 without a gate, 422 without a repo or with a repo not on GitHub, 409 without a connection.

## 6. Worker wiring + private clone
- [x] `agentic_worker/main.py`:
  - `build_github` from `GITHUB_APP_*`.
  - `_github_target` per run (installation, `owner/name`, base).
  - Setup fails if the spec needs GitHub and can't have it.
  - The `github` tools open next to `repo` through `RunTools`.
  - Empty env values count as unset.
- [x] Private clone: `clone_shallow(..., git_env=)` and `SandboxManager.open(..., git_env=)`. The worker passes `auth_env(token)` for GitHub repos of linked workspaces and registers the token while cloning.
- [x] `docker-compose.yml` / `.env.example`: GitHub settings and the `.secrets` mount for the worker.
- [x] Tests:
  - End to end on the worker: fake sandbox mirroring the GitHub URL, a bare remote, `FakeGithub`. Nothing is pushed while waiting; after approval the branch is on the remote, `pr_opened` is recorded, and the token is in no event or DEBUG log.
  - A run without a GitHub connection fails before cloning.
  - `build_github` unit tests.
  - The engine and tool servers agree on tool names.

## 7. Demo + docs
- [ ] `scripts/sandbox_demo.py --spec open-pr.json`: not done. The demo needs a real GitHub App and a test repo, so it can't run in CI's compose job. The README gives the curl steps instead.
- [x] README: a "Pull requests" section (args, gate rule, permissions, how it works, demo), plus updates to Gates, Sandbox and GitHub App. CHANGELOG entry.
- [ ] Run the manual demo against the dev GitHub App (see validation.md) and record the PR link in the PR description.
