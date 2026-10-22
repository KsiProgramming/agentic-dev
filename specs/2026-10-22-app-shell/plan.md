# Plan: App shell

Order: primitives, then shell, then pages, then tests in CI (user choice). The app builds and all current tests pass after each group.

## 1. Primitives and theme menu
- [ ] `pnpm dlx shadcn add sheet dropdown-menu tooltip` into `web/src/components/ui/`. Check that the copied code uses only semantic tokens (2.1 rule).
- [ ] `web/src/components/shell/theme-menu.tsx`: a `DropdownMenu` with Light, Dark and System (`useTheme` from `next-themes`). The trigger icon follows the resolved theme and has the accessible name "Theme".
- [ ] Vitest test: `theme-menu.test.tsx` (choosing an item calls `setTheme`, and the current item is checked).

## 2. App shell
- [ ] `web/src/components/shell/nav.ts`: the nav items (`href`, label, lucide icon), Runs, Templates and Settings. `isActive(pathname, href)` matches prefixes, so `/runs/123` highlights Runs.
- [ ] `sidebar.tsx`:
  - Brand and the workspace name. The name comes from `GET /workspaces` through the generated `client`, the same way the settings components fetch today. It shows a skeleton while loading and hides the name if the call fails. TanStack Query is not introduced here; 2.4 adds it with the runs list.
  - Nav links with `aria-current`.
  - A `collapsed` variant (icon rail with a `Tooltip` on each link).
- [ ] `top-bar.tsx`: the menu button (only below `lg`), a breadcrumbs slot and `ThemeMenu`.
- [ ] `mobile-nav.tsx`: a left `Sheet` with the full sidebar. It closes on route change (`usePathname` effect).
- [ ] `app-shell.tsx`:
  - CSS grid layout: full sidebar at `xl` (≥ 1280), rail at `lg` (1024–1279), none below.
  - A "Skip to content" link and `<main id="content">` with `min-w-0`, so wide children scroll in their own box.
- [ ] Wire `AppShell` into `web/src/app/layout.tsx` inside `ThemeProvider`.
- [ ] Vitest tests:
  - `nav.test.ts`: active matching.
  - `app-shell.test.tsx`: the active link has `aria-current`, the menu button opens the drawer, Escape closes it, and focus returns to the button.

## 3. Page header and breadcrumbs
- [ ] `web/src/components/page-header.tsx`:
  - Props: `title`, `description?`, `breadcrumbs?: {label, href?}[]` and `actions?`.
  - Actions on the right at `md`, stacked below that.
  - The breadcrumbs render in the top bar (through a small context or slot) with `nav[aria-label="Breadcrumb"]`, and the last item has `aria-current="page"`.
- [ ] Vitest test: `page-header.test.tsx` (heading level, breadcrumb links, the last crumb is not a link).

## 4. Route moves and page migration
- [ ] `web/src/app/templates/page.tsx`: move today's `/` content (Generate docs card and start-run form) here, with `PageHeader` "Templates".
- [ ] `web/src/app/runs/page.tsx`: `PageHeader` "Runs" and the shared `EmptyState` ("Run history is coming soon", with an action to `/templates`).
- [ ] `web/src/app/page.tsx`: `redirect("/runs")`.
- [ ] `/runs/[id]`:
  - `PageHeader` with breadcrumbs Runs › `<short run id>` (mono font). Remove the hand-made back link.
  - Make sure the event table scrolls inside its own box at 375 px.
- [ ] `/settings`: `PageHeader` "Settings" and remove the back link.
- [ ] Per-route `metadata.title` and a layout title template `"%s · Agentic Dev"`.
- [ ] Move `web/src/app/page.test.tsx` to the templates page and update any test that targets `/`.

## 5. E2E: viewports, overflow, screenshots, axe
- [ ] `web/playwright.config.ts`:
  - Add the projects `mobile-375`, `tablet-768`, `laptop-1024` and `desktop-1440`. The existing specs keep running on the desktop project.
  - Layout and a11y specs run on all of them (`grep`/`testMatch` per project).
- [ ] `web/e2e/layout.spec.ts`, for each page (`/runs`, `/templates`, `/settings`, a finished run, a run waiting at a gate, an unknown run):
  - Assert `document.documentElement.scrollWidth <= clientWidth`.
  - Assert the nav is reachable: a visible sidebar at ≥ 1024, or the menu button opens the drawer below that.
  - Save a full-page screenshot to `test-results/screenshots/<project>/<page>.png`.
- [ ] `/` redirects to `/runs` (`home.spec.ts` updated).
- [ ] `web/e2e/a11y.spec.ts`:
  - Cover `/runs` and `/templates`, and run on the mobile and desktop projects in both themes.
  - Add a keyboard test: Tab reaches "Skip to content", then the nav, and the drawer traps focus at 375 px.
- [ ] `.github/workflows/ci.yml` smoke job: always upload `web/test-results/screenshots` as the `layout-screenshots` artifact, and keep the report upload on failure.

## 6. Docs
- [ ] README: a short "UI shell" section covering where pages go, how to use `PageHeader`, and how to run the layout e2e locally.
- [ ] `specs/tech-stack.md`: note that the theme control is a three-way menu, if the wording needs it.
- [ ] CHANGELOG entry for 2.2.
