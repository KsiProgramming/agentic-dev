# Validation: Atlassian OAuth 3LO per workspace, project scoping

## Done when (from roadmap)
> Jira connection stored encrypted

Made checkable: after the OAuth flow, the workspace's `jira` connection holds the access and refresh tokens only as ciphertext under the workspace's data key; a valid access token can be obtained from it after the first one expires; the tokens appear in no log, audit entry, event or API response; and only the projects the user picked pass `allowed_project`.

## Automated checks

### No token anywhere (chosen in the interview)
- [ ] `test_jira_tokens_appear_nowhere`: with the fake platform issuing known token strings, run connect, a forced refresh, a project save and disconnect; assert neither string (nor the client secret) is in any captured log record, any `audit_events` row, any API response body or header, or the redirect URL.
- [ ] `test_jira_secret_is_ciphertext`: the `connections` row's `secret_ciphertext` does not contain either token, `key_hint` is not part of a token, and `load_secret` with another master key raises `SecretDecryptError`.

### Store (Testcontainers Postgres)
- [ ] Grant round trip; a reconnect replaces the secret and keeps the picked projects of sites still reached, drops those of sites no longer reached.
- [ ] `allowed_project`: true only for a picked project on an enabled site of a connection that is not `needs_attention`.
- [ ] Deleting the connection deletes its sites and projects; migration `0033` upgrades and downgrades.

### `packages/jira`
- [ ] The authorize URL carries `audience=api.atlassian.com`, the six scopes, `response_type=code`, `prompt=consent`, the redirect URI and the state.
- [ ] Exchange, refresh, account, sites and project search against a mocked transport; `invalid_grant`, a timeout and a 5xx map to their fixed reasons.
- [ ] `access_token`: a fresh token makes no call; one within 60 s of expiry is refreshed and the rotated pair stored; a refused refresh marks the connection `needs_attention` and raises.

### API (fake platform)
- [ ] Connect: authorize URL, callback, `GET /workspaces/{id}/jira` shows the account and both fake sites.
- [ ] A state is single use and expires; a callback with a wrong, used or missing state stores nothing and redirects with `reason=state`; `error=access_denied` redirects with `reason=denied`.
- [ ] A grant missing a scope is stored as `needs_attention` with `reason=scopes`.
- [ ] Project search and save per site; an unknown project id is refused with `422`; a site switched off keeps its projects and fails `allowed_project`.
- [ ] Disconnect answers `204`, then `not_connected`; an unconfigured server answers `503` on the Jira routes and `configured: false`.
- [ ] Audit entries: `connection.added`, `jira.projects_changed`, `jira.site_updated`, `connection.needs_attention`, `connection.removed`.

### Web
- [ ] `jira-connection.test.tsx`: the four card states (not configured, not connected, connected, needs attention), Connect follows the API's URL, Disconnect confirms first, each error reason has its sentence.
- [ ] `jira-projects-sheet.test.tsx`: loading, empty, error with Retry, search, save.

### Repo checks
- [ ] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pytest` for `store`, `jira` and `api` (not `packages/sandbox/tests` as a whole).
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test`.
- [ ] `pnpm test:e2e` with `AGENTIC_JIRA=fake`: the existing suite stays green, including `a11y.spec.ts` and `layout.spec.ts` on Settings › Integrations with the new card. No new connect-flow spec (out of scope).

## Manual / demo checks

### Real Jira Cloud site (chosen in the interview)
Needs an OAuth 2.0 (3LO) app in the Atlassian developer console with the callback `<API>/jira/callback` and the six scopes, and `ATLASSIAN_CLIENT_ID` / `ATLASSIAN_CLIENT_SECRET_FILE` set.
- [ ] Settings › Integrations → Connect on the Jira card → Atlassian's consent screen lists the scopes → back on the card: Connected, the account name, the site.
- [ ] "Choose projects": search, pick two, Save; the card reads "2 projects"; reload keeps it.
- [ ] `SELECT provider, key_hint, length(secret_ciphertext) FROM connections WHERE provider = 'jira'` shows a ciphertext; the API and worker logs of the session contain no token (search for `eyJ`).
- [ ] Force a refresh (set the stored expiry to the past through a test helper, or wait an hour) and open "Choose projects" again: the list loads, and the audit log has no `needs_attention`.
- [ ] Revoke the app in the Atlassian account's connected apps, then open "Choose projects": the card turns to Needs attention with Reconnect; Reconnect brings it back with the two projects still picked.
- [ ] Disconnect → confirm → Not connected; the row, sites and projects are gone.
- [ ] The card at 375 and 1440 px, light and dark; every action reachable by keyboard.
- [x] Record the date, the site used (not its tokens) and the outcome here.

**Result (2026-11-16):** run by hand on the local compose stack against a real Jira Cloud site, with the maintainer's own Atlassian OAuth 2.0 (3LO) app (callback `http://localhost:8000/jira/callback`, the six scopes). Atlassian's consent screen accepted the scopes, the card came back connected with the real account and sites, and the maintainer reported the checks above as working. The fake Atlassian was used before it for the screens (`AGENTIC_JIRA=fake`).

### With the fake (no Atlassian account)
- [ ] `AGENTIC_JIRA=fake docker compose up`: connect, pick projects and disconnect work end to end.
- [ ] With no Atlassian settings and `AGENTIC_JIRA` unset: the muted card says the server has no Atlassian app configured.

## Merge criteria
- [ ] All checks above pass locally, then in CI
- [ ] tech-stack (contract, audit actions, decisions log), CHANGELOG and the docs pages are updated in the same PR
- [ ] No token or client secret in any log, fixture or screenshot (the one-time authorization code is in the callback's access log line: single use, useless without the client secret)
- [ ] The roadmap row 7.1 is marked done by the PR (CI does it)
- [ ] A human squash-merges
