# Validation: GitHub App install + `GET /repos`

## Done when (from roadmap)
> User sees repos the app is installed on

Made checkable: after the install flow, `/settings` lists the repos returned by `GET /workspaces/{id}/repos` for the workspace's stored installation. This is proven with mocked GitHub HTTP in the API tests and a mocked API in the web tests.

## Automated checks
- [x] `packages/github/tests` (respx, test RSA key):
  - [x] App JWT auth on `get_installation`.
  - [x] The installation token is fetched once and reused.
  - [x] `list_repos` follows pagination.
  - [x] 404 → `InstallationNotFoundError`; 403 and 5xx → `GithubApiError`.
  - [x] The PEM is redacted in captured logs.
- [x] `packages/store/tests/test_connections.py` (Testcontainers Postgres):
  - [x] GitHub connection put, replace, get and delete.
  - [x] Claude and GitHub rows coexist.
  - [x] The check constraint enforced per provider.
  - [x] Migration 0008 upgrades and downgrades.
- [x] `packages/api/tests/test_github.py`:
  - [x] The install URL contains the slug and a single-use state.
  - [x] Setup → stored connection → 303 to `/settings?github=connected`.
  - [x] A replayed or expired state, an unknown installation and `setup_action=request` each redirect with the right `reason`.
  - [x] `GET /workspaces/{id}/repos`:
    - [x] Sorted `RepoOut[]` on success.
    - [x] 404 for an unknown workspace.
    - [x] 409 `no_connection`.
    - [x] 409 `installation_gone`.
    - [x] 502 on a GitHub error.
    - [x] 503 when the App is not configured.
  - [x] No error body contains a token.
  - [x] `GET /workspaces/{id}/connections` includes the GitHub row with `account_login`.
- [x] Existing 1.4 tests (`test_workspaces.py`, `test_no_secret_leak.py`) still pass unchanged.
- [x] `web/src/settings/github-connection.test.tsx` (Vitest + Testing Library):
  - [x] Not connected → install button → navigates to `install_url`.
  - [x] Connected → repo list with private badge and default branch.
  - [x] Disconnect calls DELETE.
  - [x] The 503 and `installation_gone` messages.
  - [x] The `?github=connected|error` banner.
- [x] `ruff`, `pyright`/`mypy` strict, ESLint, Prettier and `tsc` pass.
- [x] The OpenAPI client is up to date: CI regenerates `schema.d.ts` with no diff.

## Manual / demo checks
- [x] `docker compose up` with the GitHub variables blank:
  - [x] Health is OK.
  - [x] `/settings` renders (200), `GET …/repos` answers 503 naming `GITHUB_APP_ID`, and `/github/setup` redirects with `reason=not_configured`. The section shows that 503 as "not configured" (Vitest).
  - [x] The Claude key still saves (`PUT …/connections/claude` → hint `1234`) and is not in the API logs.
  - Run as a separate compose project on ports 18000/13000, then removed with `down -v`.

A real GitHub App demo was not chosen for this phase. It is tracked in the Open questions of `requirements.md` and should happen before 1.11.

## Merge criteria
- [ ] All checks above pass in CI (`ci.yml`). They pass locally.
- [ ] The roadmap phase 1.5 is marked done (`pr-checks.yml` / `complete-phase`).
- [x] The README "GitHub App (dev)" section, `.env.example` and the CHANGELOG are updated.
- [x] No PEM or installation token in the repo or in API error bodies (tested), and the PEM is redacted from logs (tested). `.secrets/` is gitignored. No end-to-end no-leak test was chosen (see Open questions).
- [x] The tasks in `plan.md` are ticked, and the open questions in `requirements.md` are updated.
