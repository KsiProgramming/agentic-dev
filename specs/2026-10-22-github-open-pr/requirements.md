# `github.openPR` tool behind a gate

Roadmap phase: 1.8
Branch: plan/1.8-github-open-pr

## Context
After 1.7, a writer node commits to `agent/<run>/<node>` inside the run's sandbox, and a gate pauses the run until a human decides. Nothing has left the sandbox yet. This phase adds the first irreversible action. After an approved gate, a `tool` node pushes the writer's branch to GitHub and opens a pull request.

It depends on these phases, all done:
- 1.5: the GitHub App, the workspace's `github` connection and the `agentic_github` package. That package was built so a `github` tool server could reuse it.
- 1.6: the `tool` primitive, the writer worktrees and branches, and the `RepoTools` router keyed by `node_id`.
- 1.7: the `gate` primitive. It keeps the sandbox across the pause, so the writer's branch still exists after approval.

It unblocks:
- 1.11: the "Generate docs" template (AC-1: "docs run opens a PR").
- 1.12: creating a repo behind a gate, which reuses the same server and gate rule.
- 2.4: full spec validation, which takes over the gate rule added here.
- 5.3: the integration branch, which pushes merged writer branches through the same path.
- 6.6: PR review comments, which need the PR this phase opens.

Principles that apply:
- **Humans approve irreversible actions (3):** a push and a PR are irreversible. `POST /runs` refuses a spec in which a `github.*` write node has no gate before it. This answers the open question from 1.7: the push happens **after** the gate, never before it.
- **Tools live in the platform (4):** `github` is an MCP server owned by the platform, reached through the same `McpToolExecutor` bridge as `repo` (tech stack, "Tool layer").
- **Credentials stay inside the tool servers (tech stack):** the installation token is used on the worker host only. The sandbox keeps `network_mode=none` and never sees the token.
- **Repo content is data (5):** the PR title and body come from the spec's `args`, not from the repo. Commits are moved out of the sandbox as a git bundle and checked on the host before anything is pushed.
- **Transparency (6):** a `pr_opened` event records the PR URL, number and branch in `run_events`.
- **Small, verifiable steps (7):** one tool (`openPR`), called from a deterministic `tool` node, with one PR per writer node.

## Scope
### In scope
- **`agentic_github` additions:**
  - `installation_token(installation_id)` returns a short-lived token (a `SecretStr`, registered for redaction).
  - `open_pull_request(installation_id, full_name, head, base, title, body)` returns `PullRequestInfo` (`number`, `html_url`, `head`, `base`).
  - `push_bundle(...)` pushes a branch from a git bundle with the token over `https://`. The token is passed through environment config (`GIT_CONFIG_*` as an `http.extraHeader`), never through argv or a remote URL in a config file.
  - `repo_full_name(url)` parses `https://github.com/<owner>/<name>(.git)` and refuses anything else.
- **Sandbox bundle export:**
  - `Sandbox.export_bundle(branch) -> bytes` runs `git bundle create` for `<base>..<branch>` in the sandbox and copies the file out with `get_archive`.
  - The fake sandbox does the same with host git.
  - The bundle is capped in size.
  - `Sandbox.base_sha` records the clone's `HEAD` at creation.
- **`github` MCP server** (`agentic_tools.github`), opened per run on the worker:
  - The server is bound to the run's installation id, repo full name, base ref and sandbox.
  - It has one tool, `openPR(from_node, title, body?, base?)`:
    1. It resolves the writer branch `agent/<run>/<from_node>` and fails if that node made no commit.
    2. It exports the bundle, then fetches it on the host into a temp repo that has a shallow fetch of the base.
    3. It checks that the branch has the base commit as an ancestor and pushes it as create only (`--force-with-lease=<branch>:`).
    4. It opens the PR with `base` defaulting to the run's ref, or the repo's default branch.
    5. It returns the PR URL and number as text and as structured content.
  - The schema has an `examples` entry, so the fake runtime and the fixtures work.
  - The run-level router sends `repo.*` calls to `RepoTools` and `github.*` calls to the github server.
- **Engine:**
  - A `tool` node whose result carries a PR emits `pr_opened` (`node_id`, `url`, `number`, `head`, `base`) before `node_completed`.
  - `github.openPR` counts as a **write** tool for grants. It is not a writer: it gets no worktree.
- **Gate rule (spec level):**
  - `POST /runs` returns `422` in any of these cases:
    - A node using `github.openPR` has no `gate` between its `from_node` writer and itself, in run order.
    - `from_node` does not name an earlier writer node.
    - An agent lists `github.openPR`.
  - A `github.*` tool also needs the run's `repo` to be a GitHub URL; if it isn't, the request gets `422`. The workspace also needs a GitHub connection; without one, it gets `409`.
- **Private repo clone:**
  - When the run's repo is a GitHub URL and the workspace has an installation, the worker clones with an installation token.
  - The token is passed through the environment and never written to the `.git/config` that is tarred into the sandbox.
  - Public and local-path clones behave as before.
- **Worker:**
  - It builds `GithubApp` from the same `GITHUB_APP_*` settings as the API and loads the run's installation id.
  - If those settings are missing, a run that uses `github.*` fails setup with a clear reason.
  - Compose passes the GitHub settings and the PEM mount to the worker.
- **Demo fixture** `open-pr.json`: a writer agent, then a gate, then a `tool` node `github.openPR` with `from_node` set to the writer.
- **Docs:**
  - A README section covers the tool, the gate rule, the App permissions (Contents: read & write; Pull requests: read & write) and the end-to-end demo steps.
  - A CHANGELOG entry.

### Out of scope
- `github.openPR` as an agent tool, so an agent writes the title and body: later, once 2.6 lets a human edit the artifact at the gate.
- A run summary that lists branches and PRs: 2.5 (node detail).
- Merging, closing or updating PRs, and draft PRs.
- Merging several writer branches into one PR: 5.3.
- Webhooks and PR review comments: 6.6.
- Full graph validation (gates inside `parallel`, `map`, `router`): 2.4. This phase checks plain sequence order only.
- Creating the repo: 1.12.
- An egress allowlist for the sandbox: 9.2. The sandbox stays without network.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | A deterministic `tool` node `github.openPR` + a spec-level gate rule + private clone + a `pr_opened` event | User choice. It meets "Done when" and makes Principle 3 a hard rule, not a convention. |
| Where push runs | On the worker host, inside the `github` MCP server, from a git bundle exported from the sandbox | User choice. The token never enters the sandbox, and the sandbox keeps `network_mode=none`. |
| Server shape | An MCP server through the existing bridge, not a plain `ToolExecutor` | Tech stack: integrations are MCP servers owned by the platform (Principle 4). It mirrors `repo`. |
| Which branch | `from_node` names the writer node, and the branch is derived as `agent/<run>/<from_node>` | The branch name is fixed by 1.6. Naming a node keeps the spec readable and lets validation check it. |
| Push safety | Create only (`--force-with-lease=<branch>:`), and the base commit must be an ancestor | A rerun can't overwrite an existing branch, and a bundle can't push unrelated history. |
| When to check the gate | At `POST /runs` (422), from sequence order | It fails before any work is done. Full graph checks move to 2.4. |
| Token handling | `SecretStr`, registered for redaction, passed through env, never through argv or a config file | No secrets in logs (1.4), and nothing left behind in temp repos or the sandbox. |
| Where GitHub settings live | The same `GITHUB_APP_*` settings and PEM mount as the API, now also given to the worker | One platform App (1.5). |
| Validation | respx-mocked GitHub, a local bare repo as the push remote, plus one manual demo on a real dev App | User choice. CI stays offline, and the demo proves "Done when" for real. |
| Gate rule, as built | The gate must sit **between the writer (`from_node`) and the publishing node**, and only a tool node may publish. The check is a `WorkflowSpec` validator (`publish_gate_errors`). | It is stronger than "a gate before it": the approver must see what the writer produced. Living in the spec, it holds for every consumer (API, canvas, Architect), not only `POST /runs`. |
| Repo not on GitHub | `422`, not `409` | It is a problem with the request body, not with the workspace's state. A missing connection is still `409`. |
| Retries | Pushing the same commit again is a no-op, and an open PR from the branch is reused | A run resumed after its worker died runs `openPR` again (AC-8). It must not fail on its own earlier work. |

## Open questions
- ~~**Shallow base on the host:** is a `--depth 1` fetch of the base enough for `git fetch <bundle>` to resolve the bundle's prerequisite commit, even when the base branch has moved since the clone?~~ Resolved in groups 1–2: yes. The sandbox bundles `<clone HEAD>..<branch>` from its shallow clone, and the push fetches that exact SHA with `--depth 1` before fetching the bundle. `test_push_works_after_the_base_branch_moved` covers a base that has moved, and `test_a_branch_bundles_onto_the_clone_head` covers the Docker sandbox. Pushing the same commit again is a no-op, so a retried node succeeds.
- **Sandbox lost during the pause:** if the sandbox is gone at approval time (for example after a host reboot), this phase fails `openPR` with "writer branch missing". Running the writer again would need a new approval, which belongs with 2.6.
