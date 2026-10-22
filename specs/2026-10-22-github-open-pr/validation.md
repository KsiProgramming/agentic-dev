# Validation: `github.openPR` tool behind a gate

## Done when (from roadmap)
> A run opens a PR after approval

## Automated checks
User choice: GitHub is mocked with respx, and a local bare repo stands in as the push remote. CI stays offline and needs no App secrets.

- [ ] `agentic_github`:
  - The token and `open_pull_request` work against respx mocks, covering success, an existing PR and a 404.
  - `push_bundle` creates the branch on a local bare repo.
  - `push_bundle` refuses to overwrite an existing branch.
  - `push_bundle` refuses a bundle whose history does not contain `base_sha`.
- [ ] No leak: an installation token used for the push and the clone does not appear in captured logs, exception messages, `run_events` payloads or the tarred `.git/config`.
- [ ] Sandbox:
  - `export_bundle` round-trips on the fake sandbox.
  - `export_bundle` round-trips in the Docker sandbox (Docker-marked test).
  - The size cap is enforced.
- [ ] `github` server: `openPR` pushes and returns `{url, number, head, base}`. It returns a tool error for a writer with no commit, an unknown `from_node` or an existing PR.
- [ ] Engine (`test_open_pr.py`, fake runtime, `InMemorySaver`):
  - `writer → gate → openPR` returns `waiting` at the gate, and openPR has not been called.
  - Approve: `gate_decided`, `tool_call(github.openPR)`, `tool_result`, `pr_opened`, `run_completed`, with gap-free `seq`.
  - Reject: `run_cancelled`, and the github executor is never called.
- [ ] Spec/API:
  - `valid/open-pr.json` validates.
  - Both invalid fixtures are rejected.
  - `POST /runs` returns 422 for a spec with no gate or with the gate after the PR node.
  - `POST /runs` returns 409 when the workspace has no GitHub connection.
  - The JSON Schema export includes `pr_opened`.
- [ ] Worker: the full gated flow, with a fake sandbox, a bare remote and mocked GitHub, ends with a `pr_opened` event and the branch on the remote.
- [ ] The existing engine, store, API, worker, sandbox and tools suites still pass.
- [ ] `ruff check`, `ruff format --check`, strict `pyright`/`mypy` are clean. CI is green.

## Manual / demo checks
The demo runs against a real dev GitHub App (README setup from 1.5, with Contents and Pull requests set to read & write) and a test repo it is installed on, using `docker compose up --build` and `AGENT_RUNTIME=fake`.

- [ ] Connect GitHub in `/settings`. The test repo is listed.
- [ ] `POST /runs` with `open-pr.json` and `repo.url=https://github.com/<owner>/<test-repo>` returns `202`.
- [ ] The SSE stream shows the writer's `commit` result and `gate_waiting`, then nothing more. No `agent/<run>/...` branch exists on GitHub yet.
- [ ] `POST /runs/<id>/approvals` with `{"node_id":"gate","decision":"approve"}` returns `202`. The stream continues with `gate_decided`, `tool_call(github.openPR)`, `pr_opened` with a URL, and `run_completed`.
- [ ] Open the URL. The PR goes from `agent/<run>/<writer>` into the default branch, has the spec's title and body, and contains the file the writer committed.
- [ ] Reject path: on a new run, reject. No branch or PR appears on GitHub.
- [ ] Same flow on a **private** test repo: the clone and the PR both work.
- [ ] Gate rule: `POST /runs` with the gate removed from the spec returns `422`, and the message names the PR node.
- [ ] `docker compose logs api worker | grep -E 'ghs_|BEGIN RSA'` prints nothing.

## Merge criteria
- [ ] All automated checks pass in CI.
- [ ] The manual demo was done, and the PR link is recorded in the PR description.
- [ ] README and CHANGELOG are updated. `.env.example` documents the worker's GitHub settings.
- [ ] No token or PEM appears in logs, events or sandbox files.
- [ ] Open questions in requirements.md are resolved or moved to a named later phase.
- [ ] Roadmap phase 1.8 is marked done (`complete-phase`).
