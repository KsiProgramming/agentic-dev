# App shell

Roadmap phase: 2.2
Branch: plan/2.2-app-shell

## Context
2.1 gave us tokens, shadcn/ui primitives and shared status, empty, loading and error states. The three pages (`/`, `/runs/[id]`, `/settings`) still sit alone, each with a hand-made back link, and there is no theme switch in the UI. Every later Milestone 2 phase adds a page or a region of one: the runs list (2.4), run console v2 (2.5), approval dock (2.6) and start screen (2.8). They all need one shell to live in, so the shell comes first.

This phase does not depend on 1.12, which is still unplanned. It was skipped on purpose to start Milestone 2.

Principles and choices that apply:
- **Mission 8, Enterprise-grade, calm UI:** one layout from a phone to a wide monitor, with no horizontal scroll.
- **Tech stack → UI design system → Layout:** a sidebar with Runs, Templates and Settings. The sidebar collapses to icons from 1024 to 1279 px and becomes a drawer below 1024 px. The page header has a title, a description and actions, and the actions stack below the title on mobile. Breakpoints are 375, 768, 1024 and 1440 px.
- **Tech stack → Theme:** light, dark and system, switched from the top bar (`next-themes`, already installed).
- **Tech stack → Interaction and accessibility:** WCAG 2.2 AA, visible focus, every action reachable by keyboard, motion of 150–200 ms that respects `prefers-reduced-motion`.
- **Tech stack → Testing:** Playwright screenshots at 375, 768 and 1440 px, and `@axe-core/playwright`.

## Scope
### In scope
- **New shadcn/ui primitives** in `web/src/components/ui`: `sheet` (the drawer), `dropdown-menu` (the theme menu) and `tooltip` (labels for the icon-rail items).
- **`AppShell`** (`web/src/components/shell/`), rendered by the root layout around every page:
  - **Sidebar:**
    - Product name at the top, with the current workspace name under it (read only, from `GET /workspaces`).
    - Nav items Runs (`/runs`), Templates (`/templates`) and Settings (`/settings`), with lucide icons. The active item is highlighted and has `aria-current="page"`.
    - Width by viewport: full at ≥ 1280 px, an icon rail with tooltips at 1024–1279 px, and hidden below 1024 px.
  - **Top bar:**
    - Breadcrumbs.
    - Theme menu (Light, Dark, System) with the current choice checked.
    - A menu button below 1024 px that opens the sidebar as a left `Sheet`. The sheet closes on navigation and on Escape, and focus returns to the menu button.
  - **Content area:** max width with a 16 px gutter on mobile. Wide content scrolls inside its own box, never the page.
  - A "Skip to content" link as the first focusable element.
- **`PageHeader`:** title (`h1`), optional description, breadcrumbs and an actions slot. The actions sit on the right at ≥ 768 px and stack under the title below that.
- **Route moves:**
  - Today's home content (Generate docs card and sample-run form) moves to `/templates`.
  - `/runs` is a placeholder with the shared empty state ("Run history is coming soon", plus a primary action to `/templates`). 2.4 replaces it.
  - `/` redirects to `/runs`, the future home (roadmap 2.4: "Runs page (new home)").
  - `/runs/[id]` and `/settings` render inside the shell with a `PageHeader`. Their hand-made back links are removed.
  - The GitHub install redirect to `/settings` is unchanged.
- **Page title** per route through Next.js `metadata`, using the template `"%s · Agentic Dev"`.
- Docs: a README note on the shell, page layout rules for new pages, and a CHANGELOG entry.

### Out of scope
- **A real workspace switcher.** Only one workspace exists, so the name is shown read only. A dropdown comes when multiple workspaces exist (later; not a roadmap phase yet).
- **User menu, avatar and auth:** no auth exists yet.
- **Runs list content and the `GET /runs` API:** 2.3 and 2.4.
- **Run console layout changes** (timeline, tabs): 2.5. In this phase the monitor only moves into the shell.
- **Approval dock and the "● Needs approval" title prefix:** 2.6.
- **Start screen redesign** (template gallery, "New run" sheet): 2.8. In this phase `/templates` hosts today's content unchanged.
- **Pixel-diff visual regression baselines:** not chosen. Screenshots are uploaded for review only (see Decisions).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Shell and route moves | User choice. Nav items must point at real routes, so the content moves now instead of shipping links that do nothing. |
| Where the home content goes | `/templates` | It is template-launching content, and 2.8 redesigns it in place. |
| What `/` does | Redirects to `/runs` | The roadmap makes Runs the home (2.4). Redirecting now means no link changes later. |
| `/runs` before 2.4 | Empty state with a link to Templates | Mission 8: every view has a defined empty state. A temporary empty list is honest. |
| Workspace in the top-left | Name only, from `GET /workspaces` | There is one workspace today. A switcher would be UI with no behaviour. |
| Drawer component | shadcn `Sheet` (Radix Dialog) | It is in the tech-stack UI kit and gives focus trap, Escape and focus return for free. |
| Collapsed-rail breakpoint | Icon rail at 1024–1279 px with tooltips | The tech-stack layout rule. Tested at 1024 px in addition to the three required viewports. |
| Theme control | Dropdown with Light, Dark and System | The tech stack says "light, dark and system". A two-state toggle cannot select System. |
| Order of work | Primitives, then shell, then pages, then tests in CI | User choice. The app keeps working after each group. |
| Screenshot checks | Upload as a CI artifact; assert no overflow in code | User choice. Pixel baselines are flaky across fonts and OS. The overflow assertion is the real "Done when" check. |

## Open questions
- **Shell layout for e2e in CI:** the smoke job runs Playwright against compose. Adding three viewport projects roughly triples the e2e time. If the job gets too slow, run only the layout and axe specs at every viewport and the rest at desktop only.
