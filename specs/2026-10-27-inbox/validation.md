# Validation: Inbox

## Done when (from roadmap)
> A gate is approved from the Inbox without opening the run console; the console's approval dock keeps working

"Without opening the run console": the e2e test never navigates to `/runs/{id}` before the run resumes. "Keeps working": the existing dock e2e specs pass unchanged.

## Automated checks
- [ ] API (pytest, Testcontainers): `GET /runs/{id}/gate` returns the gate with `changes`, `changes_error`, `expires_at`, `repo`, `base` and `branches`; `409` for a run not waiting and for a gate past its expiry; `404` for an unknown run
- [ ] Web unit (Vitest): the Inbox lists waiting runs oldest first and leaves out an expired gate; `?run=` selects a row (first row by default); the review shows what approving does, the summary or files, cost and active time; Approve / Reject call the API (with edits); `A` / `R` work and are ignored in a field; next gate selected after a decision; loading, empty and error states; the sidebar badge is on Inbox, not Runs; the dock's existing tests pass unchanged
- [ ] e2e (Playwright): `inbox.spec.ts` approves a gate from `/inbox` (button and `A`) and the run resumes without visiting its console; `gate-edits.spec.ts`, `monitor.spec.ts` and the rest of the suite stay green; `/inbox` in `a11y.spec.ts` and `layout.spec.ts`
- [ ] `ruff`, `pyright`, `pytest`; `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`

## Manual / demo checks
- [ ] On the dev stack, start a docs run that pauses at its gate; open `/inbox`, review the changed files, approve with `A`; the run continues and opens its PR
- [ ] Look at `/inbox` at 375 and 1440 px, in light and dark: list and review side by side at 1440, stacked at 375, no horizontal page scroll

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `openapi.json` and `schema.d.ts` regenerated and committed
- [ ] tech-stack and `CHANGELOG.md` updated in the same PR (and `CLAUDE.md` if a rule changed)
