# Plan: Design system: tokens, primitives and states

## 1. Tokens, fonts and theme foundation
- [x] `pnpm add lucide-react next-themes sonner` and `pnpm dlx shadcn@latest init` (Tailwind v4, base colour zinc, CSS variables on, `components.json` aliases to `@/components`, `@/lib`). Commit `components.json` and `web/src/lib/utils.ts` (`cn`).
- [x] `web/src/app/globals.css`: `:root` and `.dark` token sets (neutral zinc, indigo `--primary`/`--ring`, `--radius: 0.5rem`, small shadows), `--status-*` triples for the six statuses, `@theme inline` mapping to Tailwind utilities (`bg-background`, `text-muted-foreground`, `bg-status-failed-muted`, …), `@custom-variant dark`, base layer (body background/foreground, border colour, 14 px base, visible `focus-visible` ring), `prefers-reduced-motion` guard.
- [x] Check every foreground/background token pair (including status label on status muted background) is at least 4.5:1 in light and dark. Note the pairs in a comment above the status tokens.
- [x] `web/src/app/layout.tsx`: Inter and JetBrains Mono via `next/font/google` as `--font-sans`/`--font-mono`; `<html suppressHydrationWarning>`; `ThemeProvider` (`attribute="class"`, `defaultTheme="system"`, `enableSystem`, `disableTransitionOnChange`); `<Toaster />`.
- [x] Existing Vitest and Playwright suites still pass (no screen changed yet).

## 2. Primitives and shared components
- [x] `pnpm dlx shadcn@latest add button card badge input label textarea alert skeleton table sonner native-select` into `web/src/components/ui` (NativeSelect for the docs card repo picker). Prettier/ESLint pass over the copied code.
- [x] `web/src/components/status-badge.tsx`: `RunStatus = "queued" | "running" | "waiting" | "succeeded" | "failed" | "cancelled"`; map to lucide icon (`Clock`, `LoaderCircle` (spinning only under `motion-safe`), `CirclePause`, `CircleCheck`, `CircleX`, `Ban`), label and status tokens; built on `Badge`. Icon `aria-hidden`, label always rendered.
- [x] `web/src/components/states.tsx`: `EmptyState({icon, message, action?})`, `LoadingState({rows?})` (Skeleton), `ErrorState({message, onRetry})` (Alert + Retry Button).
- [x] Vitest: `status-badge.test.tsx` (each status renders its label and icon), `states.test.tsx` (empty action renders, Retry calls `onRetry`).

## 3. Migrate screens (one commit per screen)
- [x] **Home** (`app/page.tsx`, `templates/docs-card.tsx`, `runs/start-run-form.tsx`): Card, Label/Input/Textarea, Button; repo list loading/empty ("No repositories yet" → Connect GitHub)/error states; API errors in `Alert variant="destructive"`; spec textarea `font-mono`.
- [x] **Run monitor** (`app/runs/[id]/page.tsx`, `runs/run-events.tsx`, `runs/gate-panel.tsx`): run status via `StatusBadge` (`runs/status.ts` maps the stream state, and "Needs approval" while a gate waits; `data-status` replaces the old text in `monitor.spec.ts`); event table on `Table` with `text-[13px] tabular-nums` and `font-mono` ids; loading/empty ("Waiting for the first event")/error states; gate panel as a Card using `--status-waiting` tokens, Approve = primary, Reject = `destructive` variant; approval result shown with `toast`.
- [x] **Settings** (`app/settings/page.tsx`, `settings/claude-connection.tsx`, `settings/github-connection.tsx`): connection Cards with connected/missing shown as icon + label; masked key `font-mono`; form errors in Alert; save/remove results as toasts.
- [x] Update the existing Vitest tests to the new markup (query by role/label, not by class). Keep every existing assertion's intent and delete none.
- [x] `grep -rnE '\b(bg|text|border|ring|fill|stroke|from|to|via)-(red|green|blue|amber|yellow|gray|zinc|slate|neutral|stone|indigo|emerald|orange|sky)-[0-9]{2,3}\b' web/src --include=*.tsx --include=*.ts | grep -v components/ui` returns nothing.

## 4. Accessibility checks
- [x] `pnpm add -D @axe-core/playwright`.
- [x] `web/e2e/a11y.spec.ts`: for `/`, `/settings`, a finished run, a run waiting at a gate and an unknown run (runs started through `POST /runs` on the fake runtime, as `monitor.spec.ts` does), run `AxeBuilder` with tags `wcag2a, wcag2aa, wcag21aa, wcag22aa` in light (`colorScheme: "light"`) and dark (`colorScheme: "dark"`; `next-themes` follows system). Fail on any `serious` or `critical` violation and print the rule ids and targets.
- [x] Fix whatever it finds. It found one: the Reject button on the amber gate card in dark mode (contrast), fixed by a lighter dark `--destructive`.
- [x] Runs in the existing compose `e2e` CI job; no workflow change expected beyond the dependency.
