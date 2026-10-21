# Validation: GitHub App install + `GET /repos`

## Done when (from roadmap)
> User sees repos the app is installed on

Made checkable: after the install flow, `/settings` lists the repos returned by `GET /workspaces/{id}/repos` for the workspace's stored installation. This is proven with mocked GitHub HTTP in the API tests and a mocked API in the web tests.

## Automated checks
- [ ] `packages/github/tests` (respx, test RSA key):
  - [ ] App JWT auth on `get_installation`.
  - [ ] The installation token is fetched once and reused.
  - [ ] `list_repos` follows pagination.
  - [ ] 404 → `InstallationNotFound`; 403 and 5xx → `GithubApiError`.
  - [ ] The PEM is redacted in captured logs.
- [ ] `packages/store/tests/test_connections.py` (Testcontainers Postgres):
  - [ ] GitHub connection put, replace, get and delete.
  - [ ] Claude and GitHub rows coexist.
  - [ ] The check constraint enforced per provider.
  - [ ] Migration 0008 upgrades and downgrades.
- [ ] `packages/api/tests/test_github.py`:
  - [ ] The install URL contains the slug and a single-use state.
  - [ ] Setup → stored connection → 303 to `/settings?github=connected`.
  - [ ] A replayed or expired state, an unknown installation and `setup_action=request` each redirect with the right `reason`.
  - [ ] `GET /workspaces/{id}/repos`:
    - [ ] Sorted `RepoOut[]` on success.
    - [ ] 404 for an unknown workspace.
    - [ ] 409 `no_connection`.
    - [ ] 409 `installation_gone`.
    - [ ] 502 on a GitHub error.
    - [ ] 503 when the App is not configured.
  - [ ] No error body contains a token.
  - [ ] `GET /workspaces/{id}/connections` includes the GitHub row with `account_login`.
- [ ] Existing 1.4 tests (`test_workspaces.py`, `test_no_secret_leak.py`) still pass unchanged.
- [ ] `web/src/settings/github-connection.test.tsx` (Vitest + Testing Library):
  - [ ] Not connected → install button → navigates to `install_url`.
  - [ ] Connected → repo list with private badge and default branch.
  - [ ] Disconnect calls DELETE.
  - [ ] The 503 and `installation_gone` messages.
  - [ ] The `?github=connected|error` banner.
- [ ] `ruff`, `pyright`/`mypy` strict, ESLint, Prettier and `tsc` pass.
- [ ] The OpenAPI client is up to date: CI regenerates `schema.d.ts` with no diff.

## Manual / demo checks
- [ ] `docker compose up` with the GitHub variables blank:
  - [ ] Health is OK.
  - [ ] `/settings` shows "GitHub App not configured".
  - [ ] The Claude section still works.

A real GitHub App demo was not chosen for this phase. It is tracked in the Open questions of `requirements.md` and should happen before 1.11.

## Merge criteria
- [ ] All checks above pass in CI (`ci.yml`).
- [ ] The roadmap phase 1.5 is marked done (`pr-checks.yml` / `complete-phase`).
- [ ] The README "GitHub App (dev)" section, `.env.example` and the CHANGELOG are updated.
- [ ] No PEM, JWT or installation token in the repo, logs, API responses or `run_events`. `.local-secrets/` is gitignored.
- [ ] The tasks in `plan.md` are ticked, and the open questions in `requirements.md` are updated.
