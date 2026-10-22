# Validation: Design system: tokens, primitives and states

## Done when (from roadmap)
> Every existing screen uses only shared components and tokens (no raw palette colours); axe finds no serious issues

## Automated checks
- [ ] `web/e2e/a11y.spec.ts`: axe (WCAG 2.0/2.1/2.2 A + AA tags) reports **no serious or critical** violations on `/`, `/settings`, a finished run, a run waiting at a gate and an unknown run, each in light and dark (10 checks).
- [ ] Existing Playwright specs (`home.spec.ts`, `monitor.spec.ts`) still pass against the compose stack.
- [ ] Vitest: new `status-badge.test.tsx` and `states.test.tsx` pass, plus Retry tests for the docs card, GitHub settings and the run stream; all existing component tests pass after markup updates, with none deleted.
- [ ] `pnpm lint`, `pnpm format:check`, `pnpm typecheck` green (copied shadcn code included).
- [ ] Python CI jobs unchanged and green (no backend change expected; `openapi.json` diff check clean).

## Manual / demo checks
- [ ] **No raw palette colours**: from the repo root,
      `grep -rnE '\b(bg|text|border|ring|fill|stroke|from|to|via)-(red|green|blue|amber|yellow|gray|zinc|slate|neutral|stone|indigo|emerald|orange|sky)-[0-9]{2,3}\b' web/src --include=*.tsx --include=*.ts | grep -v components/ui`
      prints nothing. Palette values (oklch) appear only in `web/src/app/globals.css`.
- [ ] **Shared components only**: no screen file under `web/src/app`, `web/src/runs`, `web/src/settings` or `web/src/templates` renders a raw `<button>`, `<input>`, `<textarea>` or `<table>`. Reviewer check: `grep -rnE '<(button|input|textarea|table)\b' web/src --include=*.tsx | grep -v components/` prints nothing.
- [ ] `docker compose up`, open `http://localhost:3000` with the OS in light then dark mode: home, settings and a docs run monitor render with tokens, Inter for UI text, JetBrains Mono for ids/JSON; a waiting gate shows an amber `StatusBadge` with icon + label; a failed run shows red with icon + label.
- [ ] Repo list empty, loading and error states are reachable (no GitHub connection / slow API / API stopped) and the error state's Retry refetches.
- [ ] Keyboard only: every action on the three screens is reachable with Tab and shows a visible focus ring.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] Screenshots of the three screens in light and dark attached to the PR
- [ ] tech-stack.md "UI design system" still matches what was built (update it if a token name or primitive changed)
- [ ] Roadmap phase 2.1 marked done by the PR (`complete-phase` / CI check)
