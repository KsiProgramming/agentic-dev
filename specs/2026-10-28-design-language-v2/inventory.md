# Inventory: Design language v2

The evidence behind [requirements.md](requirements.md). Paths are relative to `web/src/` unless they start with `packages/` or `specs/`. Line numbers are as of `fbecbde`. Contrast is the WCAG ratio, computed from the oklch values in `app/globals.css` (now) and the hex values in `specs/design-language.md` (after). "Uses" counts class occurrences in non-test `.ts`/`.tsx` files.

## 1. Tokens: light (`app/globals.css:86-121`)

| Token | Now | Target | Contrast now → after | Uses |
|---|---|---|---|---|
| `--background` | `oklch(1 0 0)` | unchanged `#ffffff` | — | 15 |
| `--foreground` | `oklch(0.141 0.005 285.823)` `#09090b` (:90) | `oklch(0.210 0.006 285.9)` `#18181b` | on background 19.9 → 17.7; on muted 18.1 → 16.1 | 52 |
| `--muted-foreground` | `oklch(0.5 0.016 285.9)` `#62626c` (:100) | `oklch(0.442 0.015 285.8)` `#52525b` | on background 6.0 → 7.7; on muted 5.5 → 7.0; on surface-subtle — → 7.4; on surface-sunken — → 7.2 | 167 |
| `--muted` | `oklch(0.967 0.001 286.375)` `#f4f4f5` (:99) | unchanged | — | 50 (`bg-muted` 15, `bg-muted/30-50` 12, `hover:bg-muted*` 23) |
| `--primary` | indigo `oklch(0.511 0.262 276.966)` `#4f39f6` (:95) | ink `oklch(0.210 0.006 285.9)` `#18181b` | as text on background 6.4 → 17.7 | 34 (`bg-primary` 6, `text-primary` 12, `border-primary` 6, others 10) |
| `--primary-foreground` | `oklch(0.985 0 0)` (:96) | `#ffffff` `oklch(1 0 0)` | on primary 6.2 → 17.7 | 5 |
| `--ring` | indigo `oklch(0.585 0.233 277.117)` `#615fff` (:106) | `#18181b` | against background 4.6 → 17.7 | 39 |
| `--border` | `oklch(0.92 0.004 286.32)` `#e4e4e7` (:104) | unchanged | — | 7 explicit (every `border` via `globals.css:170`) |
| `--input` | `oklch(0.871 0.006 286.286)` `#d4d4d8` (:105) | `var(--border-strong)` | against background 1.48 → 1.48 (unchanged; not a text colour) | 23 |
| `--card`, `--popover` | `oklch(1 0 0)` (:91, :93) | unchanged (white) | — | 13 / 12 |
| `--secondary`, `--accent` | `oklch(0.967 0.001 286.375)` (:97, :101) | `var(--muted)` | — | 7 / 16 |
| `--destructive` | `oklch(0.505 0.213 27.518)` `#c10007` (:103) | `var(--status-failed)` `#b91c1c` | on background 6.4 → 6.5 | 56 |
| `--status-running` / `-muted` | `#1447e6` / `#eff6ff` (:113-114) | `#1d4ed8` `oklch(0.488 0.217 264.4)` / `#eff6ff` | text on fill 6.3 → 6.2; on background 6.8 → 6.7 | 8 |
| `--status-succeeded` / `-muted` | `#016630` / `#f0fdf4` (:118-119) | `#15803d` `oklch(0.527 0.137 150.1)` / `#f0fdf4` | text on fill **6.8 → 4.8**; on background 7.1 → 5.0 (open question 1) | 10 |
| `--status-waiting` / `-muted` | `#973c00` / `#fffbeb` (:116-117) | `#b45309` `oklch(0.555 0.146 49.0)` / `#fffbeb` | text on fill **6.9 → 4.8**; on background 7.1 → 5.0 (open question 1) | 14 |
| `--status-failed` / `-muted` | `#c10007` / `#fef2f2` (:120-121) | `#b91c1c` `oklch(0.505 0.190 27.5)` / `#fef2f2` | text on fill 5.9 → 5.9; on background 6.4 → 6.5 | 11 |
| `--status-queued`, `--status-cancelled` / `-muted` | `#52525c` / `#f4f4f5` (:111-112, :122-123) | `#52525b` / `#f4f4f5` | text on fill 7.0 → 7.0 | 6 / 3 |

## 2. Tokens: dark (`app/globals.css:131-161`)

| Token | Now | Target | Contrast now → after |
|---|---|---|---|
| `--background` | `#09090b` (:132) | `#09090b` `oklch(0.141 0.004 285.8)` | — |
| `--card`, `--popover` | `#18181b` `oklch(0.21 …)` (:134, :136) | `#111113` `oklch(0.179 0.004 286.0)` | foreground on card 17.0 → 18.1 |
| `--foreground` | `#fafafa` (:133) | unchanged | on background 19.1 → 19.1 |
| `--muted` | `#27272a` (:142) | `#1c1c1f` `oklch(0.228 0.006 285.9)` | muted-foreground on muted 5.7 → 6.6 |
| `--muted-foreground` | `#9f9fa9` (:143) | `#a1a1aa` `oklch(0.712 0.013 286.1)` | on background 7.6 → 7.8; on card 6.7 → 7.4 |
| `--primary` / `-foreground` | indigo `#7c86ff` / `#09090b` (:139-140) | `#fafafa` / `#09090b` | fg on primary 6.4 → 19.1 |
| `--ring` | indigo (:150) | `#fafafa` | — |
| `--border` | `oklch(1 0 0 / 10%)` ≈ `#222224` (:148) | `#27272a` `oklch(0.274 0.005 286.0)` | — |
| `--input` | `oklch(1 0 0 / 15%)` (:149) | `var(--border-strong)` `#3f3f46` | against background 1.47 → 1.91 |
| `--status-running` / `-muted` | `#8ec5ff` / `#162456` | `#93c5fd` / `#172554` | 8.1 → 8.1 |
| `--status-succeeded` / `-muted` | `#7bf1a8` / `#032e15` | `#86efac` / `#052e16` | 10.7 → 10.6 |
| `--status-waiting` / `-muted` | `#ffd230` / `#461901` | `#fcd34d` / `#2a1a05` | 10.4 → 11.7 |
| `--status-failed` / `-muted` | `#ffa2a2` / `#460809` | `#fca5a5` / `#2a0a0a` | 8.4 → 9.7 |
| `--status-queued`, `--status-cancelled` / `-muted` | `#d4d4d8` / `#27272a` | `#d4d4d8` / `#1c1c1f` | 10.1 → 11.5 |

## 3. New tokens

Add each to `:root` and `.dark`, and its `--color-*` line to `@theme inline` (`globals.css:38-69`), so the class in the last column works.

| Token | Light | Dark | `@theme` name → class | Contrast (light / dark) |
|---|---|---|---|---|
| `--foreground-secondary` | `#3f3f46` `oklch(0.370 0.012 285.8)` | `#d4d4d8` `oklch(0.871 0.005 286.3)` | `--color-foreground-secondary` → `text-foreground-secondary` | background 10.4 / 13.5; muted 9.5 / 11.5; surface-subtle 10.0 / 12.4 |
| `--placeholder` | `#6e6e77` `oklch(0.541 0.014 285.9)` | `#8b8b93` `oklch(0.639 0.012 286.1)` | `--color-placeholder` → `text-placeholder`, `placeholder:text-placeholder` | background 5.1 / 5.9; muted 4.6 / 5.0 |
| `--surface-sunken` | `#f7f7f8` `oklch(0.976 0.001 286.4)` | `#0f0f11` `oklch(0.169 0.004 286)` | `--color-surface-sunken` → `bg-surface-sunken` | — |
| `--surface-subtle` | `#fafafa` `oklch(0.985 0 0)` | `#141416` `oklch(0.192 0.004 286)` | `--color-surface-subtle` → `bg-surface-subtle` | — |
| `--border-strong` | `#d4d4d8` `oklch(0.871 0.005 286.3)` | `#3f3f46` `oklch(0.370 0.012 285.8)` | `--color-border-strong` → `border-border-strong` | — |
| `--divider` | `#f0f0f2` `oklch(0.956 0.003 286.3)` | `#1c1c1f` `oklch(0.228 0.006 285.9)` | `--color-divider` → `border-divider`, `divide-divider` | — |
| `--status-running-border` | `#bfdbfe` `oklch(0.882 0.057 254.1)` | `#1e3a8a` `oklch(0.379 0.138 265.5)` | `--color-status-running-border` → `border-status-running-border` | — |
| `--status-succeeded-border` | `#bbf7d0` `oklch(0.925 0.081 156.0)` | `#14532d` `oklch(0.393 0.090 152.5)` | `--color-status-succeeded-border` | — |
| `--status-waiting-border` | `#fde68a` `oklch(0.924 0.115 95.7)` | `#78350f` `oklch(0.414 0.105 45.9)` | `--color-status-waiting-border` | — |
| `--status-failed-border` | `#fecaca` `oklch(0.885 0.059 18.3)` | `#7f1d1d` `oklch(0.396 0.133 25.7)` | `--color-status-failed-border` | — |
| `--status-queued-border`, `--status-cancelled-border` | `#e4e4e7` `oklch(0.920 0.004 286.3)` | `#3f3f46` | `--color-status-queued-border`, `--color-status-cancelled-border` | — |
| `--text-kbd` (+ `--line-height` 1rem) | `0.6875rem` (11 px) | same | `@theme` → `text-kbd` | — |
| `--spacing-row-header` | `2.25rem` (36 px) | same | `@theme` → `h-row-header` | — |
| `--container-sheet-sm` / `-md` / `-lg` | 480 / 560 / 720 px | same | `@theme` → `max-w-sheet-sm`, `-md`, `-lg` | — |
| `--container-sheet-file` | 640 px | same | `@theme` → `max-w-sheet-file` | — |
| `--container-inbox-list` | 22rem (352 px) | same | `@theme` → used as `lg:grid-cols-[var(--container-inbox-list)_minmax(0,1fr)]`, no px literal | — |

`body` (`globals.css:174-176`) becomes `bg-background text-meta text-foreground antialiased`, with `font-feature-settings: "cv11", "ss01"; font-variant-numeric: tabular-nums;`.

## 4. Components

"Where" means a change at the primitive (P) or per call site (C). Call-site counts are JSX uses outside `components/ui` and tests.

| Component | File | Call sites | Now | Target | Where | Overriding call sites |
|---|---|---|---|---|---|---|
| Button | `components/ui/button.tsx` | 61 in 33 files. outline 26, ghost 16, default 13, link 4, destructive 1; size default 33, sm 23, icon-sm 2, icon 1, xs 1, icon-xs 1 | base `rounded-lg text-sm font-medium`, focus `ring-3 ring-ring/50` (:7); `sm` `h-7 text-[0.8rem]` (:26) | base `text-meta font-medium`, focus `ring-2 ring-ring ring-offset-2 ring-offset-background`. `outline`: `bg-background border-border text-foreground`, no `dark:input` (:12-13). `ghost`: `text-foreground-secondary`. `link`: `h-auto px-0 text-foreground hover:underline`. `destructive`: `bg-background border-border text-status-failed hover:bg-status-failed-muted`. New `destructive-solid`: `bg-status-failed text-primary-foreground`. `sm`: `h-7 text-meta rounded-md`. `icon-sm` → 32 px. Remove unused `secondary`, `lg`, `icon-lg` | P | `link` + `h-auto px-0`: gate-decision.tsx:58, run-banner.tsx:44, :71, run-console.tsx:149 (drop). command-palette.tsx:74 (input look, see shell). repo-combobox.tsx:54 (input look) |
| Badge | `components/ui/badge.tsx` | 8 in 6 files | `h-5 rounded-4xl border border-transparent text-xs font-medium` (:7) | `h-6 text-caption font-medium border`. `secondary` → `bg-muted border-border text-foreground-secondary`. `outline` keeps `border-border`. Remove `destructive`, `ghost`, `link` | P | status-badge.tsx:74, connection-card.tsx:43 (`h-6 px-2 text-xs`, drop), model-pricing.tsx:257 (`h-5 px-1.5 text-xs`, drop), template-gallery.tsx:34 (`h-6 gap-1 px-2`, drop) |
| StatusBadge | `components/status-badge.tsx` | 4: command-palette.tsx:110, run-header.tsx:133, step-panel.tsx:88, runs-list.tsx:63 | tone map `bg-status-X-muted text-status-X` (:28-59), no edge | add `border-status-X-border` to each tone (expired uses cancelled) | P (component) | none |
| ConnectionBadge | `settings/connection-card.tsx:17-48` | 3 (one per connection card) | hand-built pill, same tones, no edge | reuse `StatusBadge`'s tone classes (export `statusTone`), so it gets the edge | C | — |
| Card | `components/ui/card.tsx` | 4 files: audit-list.tsx:113, runs-list.tsx:277, connection-card.tsx:74, template-gallery.tsx:58 | `rounded-xl ring-1 ring-foreground/10 text-sm bg-card` (:14); title `text-base font-medium` (:40); description `text-sm text-muted-foreground` (:52); footer `bg-muted/50` (:79) | `rounded-lg border bg-card text-meta`; header with content: `border-b bg-surface-subtle px-4 py-3`; title `text-section font-semibold`; description `text-meta text-foreground-secondary`; footer `bg-surface-subtle rounded-b-lg` | P | connection-card.tsx:77 and template-gallery.tsx:65 icon tile `bg-muted/40` → `bg-surface-subtle` (C) |
| Tabs | `components/ui/tabs.tsx` | 3 files: run-console.tsx:359, step-panel.tsx:108/272, new-run-sheet.tsx:231 | `TabsList` grey pill `rounded-lg bg-muted p-1` (:22); trigger `h-7 rounded-md text-sm`, active `bg-background shadow-xs` (:35) | default `line`: list `flex h-9 items-end gap-4 border-b border-border overflow-x-auto` with an edge fade (`mask-image` on overflow); trigger `h-9 px-0.5 text-meta font-medium text-foreground-secondary`, active `text-foreground` + `after:` 2 px `bg-primary` bar at the bottom. `variant="segmented"` keeps today's look. Export `tabsListVariants`/`tabsTriggerVariants` for link tabs | P | new-run-sheet.tsx:231 → `variant="segmented"`; TabsContent `pt-2/pt-3` at run-console.tsx:374,393,408 and step-panel.tsx:115-147 (drop, spacing in primitive) |
| Run view tabs (hand-rolled) | `runs/run-views.tsx:24-58` | 1 | pill copy at `text-body` (:25, :38-39); count `text-caption` (:48) | links styled with `tabsListVariants`/`tabsTriggerVariants`; count `text-meta font-normal text-muted-foreground` | C | — |
| Table | `components/ui/table.tsx` | 5 files: runs-list.tsx:214, audit-list.tsx:75, findings-view.tsx:103, raw-events.tsx:161, model-pricing.tsx:138 | container `overflow-x-auto`, no border (:19); header no fill (:32); head `h-row px-2` (:73); row `border-b hover:bg-muted/50` (:60); cell `px-2` (:86) | container `rounded-lg border bg-card overflow-x-auto` (prop `bordered={false}` to opt out); `TableHeader` `bg-surface-subtle`, header rows never hover; head `h-row-header px-3`; row `border-b border-divider hover:bg-muted`; cell `px-3` | P | all 5 pass a redundant `text-meta` (drop); 5 header rows `hover:bg-transparent` (drop); model-pricing.tsx:136 wrapper `rounded-md border` (drop); runs-list.tsx:214 `lg:overflow-x-visible` (keep, for sticky date headers) |
| Input, Textarea, NativeSelect, InputGroup | `components/ui/input.tsx:10`, `textarea.tsx:9`, `native-select.tsx:22`, `input-group.tsx:17` | 11 / 2 / 9 / 1 | `rounded-lg border-input text-base md:text-sm placeholder:text-muted-foreground dark:bg-input/30` | `h-8 rounded-md border-border-strong bg-background text-base md:text-meta placeholder:text-placeholder`; focus as Button. NativeSelect `sm` removed (filters become chips) | P | audit-filters.tsx:52,114,125 `h-8 … text-xs` (drop `h-8`; mono id input `text-caption`) |
| Label, Field | `components/ui/label.tsx:12`, `field.tsx` | Label 8 (6 `sr-only`); FieldLabel 16, FieldDescription 12 | Label `text-sm font-medium`; FieldDescription `text-sm text-muted-foreground` (:127); FieldError `text-sm text-destructive` (:205); checked label `border-primary/30 bg-primary/5` (:100) | Label `text-meta font-medium text-foreground`; FieldDescription `text-caption text-muted-foreground`, links `hover:text-foreground underline`; FieldError `text-caption text-status-failed`; checked label `border-border-strong bg-muted` | P | audit-filters.tsx:111,122 `text-xs text-muted-foreground` → keep as 12 px filter labels |
| Alert | `components/ui/alert.tsx` | 22 in 15 files (16 destructive) | `px-2.5 py-2 text-sm` (:6); destructive `bg-card text-destructive` (:12); description `text-sm text-muted-foreground` (:54) | base `px-3 py-2.5 text-meta`; `destructive` → `bg-status-failed-muted border-status-failed-border text-status-failed`, description `text-foreground-secondary`; new `waiting` → `bg-status-waiting-muted border-status-waiting-border`, icon `text-status-waiting`; description `text-meta text-foreground-secondary` | P | states.tsx:68-70 description `text-destructive` (drop); run-banner.tsx:62-63 → `variant="waiting"`; github-connection.tsx:255, templates-view.tsx:59 description `text-foreground` (drop) |
| Sheet | `components/ui/sheet.tsx` | 7 | header `p-4` (:82); footer `p-4` (:92); title `text-base font-medium` (:102); description `text-sm text-muted-foreground` (:115) | header `border-b bg-surface-subtle px-4 py-3 pr-12`; footer `border-t`; title `text-section font-semibold`; description `text-meta text-foreground-secondary`; `size` prop `sm/md/lg/file` → `max-w-sheet-*` | P | 6 SheetHeaders `border-b pr-12` (drop); 2 SheetFooters `border-t` (drop); widths at new-run-sheet.tsx:346, raw-events.tsx:49, decision-controls.tsx:199, step-output.tsx:102, artifact-cards.tsx:147 → `size` |
| Dialog, AlertDialog | `components/ui/dialog.tsx:56`, `alert-dialog.tsx:32` | 2 / 2 | `rounded-xl ring-1 ring-foreground/10`, title `text-base font-medium`, footer `bg-muted/50`; AlertDialogAction `variant="destructive"` | `rounded-lg border shadow-lg text-meta`; title `text-section font-semibold`; description `text-foreground-secondary`; footer `bg-surface-subtle`; destructive action → `destructive-solid` | P | cancel-run-button.tsx:66, confirm-dialog.tsx:48 (get the solid red through the variant) |
| DropdownMenu, Popover, Command | `dropdown-menu.tsx:37,65`, `popover.tsx:28`, `command.tsx:22,46,66,147` | 3 / 1 / 2 | `ring-1 ring-foreground/10`, items `text-sm`, `focus:bg-accent`, Command `rounded-xl!` | `border`, `rounded-lg`, items `text-meta`, `focus:bg-muted`, destructive item `text-status-failed`, separator `bg-divider`, shortcut `text-kbd` | P | user-menu.tsx:48 trigger (sidebar item style, see shell) |
| Skeleton | `components/ui/skeleton.tsx:7` | 7 | `rounded-md bg-muted` | unchanged | — | template-gallery.tsx:111 `rounded-xl` → `rounded-lg` |
| PageHeader | `components/page-header.tsx` | 7: settings/layout.tsx:9, audit-view.tsx:56, inbox-view.tsx:67, run-console.tsx:279, run-header.tsx:128, runs-view.tsx:103, templates-view.tsx:44 | `flex … gap-3`; description `text-muted-foreground` 14 px (:38, :40); parents `gap-6` | band: `-mx-4 -mt-6 px-4 pt-6 md:-mx-8 md:px-8 border-b bg-background`; `pb-4` when no tabs, `pb-0` with tabs; description `text-meta text-foreground-secondary max-w-prose`; new `tabs` slot rendered last in the band, its underline on the border | P | runs-view.tsx:124-131 (tabs move into the slot); settings/layout.tsx:15 (mobile `SettingsNav` into the slot below 768 px) |
| EmptyState | `components/states.tsx:9-34` | 17 | dashed box, 24 px icon, `message` in muted 14 px | no box; 40 px `rounded-lg border bg-surface-subtle` icon tile with `size-5 text-muted-foreground` icon; `title` `text-section font-semibold`; optional `description` `text-meta text-foreground-secondary`; action is a default (ink) button | P (API change `message` → `title` + `description`, all 17 sites) | outline actions at audit-view.tsx:90, inbox-review.tsx:89, inbox-view.tsx:81, runs-view.tsx:183, :197 → default |
| ErrorState | `components/states.tsx:57-81` | 22 | `Alert destructive`; Retry `outline sm` | Alert destructive (new tokens); Retry `outline` default size | P | none |
| LoadingState | `components/states.tsx:37-54` | 21 | `h-5` bars | unchanged | — | — |
| StatTile + new StatStrip | `components/display/stat-tile.tsx` | 14 in 4 grids: run-tiles.tsx:65, inbox-review.tsx:140, step-usage.tsx:27, findings-view.tsx:232 | each tile `rounded-lg border bg-card px-4 py-3` (:20); label 400 muted (:22); secondary muted (:25) | `StatStrip` (`display/stat-strip.tsx`): `grid rounded-lg border bg-card` with cells split by `border` lines (`divide-x` on one row; at 2 columns `border-t` between rows), `grid-cols-2` below 768 px with an odd last tile `col-span-2`. Tile: no border or fill, `px-4 py-3`; label `text-caption font-medium text-muted-foreground`; value `text-stat font-semibold tracking-tight`; secondary `text-caption text-foreground-secondary`, or `tone` prop for a status colour | P + C (4 grids → StatStrip) | run-tiles.tsx:33 value `font-mono text-section` (keep for a repo name); findings-view.tsx:232 → chip line (screens.md) |
| IdChip | `components/display/id-chip.tsx` | 6 | `rounded-sm font-mono`, no size (:12-13); link `text-primary` (:42); copy button `text-muted-foreground` (:68) | copy form: `rounded-md border px-1.5 font-mono text-caption text-foreground-secondary`, copy icon `size-3`; link form: same, no border, `hover:underline`; in-row (`focusable={false}`): mono 12 px `foreground-secondary`, no border | P | audit-list.tsx:52 `text-xs` (drop); command-palette.tsx:112 `text-muted-foreground` (drop) |
| Display values (RelativeTime, Duration, Money, TokenCount, Percent, ExpiresIn, WaitingTime) | `components/display/*` | 7 / 11 / 10 / 10 / 2 / 4 / 6 | `tabular-nums`, colour from the parent | unchanged, except `WaitingTime` gets `tone="status"` (`text-status-waiting`) for stat secondaries | C | Duration `text-xs` at tool-calls.tsx:108, work-block.tsx:114 → `text-caption`; ExpiresIn `text-muted-foreground` at inbox-review.tsx:128, approval-dock.tsx:98 → `text-foreground-secondary`; run-banner.tsx:67 → `text-status-waiting` |
| JsonView | `components/json-view.tsx` | 8 (+ OutputView 3, TextView 2) | box `rounded-md border bg-muted/40 text-xs` (:108); keys muted (:44); scalars `text-primary` (:27) | box `rounded-lg border bg-surface-subtle text-caption`; keys `text-foreground-secondary`; non-string scalars `text-foreground` (no hue) | P | none |
| Kbd | `runs/console/decision-controls.tsx:41-47` | 2 | `text-[11px] border-current/30 opacity-70` | move to `components/ui/kbd.tsx`: `rounded-sm border px-1 font-mono text-kbd font-medium text-muted-foreground`; inside a primary button `border-primary-foreground/30 text-primary-foreground` | P (new) | command-palette.tsx:88 `⌘K` (use Kbd) |
| ApproveButton / RejectButton | `decision-controls.tsx:50-101` | 3 / 3 (Inbox + console) | default / outline | Approve unchanged (ink); Reject `variant="destructive"` (outlined red) | C | — |
| AgentMessage | `runs/console/agent-message.tsx` | 5 | link `text-primary` (:20); inline code `text-[0.85em] rounded-sm` (:30); pre `bg-muted/40` (:35); h1/h2 `text-base` (:23-24) | link `text-foreground underline`; inline code `text-caption bg-muted rounded-sm px-1`; pre `bg-surface-subtle rounded-lg`; h1/h2 `text-section font-semibold` | P | work-block.tsx:73 `text-meta text-muted-foreground` → `text-foreground-secondary` |
| FieldMessage | `forms/schema-form/schema-fields.tsx:23-30` | 10 | `text-sm text-destructive` | `text-caption text-status-failed`, icon `size-3` | P | — |
| ArtifactCards | `runs/artifacts/artifact-cards.tsx:173-215` | 3 | card `bg-card hover:bg-muted`; name `font-mono text-meta` 400 (:199); facts muted (:200) | name `font-medium`; facts `text-foreground-secondary` | P | — |
| FilterChip, AddFilter (new) | `components/filters.tsx` | — (Runs, Audit) | — | chip: `inline-flex h-7 rounded-md bg-muted px-2 text-meta`, label `text-muted-foreground`, value `font-medium text-foreground`, remove `XIcon size-3` icon button (`aria-label="Remove <label> filter"`); "+ Filter": `h-7 rounded-md border border-dashed border-border-strong px-2 text-meta font-medium text-foreground-secondary`, opens a `DropdownMenu` of filters, each opening a `Popover` with its control (Command list, id input or date inputs) | P (new) | — |
| TruncatedPath (new) | `components/display/truncated-path.tsx` | — (findings, Inbox, gate files, pricing, written files, sheet titles) | `break-all` or end `truncate` | mono `text-caption`, truncates from the left (`…/svc/config.py:12`): the file name and line always show; full path in `ValueTooltip`; `.` renders "repo root" | P (new) | see Hard-coded values |

## 5. Hard-coded values

| file:line | Value | Use instead |
|---|---|---|
| `components/ui/button.tsx:25,26,30,32` | `rounded-[min(var(--radius-md),10px)]`, `text-[0.8rem]` | `rounded-md`, `text-meta` (`text-caption` for `xs`) |
| `components/ui/native-select.tsx:22` | `data-[size=sm]:rounded-[min(var(--radius-md),10px)]` | remove the `sm` size |
| `components/shell/app-shell.tsx:37` | `text-[10px]` drawer badge | `text-kbd` on a `h-4 min-w-4` pill, or a 8 px dot with the count in `aria-label` |
| `components/shell/sidebar.tsx:63` | `text-[0px]` rail dot | allowed by the lint exception (it hides the count visually) |
| `runs/console/decision-controls.tsx:43` | `text-[11px] leading-4 opacity-70` | `Kbd` (`text-kbd`) |
| `runs/console/agent-message.tsx:30` | `text-[0.85em]` | `text-caption` |
| `runs/console/rail.tsx:47` | `left-[9px]` | `left-2.25` (Tailwind v4 spacing scale) |
| `runs/new-run/new-run-sheet.tsx:346` | `sm:max-w-[480px]!` | `Sheet size="sm"` |
| `runs/console/raw-events.tsx:49`, `decision-controls.tsx:199` | `sm:max-w-[560px]!` | `size="md"` |
| `runs/console/step-output.tsx:102` | `sm:max-w-[640px]!` | `size="file"` |
| `runs/artifacts/artifact-cards.tsx:147` | `sm:max-w-[720px]!` | `size="lg"` |
| `inbox/inbox-view.tsx:90` | `lg:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]` | `lg:grid-cols-[var(--container-inbox-list)_minmax(0,1fr)]` |
| `runs/runs-list.tsx:198` | `sticky top-14` | `top-12` (48 px bar) |
| `app/settings/layout.tsx:14` | `md:top-20` | `md:top-16` |
| `inbox/inbox-view.tsx:97`, `run-console.tsx:421` | `scroll-mt-20` | `scroll-mt-16` |
| `runs/runs-list.tsx:182`, `:286`; `audit-list.tsx:36,52,54,116,123`; `audit-filters.tsx:52,65,111,114,122,125`; `settings/github-connection.tsx:94`; `model-pricing.tsx:229,255,257,263,309`; `repo-combobox.tsx:102`; `gate-files.tsx:56,158,169`; `graph-nodes.tsx:79,159,200,223`; `tool-calls.tsx:108,115,119,180`; `work-block.tsx:114,179`; `activity-line.tsx:33`; `raw-events.tsx:157`; `template-gallery.tsx:76` | `text-xs` | `text-caption` |
| `connection-checklist.tsx:69,89`; `new-repo-fields.tsx:74`; `connection-card.tsx:86`; `audit-list.tsx:120`; `run-limits.tsx:418,431,443`; `approval-dock.tsx:102` | `text-sm` | `text-meta` |
| `findings-view.tsx:50,56,124,166,188`; `inbox-review.tsx:205,231`; `gate-files.tsx:153,190`; `model-pricing.tsx:255`; `step-output.tsx:87,105`; `artifact-cards.tsx:150`; `raw-events.tsx:52`; `port-errors.tsx:51`; `step-input.tsx:23`; `run-banner.tsx` failed step name | `break-all` (paths, rule ids, model ids, branches) | `TruncatedPath` for paths; rule and model ids `whitespace-nowrap truncate` with a tooltip |
| `connection-card.tsx:77`; `template-gallery.tsx:65`; `work-block.tsx:25`; `tool-calls.tsx:44`; `graph-nodes.tsx:174`; `json-view.tsx:108`; `agent-message.tsx:35` | `bg-muted/30`, `/40`, `bg-background/60` (`graph-nodes.tsx:219`) | `bg-surface-subtle` |
| `tool-calls.tsx:45` | `border-status-failed/30` | `border-status-failed-border` |
| `graph-nodes.tsx:146` | `shadow-xs` on a graph node | none |
| `run-graph.tsx:89`, `gate-review-sheet.tsx:50` | `h-[min(70svh,720px)]`, `w-[min(1100px,92vw)]` | keep: specified in tech-stack → Run console; not type sizes |

## 6. Data for the content rules

| Rule (DL → Content rules) | Status | Field or derivation |
|---|---|---|
| "$0.00 · no model calls" | Available | Ended run with `usage.input_tokens + output_tokens + cache_*_tokens === 0` and `usage.cost_complete === true` (`packages/api/src/agentic_api/runs/models.py:271-286`; tool nodes log no usage, `packages/engine/src/agentic_engine/tool.py:31`). While live: no model node in `RunDetail.spec` (agent, reduce `strategy: "agent"`, router with `classifier`). Today 0 tokens becomes `null` usage → "—": `run-console.tsx:119`, `runs-list.tsx:168-174` |
| Output tile shows the artifact | Available (console) | `GET /runs/{id}/artifacts` (`useRunArtifacts`, `runs/artifacts/use-run-artifacts.ts:27`): latest `created_at`. Runs list: needs an API change (follow-up) |
| Waiting vs active time | Available | `active_ms`, `waiting_ms`, `measured_at` on list and detail (`models.py:321-333`). Per step: gates only, derived (`step-list.tsx:93-97`) |
| "2 of 4 scans" | Available | `finding.sources.length` of `report.sources.length` (`packages/runtime/src/agentic_runtime/findings.py:75, 93-116`); source ids are check names in the audit (`packages/engine/src/agentic_engine/templates/audit.py:184-200`) |
| Zeros are quiet | Available | `FindingsReport.counts` (`findings.py:108`), read at `runs/findings/findings.ts:67` |
| "repo root" and a deduplicated Checked list | Available, client-side | `Check.path` is `"."` for the root (`packages/tools/src/agentic_tools/scan/server.py:130-141`); merged reports repeat checks (`findings.py` ~200); key `(path, kind, tool)` |
| Distinct step one-liners | Available, client-side | `stepOutline` (`runs/console/step-entries.ts:228-267`): add tool-node lines from the parsed findings output ("Linted 3 modules · 2 findings", "No secrets found") and, for agents with an `output_schema`, the role or "Answered with N findings" instead of the JSON's first line |
| Template icon in the header | Available | `template_id` (`models.py:297`); icons are private in `templates/template-gallery.tsx:23-27` (export as `templateIcon`) |

## 7. Tests the change touches

| Test | Asserts | Change |
|---|---|---|
| `components/status-badge.test.tsx:16` | `text-status-${status}` class | add `border-status-${status}-border` |
| `components/display/display.test.tsx:55,86,192,209-220` | `tabular-nums`, IdChip `font-mono`, StatTile `<dl>` with `text-stat` | keep; add StatStrip cases (2 columns, odd last tile spans) |
| `components/states.test.tsx:25` | EmptyState message, action | `title` / `description` |
| `components/page-header.test.tsx:15,23` | one h1, no `<p>` without description | add the `tabs` slot |
| `runs/findings/findings.test.tsx:90-104,131,195-215,243,251` | "Found by 2 of 3: lint, reviewer", "67% confidence", table name, Checked `"."` | "2 of 3 scans: lint, reviewer"; no confidence; "repo root"; dedup; container-query cards |
| `runs/console/run-console.test.tsx:176,215-222,331,858,872` | tab roles, the five tile labels | labels unchanged; Output tile cases (artifact, "no model calls") |
| `runs/console/step-entries.test.ts:106-135`, `step-view.test.tsx:223-265` | one-liner strings, `aria-current` | new tool and JSON-agent lines |
| `runs/runs-list.test.tsx`, `runs-view.test.tsx` | tables, `run-time` text, views | filter chips instead of selects |
| `templates/templates-view.test.tsx:242` | `role="tab"` "New repo" | still a tab (segmented variant keeps Radix Tabs) |
| `audit/audit-view.test.tsx:98,140` | filters, table | filter chips |
| `components/shell/app-shell.test.tsx:51-183` | sidebar, breadcrumbs, drawer | unchanged roles |
| `web/eslint/no-raw-colors.test.mjs` | colour cases | add `text-[13px]` (invalid), `text-[0.85em]`, `text-[0px]` (valid) |
| `e2e/layout.spec.ts` | 26 screenshots at 375/768/1024/1440, light only; sticky and fit checks (`:292-373`) | add dark at 375; new names `run-findings-pane-narrow`, `not-found` |
| `e2e/a11y.spec.ts` | axe light and dark at 375 and 1440 | add the `tablet-768` project to its `testMatch` (`playwright.config.ts`) |
| `e2e/console.spec.ts`, `graph.spec.ts`, `monitor.spec.ts`, `runs-page.spec.ts` | tab roles, `data-status`, view link text | runs-page: view tabs now in the header band; text unchanged |
