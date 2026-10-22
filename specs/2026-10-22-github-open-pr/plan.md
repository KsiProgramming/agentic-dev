# Plan: `github.openPR` tool behind a gate

The groups are ordered so the project works after each one. Every group has its own tests.

## 1. `agentic_github`: tokens, PRs, push
- [ ] `models.py`: `PullRequestInfo`.
- [ ] `app.py`:
  - `installation_token(installation_id) -> SecretStr`, registered with the redaction registry.
  - `open_pull_request(...)`, which maps GitHub's 422 "A pull request already exists" to `PullRequestExistsError`.
- [ ] `push.py`:
  - `repo_full_name(url)` accepts only `https://github.com/<owner>/<name>(.git)`.
  - `push_bundle(bundle, *, remote_url, base_sha, branch, token)` uses a temp repo: a shallow fetch of `base_sha`, a fetch of the bundle, an ancestor check, then `git push --force-with-lease=<branch>: origin <branch>`. The token goes through `GIT_CONFIG_*` env as an `http.extraHeader`, and the temp dir is removed afterwards.
- [ ] `testing.py`: payload helpers for PRs.
- [ ] Tests:
  - respx tests for the token and the PR call, covering success, an existing PR and a 404.
  - `push_bundle` against a local bare repo (a `file://` remote allowed in tests only).
  - A no-leak test: the token does not appear in captured logs or error messages.

## 2. Sandbox bundle export
- [ ] `protocol.py`: `export_bundle(branch) -> bytes` and `base_sha`.
- [ ] `docker_backend.py`: run `git bundle create` for `<base>..<branch>` as the sandbox user into an `.outgoing/` dir, read it with `get_archive`, and enforce a size cap.
- [ ] `fake.py`: the same with host git.
- [ ] Tests:
  - Fake sandbox: a commit in a writer worktree exports a bundle that fetches cleanly.
  - Docker (marked like the existing Docker tests): the same inside the real image.
  - A shallow-base case. Settle the open question about the shallow base here and record the answer in requirements.md.

## 3. `github` MCP server + routing
- [ ] `agentic_tools/github/server.py`: `build_github_server(app, installation_id, full_name, base_ref, sandbox, run_id)` with the `openPR` tool, its schema `examples` and structured output `{url, number, head, base}`.
- [ ] `agentic_tools/routing.py`, or an extension of `RepoTools`: a run-level executor that routes by tool prefix (`repo.` / `github.`).
- [ ] Tests:
  - `openPR` on the fake sandbox with a bare-repo remote and a respx-mocked PR call.
  - Errors: no commit on the writer branch, unknown `from_node`, PR already exists.

## 4. Engine: write tool + `pr_opened`
- [ ] `spec`: list `github.openPR` as a write tool that is not a writer, so it gets no worktree. `node_tools` reports it.
- [ ] `tool.py`: emit `pr_opened` when the structured result carries a PR.
- [ ] `events.py`: add the `pr_opened` kind. Re-export the JSON Schema.
- [ ] Fixtures: `valid/open-pr.json`, `invalid/open-pr-without-gate.json`, `invalid/open-pr-unknown-from-node.json`.
- [ ] Tests (fake runtime, fake github executor):
  - `writer → gate → openPR` pauses at the gate.
  - On approve it emits `tool_call`, `tool_result`, `pr_opened` and `run_completed`.
  - On reject, openPR never runs.

## 5. API: gate rule + GitHub checks at `POST /runs`
- [ ] `runs/models.py`: a validator for the gate rule (sequence order) and for `from_node` naming an earlier writer.
- [ ] `runs/routes.py`: `409` if the spec uses `github.*` and the workspace has no GitHub connection or the repo URL is not a GitHub URL.
- [ ] Tests: 422 without a gate, 422 with the gate after the PR node, 422 with an unknown `from_node`, 409 without a connection, 202 for the valid fixture.

## 6. Worker wiring + private clone
- [ ] `agentic_worker/main.py`:
  - Build `GithubApp` from settings and load the installation id per run.
  - Open the `github` server next to `RepoTools`.
  - Fail setup clearly if the App is unconfigured and the spec needs it.
- [ ] `agentic_sandbox/source.py`: an optional token for `https://github.com` clones, passed through `GIT_CONFIG_*` env.
- [ ] `docker-compose.yml` / `.env.example`: GitHub settings and the `.secrets` mount for the worker.
- [ ] Tests:
  - Worker: with a fake sandbox, a bare remote and mocked GitHub, the full gated flow reaches `pr_opened`.
  - Clone: the tarred `.git/config` holds no credentials.

## 7. Demo + docs
- [ ] `scripts/sandbox_demo.py --spec open-pr.json` support, if useful for local runs.
- [ ] README: a `github.openPR` section (args, gate rule, App permissions, demo with curl).
- [ ] CHANGELOG entry.
- [ ] Run the manual demo against the dev GitHub App (see validation.md) and record the PR link in the PR description.
