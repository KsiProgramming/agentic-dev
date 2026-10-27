# Plan: Shell and settings v2

## 1. API: run search
- [ ] `agentic_store.summaries`: `query: str | None` on `list_run_summaries` (and `_filtered`): id prefix (`cast(Run.id, Text).like(f"{q}%")` for 4+ hex/dash characters), PR number (`Run.pr_url.like("%/pull/<n>")` for `n` or `#n`), workflow name (`Run.spec["name"].astext.ilike("%q%")`, wildcards escaped); OR'd together, AND'd with the other filters
- [ ] `agentic_api.runs.routes`: `q` query param on `list_runs` (max 100 characters), passed through; docstring updated
- [ ] pytest (Testcontainers): id prefix, full id, `42` and `#42` for a PR, workflow name in any case, a `%` in `q` matched literally, combined with `status`, other workspaces never matched, cursor paging with `q`
- [ ] Regenerate `openapi.json` and `web/src/api/schema.d.ts`; `useRunSearch(q)` in `web/src/runs/use-run-search.ts` (beside the other `GET /runs` hooks, under the runs query key)
- [ ] github `return_to` default → `/settings/integrations`

## 2. User menu (shell)
- [ ] `src/components/shell/user-menu.tsx`: a "Preferences" `DropdownMenu` at the bottom of `Sidebar` (icon on the rail with a tooltip, full in the drawer): Theme radio group, Density radio group
- [ ] The density store moves to `use-density.ts` (`useCompact`); `theme-menu.tsx` and `density-toggle.tsx` (and their tests) are removed
- [ ] Vitest (`user-menu.test.tsx`): menu opens from keyboard, theme and density change and persist; `app-shell.test.tsx`: the top bar no longer has them

## 3. Command palette
- [ ] `src/components/shell/command-palette.tsx`: `CommandDialog` with `shouldFilter={false}` (runs filtered by the API, commands here); `⌘K` / `Ctrl+K` listener in the shell (ignored inside the Monaco diff editor), a "Search… ⌘K" button in the top bar (icon below `md`, `aria-label`, `aria-keyshortcuts`); `CommandDialog`'s title moved inside its content so the dialog is named
- [ ] Groups: Runs (`useRunSearch`, debounced 200 ms, 5 rows, "Open run" for a full UUID not found), Actions (New run → `/runs?new=1`, which the Runs page reads to open its sheet; Switch theme; Approve → `/inbox?run=<id>`), Go to (`NAV_ITEMS` + settings sub-pages from `src/settings/pages.ts`)
- [ ] Row content from shared parts only: `StatusBadge` via `badgeStatus`/`statusLabel`, short id in mono, `repoLabel`, PR number; loading, empty and error rows
- [ ] Vitest: opens on `⌘K` and `Ctrl+K`, from a page input but not inside the diff editor; typing a short id lists the run and Enter navigates to `/runs/{id}`; `#42` finds by PR; a full UUID not in results still opens; Toggle theme; Approve opens the Inbox; error row with retry

## 4. Settings sub-pages
- [ ] `src/app/settings/layout.tsx`: `PageHeader` + `SettingsNav` (`src/settings/settings-nav.tsx`, `aria-current`, vertical from `md`, horizontal scrolling links below)
- [ ] `src/app/settings/integrations/page.tsx` (Claude + GitHub with the `github` / `reason` params), `models/page.tsx`, `limits/page.tsx`, each with its `metadata` title
- [ ] `src/app/settings/page.tsx` removed; `/settings` → `/settings/integrations` as a `next.config` redirect (keeps the query; a page awaiting `searchParams` would be dynamic under `cacheComponents`)
- [ ] `nav.ts` `breadcrumbsFor`: "Settings › Integrations" (sub-page labels, not mono); update `nav.test.ts`
- [ ] The sidebar's Settings link stays `/settings` (the redirect opens Integrations); the templates install flow returns to its own page and is unchanged

## 5. Pricing table refit
- [ ] `model-pricing.tsx`: columns Model, Input, Output, Cache write (two stacked prices with muted "5 min" / "1 h"), Cache read, actions; drop `overflow-x-auto` from the desktop table; cards below `md`
- [ ] Vitest: both cache-write prices render in one cell with their windows; edit/override flow unchanged

## 6. Limits form
- [ ] `run-limits.tsx`: unit addons (`InputGroup`) per field, "Platform limit: N" help kept; bottom Save button replaced by a sticky `bottom-0` bar ("Unsaved changes", Discard, Save limits) rendered only when `isDirty`; Discard → `form.reset(saved)`; after a save, reset to the new values so the bar goes
- [ ] Vitest: no bar on load; bar after a change; Discard restores and hides it; Save posts and hides it; 422 shown on its field

## 7. e2e, specs and changelog
- [ ] `layout.spec.ts`: the three sub-pages at 375, 768, 1440 px, asserting no horizontal page scroll and the pricing table without its own scroll at 1440; `/settings` replaced by the sub-pages
- [ ] `a11y.spec.ts`: each sub-page, the open palette and the open user menu
- [ ] `journey.spec.ts`: GitHub install return expects `/settings/integrations?github=connected`; any `/settings` selectors updated
- [ ] tech-stack: 11.7 moved from UI v2 into Look (Theme), Layout (App shell, top bar, palette), Start and settings; `q` in the run history contract; decisions log row; `CLAUDE.md` only if a rule changes; `CHANGELOG.md` under `[Unreleased]`
