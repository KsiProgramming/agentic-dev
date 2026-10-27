# Design system: tokens, primitives and states

Roadmap phase: 2.1
Branch: plan/2.1-design-system-tokens

## Context
Milestone 1 proved the engine end to end, but the three web screens (home `/`, run monitor `/runs/[id]`, settings `/settings`) are a debug view: `globals.css` is only `@import "tailwindcss"`, and the components use about 60 raw palette classes (`text-gray-500`, `bg-red-100`, `border-amber-300`, …). Every later milestone adds screens, so the design system comes first (mission principle 8, "Enterprise-grade, calm UI"). The rules are already fixed in [tech-stack.md → UI design system](../tech-stack.md#ui-design-system). This phase puts them into code.

Depends on nothing open; Milestone 2 does not depend on 1.12. It unblocks 2.2 (app shell and theme toggle) and every screen after it.

## Scope
### In scope
- **Tokens** in `web/src/app/globals.css` (Tailwind v4 `@theme inline` + CSS variables), light and dark (`.dark`): `--background`, `--foreground`, `--card`, `--muted`, `--muted-foreground`, `--border`, `--input`, `--ring`, `--primary` (indigo), `--primary-foreground`, `--destructive`, `--radius: 0.5rem`, small shadows, and `--status-{running,waiting,succeeded,failed,cancelled,queued}` (+ `-foreground`/`-muted` for badge backgrounds). Neutral base is zinc.
- **Fonts** via `next/font`: Inter (UI, 14 px base; 13 px utility for dense tables) and JetBrains Mono (`font-mono` for ids, paths, JSON). `tabular-nums` utility for numbers.
- **shadcn/ui** init (Tailwind v4 mode, code in `web/src/components/ui`) with only the primitives the current screens need: Button, Card, Badge, Input, Label, Textarea, Alert, Skeleton, Table, Sonner.
- **`next-themes` provider** in the root layout (`attribute="class"`, default `system`). No toggle UI yet.
- **`lucide-react`** icons.
- **Shared components** in `web/src/components/`: `StatusBadge` (icon + label, never colour alone, one per status), `EmptyState` (icon, one sentence, primary action), `LoadingState` (skeleton), `ErrorState` (message + Retry).
- **Migrate the existing screens** (home + docs card + start-run form, run monitor + event table + gate panel, settings + Claude/GitHub connection cards) to tokens and shared components only. Each data view gets its empty, loading and error state.
- **axe checks** in Playwright on the three screens, in light and dark.

### Out of scope
- Sidebar, top bar, theme toggle, breadcrumbs, responsive drawer → **2.2**.
- Multi-viewport Playwright screenshots → **2.2**.
- Dialog, Sheet, DropdownMenu, Tabs, Tooltip, Combobox → added by the phase that first needs them (2.5, 2.6).
- Run console redesign (merged messages, tool-call cards, Markdown) → **2.5**. In 2.1 the monitor keeps its event table, restyled.
- Collapsible JSON viewer and `react-markdown` → **2.5**.
- A lint or CI guard against raw palette classes (not chosen for now; see Open questions).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Foundation + restyle of the three screens | Meets "Done when" without adding components no screen uses yet (mission principle 7). |
| Primitive set | Only what current screens use, plus Sonner | Later phases add primitives as they need them; keeps the PR reviewable. |
| Theme wiring | `next-themes` provider now, toggle in 2.2 | Dark tokens are testable now (axe in dark) by forcing the class, without building top-bar UI early. |
| Token format | shadcn's Tailwind v4 convention (`@theme inline` mapping CSS variables, oklch values) | Matches tech-stack "Tokens" and lets copied shadcn components work unchanged. |
| Status colours | `running` blue, `waiting` amber, `succeeded` green, `failed` red, `cancelled`/`queued` grey, defined as tokens only | Tech-stack "Colour means status only". Palette values live in `globals.css` and nowhere else. |
| Status mapping | One `RunStatus` → `{icon, label, token}` map in `StatusBadge` | One place to change; event/gate code passes a status, not a colour. |
| Work order | Tokens → components → migrate per screen → a11y checks | The app stays working after each group. |
| A11y proof | `@axe-core/playwright` in the existing compose e2e job, light + dark, fail on serious/critical | "Done when" names axe; dark mode has its own contrast risks. |

## Open questions
- Should a CI guard (ESLint rule or grep script) block raw palette classes after 2.1? Not chosen now; for this phase the merge check is a one-off grep (see validation.md). It can be added cheaply in 2.2 if colours drift back in.
