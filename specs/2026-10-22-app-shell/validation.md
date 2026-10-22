# Validation: App shell

## Done when (from roadmap)
> Every page renders in the shell at 375, 768 and 1440 px with no horizontal scroll (Playwright screenshots in CI)

"Every page" means `/runs`, `/templates`, `/settings` and `/runs/[id]` in three states: finished, waiting at a gate, and not found. `/` only redirects.

## Automated checks
- [ ] **Vitest (`pnpm test`):**
  - `nav.test.ts`: active matching (`/runs/abc` highlights Runs).
  - `app-shell.test.tsx`:
    - The active link has `aria-current="page"`.
    - The menu button opens the drawer.
    - Escape closes it and focus returns to the menu button.
    - Navigating closes the drawer.
  - `theme-menu.test.tsx`: Light, Dark and System each call `setTheme`, and the current item is checked.
  - `page-header.test.tsx`: one `h1`, breadcrumbs inside `nav[aria-label="Breadcrumb"]`, and the last crumb has `aria-current` and is not a link.
  - Existing tests still pass after the route moves.
- [ ] **Playwright `layout.spec.ts`** on the `mobile-375`, `tablet-768`, `laptop-1024` and `desktop-1440` projects:
  - For every page above, `scrollWidth <= clientWidth`.
  - Nav is reachable: the sidebar is visible at 1440, the icon rail at 1024, and a menu button that opens the drawer at 768 and 375.
  - A screenshot is saved for each page and project.
- [ ] **Playwright `home.spec.ts`:** `/` redirects to `/runs` with no console errors.
- [ ] **Playwright `a11y.spec.ts`:**
  - Every page above, at 375 and 1440 px, light and dark: axe (WCAG 2.2 AA tags) finds no serious or critical issues.
  - Keyboard: the first Tab focuses "Skip to content". At 375 px the drawer traps focus and Escape returns focus to the menu button.
- [ ] **CI jobs green:**
  - `web`: lint, `format:check`, `typecheck`, unit tests.
  - `api-contract`: unchanged.
  - `smoke`: compose and e2e.
- [ ] The `layout-screenshots` artifact is attached to the CI run.

## Manual / demo checks
- [ ] `docker compose up -d --build`, then open http://localhost:3000.
  - Expected: you land on `/runs`, with the empty state and a link to Templates.
- [ ] In Templates, start the sample run.
  - Expected: you land on `/runs/<id>` inside the shell, with breadcrumbs "Runs › <id>", and the Runs nav item is active.
- [ ] Resize the browser through 1440, 1200, 900 and 375 px.
  - Expected: full sidebar, then icon rail (hovering an icon shows its label), then a menu button that opens the drawer. There is never a horizontal scrollbar, and the event table scrolls in its own box at 375 px.
- [ ] Switch the theme with the top-bar menu: Light, Dark and System.
  - Expected: the page follows the choice, the choice survives a reload, and System follows the OS setting.
- [ ] Connect GitHub from Settings.
  - Expected: the install redirect still lands on `/settings` inside the shell.
- [ ] Open the CI run's `layout-screenshots` artifact and look at each page at each viewport for clipped or overlapping content.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] No raw palette classes in the new shell code. Only semantic tokens are used (2.1 rule).
- [ ] README "UI shell" section and CHANGELOG entry are added.
- [ ] Roadmap 2.2 is marked done by the implementing PR (`complete-phase`).
