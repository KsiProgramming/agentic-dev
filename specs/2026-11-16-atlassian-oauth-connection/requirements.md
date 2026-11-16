# Atlassian OAuth 3LO per workspace, project scoping

Roadmap phase: 7.1
Branch: plan/7.1-atlassian-oauth-connection

## Context

First phase of Milestone 7 (Jira and Spec-Driven Development). Milestones 6 and 12 are done (12.4 merged as #236), so Milestone 7 is next. The roadmap's "Next up" line still names Milestone 6 at 6.7; it is updated in its own PR, as the roadmap asks, not here.

Today a workspace has two connections: Claude (an API key, encrypted under the workspace's data key, 1.4) and GitHub (an App installation, no secret, 1.5). This phase adds the third, Jira, which every other phase of the milestone needs: the `jira` MCP server (7.2), the webhook trigger (7.3), field mapping (7.4) and the SDD template (7.5, AC-5).

It depends only on done work: encrypted connections (1.4), the GitHub install flow whose `state` handling it copies (1.5), the Settings › Integrations page (11.7) and the audit log (3.7).

Principles: **3. Humans approve irreversible actions** (this phase writes nothing to Jira; the write scopes it asks for are used behind gates from 7.2), **4. Tools live in the platform** (the tokens stay in the platform, agents never see them), **5. Jira content is data** (site and project names are shown as text), **6. Transparency** (connect, project changes, failures and disconnect are audit entries). Tech stack: "Integrations → Jira: Atlassian OAuth 2.0 (3LO) per workspace, scoped to selected projects" and "No personal access tokens are stored"; secrets encrypted with a key per workspace (Security & secrets). The v1 decision "self-hosted first" means each deployment registers its own Atlassian OAuth app, as it does its GitHub App.

The phase does not change what agents receive, so lessons.md rule 1's real Claude run does not apply.

Checked against Atlassian's docs on 2026-11-16 ("OAuth 2.0 (3LO) apps"): consent is given per **site**, never per project; refresh tokens **rotate** (each use returns a new one, 90 days of inactivity ends it, a used token is accepted again for 10 minutes); the sites a grant reaches come from `GET https://api.atlassian.com/oauth/token/accessible-resources`.

## Scope

### In scope
- **OAuth flow.** `POST /workspaces/{id}/jira/authorize-url` returns Atlassian's authorize URL with a single-use `state` kept in Redis for 10 minutes (as the GitHub install); `GET /jira/callback` consumes the state, exchanges the code, stores the grant and sends the browser back to `/settings/integrations?jira=connected` (or `jira=error&reason=…`).
- **Stored encrypted.** The access token, the refresh token, the expiry and the granted scopes are one JSON secret in the workspace's `jira` connection, encrypted under the workspace's data key by the existing envelope (`agentic_secrets`), with the Atlassian account's name as the hint shown.
- **Token refresh.** One function gives a valid access token to any caller (the API now, the worker and the `jira` tools from 7.2). It refreshes under a row lock on the connection when the token is within 60 s of its expiry and stores the rotated pair before it releases the lock.
- **Several sites.** One grant per workspace, and every Jira site that grant reaches (`jira_sites`: cloud id, URL, name). The user turns sites on or off; nothing is usable on a site until projects are picked.
- **Project picker.** Per site, the projects the workspace may use (`jira_projects`: id, key, name as picked), chosen from a searchable list read live from Jira. This allowlist is ours, since Atlassian has no project-level consent, and `allowed_project(workspace, cloud_id, key)` is the one check 7.2 to 7.5 call.
- **All Milestone 7 scopes now.** `read:jira-work`, `write:jira-work`, `manage:jira-webhook`, `read:jira-user`, `read:me` and `offline_access`, so 7.2 and 7.3 need no second consent. The card lists what was granted.
- **Needs attention.** A refresh Atlassian refuses (`invalid_grant`), or a grant missing a scope we need, marks the connection "Needs attention" with the reason and a Reconnect action, and writes an audit entry. Reconnecting keeps the sites and projects already picked when the account still reaches them.
- **Settings card.** A Jira `ConnectionCard` on Settings › Integrations: Connect, the account, each site with its project count and "Choose projects", Reconnect, Disconnect (confirmed in a dialog). With no Atlassian app configured on the server, a muted card with the reason and no action.
- **Disconnect.** `DELETE /workspaces/{id}/connections/jira` removes the tokens, sites and projects, and tells the user where to remove the app's access in their Atlassian account.
- **A new package, `packages/jira`,** mirroring `packages/github`: `JiraPlatform` (authorize URL, code exchange, refresh, accessible resources, project search), a real client and a fake (`AGENTIC_JIRA=fake`, refused in production) for tests, local dev and the e2e stack.
- Specs and docs: tech-stack ("Jira connection (API contract)", the audit actions, decisions-log rows), `docs/integrations/connecting-platforms.md` (registering the Atlassian app), `docs/security/security-model.md`, `.env.example`, CHANGELOG.

### Out of scope
- **Any Jira tool for agents** (read issue, comment, transition): 7.2. This phase calls Jira only to list sites and projects.
- **Webhooks and triggers:** 7.3. The `manage:jira-webhook` scope is asked for now and not used.
- **Field mapping per project:** 7.4. The picker stores which projects, not how their fields map.
- **A "Jira" chip in a template's Requires line and the run sheet's checklist:** 7.5, the first template that requires Jira.
- **Jira Data Center or Server.** Cloud only; 3LO as specified here is a Cloud flow.
- **Several Atlassian accounts per workspace.** One grant; several sites through it.
- **Users and roles.** The workspace is the actor (roadmap note); the connecting person's Atlassian account is recorded on the connection.
- **A new Playwright spec for the connect flow, and a concurrent-refresh test** (not chosen in the interview). The existing e2e suite (axe and layout on the Integrations page) must stay green, and the flow is covered by API and component tests.
- **The roadmap's "Next up" line** (its own PR).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the code lives | `packages/jira` with a `JiraPlatform` protocol, a real client and a fake | Chosen in the interview. The worker and the 7.2 tools need the same client and token; the fake keeps tests and the e2e stack off the network, as `agentic_github.fake` does. |
| HTTP client | `httpx2`, already used by `packages/runtime`; no Atlassian SDK | Five endpoints, all plain JSON. An SDK would add a dependency for less code than its wrapper. |
| What is stored | One encrypted JSON secret on the `connections` row (`access_token`, `refresh_token`, `expires_at`, `scopes`); sites and projects in their own tables, in the clear | The roadmap's "stored encrypted" with the envelope that exists. Site and project names are not secrets and the UI lists them without decrypting. |
| Who refreshes | Whoever needs a token, under `SELECT … FOR UPDATE` on the connection row, 10 s HTTP timeout | Refresh tokens rotate, so two refreshes must not race. No background job to run and monitor; the lock is held for one short call. Atlassian's 10-minute reuse window covers a crash between the call and the commit. |
| Project scoping | Our own allowlist per site, enforced in the platform by one function | Atlassian grants per site. An allowlist the platform checks is the only way to meet "scoped to selected projects". |
| Scopes | Classic scopes for all of Milestone 7, asked once | Chosen in the interview: no reconnect at 7.2 and 7.3. Atlassian recommends classic scopes over granular ones where they suffice. Nothing is written before a gate (principle 3). |
| Several sites | One grant, every site it reaches, each on or off with its own projects | Chosen in the interview. One consent already covers several sites, so this costs two tables and no second OAuth flow. |
| Needs attention | A `needs_attention` reason on the connection, set on `invalid_grant` or a missing scope, cleared by a successful reconnect | Chosen in the interview. The card's existing amber state; the failure is visible before a run trips on it. |
| State handling | Random `state` in Redis, 10 minutes, consumed before anything else | Same as the GitHub install (`github:install-state`), so one pattern to review. |
| Configuration | `ATLASSIAN_CLIENT_ID`, `ATLASSIAN_CLIENT_SECRET_FILE`; unset means "not configured" | Self-hosted first: each deployment's own app. A file for the secret, as for the GitHub App key. |
| Disconnect | Delete locally, point the user to their Atlassian account for the app's access | The 3LO docs give no revoke endpoint to rely on; deleting the refresh token ends our use of the grant. |

## Open questions
- Atlassian acts as the person who consented, so 7.2's comments will carry that person's name. The docs page tells teams to connect with a dedicated Jira account; whether the card should say so too is decided with 7.2.
- Whether `read:jira-user` is needed at all is confirmed when 7.4 maps fields; it is dropped from the request if not.
