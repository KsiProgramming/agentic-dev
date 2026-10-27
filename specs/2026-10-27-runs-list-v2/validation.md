# Validation: Runs list v2

## Done when (from roadmap)
> Real runs are the first rows on the page whatever is waiting; a waiting run is one click away; no test run appears in the default workspace

"First rows": with no view chosen, the list shows the newest runs under date headers, with no section above it. "One click": the Needs approval tab, then the row's badge or link.

## Automated checks
- [ ] API (pytest, Testcontainers): migration `0022` backfills `trigger` and `branch`; `POST /runs` stores `trigger` (default `api`) and rerun stores `rerun`; `branch` comes from `repo.ref` and from `repo_created`; `GET /runs/counts` gives the count per view with the template and repo filters, does not count a gate past its expiry as waiting, and answers `404` for an unknown workspace; `POST /workspaces` creates one that `GET /workspaces` lists
- [ ] Web unit (Vitest): view ↔ URL round trip; date groups at the day boundaries in UTC; the tabs show counts and mark the current view; the Run column shows the id and the trigger ("Rerun of …"); a waiting row's badge links to the run; no Review button; per-view empty states; `useWorkspaceId` reads the cookie
- [ ] e2e (Playwright): `runs-page.spec.ts` covers the three Done-when clauses (the default workspace's `GET /runs` lists no run the suite started); every other spec is green in the E2E workspace; `a11y.spec.ts` and `layout.spec.ts` pass at 375, 768 and 1440 px
- [ ] `ruff`, `pyright`, `pytest`; `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`

## Manual / demo checks
- [ ] On the dev stack, run the e2e suite, then open `/` in a normal browser: the Default workspace shows no new e2e runs
- [ ] Look at `/` at 375 and 1440 px, in light and dark: tabs, sticky date headers, the Run and Repository columns, and no horizontal page scroll

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `openapi.json` and `schema.d.ts` regenerated and committed
- [ ] tech-stack and `CHANGELOG.md` updated in the same PR (and `CLAUDE.md` if a rule changed)
