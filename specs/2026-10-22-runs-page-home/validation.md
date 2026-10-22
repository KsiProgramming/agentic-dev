# Validation: Runs page (new home)

## Done when (from roadmap)
> User finds any past run and sees whether it succeeded, failed or is waiting

## Automated checks
- [ ] **Vitest, data layer:** `formatDuration`, relative time and `repoLabel`. `useRunList` pages through `next_cursor` and sends repeatable `status` params. The filter ↔ URL round-trip is lossless.
- [ ] **Vitest, components:** each status shows icon plus label in both the table row and the card. The PR link shows only when `pr_url` is set. The "Needs approval" section shows waiting runs first and is hidden when there are none. The states render: skeleton, "no runs", "no runs match these filters" with Clear, and error with a working Retry. "Load more" appends the next page.
- [ ] **Vitest, live:** with a fake `EventSource`, a `run_summary` frame updates the row in place. A list the run joins (new run) or leaves (no longer matches its filters) is refetched. A reconnect refetches the lists; the first connection does not. The stream closes on unmount. The `aria-live` region announces the change.
- [ ] **pytest, `GET /runs/stream`** (Testcontainers Postgres): a gated run streams waiting, then completed after approval, with no summary sent twice. Text deltas send nothing. Runs from another workspace never appear. A change with no notification still arrives on the recheck. An unknown workspace is `404`, and `/runs/stream` is not captured by `/{run_id}`.
- [ ] **Playwright e2e `runs-page.spec.ts`:** start a succeeded run, a failed run and a gated run through the API, then open `/`.
  - The page lands on `/runs` and lists all three with the labels Succeeded, Failed and Waiting.
  - The waiting run is in "Needs approval" at the top.
  - Filtering by Failed shows only the failed run, and the URL holds the filter after a reload.
  - Approving the gate through the API makes the waiting run show Succeeded with no reload (within 15 s, which includes the worker picking the run up again), and it leaves "Needs approval".
  - Clicking a row opens `/runs/{id}`.
- [ ] Existing e2e (`home`, `layout`, `a11y`, `monitor`) still pass, updated where they relied on the placeholder.
- [ ] Lint and types: `ruff`, `pyright`/`mypy` strict, ESLint, Prettier and `tsc` are clean. The OpenAPI/schema-is-current check is green.

## Manual / demo checks
- [ ] `docker compose up`, then open http://localhost:3000. The Runs page lists the real past runs, including runs from before 2.3 (backfilled), with the right status and duration.
- [ ] Start a docs run from Templates and go back to Runs. The row goes Queued → Running → Waiting, appears under "Needs approval", and moves back after approval, all without a reload.
- [ ] Narrow the window below 768 px. The rows turn into cards and the filters stack below the header.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] No raw palette classes. Only tokens and shared components are used (2.1 rule).
- [ ] Roadmap 2.4 is marked `✅ Done` in the implementation PR.
- [ ] The stream sends no secrets or run `input` (only `RunSummary` fields).
