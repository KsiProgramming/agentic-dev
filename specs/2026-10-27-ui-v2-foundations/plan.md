# Plan: UI v2 foundations

One PR, one commit per group. The app stays working after each group; the lint rule lands last so it lands green.

## 1. Tokens: type scale and density
- [ ] `web/src/app/globals.css`: `--text-caption` (12px), `--text-meta` (13px), `--text-body` (14px), `--text-section` (16px), `--text-page` (20px), `--text-stat` (24px) with line heights in `@theme`; `--row-height` 40px, overridden to 32px under `.compact`.
- [ ] `web/src/components/ui/table.tsx`: rows use the row-height token; headers `text-caption`, sentence case; cells `text-meta`.
- [ ] `PageHeader` title `text-page`; section titles `text-section`.
- [ ] Compact-mode toggle: `web/src/components/shell/density-toggle.tsx` (icon button with `aria-label`, `aria-pressed`), state in `localStorage`, class on `<html>` set before paint (same pattern as the theme provider). Placed in the top bar.

## 2. Locale and display components
- [ ] `web/src/lib/locale.ts`: `displayLocale()` → `{ locale, timeZone }` from `Intl.DateTimeFormat().resolvedOptions()`; `useDisplayLocale()` hook.
- [ ] Formatters in `@/runs/summaries` and `@/runs/cost` take the locale/time zone (no `en-US`, no bare `toLocale*`); 24-hour where the locale is (`hourCycle` from the locale).
- [ ] `web/src/components/display/`: `relative-time.tsx` (`<time dateTime>`, relative text, `formatAbsolute` tooltip, ticks via `use-now`), `duration.tsx`, `money.tsx` (cost + caveat/usage tooltip, "—" / "≥ $x" for unpriced), `token-count.tsx` (compact, exact + `usageDetails` tooltip), `id-chip.tsx` (mono id8, full id tooltip, click to copy with toast, a real `<button>` with `aria-label`), `stat-tile.tsx` (label, value in `text-stat`, one secondary line), `index.ts`. All `tabular-nums`.
- [ ] Vitest for each component (`*.test.tsx`) and the updated formatters.

## 3. Migrate every page
- [ ] Runs list and cards (`runs-list.tsx`): started → `RelativeTime`, duration → `Duration`, cost → `Money`, id → `IdChip`.
- [ ] Run console: `run-header.tsx`, `step-view.tsx`, `tool-calls.tsx`, `raw-events.tsx` (drop `toLocaleTimeString`), graph node sheet, approval dock.
- [ ] Audit (`audit-list.tsx`, `actions.ts` money via the shared formatter), Settings (`claude-connection.tsx`, `model-pricing.tsx`), Templates.
- [ ] Full width: remove `mx-auto max-w-*` from `runs-view.tsx`, `app/runs/[id]/page.tsx`, `templates-view.tsx`, `app/settings/page.tsx`, `audit-view.tsx` and the dock's inner wrapper; one `max-w-[1600px]` content cap in the shell; `max-w-[72ch]` on description and Markdown text.
- [ ] Update affected unit tests and e2e selectors; refresh layout screenshot baselines.

## 4. Lint rule
- [ ] `web/eslint/no-raw-colors.mjs`: flags palette classes (`(bg|text|border|ring|fill|stroke|from|to|via|outline|decoration|shadow|divide|placeholder|caret|accent)-(slate|gray|zinc|neutral|stone|red|…|rose)-\d+`, `-(black|white)` excluded only where tokens cover it), arbitrary colour values (`-[#…]`, `-[rgb(`, `-[oklch(`, `-[hsl(`) and hex/`rgb(`/`oklch(`/`hsl(` in string literals. Ignores `globals.css` (not linted) and `src/api/schema.d.ts`.
- [ ] Register it in `web/eslint.config.mjs` for `src/**/*.{ts,tsx}`.
- [ ] `web/eslint/no-raw-colors.test.mjs` with ESLint `RuleTester` (run by Vitest): rejects `bg-red-100`, `text-indigo-600`, `bg-[#4f46e5]`, `"#4f46e5"`, `text-[oklch(0.5_0.1_20)]`; accepts `bg-background`, `text-status-failed`, `bg-status-waiting-muted`.
- [ ] Fix any violations it finds; `pnpm lint` green.

## 5. Specs and docs
- [ ] `specs/tech-stack.md`: move Foundations (11.1) from "UI v2" into Look / Layout / a new "Display components" list; note locale comes from the browser until a workspace setting exists; decisions-log rows (accent indigo, browser locale, local lint rule).
- [ ] `CLAUDE.md` rule 3: table names the components (`RelativeTime`, `Duration`, `Money`, `TokenCount`, `IdChip`, `StatTile`); rule 1 mentions the lint rule; drop the "From phase 11.1" sentence.
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
