# TODO

Open points from a review of the Milestone 1 GitHub integration (phases 1.4, 1.5, 1.8 and fix #26). To be challenged before any of it goes on the roadmap.

## 1. Users and auth phase (no roadmap phase owns it)
No phase covers users, login, workspace membership or the GitHub OAuth callback. The 1.4 and 1.5 specs say it "must be added before 9.5", but 9.5 is now "Architect chat" after renumbering; the intent was probably the SaaS phase, now **10.5**.

- **Deadline:** before 10.5 (multi-tenant SaaS).
- **Proposed slot:** early Milestone 3, before 3.6 (gate approval with edits, which should record who approved) and 3.7 (audit log for admins, which needs roles).
- **Scope:**
  - Sign-in (GitHub OAuth as the login) and sessions.
  - Users, workspaces and membership with roles, enforced on every API endpoint (today the API has no auth at all).
  - In `/github/setup`, exchange the OAuth `code` for a user token and check with `GET /user/installations` that the user can access `installation_id` before linking it (see 2).
  - Record who approved each gate.

## 2. Installation hijack on `/github/setup`
`/github/setup` checks that the installation belongs to our App (App JWT), but not that the browser user can access it. Installation ids are not secret: someone could take a valid `state` from their own install flow, then call `/github/setup?installation_id=<another account's id>&state=<theirs>` and link another account's repos to their workspace. GitHub's docs warn about this.

- **Today:** not exploitable, because there is one default workspace and no users.
- **Fix:** turn on "Request user authorization (OAuth) during installation" on the App, and add the check from 1.
- Code: `packages/api/src/agentic_api/github/routes.py` (`complete_install`).

## 3. Narrow installation tokens
`GithubApp.installation_token()` (`packages/github/src/agentic_github/app.py`) asks for a token over every repo in the installation, with all of the App's permissions. GitHub's create-installation-token call accepts `repositories` and `permissions`.

- **Fix:** ask for the run's repo only, with `contents: write` and `pull_requests: write` (or `contents: read` for the clone). That limits the damage if a token leaks.

## 4. Stale phase references in specs
Older specs point at phase numbers from before the renumbering:
- "before 9.5" (users/auth): should be 10.5, or the new auth phase from 1.
- "Webhooks: 6.6" in the 1.5 and 1.8 specs: now **7.6**.

## 5. Webhooks (already planned: 7.6)
Not missing, only deferred. Until 7.6, an uninstalled or suspended App is noticed only lazily, as `installation_gone` on the next `GET …/repos` or run. When 7.6 is planned, also handle `installation` (deleted/suspended) and `installation_repositories` (repos removed), and verify the webhook signature (HMAC secret).

## Notes to keep in mind when challenging
- The Setup URL (`/github/setup`) is required and already built: it is how the installation id reaches us. Only the OAuth user-authorization callback is missing.
- User sign-in does not replace the App private key. Runs push and open PRs in the background, possibly hours after approval, as the App bot, using short-lived installation tokens minted from the key. Sign-in controls *who may link and use* a workspace; the App's permissions control *what the platform may do* on GitHub.

## 6. Say why each tool call is made (run console)
Claude Code shows a one-line intent per tool call ("Bash · Check group summary spans"). The run console (2.5) shows what a call did ("Read `src/app.ts`") but not why.

- **Idea:** add an optional `description` argument to the platform's `repo.*` and `github.*` tools, which agents fill in, and show it next to the call in the console.
- **Touches:** the tool schemas (`agentic_tools`), the agent instructions, and `web/src/runs/console/tool-describe.ts`. Small enough for its own phase; not part of 2.5.
