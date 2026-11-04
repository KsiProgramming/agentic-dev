# Design language

How the product looks: the exact colours, type and surface treatments every screen uses. `tech-stack.md → UI design system` says *what* each screen shows; this file says *how it looks*. Coding agents read it before any change in `web/`.

It is in force from roadmap phase 11.9 ([plan](2026-10-28-design-language-v2/requirements.md)); `tech-stack.md → UI design system → Look` points here.

This file is the only reference for the look. The two run-detail mockups in [`2026-10-28-design-language-v2/mockups/`](2026-10-28-design-language-v2/mockups/) show layout ideas only: where they differ from this file (indigo buttons, grey pill tabs, separate tinted stat cards, an icon-only sidebar), this file wins. A case this file does not cover is decided in the phase's `screens.md`, then added here.

## Why this exists

The shipped screens pass contrast checks but look faded. No single colour is to blame (muted text is 6:1 on white). The cause is a flat hierarchy:

- Only two text levels: near-black and one grey. Most text that is not a title is grey, so nothing stands out.
- Every surface is the same white. The sidebar, table headers and panes are separated by hairlines only.
- Badges and tabs have fills but no edges, so they read as washed-out blobs.
- Almost all text is weight 400 at 13 px, which renders thin with `antialiased`.
- The accent (indigo) barely appears, so primary actions do not anchor the page.

The fix is three text levels, tinted surfaces, edges on badges and selected states, heavier weights for names and labels, and a near-black "ink" primary.

## Colour tokens

Every value below is a token in `web/src/app/globals.css`, in light and dark. Components use the token names only (CLAUDE.md rule 1). New tokens are marked **new**.

### Light

| Token | Value | Use | Contrast |
|---|---|---|---|
| `--background` | `#ffffff` · `oklch(1 0 0)` | Page and pane background | — |
| `--foreground` | `#18181b` · `oklch(0.210 0.006 285.9)` | Titles, names, values, body text | 17.7:1 |
| `--foreground-secondary` **new** | `#3f3f46` · `oklch(0.370 0.012 285.8)` | Metadata a reader needs: repo, branch, started time, step summaries, table cells that are not the row's name | 10.4:1 |
| `--muted-foreground` | `#52525b` · `oklch(0.442 0.015 285.8)` (was 0.5) | Labels and captions: stat-tile labels, table headers, help text, counts | 7.7:1 |
| `--placeholder` **new** | `#6e6e77` · `oklch(0.541 0.014 285.9)` | Placeholders, disabled text, "—". Never for content | 5.1:1 (4.6:1 on `muted`) |
| `--surface-sunken` **new** | `#f7f7f8` · `oklch(0.976 0.001 286.4)` | Sidebar background | — |
| `--surface-subtle` **new** | `#fafafa` · `oklch(0.985 0 0)` | Table header row, pane headers, file headers in a diff | — |
| `--muted` | `#f4f4f5` | Hover fills, segmented-control track, kbd, inline code | — |
| `--border` | `#e4e4e7` | Card, pane and input borders | — |
| `--border-strong` **new** | `#d4d4d8` · `oklch(0.871 0.005 286.3)` | Input borders, dashed "+ Filter" buttons, focus-adjacent edges | — |
| `--divider` **new** | `#f0f0f2` · `oklch(0.956 0.003 286.3)` | Row dividers inside a table or list | — |
| `--primary` | `#18181b` (ink) | Primary buttons, selected tab underline, active nav text | — |
| `--primary-foreground` | `#ffffff` | Text on primary | 17.7:1 |
| `--ring` | `#18181b` | Focus ring, 2 px with 2 px offset | — |
| `--link` | not a token | Links in text are `text-foreground` with an underline on hover. Not a colour of their own | — |

The shadcn tokens the primitives read keep their names and map onto the ones above: `--card` and `--popover` = `--background` (light) or `#111113` (dark); `--secondary` and `--accent` = `--muted`; `--secondary-foreground` and `--accent-foreground` = `--foreground`; `--input` = `--border-strong`; `--destructive` = `--status-failed`. `--overlay` and the shadows stay as they are.

Status colours (`--status-X`, `--status-X-muted` and a **new** `--status-X-border`):

| Status | Text and icon | Fill | Border | Text on fill |
|---|---|---|---|---|
| running | `#1d4ed8` | `#eff6ff` | `#bfdbfe` | 6.2:1 |
| succeeded | `#15803d` | `#f0fdf4` | `#bbf7d0` | 4.8:1 |
| waiting | `#b45309` | `#fffbeb` | `#fde68a` | 4.8:1 |
| failed | `#b91c1c` | `#fef2f2` | `#fecaca` | 5.9:1 |
| queued, cancelled, expired | `#52525b` | `#f4f4f5` | `#e4e4e7` | 7.0:1 |

Severity colours (`--severity-X`, `-muted`, `-border`): a finding's severity is not a status, so it has its own hues, never the status ones. A Critical finding must not read as a failed run. The shape of each icon differs too (octagon, triangle, diamond, circle, info), so colour is never the only cue.

| Severity | Text and icon | Fill | Border | Text on fill | Dark: text / fill / border |
|---|---|---|---|---|---|
| critical | `#991b1b` | `#fef2f2` | `#fecaca` | 7.6:1 | `#fca5a5` / `#2a0a0a` / `#7f1d1d` |
| high | `#c2410c` | `#fff7ed` | `#fed7aa` | 4.9:1 | `#fdba74` / `#2a1405` / `#7c2d12` |
| medium | `#a16207` | `#fefce8` | `#fde68a` | 4.8:1 | `#fde047` / `#262005` / `#713f12` |
| low | `#1d4ed8` | `#eff6ff` | `#bfdbfe` | 6.2:1 | `#93c5fd` / `#172554` / `#1e3a8a` |
| info | `#52525b` | `#f4f4f5` | `#e4e4e7` | 7.0:1 | `#d4d4d8` / `#1c1c1f` / `#3f3f46` |

### Dark

| Token | Value |
|---|---|
| `--background` | `#09090b` · `oklch(0.141 0.004 285.8)` |
| `--card` | `#111113` · `oklch(0.179 0.004 286)` |
| `--surface-sunken` | `#0f0f11` · `oklch(0.169 0.004 286)` |
| `--surface-subtle` | `#141416` · `oklch(0.192 0.004 286)` |
| `--muted` | `#1c1c1f` · `oklch(0.228 0.006 285.9)` |
| `--foreground` | `#fafafa` (19:1) |
| `--foreground-secondary` | `#d4d4d8` (13.5:1) |
| `--muted-foreground` | `#a1a1aa` (7.8:1) |
| `--placeholder` | `#8b8b93` (5.9:1; 5.0:1 on `muted`) |
| `--border` | `#27272a` |
| `--border-strong` | `#3f3f46` |
| `--divider` | `#1c1c1f` |
| `--primary` / `--primary-foreground` | `#fafafa` / `#09090b` |
| `--ring` | `#fafafa` |

| Status (dark) | Text and icon | Fill | Border |
|---|---|---|---|
| running | `#93c5fd` | `#172554` | `#1e3a8a` |
| succeeded | `#86efac` | `#052e16` | `#14532d` |
| waiting | `#fcd34d` | `#2a1a05` | `#78350f` |
| failed | `#fca5a5` | `#2a0a0a` | `#7f1d1d` |
| neutral | `#d4d4d8` | `#1c1c1f` | `#3f3f46` |

Every text colour above is at least 4.5:1 on every surface it sits on, in both themes.

### Where each text level goes

| Level | Examples |
|---|---|
| `foreground` | Page and section titles, workflow and step names, stat values, table cell that names the row, agent output, button labels |
| `foreground-secondary` | Repo and branch, "Started 27 min ago", step one-liners ("Linted the repository"), finding text, durations and costs in tables |
| `muted-foreground` | Stat-tile labels, table headers, field help, "Found by 2 of 4", counts beside tabs, "+42 more lines" |
| `placeholder` | Input placeholders, disabled items, "—" |

If more than about a third of a screen's text is `muted-foreground`, the hierarchy is wrong: move metadata up to `foreground-secondary`.

## Type

Inter for UI, JetBrains Mono for ids, paths, branches, code and JSON. All numbers use `tabular-nums`.

| Role | Size / line height | Weight | Extra |
|---|---|---|---|
| Page title | 20 / 28 px | 600 | `tracking-tight` (−0.01em) |
| Stat value | 24 / 32 px | 600 | `tracking-tight` |
| Section and pane title | 16 / 24 px | 600 | — |
| Body, agent output | 14 / 22 px | 400 | Max 72 characters wide |
| UI text, table cells | 13 / 20 px | 400 | — |
| Names in lists and tables (workflow, step, file) | 13 / 20 px | **500** | — |
| Buttons, tabs, nav items | 13 / 20 px | **500** | — |
| Labels, table headers, captions | 12 / 16 px | **500** | Sentence case, never uppercase |
| Form field labels (above an input) | 13 / 20 px | 500 | `foreground` |
| Mono (ids, paths) | 12 / 16 px | 400 | Also 12 px when under a name (no fractional sizes) |
| Keyboard hint | 11 / 16 px | 500 | `text-kbd`, the one size below the scale |

Every size is a type-scale token (`text-caption`, `text-meta`, `text-body`, `text-section`, `text-page`, `text-stat`, `text-kbd`). The page's default text (`body`) is `text-meta`. Inter uses `font-feature-settings: "cv11", "ss01"` (single-storey a, open digits) and every number is `tabular-nums`, both set once on `body`.

Weight 500 on names, labels, buttons and tabs is what makes a screen look solid. Do not drop it to save space.

## Surfaces and structure

- **Sidebar:** `surface-sunken` background with a `border` on its right. The active item is a `background` (white) pill with a 1 px `border` ring and `foreground` text at weight 500. Inactive items are `foreground-secondary`. Count badges are pills in the waiting colours.
- **Top bar:** 48 px, `background`, bottom `border`. Breadcrumbs in `muted-foreground`, current page in `foreground` at 500, ids in mono.
- **Page:** full content width up to 1600 px with 32 px side padding from 768 px (16 px below). No centred narrow column.
- **Page header band:** the page title row (title, one-line description, actions) sits on `background` with a bottom `border` that runs the width of the content area, padding 24 px top and 16 px bottom. Page-level tabs (the runs views; settings below 768 px) sit at the bottom of the band, their 2 px underline on its border. The page body starts 24 px below.
- **Cards and panes:** `card` (white in light, `#111113` in dark), 1 px `border`, radius 8 px, no shadow. Both panes of a two-pane layout get the same border. A pane or card with a title has a header row on `surface-subtle`, 12 px vertical and 16 px horizontal padding, separated by a `border`.
- **Tables:** inside a bordered card with radius 8 px. Header row on `surface-subtle`, 36 px, 12 px labels in `muted-foreground`, cells 12 px horizontal padding. Body rows 40 px (32 px compact), separated by `divider`. Date group headers (Today, Earlier this week) are 12 px weight 600 `foreground-secondary`.
- **Nested lists** (the console's step list): children are joined to their parent by 1 px `border-strong` tree lines, which run down from the parent's icon, elbow into each child's icon and stop at the last child.
- **Rows:** a clickable row (table, list, step list, Inbox list) gets a `muted` fill on hover. A selected row is `surface-subtle` with a 2 px `primary` bar on its left edge and `aria-current`; hover on it stays `muted`.
- **Stat tiles:** one bordered strip divided into equal cells by `border` lines, not separate floating cards. Label 12 px weight 500 `muted-foreground`, value 24 px weight 600, one secondary line 12 px in `foreground-secondary`, or in a status colour when it means status ("waited 1m 52s" in waiting).
- **Shadows:** only on floating layers: menus, popovers, sheets, dialogs, toasts, and the bars fixed over scrolling content (the approval dock, the limits form's save bar, "Jump to latest").

## Components

| Component | Treatment |
|---|---|
| `StatusBadge` | Pill, 1 px `--status-X-border`, `--status-X-muted` fill, `--status-X` text at 12 px weight 500, 12 px icon. The edge is not optional: without it the badge looks faded |
| Tabs (page and pane level) | Underline tabs: weight 500, 36 px tall; the selected tab is `foreground` with a 2 px `primary` underline over the tab row's bottom `border`; others are `foreground-secondary`. Counts after the label in `muted-foreground` weight 400. **No grey segmented pill for tabs** |
| Segmented control | Only for switching a view of the same data (List / Graph, Rendered / Source) or a two-way choice inside a form (Existing repo / New repo): `muted` track, selected item `background` with a 1 px shadow |
| `SeverityBadge` | Pill like `StatusBadge`: `--severity-X-muted` fill, 1 px `--severity-X-border`, `--severity-X` text at 12 px weight 500, the severity's own icon |
| Run map (the console's Graph tab) | A tree read left to right, like Claude Code's agent map, not a canvas: compact cards (`card`, 1 px `border`, radius 8 px, 8 × 12 px padding) joined by 1 px `border-strong` elbow lines. Each card: a 8 px status dot (status colour; hollow when not started), the name at 13 px weight 500 (mono for node ids), one line 12 px `foreground-secondary` ("4m 29s · 113.2K tokens", or what it does before it runs). Containers (map, parallel, loop, router) are a card whose children hang off it to the right. The selected card has a 2 px `primary` ring. No pan or zoom: the map scrolls inside its pane like a list |
| `EmptyState` | No box of its own: a 40 px `surface-subtle` square, radius 8 px, 1 px `border`, holding a 20 px `muted-foreground` icon; a title 16 / 24 px weight 600 `foreground`; an optional line 13 px `foreground-secondary`; at most one action, the primary button |
| Primary button | `primary` (ink) fill, `primary-foreground` text, weight 500, 32–34 px tall. One per area |
| Secondary button | `background` with a 1 px `border`, `foreground` text, weight 500 |
| Destructive action | `background` with a 1 px `border` and `--status-failed` text; the dialog's confirm button is filled `--status-failed` |
| Icon button | Ghost, 32 px, `foreground-secondary` icon, `aria-label` |
| Input | 1 px `border-strong`, radius 6 px, 32 px tall, placeholder in `placeholder` |
| Filter chip | `muted` fill, the value in `foreground` weight 500, a remove button |
| "+ Filter" | Dashed 1 px `border-strong` |
| `IdChip` | Mono 12 px `foreground-secondary`, 1 px `border`, radius 6 px, copy icon |
| Keyboard hint (`kbd`) | 11 px (`text-kbd`), 1 px `border`, radius 4 px, `muted-foreground`; on a primary button `primary-foreground` with a `primary-foreground`/30 border |
| Links | `foreground`, underlined on hover; external links get a 12 px external icon |
| Code inline | Mono 12 px on `muted`, radius 4 px |

## Content rules (from the review of the run console)

- **Tables become cards by container width, not screen width.** A table inside a pane narrower than about 720 px renders as stacked cards (as the mobile findings list does). Use a container query on the pane.
- **Paths and rule ids never wrap mid-word.** Truncate a path from the left (`…/svc/config.py:1`) with the full path in a tooltip; rule ids are mono chips that do not wrap.
- **No empty stat tiles.** A tile with no value either says why in words ("$0.00 · no model calls", "None · no agents ran") or is left out. An Output tile shows the run's real output: a PR, or the artifact it wrote (`findings.json`).
- **Zeros are quiet.** Counts by category (severity, status) are one line of chips with zero counts in `placeholder` ("1 High · 1 Medium · 0 Critical · 0 Low · 0 Info"), not one big tile per category.
- **Say each fact once.** A confidence of 50% next to "Found by 2 of 4" repeats itself; keep the one a reader understands ("2 of 4 scans").
- **Lists line up.** Key-value lists ("Checked") are a two- or three-column grid, deduplicated, and show "repo root" instead of `.`.
- **Steps that do different things say different things.** Two steps with the same one-liner is a bug in the summary, not a design choice.
- **"Show JSON" and similar view toggles** sit at the right end of the tab row as ghost buttons, never above the content.

## Mobile (below 768 px)

The sidebar is a drawer below 1024 px and an icon rail from 1024 to 1279 px (tech-stack → Layout); the rules below are for phones.

- Stat tiles collapse to a two-column list of label and value, not a stack of cards; an odd last tile spans both columns.
- Selecting a step opens its detail as a full-height sheet instead of stacking it under the step list. A link to a step (`?step=`) opens on its sheet.
- Tabs that do not fit scroll sideways with a fade at the edge, or move the last ones into a "More" menu. Never cut a label off without a hint.
- Side padding 16 px; cards keep their 1 px border.

## How this is checked

- Token values: `globals.css` matches the tables above (light and dark). The 11.1 lint rule (`agentic-ui/no-raw-colors`) rejects colours written anywhere else, and from 11.9 it also rejects arbitrary text sizes (`text-[13px]`).
- Contrast: axe in `e2e/a11y.spec.ts` at 375, 768 and 1440 px, light and dark.
- Look: the layout screenshots in `e2e/layout.spec.ts` (light, and dark at 375 px) are checked against this file by a person in review. A PR that changes a screen attaches its 1440 px light and 375 px dark screenshots.
