# Create new repo (behind a gate) + scaffold commit

Roadmap phase: 1.12
Branch: plan/1.12-create-repo-scaffold

## Context
The mission promises the three day-one outcomes "on an existing or newly created GitHub repo". After 1.11 a docs run works on a repo the GitHub App can already reach. This phase lets a user start the same run on a repo that does not exist yet. The run asks for approval, creates the repo in the installation's organisation with one scaffold commit, clones it and then runs the docs flow as usual, ending in a PR.

It depends on these phases, all done:
- 1.5: the GitHub App, its installation per workspace and `agentic_github`.
- 1.7 / 1.8: gates, the `github` MCP server and the publish-gate rule this phase extends.
- 1.11: the docs template and `POST /runs` with `template`.
- 2.6: the "New run" sheet and repo combobox, which get a "New repo" option.
- 3.4: the one validator (`validate_workflow`) with stable issue codes.
- 3.7: the audit log, which records the creation.

It unblocks 4.7 (audit on a new repo makes no sense, but the mechanism is template-agnostic) and 7.5 (SDD on a greenfield repo).

Principles and stack choices that apply:
- **Humans approve irreversible actions (3):** repo creation is named there explicitly. The create node always has a gate before it, enforced by the validator, not by the template.
- **Tools live in the platform (4):** creation is a `github.createRepo` tool in the existing `github` MCP server. Credentials stay on the worker.
- **One spec, many views (1):** the gate and the create node are ordinary nodes in the run's stored spec, so the timeline, graph tab and audit show them with no special casing.
- **Transparency (6):** a `repo_created` event and a `repo.created` audit row.
- **Small, verifiable steps (7):** organisations only, a fixed scaffold, no new sandbox mechanics.
- **Tech stack, "Integrations":** GitHub App installation tokens, `githubkit`, no personal access tokens. GitHub only accepts installation tokens on `POST /orgs/{org}/repos` (Administration: write). `POST /user/repos` needs a *user* access token, so personal-account installations are out of scope until users exist.

## Scope
### In scope
- **`agentic_github`:**
  - `GithubApp.create_org_repo(installation_id, org, name, *, private, description, gitignore_template, license_template) -> RepoInfo` through `POST /orgs/{org}/repos` with `auto_init: true`. GitHub makes the scaffold commit: `README.md` (name + description), plus the chosen `.gitignore` and license.
  - `GithubApp.get_repo(installation_id, full_name) -> RepoInfo | None` for the pre-check and for retries.
  - Errors: `RepoExistsError` (422 "name already exists"), `RepoCreationNotAllowedError` (403, the App lacks Administration write or the org forbids it), and the existing `GithubApiError` / `InstallationNotFoundError`.
  - `FakeGithubApp.create_org_repo` creates a bare repo under the fixtures root with one scaffold commit on `main` (host git), so local dev and e2e tests clone it like any fake repo.
- **`github.createRepo` tool** (in `agentic_tools.github`): `createRepo(name, private, description?, gitignore?, license?)`, with the owner fixed to the run's target organisation.
  - It returns `{full_name, html_url, default_branch, private, created}` as structured content.
  - It is idempotent for retries (AC-8): if the repo already exists and was created at or after the run's `created_at`, it is returned with `created: false`. Otherwise it fails with "repo already exists".
  - The server can be opened with no sandbox (only `createRepo` is then available).
- **Spec and validator:**
  - `CREATE_TOOLS = {"github.createRepo"}`, added to `PLATFORM_TOOLS`.
  - New issue codes: `create_not_tool_node`, `create_without_gate`, `create_not_first`. The create node must be a tool node, directly in the top-level sequence, after a gate, at most one per spec. No node before it may name a `repo.*` or `github.*` tool other than itself, since nothing is cloned yet.
- **Engine:** after a `github.createRepo` tool node completes, the run emits `repo_created` (`node_id`, `full_name`, `url`, `default_branch`, `private`, `created`) and stops the attempt at a **`repo_ready`** interrupt (a `<id>.ready` step). This is not a gate: it needs no decision, writes no event, and the run is never `waiting`; the attempt ends `suspended`.
- **Worker:**
  - A run whose spec has a create node and no `repo_created` event yet opens **no sandbox**. Its tools are only the `github` server without a sandbox.
  - On `suspended` it starts the run's next attempt at once, while it still holds the lease (changed during implementation; see Decisions).
  - The next attempt sees `repo_created` and clones the new repo with an installation token, then resumes from the checkpoint into the docs flow.
- **Run request and store:**
  - `CreateRunRequest.new_repo: {name, private=true, description?, gitignore?, license?}`, exclusive with `repo`.
  - The API reads the owner from the workspace's installation and refuses with `409 personal_account` if it is a user account, or `409 repo_exists` if the name is taken (the `get_repo` pre-check).
  - It sets `run.repo` to `https://github.com/<org>/<name>` (so lists and summaries show it from the start).
  - It wraps the template's or workflow's root in `sequence[gate create_repo, tool create_repo_tool, <root>]`. The gate prompt reads "Create private repo `acme/docs-demo` with a Python .gitignore and MIT license?", and the artifact holds the settings.
  - The repo-tools check in `_repo_for_repo_tools` accepts a `new_repo` run.
  - `run.created`'s audit details are unchanged: `repo_url` already names the new repo, and `repo.created` follows.
  - Rerun of a run that created its repo is refused with `409 repo_exists`; the message says to start a run on the existing repo.
- **Audit:** `repo.created` (actor `system`, written by the event sink on `repo_created`; `details`: `full_name`, `private`, `node_id`).
- **API surface:**
  - `GET /workspaces/{id}/repos/new-repo-options` returns `{owner, can_create, reason, gitignore_templates, licenses}`. `can_create` is false for a personal account or with no installation. The lists are short and fixed (none, Python, Node, Go, Rust, Java, VisualStudio; none, MIT, Apache-2.0).
  - OpenAPI and the web client are re-exported.
- **Web:** in the "New run" sheet, the repo section becomes a two-option toggle: **Existing repo** (the combobox, unchanged) / **New repo**. New repo shows:
  - the owner (read-only, mono);
  - a name with GitHub's rules checked client-side (`[A-Za-z0-9._-]{1,100}`, not `.`/`..`);
  - Private (default on), description, .gitignore and license selects.
  - When `can_create` is false, the option is disabled with its reason. A `409 repo_exists` shows on the name field.
  - The audit formatter learns `repo.created`.
- **Docs template:** works on the scaffold. Found during implementation: a scaffold has no manifest and no source directory, so `repo.list_modules` falls back to the repo root (`.`) as its one module, and the docs flow documents it. No change was needed; the worker e2e test asserts it.
- **Docs:**
  - README "Create a new repo" section: App permission Administration (write); install on the organisation; personal accounts are not supported.
  - tech-stack.md: gains the create rule, `repo_ready` and the `repo.created` audit action.
  - CHANGELOG entry.

### Out of scope
- Repos on personal accounts (needs GitHub App user access tokens and sign-in): later, with users.
- An agent-written scaffold or creation from a template repo: later, if a template needs it.
- Repo settings beyond private/description/.gitignore/license (topics, branch protection, teams).
- Deleting a created repo when the run is rejected later or fails: the repo stays, and its URL is in the run and the audit log.
- Creating a repo inside `map`, `loop` or a later step: the create node must be first.
- A lazy sandbox opened mid-attempt: not needed with the requeue.
- Playwright coverage of the new-repo flow (not chosen for validation).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Who can own the repo | The installation's organisation only | User choice. GitHub accepts installation tokens on `POST /orgs/{org}/repos` but not on `POST /user/repos`. There are no user tokens yet. |
| Scaffold | GitHub `auto_init` with an optional `.gitignore` and license template: one commit | User choice. It is deterministic, made by GitHub (nothing pushed from the sandbox), and the commit exists before the clone. |
| Run shape | One run: gate → `createRepo` → `repo_ready` stop → new attempt clones → docs flow | User choice. The next attempt clones like any other, so the sandbox, repo tools and gate review are unchanged. |
| How the next attempt starts | The worker loops over attempts while it holds the lease, instead of going back through the Redis queue | Changed during implementation. Same result with less machinery: no lease release and claim, and wall time and cancel watchers cover both attempts. |
| Where the create steps come from | The API wraps any spec when the request has `new_repo` | This works for every template and raw workflow, and the template schemas stay unchanged. The stored spec shows the steps (Principle 1). |
| Repo known at creation | `run.repo` is set to the target URL when the run is created | Lists, summaries, `_github_target` and the audit have the repo from the start. The worker skips the clone until `repo_created` exists. |
| Gate rule | A validator rule with three new issue codes, like `publish_without_gate` | Safe by construction (Principle 2) for every client: API, canvas, Architect. |
| Retries and rerun | Accept an existing repo only if it was created at or after the run; refuse a rerun with `409 repo_exists` | A worker crash after the GitHub call must not fail the run (AC-8). A rerun must never take over a repo it did not create. |
| Pre-check | `get_repo` at `POST /runs` | A taken name fails before any approval is asked for. |
| Audit | `repo.created` written by the event sink, actor `system` | It matches `run.ended`: the worker performs it, and the row exists only if the event was committed. |
| Order of work | GitHub client → tool + validator → engine/worker requeue → API → web → docs | User choice ("create node, then requeue"). Each step is testable on fakes before the next uses it. |
| Validation | respx unit tests, API tests, worker e2e on fakes, manual demo on a real org | User choice. |

## Open questions
- **Selected-repositories installations:** does a repo created through an installation token join an installation limited to selected repos? Check it in the manual demo. If not, `new-repo-options` reports `can_create: false` with "install the App on all repositories".
- **"Repository creation" permission:** GitHub lists it next to Administration for this endpoint. Confirm in the demo whether a GitHub App can be granted it instead of the broader Administration write.
- **Org policy:** orgs that forbid members from creating repos (or private repos) answer 403. The node fails with a readable reason; nothing is checked up front.
