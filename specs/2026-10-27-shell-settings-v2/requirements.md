# Shell and settings v2

Roadmap phase: 11.7
Branch: plan/11.7-shell-settings-v2

## Context
The shell (2.2) puts the theme and density toggles in the top bar, there is no quick way to reach a run except through the runs list, and `/settings` is one long page: two connection cards, a pricing table that scrolls sideways (five price columns, two of them "Cache write (5 min)" and "Cache write (1 h)") and a limits form whose Save button sits at the bottom. The review behind Milestone 11 called this "settings is one long page". tech-stack → UI v2 → "Shell and settings (11.7)" fixes its shape. The phase serves mission principle 8: an enterprise-grade, calm UI where what the user needs is one step away.

It builds on 11.1 (display components, full content width, type scale), 11.4 (`useWorkspaceId`, the E2E workspace) and 11.5 (the Inbox review that the palette's Approve action opens), all done. It unblocks 11.8 only in that the shell stops changing under it. Milestone 5's canvas will add palette actions later.

There are no users yet, so the "user menu" holds the per-browser preferences (theme, density) and the workspace name, not an account.

## Scope
### In scope
- **API: run search.** `GET /runs` takes an optional `q` that matches a run whose id starts with `q` (hex and dashes, at least 4 characters), whose `pr_url` ends in `/pull/<n>` for `q` = `n` or `#n`, or whose workflow name (`spec->>'name'`) contains `q` (case-insensitive). It combines with the other filters and keeps the newest-first cursor paging. No migration: the columns exist.
- **User menu.** A "Preferences" button at the bottom of the sidebar (icon only on the rail, full in the drawer) opens a menu with Theme (Light, Dark, System) and Density (Comfortable, Compact); the workspace name stays at the top of the sidebar. `ThemeMenu` and `DensityToggle` leave the top bar; the top bar keeps breadcrumbs and gains a "Search… ⌘K" button that opens the palette (an icon button below `md`).
- **Command palette** on `⌘K` / `Ctrl+K` (`CommandDialog` on `cmdk`, already in `components/ui/command.tsx`):
  - *Runs*: typing searches `GET /runs?q=` (debounced, 5 results): each row is the run's `StatusBadge`, workflow, `IdChip`-style short id (not focusable), `repoLabel` and PR number. Enter opens `/runs/{id}`. A full UUID that is not in the results still offers "Open run" (the console shows its own not-found state).
  - *Actions*: New run (opens the "New run" sheet from the Runs page), Toggle theme (light ↔ dark), and **Approve** for each waiting run among the results or, with no query, the oldest waiting gate, which opens `/inbox?run=<id>` (the decision itself stays in the Inbox review, so it still confirms what approving does).
  - *Go to*: the sidebar's sections (`NAV_ITEMS`) and the three settings sub-pages.
  - Loading, empty ("Nothing matches “…”.") and error rows inside the list. The shortcut works from any field (it has a modifier, so it never types) except inside the diff editor, whose own shortcuts start with `Ctrl+K`.
- **Settings sub-pages** under a `settings/layout.tsx`: `PageHeader` ("Settings"), then a secondary nav (a vertical list from `md`, horizontal tabs-styled links below) and the sub-page:
  - `/settings/integrations`: Claude and GitHub connection cards (unchanged cards).
  - `/settings/models`: "Models and pricing", the pricing card.
  - `/settings/limits`: "Limits and budgets", the limits card.
  - `/settings` redirects to `/settings/integrations`, keeping its query, so the GitHub install return (`?github=connected`) and old links still land. The API's default `return_to` becomes `/settings/integrations`. Breadcrumbs read "Settings › Integrations".
- **Pricing table fits its card:** columns Model, Input, Output, Cache write, Cache read, actions. The "Cache write" cell stacks its two prices, each with its window ("5 min", "1 h") as a muted label. No `overflow-x-auto` needed at 1024 px and up; below `md` each model is a card (tables from `md`, CLAUDE.md rule 10).
- **Limits form:** each field shows its unit as an input addon (agents, rounds, levels, hours, USD) and "Platform limit: N" in its help text. The Save button at the bottom goes; a sticky Save / Discard bar at the bottom of the content area appears only when the form is dirty (`formState.isDirty`), with "Unsaved changes". Discard resets to the saved values. "Reset to platform limits" stays as the card's own action with its confirm dialog.
- **Specs, in the same PR.** tech-stack moves "Shell and settings (11.7)" from UI v2 into the main rules (Layout → App shell, Start and settings, Theme line in Look), adds `q` to the run history contract, and a decisions log row for the palette's run search; `CLAUDE.md` if a rule changes; a `CHANGELOG.md` entry.

### Out of scope
- Approving a gate from inside the palette without its review (the review shows what approving does; it stays in the Inbox).
- Searching templates, audit entries or settings fields from the palette.
- User accounts, sign-out or profile in the user menu: they come with users and sign-in.
- A workspace switcher in the menu (one workspace per browser today, picked by cookie).
- Full-text search on run input or agent output.
- Workspace locale and time-zone settings (tech-stack Display values: "a workspace setting will pin it later").

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| How the palette finds a run | A `q` filter on `GET /runs` (id prefix, PR number, workflow name), not a client-side match over loaded runs | A short id or a PR number of a run older than the first page must still be found. One filter on the existing list keeps one list endpoint, its paging and its workspace scoping. |
| Id prefix match | `id::text LIKE 'q%'`, `q` at least 4 hex characters | Short ids are 8 characters (`IdChip`); 4 keeps the match useful without scanning on one character. The run count per workspace is small; an index is added only if it shows up in timings. |
| Approve in the palette | Opens the gate in the Inbox (`/inbox?run=`), it does not approve | Approving pushes and opens a PR (mission principle 3); the Inbox review shows the changes and what approving does first. |
| Settings routes | Nested routes with a shared `layout.tsx`, `/settings` redirects to `/settings/integrations` with its query | Each sub-page has its own URL, breadcrumb and back-button entry; old links and the GitHub install return keep working. |
| User menu contents | Theme and Density, labelled "Preferences" | They are per-browser preferences; leaving them in the top bar clutters it, and there is no account yet. |
| Unsaved limits | A sticky bar shown only when dirty, with Discard | The Save button is never below the fold of a long form, and a clean form shows no bar to ignore. |

## Open questions
- None
