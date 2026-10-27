# UI v2 foundations

Roadmap phase: 11.1
Branch: plan/11.1-ui-v2-foundations

## Context
Milestone 11 is "Next up". A review of the Milestone 2 and 3 screens found that values are formatted in many ad hoc ways (`toLocaleString()` with no options in raw events and settings, `en-US` hard-coded in cost and pricing, durations and times formatted by hand in each view), pages sit in centred `max-w-*` columns of different widths, and the colour rule in `CLAUDE.md` is only enforced by review. 11.1 lays the base every later UI v2 phase builds on: tokens for type and density, one component per kind of value, full-width pages, and a lint rule that makes the colour rule mechanical.

It depends on nothing open (Milestones 2 and 3 are done). 11.2 to 11.8 build on it: 11.2 extends `Duration` with waiting time, 11.4 and 11.6 use `StatTile`, `IdChip` and the density tokens.

Drivers: mission principle 8 (calm, enterprise-grade UI; truthful numbers), principle 10 (the specs govern the work); tech-stack → UI design system and → UI v2 → Foundations (11.1) and "How the rules are enforced".

## Scope
### In scope
- **Brand accent:** decided as **indigo** (current tokens unchanged). The open question in tech-stack is closed.
- **Type scale tokens** in `web/src/app/globals.css` (`@theme`): caption 12 px (also table headers), meta 13 px (tables, metadata), body 14 px (body, agent output), section 16 px, page 20 px, stat 24 px; table headers in sentence case.
- **Density tokens:** table row 40 px, compact 32 px. A compact-mode toggle stored per browser (`localStorage`), applied as a class on `<html>`; the `Table` primitive reads the token. The toggle lives in the top bar next to the theme toggle until 11.7 moves both into the user menu.
- **Display components** in `web/src/components/display/`: `RelativeTime`, `Duration`, `Money`, `TokenCount`, `IdChip`, `StatTile`, built on the existing formatters (`@/runs/summaries`, `@/runs/cost`) and `Tooltip`.
- **Locale and time zone:** one `useDisplayLocale()` hook (and a non-hook `displayLocale()` for formatters) returning the browser's locale and time zone from `Intl`. Every date and number formatter takes them from there; no `en-US` or `undefined` locale left in components. Shaped so a workspace setting can feed it later.
- **Migration:** every page (Runs, Run console incl. raw events, graph sheet and dock, Templates, Settings, Audit) shows times, durations, costs, token counts and ids through the new components. `toLocaleString()` / `toLocaleTimeString()` / `toLocaleDateString()` disappear from components.
- **Full width:** pages drop `mx-auto max-w-*` wrappers and use the content width up to 1600 px (one shell-level cap); reading text (descriptions, agent output Markdown) capped at 72 ch.
- **ESLint rule:** a local rule in `web/eslint.config.mjs` that rejects Tailwind palette colour classes (`bg-red-100`, `text-indigo-600`, …), arbitrary colour values (`bg-[#…]`, `text-[oklch(…)]`, `rgb(`) and hex/`rgb()`/`oklch()` literals in `web/src` (excluding `globals.css`).
- **Docs:** `CLAUDE.md` rule 3 names the components instead of the formatters; tech-stack moves the Foundations bullets from "UI v2" into the main design-system rules; decisions log rows; `CHANGELOG.md` entry.

### Out of scope
- A workspace `locale` / `time_zone` setting in the API and settings page (later; noted in tech-stack as the hook's future source).
- Active vs waiting time and the "waited" chip (11.2). `Duration` shows what it is given; no new start-to-end "Duration" places are added (CLAUDE.md rule 4).
- Stat tiles on the console header (11.6); `StatTile` is built and tested here, used there.
- Moving the theme and density toggles into a user menu (11.7).
- Restyling screens beyond the value components, widths and type tokens (11.4–11.8).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Brand accent | Indigo stays | Already tuned for contrast in light and dark; the ink alternative would churn every screenshot baseline for no information-design gain. |
| Locale source | Browser `Intl` via one hook | Delivers consistent, locale-aware formatting now with no API change; one seam means a workspace setting later changes one file. Deviates from tech-stack's "workspace's locale" until then; recorded in the decisions log. |
| Compact mode storage | `localStorage`, per browser | A display preference, not workspace data; no users yet to store it against. |
| Lint rule form | Local ESLint plugin in the repo (`web/eslint/no-raw-colors.mjs`) | No maintained rule covers Tailwind v4 palette classes and arbitrary values exactly; a small regex rule over string literals, template literals and JSX `className` is easy to test. |
| Where components live | `web/src/components/display/` | Shared across features, beside `status-badge` and `states`; formatters stay in `@/runs/*` as the pure layer the components call. |

## Open questions
- None.
