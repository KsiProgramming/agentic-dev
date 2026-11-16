# Plan: Atlassian OAuth 3LO per workspace, project scoping

Aligned with the build on 2026-11-16: route names follow GitHub's (`connections/jira/authorize`), an unconfigured server answers `503` as it does for GitHub, the refresh lives in `agentic_jira.tokens` over an opaque `refresh_jira_secret` in the store, and a site switch has its own audit action.

Order chosen in the interview: store and migration, the `jira` package, API routes, then the Settings card. The project works after each group. Run tests locally before pushing (CI minutes are limited), and never run `packages/sandbox/tests` whole.

## 1. Specs first
- [x] `specs/tech-stack.md`: a "Jira connection (API contract)" section (routes, the stored secret, sites and projects, refresh rule, scopes, needs-attention reasons, configuration); the Integrations line updated; "Start and settings" gets the Jira card and the project sheet; the audit table gets the new actions; decisions-log rows from requirements.md.
- [x] `CHANGELOG.md`: an entry under `## [Unreleased]`.

## 2. Store and migration
- [x] Alembic `0033_jira_connection`: `connections.needs_attention` and `connections.scopes`, `connections.account_login` reused for the Atlassian account name; `ck_connections_provider_columns` extended for `jira` (a secret, no `external_id`); `jira_sites` (`connection_id`, `cloud_id`, `url`, `name`, `enabled`, unique per connection and cloud id) and `jira_projects` (`site_id`, `project_id`, `key`, `name`, unique per site and project id), both deleted with the connection.
- [x] `agentic_store.models`: `JiraSite`, `JiraProject`; `Connection.needs_attention`.
- [x] `agentic_store/jira.py`: `put_jira_connection` (encrypts the grant, upserts the sites, keeps picked projects of sites still reached), `get_jira_connection` (no secret), `set_jira_site_enabled`, `set_jira_site_projects`, `jira_project_allowed`, `mark_jira_needs_attention`, `refresh_jira_secret` (the row lock); each write calls `audit`. Deleting is `delete_connection(…, "jira")`, which cascades.
- [x] `ConnectionInfo` and `_connection_info`: `needs_attention`.
- [x] Store tests (Testcontainers Postgres): encrypt and load round trip, ciphertext only in the row, replace on reconnect, allowlist checks, cascade on delete, migration up and down.

## 3. `packages/jira`
- [x] Package scaffold in the `uv` workspace (`agentic_jira`), `httpx2` dependency, pyright strict.
- [x] `config.py`: `AtlassianAppConfig` (client id, secret from a file as `SecretStr`, redirect URI); `errors.py`: `JiraConfigError`, `JiraAuthError` (`exchange`, `invalid_grant`), `JiraUnauthorizedError`, `JiraApiError`.
- [x] `models.py`: `Grant` (tokens as `SecretStr`, `expires_at`, `scopes`), `Site`, `Project`, `Account`; `SCOPES` (the six in requirements.md) and `missing_scopes`.
- [x] `platform.py`: the `JiraPlatform` protocol (`authorize_url(state)`, `exchange(code)`, `refresh(refresh_token)`, `account(token)`, `sites(token)`, `search_projects(token, cloud_id, query, start_at)`, `get_projects(token, cloud_id, ids)`).
- [x] `client.py`: the real client against `auth.atlassian.com` and `api.atlassian.com/ex/jira/{cloud_id}/rest/api/3`, 10 s timeouts, errors mapped to the fixed reasons, no token or response body in a log line or an exception message.
- [x] `fake.py`: an in-memory platform with two sites and a few projects, a code that is refused, and switches for a refused refresh, a refused token, missing scopes and an outage.
- [x] `tokens.py`: `access_token(sessions, keys, platform, workspace_id)`: row lock, refresh inside 60 s of expiry, store the rotated pair, needs attention on `invalid_grant`; `call(…)` retries once on a `401`.
- [x] Unit tests: URL building (audience, scopes, `prompt=consent`, state), each client call against a mocked transport, error mapping, `tokens.py` (fresh token untouched, expiring token refreshed and stored, refused refresh marks the connection).

## 4. API
- [x] `agentic_api/settings.py`: `ATLASSIAN_CLIENT_ID`, `ATLASSIAN_CLIENT_SECRET_FILE`, `AGENTIC_JIRA` (`app` or `fake`; `fake` refused with `AGENTIC_ENV=production`); `app.state.jira` built at start, `None` when unconfigured. (`health` reports neither GitHub nor Jira.)
- [x] `agentic_api/jira/routes.py` and `models.py`:
  - `POST /workspaces/{id}/connections/jira/authorize` (`return_to` optional) → `{authorize_url}`; `503` when not configured.
  - `GET /jira/callback` (`code`, `state`, `error`): state consumed first, exchange, account and sites read, grant stored, redirect to the web with `jira=connected` or `jira=error&reason=state|denied|exchange|no_sites|scopes|atlassian|not_configured`.
  - `GET /workspaces/{id}/jira` → `configured`, `status` (`connected`, `needs_attention`, `not_connected`), `reason`, `account`, `scopes`, `sites` with their picked projects.
  - `PATCH /workspaces/{id}/jira/sites/{cloud_id}` (`enabled`).
  - `GET /workspaces/{id}/jira/sites/{cloud_id}/projects?q=&cursor=` (live from Jira).
  - `PUT /workspaces/{id}/jira/sites/{cloud_id}/projects` (the whole allowlist; ids checked against Jira).
  - `DELETE /workspaces/{id}/connections/jira` → `204`.
- [x] `GET /workspaces/{id}/connections` lists the `jira` connection (provider, account, `needs_attention`), never a token.
- [x] Audit actions: `connection.added` and `connection.removed` (existing, `provider: jira`, the account), `connection.needs_attention` (reason), `jira.site_updated` (site, enabled), `jira.projects_changed` (site, count and keys).
- [x] `docker-compose.yml`, `.env.example` and CI: the three settings, the secret file mount, `AGENTIC_JIRA=fake` for the e2e stack; `packages/api/Dockerfile` copies the new package.
- [x] API tests (Testcontainers, fake platform): the routes above, state single use and expiry, the no-token-anywhere test (validation.md), `openapi.json` regenerated.

## 5. Web
- [x] Read `web/AGENTS.md`, tech-stack → "UI design system" and `design-language.md` first; regenerate `web/src/api/schema.d.ts`.
- [x] `web/src/settings/jira-connection.tsx`: a `ConnectionCard` (existing) with `StatusBadge` states Connected, Not connected, Needs attention; the account; one row per site (name, URL host in mono, "N projects", "Turn off" / "Turn on" as a pressed button, since there is no switch primitive, "Choose projects"); the permissions granted; Connect, Reconnect, Disconnect through `confirm-dialog`; the muted "not configured" card; a toast for `?jira=connected` and an `Alert` for `?jira=error` with a sentence per reason.
- [x] `web/src/settings/jira-projects-sheet.tsx`: a sheet (side from 768 px, bottom below) with a search field, a checkbox list (key in mono, name as text), "N selected", Cancel and Save; `LoadingState`, `EmptyState` ("No project matches.") and `ErrorState` with Retry.
- [x] Add the card to `web/src/app/settings/integrations`; the audit page labels the three new actions.
- [x] Component tests: each card state, connect redirects to the URL the API returns, the sheet saves the selection, disconnect confirms first, the error reasons.
- [ ] Tokens only (no raw colours or sizes); icon-only buttons labelled; check 375 and 1440 px in light and dark.

## 6. Docs and the real check
- [x] `docs/integrations/connecting-platforms.md`: "Connect Jira": create the OAuth 2.0 app in the Atlassian developer console, the callback URL, the scopes to add, the settings to set, the advice to connect with a dedicated account.
- [x] `docs/security/security-model.md` and `docs/architecture/overview.md`: Jira moves from planned to connected (tools still planned), what is stored and where.
- [ ] Run the manual check in validation.md on a real Jira Cloud site and record the result there.
- [ ] If a real run of the flow shows something tests missed, add it to `specs/lessons.md` in the same PR.
