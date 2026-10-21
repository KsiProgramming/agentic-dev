# GitHub App install + `GET /repos`

Roadmap phase: 1.5
Branch: plan/1.5-github-app-repos

## Context
Runs can clone a repo (1.1), read it through the `repo` MCP server (1.2) and use a Claude key stored encrypted per workspace (1.4). Nothing links a workspace to GitHub yet, so a user can't pick a repo that the platform is allowed to touch. This phase adds that link. The platform has one GitHub App. A user installs it on their account or org, the installation is stored as the workspace's `github` connection, and the API lists the repos that installation can reach.

It depends on these phases, all done:
- 1.4: workspaces and the `connections` table, which the installation reuses (the 1.4 spec named this).
- 0.8/1.4: the web app and its `/settings` page, which get a GitHub section.

It unblocks:
- 1.6/1.8: write tools and `github.openPR` authenticate with the same installation.
- 1.11: the "Generate docs" template's "connect GitHub, pick a repo" (AC-1).
- 1.12: creating a repo needs the installation.
- 6.6: GitHub webhooks build on the same App.

Principles and stack choices that apply:
- **Tech stack, "Integrations":** "GitHub App (installation tokens …). Library: `githubkit`." and "No personal access tokens are stored."
- **Tech stack, "Tool layer":** "Credentials stay inside the tool servers. Agents never see them." The App private key and installation tokens stay in the API process (and later the tool servers), never in a run.
- **Tech stack, "Security & secrets":** secrets never appear in logs.
- **Humans approve irreversible actions (3):** this phase only reads, so it needs no gate.
- **Small, verifiable steps (7):** one App, one installation per workspace, a live repo list, no webhooks.

## Scope
### In scope
- **New package `agentic_github`** (built on `githubkit`), used by the API now and by the tool servers later:
  - `GithubAppConfig`: `app_id`, `slug`, the private key (`SecretStr`, read from `GITHUB_APP_PRIVATE_KEY_FILE`).
  - `GithubApp`: one shared `githubkit.GitHub(AppAuthStrategy(...))`.
    - `get_installation(installation_id)` returns the account login and type, and raises `InstallationNotFound`.
    - `list_repos(installation_id)` pages through `GET /installation/repositories` with installation auth and returns `RepoInfo` items (`id`, `full_name`, `name`, `owner`, `private`, `default_branch`, `html_url`).
  - Installation tokens use githubkit's built-in in-memory cache, so a token is reused until it nears expiry.
  - The PEM is registered with the 1.4 redaction registry when it is loaded.
- **Schema (Alembic, migration 0008):**
  - `connections.secret_nonce`, `secret_ciphertext` and `key_hint` become nullable.
  - New nullable columns `external_id` (the installation id) and `account_login`.
  - A check constraint: provider `claude` rows must have the secret columns, and provider `github` rows must have `external_id`.
- **Store:**
  - `put_github_connection(workspace_id, installation_id, account_login)` creates or replaces the row. Nothing is encrypted, because the installation id is not a secret.
  - `get_github_installation(workspace_id) -> int | None`.
  - `list_connections` also returns `account_login` for GitHub rows.
  - `delete_connection` already works for any provider.
- **API settings:** `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY_FILE`, `WEB_BASE_URL`. If any of them is unset, the GitHub endpoints return `503` with a clear message. Everything else keeps working.
- **API:**
  - `POST /workspaces/{id}/connections/github/install` returns `{ "install_url": "https://github.com/apps/<slug>/installations/new?state=<s>" }`.
    - `state` is random and single use. It is stored in Redis for 10 minutes and maps to the workspace.
  - `GET /github/setup?installation_id=&setup_action=&state=` is the App's Setup URL.
    - It consumes the state, checks the installation with `get_installation` (App JWT) and stores the connection.
    - On success it redirects (303) to `WEB_BASE_URL/settings?github=connected`.
    - If the state is bad or expired, the installation is unknown, or `setup_action=request` (an org admin still has to approve), it redirects to `/settings?github=error&reason=<code>`.
  - `DELETE /workspaces/{id}/connections/github` unlinks the installation locally. It does not uninstall the App on GitHub.
  - `GET /workspaces/{id}/repos` returns `RepoOut[]` sorted by `full_name`. Errors:
    - `404`: unknown workspace.
    - `409`: the workspace has no GitHub connection.
    - `409` with `installation_gone`: GitHub returns 404 for the installation.
    - `502`: any other GitHub error. The body has no GitHub token or response headers in it.
  - `GET /workspaces/{id}/connections` includes the GitHub row (provider, `account_login`, timestamps).
- **Compose:**
  - The API reads the GitHub settings from `.env`.
  - A gitignored `./.local-secrets/` directory is mounted read only at `/github` for the PEM.
  - `.env.example` documents the variables. `docker compose up` still works when they are blank.
- **Web:**
  - `/settings` gets a "GitHub" section.
    - Not connected: an "Install GitHub App" button calls the install endpoint and navigates to the URL it returns.
    - Connected: the account login, a "Disconnect" button and the list of repos (full name, private badge, default branch, link to GitHub).
    - It also shows the `?github=connected|error` result and a 503 "GitHub App not configured" state.
  - The OpenAPI client is regenerated.
- **Docs:**
  - A README section on creating a dev GitHub App: permissions, the Setup URL pointing at the API, where to put the PEM, which env vars to set.
  - A CHANGELOG entry.

### Out of scope
- Webhooks (installation added, removed or suspended; PR comments): 6.6. Until then, a removed installation shows up as `installation_gone` on the next `GET /repos`.
- Storing repos in a `repos` table, or a repo picker on the start screen: 1.11 and 4.8 pick from this live list.
- Write permissions in use (contents, pull requests), branches and PRs: 1.6 and 1.8. The README lists the permissions the App will need, so the dev App is created once.
- User OAuth ("request user authorization during installation") and checking that the browser user can access the installation: there are no users yet (see 1.4). This must be added before 9.5.
- More than one installation per workspace: the unique `(workspace_id, provider)` constraint is kept.
- Using the installation to clone in the sandbox: 1.6, or 1.11 at the latest.
- A manual demo against a real GitHub App, a no-leak test for the PEM, and Playwright tests: these were not chosen for validation in this phase (see Open questions).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Install flow and a repos list on `/settings`, live from GitHub, no webhooks | The user chose this. It meets "user sees repos" in the browser without pulling 6.6 forward. |
| App credentials | One platform App: id, slug and PEM come from platform config (a file), not from the workspace | It is SaaS (mission). The App belongs to the platform, and workspaces only own an installation. |
| Installation storage | A non-secret row in the 1.4 `connections` table (`provider='github'`, `external_id`) | The user chose this. It reuses one listing and delete path. The 1.4 spec planned for it. |
| Install CSRF | A random single-use `state` in Redis with a 10-minute TTL | Redis is already in the API. It needs no new signing key and is single use by construction. |
| Verifying the callback | Look up `installation_id` with the App JWT before storing it | A forged callback can't link an installation that doesn't belong to our App. The lookup also returns `account_login` for display. |
| Repo list | Live `GET /installation/repositories` on each request; tokens cached by githubkit | It is always current with no sync job and no webhook. Caching or storing repos can come in 1.11 if it is slow. |
| Endpoint path | `GET /workspaces/{id}/repos` (the roadmap says `GET /repos`) | Repos are scoped to the workspace's installation, which matches the 1.4 workspace routes. |
| Where GitHub code lives | A new `agentic_github` package | The API uses it now, and the `github` tool server (1.8) uses it later, without importing the API. |
| Build order | GitHub client → store → API → web → compose/docs | The user chose this. Each group leaves the project working. |
| Validation | Unit and API tests with mocked GitHub HTTP (respx), store tests on Testcontainers, Vitest for the UI | The user chose this. It is deterministic with no network, and CI needs no real App. |

## Open questions
- **Live proof:** no manual run against a real GitHub App was chosen. Do one before the AC-1 demo (1.11), following the README steps.
- **No-leak test for the PEM:** not chosen for this phase. The PEM is registered for redaction, but no test asserts it yet. Consider adding one when installation tokens reach the tool servers (1.6).
- **Large installations:** with hundreds of repos, the paginated live call may be slow. If it is, add a short TTL cache or a `repos` table in 1.11.
- **Who may install:** with no users, anyone who can open `/settings` can link an installation to the default workspace. This is fine for local dev only.
