# Validation: Shell and settings v2

## Done when (from roadmap)
> Every settings sub-page fits at 1440 px with no horizontal scroll and stacks at 375 px; `⌘K` opens a run from its id

"Fits": no horizontal page scroll and no scroll inside the pricing table at 1440 px. "Stacks": at 375 px the secondary nav sits above the content and pricing rows are cards. "From its id": a short id (8 characters) or a full id typed in the palette, then Enter, lands on `/runs/{id}`.

## Automated checks
- [ ] API (pytest, Testcontainers): `GET /runs?q=` matches an id prefix (4+ characters) and a full id, a PR by `42` and `#42`, a workflow name in any case; `%` and `_` match literally; combines with `status`; never returns another workspace's run; pages with the cursor; `q` over 100 characters is a 422
- [ ] Web unit (Vitest):
  - palette opens on `⌘K` and `Ctrl+K` and from the top-bar button, from a page field but not inside the diff editor; a short id lists its run and Enter navigates to `/runs/{id}`; `#42` finds by PR; a full id not in the results still opens; Toggle theme switches the theme; Approve opens `/inbox?run=<id>`; loading, empty and error rows
  - user menu: theme and density change from the menu; the top bar no longer has them
  - breadcrumbs read "Settings › Integrations" (the redirect itself is a `next.config` rule, checked in e2e)
  - `?new=1` on the Runs page opens the New run sheet and closing it drops the param
  - pricing: both cache-write prices in one cell with their windows; overrides still save
  - limits: no sticky bar on load, bar after a change, Discard restores the saved values and hides it, Save posts and hides it, a 422 shows on its field
- [ ] e2e (Playwright): `/settings?github=…` lands on `/settings/integrations` with its query; the settings nav sits beside the sub-page from 768 px and above it at 375 px; `layout.spec.ts` screenshots of `/settings/integrations`, `/settings/models`, `/settings/limits` at 375, 768 and 1440 px with no horizontal page scroll (and the pricing table's `scrollWidth` ≤ `clientWidth` at 1440); `a11y.spec.ts` (axe) over the three sub-pages, the open palette and the open user menu; `journey.spec.ts` green with the new return URL; the rest of the suite green
- [ ] `ruff`, `pyright`, `pytest`; `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`

## Manual / demo checks
- [ ] Look at the three settings sub-pages, the palette and the user menu at 375 and 1440 px, light and dark (required by `CLAUDE.md` before a UI change is called done)

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `openapi.json` and `schema.d.ts` regenerated and committed
- [ ] No palette classes or hard-coded colours (`agentic-ui/no-raw-colors`); values through `@/components/display` and `StatusBadge`
- [ ] tech-stack (11.7 moved out of UI v2, `q` in the run history contract, decisions log row) and `CHANGELOG.md` updated in the same PR; `CLAUDE.md` only if a rule changed
