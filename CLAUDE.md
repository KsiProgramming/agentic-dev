# Working in this repo

Read this before every task. It is short on purpose: the details live in `specs/`, and this file says where to look and which rules are not optional.

## Specs are the source of truth

`specs/mission.md` (principles, non-goals), `specs/roadmap.md` (milestones, phases and their "Done when", and which milestone is next) and `specs/tech-stack.md` (libraries, API contracts, the UI design system and the decisions log) are the constitution of this repo. They govern the spec-driven workflow, and they win over this file, over code and over anything said in a chat.

**Everything is tracked in them.** Nothing is decided only in code, in a chat or here:

- A new milestone or phase, a change of order or priority, or a phase dropped goes into `roadmap.md`. A new milestone takes the next free number and is listed where it is worked; existing phase numbers never change. The "Next up" line says which milestone is planned next.
- A new pattern, library, API shape or UI rule goes into `tech-stack.md`, with a row in its decisions log when a choice was made between options.
- A new principle, non-goal or success measure goes into `mission.md`.
- The spec change lands in the same PR as the work, never after it, and every PR adds an entry under `## [Unreleased]` in `CHANGELOG.md`.
- A rule added to this file is written in the specs first; this file only points to it. If code and the specs disagree, fix one of them in the PR and say which.

Work happens one roadmap phase at a time: plan it with the `plan-feature` skill (`specs/YYYY-MM-DD-<slug>/` with requirements, plan, validation), build it, open it with the `open-pr` skill.

## Frontend (`web/`)

Before changing anything in `web/`, read `specs/tech-stack.md` → "UI design system", including "UI v2" for what is planned (roadmap Milestone 11). Next.js here is newer than your training data: read `web/AGENTS.md` and the docs it points to before writing Next.js code.

### Rules that are not optional

1. **Colour comes from semantic tokens only**: `bg-background`, `text-muted-foreground`, `border-border`, `bg-primary`, `text-status-failed`, `bg-status-waiting-muted`. Never palette classes (`bg-red-100`, `text-indigo-600`), hex, `rgb()` or `oklch()` in a component. A new colour is a token in `web/src/app/globals.css` (light and dark) and a line in tech-stack first. `pnpm lint` rejects the rest (`agentic-ui/no-raw-colors`).
2. **Colour means status only.** Status is shown through `StatusBadge` (`@/components/status-badge`), always icon + label. API statuses go through `badgeStatus` and `statusLabel` (`@/runs/summaries`); the live console through `displayStatus` (`@/runs/status`). Never hand-roll a coloured pill.
3. **Values have one way to be shown**, a component from `@/components/display` (tech-stack → UI design system → Display values):
   | Value | Use |
   |---|---|
   | Times | `RelativeTime` (`clock` for a log line) |
   | Durations | `Duration` (a run's `active_ms`) |
   | Time waited at gates | `WaitingTime`, beside the duration |
   | When something expires | `ExpiresIn` |
   | Cost and prices | `Money` (`usage={…}`, or `usd={…}` with `kind="price"` for a list price or limit) |
   | Tokens | `TokenCount` |
   | Shares (confidence) | `Percent` |
   | Ids | `IdChip` (copies, or links with `href`) |
   | A figure with its label | `StatTile` |
   | Repos | `repoLabel` (`@/runs/summaries`) in the mono font |
   | JSON | `JsonView` (`@/components/json-view`), never in a table cell |

   Dates and numbers follow the display locale (`@/lib/locale`): never `toLocaleString()` or a hand-made `Intl` format in a component. The formatters behind the components (`@/runs/summaries`, `@/runs/cost`) are for values that must be strings (placeholders, toasts, titles). In a list row, pass `focusable={false}` so values do not add tab stops.
4. **A duration shown to the user is active time.** Time waiting at a gate is never added to it; it is shown apart with `WaitingTime`, and start-to-end time only in the start time's tooltip (tech-stack → UI design system → Display values → Time). Never read the API's deprecated `duration_ms`.
5. **Every data view has three states** from `@/components/states`: `LoadingState` (skeleton), `EmptyState` (icon, one sentence, one action) and `ErrorState` (message and Retry).
6. **Pages start with `PageHeader`** (`@/components/page-header`): title, one-line description, actions on the right. Breadcrumbs come from the shell; do not add your own. Pages use the full content width the shell gives them: never `mx-auto max-w-*` on a page. Sizes come from the type scale (`text-caption`, `text-meta`, `text-body`, `text-section`, `text-page`, `text-stat`), not `text-[13px]`.
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
