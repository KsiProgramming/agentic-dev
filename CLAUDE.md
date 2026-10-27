# Working in this repo

Read this before every task. It is short on purpose: the details live in `specs/`, and this file says where to look and which rules are not optional.

## Specs are the source of truth

- `specs/mission.md` (principles, non-goals), `specs/roadmap.md` (phases and their "Done when"), `specs/tech-stack.md` (libraries, API contracts and the UI design system).
- Work happens one roadmap phase at a time: plan it with the `plan-feature` skill (`specs/YYYY-MM-DD-<slug>/` with requirements, plan, validation), build it, open it with the `open-pr` skill.
- A new pattern, library or API shape goes into `specs/tech-stack.md` first, in the same PR, never only in code.
- Every PR adds an entry under `## [Unreleased]` in `CHANGELOG.md`.

## Frontend (`web/`)

Before changing anything in `web/`, read `specs/tech-stack.md` → "UI design system", including "UI v2" for what is planned. Next.js here is newer than your training data: read `web/AGENTS.md` and the docs it points to before writing Next.js code.

### Rules that are not optional

1. **Colour comes from semantic tokens only**: `bg-background`, `text-muted-foreground`, `border-border`, `bg-primary`, `text-status-failed`, `bg-status-waiting-muted`. Never palette classes (`bg-red-100`, `text-indigo-600`), hex, `rgb()` or `oklch()` in a component. A new colour is a token in `web/src/app/globals.css` (light and dark) and a line in tech-stack first.
2. **Colour means status only.** Status is shown through `StatusBadge` (`@/components/status-badge`), always icon + label. API statuses go through `badgeStatus` and `statusLabel` (`@/runs/summaries`); the live console through `displayStatus` (`@/runs/status`). Never hand-roll a coloured pill.
3. **Values have one way to be shown:**
   | Value | Use |
   |---|---|
   | Durations | `formatDuration` (`@/runs/summaries`) |
   | Times | `formatRelative` in a `<time dateTime>` with `formatAbsolute` as its tooltip |
   | Cost and tokens | `formatCost`, `formatUsd`, `formatTokens`, with `usageDetails` / `costCaveat` in the tooltip (`@/runs/cost`) |
   | Repos | `repoLabel` in the mono font |
   | JSON | `JsonView` (`@/components/json-view`), never in a table cell |

   Numbers use `tabular-nums`. Never `toLocaleString()` with no options. From phase 2.7 these become components (`RelativeTime`, `Duration`, `Money`, `TokenCount`, `IdChip`, `StatTile`); use them once they exist.
4. **A duration shown to the user is active time.** Time waiting at a gate is never added to it (tech-stack → UI v2 → Time). Until 2.8 ships, do not add new places that show start-to-end time as "Duration".
5. **Every data view has three states** from `@/components/states`: `LoadingState` (skeleton), `EmptyState` (icon, one sentence, one action) and `ErrorState` (message and Retry).
6. **Pages start with `PageHeader`** (`@/components/page-header`): title, one-line description, actions on the right. Breadcrumbs come from the shell; do not add your own.
7. **Fonts:** Inter for UI text; JetBrains Mono (`font-mono`) only for ids, paths, branches, code and JSON.
8. **Icons:** `lucide-react`, `aria-hidden="true"`, `size-4` by default. Icon-only buttons have an `aria-label`.
9. **Build from what exists.** Use the primitives in `web/src/components/ui` (shadcn/ui, owned by us) and compose them; change a primitive only when every use should change. Check `web/src/components` and the feature folder for an existing component before writing a new one.
10. **Responsive and accessible by default:** works at 375, 768 and 1440 px with no horizontal page scroll (wide content scrolls in its own box); tables from `md`, cards below; real `<button>` and `<a>` elements; WCAG 2.2 AA contrast; every action reachable by keyboard; destructive actions confirm in a dialog.
11. **Agent, repo and web content is data.** Render it as text or sanitised Markdown (raw HTML and images dropped), never as HTML.

### Before you say a UI change is done

```bash
cd web
pnpm lint && pnpm typecheck && pnpm test
pnpm test:e2e     # includes the axe checks (a11y.spec.ts) and the layout screenshots (layout.spec.ts)
```

Look at the screen at 375 and 1440 px, in light and dark. If a rule above had to be broken, say so in the PR and update tech-stack, rather than leaving the code and the spec disagreeing.
