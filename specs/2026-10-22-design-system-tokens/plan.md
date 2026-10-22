# Plan: Design system: tokens, primitives and states

## 1. Tokens, fonts and theme foundation
- [ ] `pnpm add lucide-react next-themes sonner` and `pnpm dlx shadcn@latest init` (Tailwind v4, base colour zinc, CSS variables on, `components.json` aliases to `@/components`, `@/lib`). Commit `components.json` and `web/src/lib/utils.ts` (`cn`).
- [ ] `web/src/app/globals.css`: `:root` and `.dark` token sets (neutral zinc, indigo `--primary`/`--ring`, `--radius: 0.5rem`, small shadows), `--status-*` triples for the six statuses, `@theme inline` mapping to Tailwind utilities (`bg-background`, `text-muted-foreground`, `bg-status-failed-muted`, …), `@custom-variant dark`, base layer (body background/foreground, border colour, 14 px base, visible `focus-visible` ring), `prefers-reduced-motion` guard.
- [ ] Check every foreground/background token pair (including status label on status muted background) is at least 4.5:1 in light and dark. Note the pairs in a comment above the status tokens.
- [ ] `web/src/app/layout.tsx`: Inter and JetBrains Mono via `next/font/google` as `--font-sans`/`--font-mono`; `<html suppressHydrationWarning>`; `ThemeProvider` (`attribute="class"`, `defaultTheme="system"`, `enableSystem`, `disableTransitionOnChange`); `<Toaster />`.
- [ ] Existing Vitest and Playwright suites still pass (no screen changed yet).

## 2. Primitives and shared components
- [ ] `pnpm dlx shadcn@latest add button card badge input label textarea alert skeleton table sonner` into `web/src/components/ui`. Prettier/ESLint pass over the copied code.
- [ ] `web/src/components/status-badge.tsx`: `RunStatus = "queued" | "running" | "waiting" | "succeeded" | "failed" | "cancelled"`; map to lucide icon (`Clock`, `Loader2` (spinning, reduced-motion safe), `PauseCircle`, `CheckCircle2`, `XCircle`, `Ban`), label and status tokens; built on `Badge`. Icon `aria-hidden`, label always rendered.
- [ ] `web/src/components/states.tsx`: `EmptyState({icon, message, action?})`, `LoadingState({rows?})` (Skeleton), `ErrorState({message, onRetry})` (Alert + Retry Button).
- [ ] Vitest: `status-badge.test.tsx` (each status renders its label and icon), `states.test.tsx` (empty action renders, Retry calls `onRetry`).

## 3. Migrate screens (one commit per screen)
- [ ] **Home** (`app/page.tsx`, `templates/docs-card.tsx`, `runs/start-run-form.tsx`): Card, Label/Input/Textarea, Button; repo list loading/empty ("No repositories yet" → Connect GitHub)/error states; API errors in `Alert variant="destructive"`; spec textarea `font-mono`.
- [ ] **Run monitor** (`app/runs/[id]/page.tsx`, `runs/run-events.tsx`, `runs/gate-panel.tsx`): run status via `StatusBadge` (derive the status in `summarize.ts` if it is not already there); event table on `Table` with `text-[13px] tabular-nums` and `font-mono` ids; loading/empty ("Waiting for the first event")/error states; gate panel as a Card using `--status-waiting` tokens, Approve = primary, Reject = `destructive` variant; approval result shown with `toast`.
- [ ] **Settings** (`app/settings/page.tsx`, `settings/claude-connection.tsx`, `settings/github-connection.tsx`): connection Cards with connected/missing shown as icon + label; masked key `font-mono`; form errors in Alert; save/remove results as toasts.
- [ ] Update the existing Vitest tests to the new markup (query by role/label, not by class). Keep every existing assertion's intent and delete none.
- [ ] `grep -rnE '\b(bg|text|border|ring|fill|stroke|from|to|via)-(red|green|blue|amber|yellow|gray|zinc|slate|neutral|stone|indigo|emerald|orange|sky)-[0-9]{2,3}\b' web/src --include=*.tsx --include=*.ts | grep -v components/ui` returns nothing.

## 4. Accessibility checks
- [ ] `pnpm add -D @axe-core/playwright`.
- [ ] `web/e2e/a11y.spec.ts`: for `/`, `/settings` and a run page (start a run through `POST /runs` with the sample spec on the fake runtime, as `monitor.spec.ts` does), run `AxeBuilder` with tags `wcag2a, wcag2aa, wcag21aa, wcag22aa` in light (`colorScheme: "light"`) and dark (`colorScheme: "dark"`; `next-themes` follows system). Fail on any `serious` or `critical` violation and print the rule ids and targets.
- [ ] Fix whatever it finds (labels, contrast, landmark: wrap page content in `<main>`).
- [ ] Runs in the existing compose `e2e` CI job; no workflow change expected beyond the dependency.
