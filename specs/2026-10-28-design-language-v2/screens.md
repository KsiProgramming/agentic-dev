# Screens: Design language v2

One section per screen: what it renders today, what changes and why, files, responsive behaviour, data, edge cases. "DL" is [`specs/design-language.md`](../design-language.md). Component targets that apply everywhere (tokens, primitives, StatusBadge, IdChip, StatStrip, EmptyState) are in [inventory.md](inventory.md) → Components and are not repeated here. Paths are relative to `web/src/`.

Every screen inherits the following without further notes:
- `body` at 13 px;
- ink primary;
- underline tabs;
- bordered tables with a 36 px `surface-subtle` header and `divider` rows;
- `muted` row hover;
- badges with edges;
- the PageHeader band.

## 1. Shell (`components/shell/*`, `app/layout.tsx`)

**Today:**
- Sidebar: `aside border-r lg:w-16 xl:w-60` with no fill (`app-shell.tsx:70`). Nav items are `text-muted-foreground` with a `bg-muted` active state (`sidebar.tsx:87-88`). The Inbox count badge has no border (`sidebar.tsx:61`).
- Top bar: 56 px with `px-4 md:px-6` (`app-shell.tsx:76`). Breadcrumbs inherit 14 px (`breadcrumbs.tsx:17`).
- Main: `px-4 py-6 md:px-6` (`app-shell.tsx:93`) inside `max-w-content` (`:95`).
- Palette button: a 36 px outline button (`command-palette.tsx:74`).
- Drawer: the badge is `text-[10px]` (`app-shell.tsx:37`).
- Error pages: there is no `not-found.tsx` or `error.tsx`.

| Part | Change | Why (DL) | Files |
|---|---|---|---|
| Sidebar | `bg-surface-sunken` on the Sidebar root (so the drawer gets it too). Item: `h-9 rounded-md px-2.5 text-meta font-medium text-foreground-secondary hover:bg-muted hover:text-foreground`. Active: `bg-background text-foreground ring-1 ring-border`. Count badge: `border border-status-waiting-border font-medium`. Product name `text-meta font-semibold`, workspace `text-caption text-muted-foreground` | Surfaces → Sidebar | `sidebar.tsx:61,87-88,137,143,147`, `user-menu.tsx:48-50` (same item style) |
| Top bar | `h-12 px-4 md:px-8`. Breadcrumbs `text-meta text-muted-foreground`; current `font-medium text-foreground`, `text-caption` when mono | Surfaces → Top bar | `app-shell.tsx:76`, `breadcrumbs.tsx:17,29` |
| Palette trigger | `h-8 rounded-md border-border-strong bg-background`, label "Search…" in `text-placeholder`, `Kbd` "⌘K". Icon-only 32 px below 768 px | Components → Input, kbd | `command-palette.tsx:74-88` |
| Palette rows | name `font-medium`; repo and PR `text-foreground-secondary`; drop the IdChip colour override | Where each text level goes | `command-palette.tsx:110-113` |
| Main | `px-4 py-6 md:px-8` | Surfaces → Page | `app-shell.tsx:93` |
| Drawer badge | an 8 px `bg-status-waiting` dot with the count in the button's `aria-label` ("Open navigation, 3 waiting") | Type scale (no `text-[10px]`) | `app-shell.tsx:29-38` |
| Sticky offsets | `top-14` → `top-12`, `top-20` → `top-16`, `scroll-mt-20` → `scroll-mt-16` | 48 px bar | inventory → Hard-coded values |
| Not found, error | `app/not-found.tsx`: PageHeader "Page not found" plus EmptyState (`FileQuestionIcon`, "This page does not exist.", "Go to runs"). `app/error.tsx` (client): `ErrorState` with Retry calling `reset()` | States everywhere (CLAUDE.md rule 5) | new files |

**Widths:**
- 375 px: drawer, `px-4`, icon-only palette trigger.
- 768 px: drawer, `px-8`, full palette field.
- 1440 px: a 240 px sunken sidebar and content up to 1600 px.

The sidebar keeps its labels (no icon rail at desktop widths). Above about 1900 px the header band's border ends at the content edge, as `max-w-content` does.

**Edge cases:**
- Long workspace name: `truncate` (exists).
- Count over 99: "99+".
- Dark mode: sunken `#0f0f11` beside background `#09090b`, separated by `border` `#27272a`.

## 2. Runs list (`/runs`: `runs/runs-view.tsx`, `run-views.tsx`, `run-filters.tsx`, `runs-list.tsx`)

**Today:** PageHeader "Runs" with New run (`runs-view.tsx:103-112`). Below it, the hand-rolled pill tabs and two `NativeSelect size="sm"` filters share one `lg:flex-row` line (`:124`). Then the table (`runs-list.tsx:202-270`), not in a card, or cards below 768 px (`:316-334`).

| Part | Change | Why | Files |
|---|---|---|---|
| Header band | Title "Runs", the description, New run (ink). The view tabs (All, Running, Needs approval, Failed with counts) go in PageHeader's `tabs` slot, styled with `tabsTriggerVariants`, count `text-meta font-normal text-muted-foreground` | Tabs; page header band | `runs-view.tsx:103-131`, `run-views.tsx:24-58` |
| Filters | A row under the band: one `FilterChip` per active filter ("Template: Generate docs ×", "Repo: owner/name ×") and "+ Filter" (Template, Repository; Repository hidden when GitHub is not connected, as today `run-filters.tsx`). "Clear filters" becomes a ghost `sm` button after the chips, shown when any chip is shown. Same URL params | Components → Filter chip, "+ Filter" | `run-filters.tsx:33-106` |
| Table | Bordered by the Table primitive. Status: StatusBadge. Run: name `font-medium text-foreground`, under it IdChip (in-row, 12 px) and trigger in `text-caption text-foreground-secondary`. Repository: `font-mono text-caption text-foreground-secondary`, branch under it the same. Started, Duration and Cost: `text-foreground-secondary`; "· waited …" `text-status-waiting` while waiting, else `text-foreground-secondary`. "—": `text-placeholder`. Pull request: `text-foreground hover:underline` plus a `size-3` external icon. Menu: `icon` (32 px) ghost | Where each text level goes; Links; Icon button | `runs-list.tsx:42-190, 241-266` |
| Cost with no model calls | an ended run with zero tokens and `cost_complete` shows "$0.00" (`Money usd={0}`) and the tooltip "No model calls" | No empty values (content rules) | `runs-list.tsx:168-174` |
| Date headers | `text-caption font-semibold text-foreground-secondary bg-surface-subtle`, sticky `top-12` from 1024 px | Tables | `runs-list.tsx:197-198,232,322` |
| Cards (< 768 px) | Card primitive (8 px, border); meta line `text-caption text-foreground-secondary` | Cards | `runs-list.tsx:277-290` |

**Widths:**
- 375 px: tabs scroll sideways with the edge fade; chips wrap; cards.
- 768 px: table in its own scroll box.
- 1440 px: the table fits; date headers stick under the 48 px bar.

**States and edges:**
- Loading, error and the per-view empty states use the new EmptyState, e.g. title "Nothing needs approval", line "Gates waiting on you show here.", action "Show all runs" (ink). The filtered empty state reads "No runs match these filters" with "Clear filters".
- Long names truncate (`max-w-72`, exists); long repos truncate with `title` (exists).
- Live: SSE updates rows and counts; a count change does not shift the tabs (`tabular-nums`).
- Dark: header `#141416`, dividers `#1c1c1f`.

## 3. New run sheet (`?new=1`, `?template=`: `runs/new-run/*`, `forms/schema-form/*`)

**Today:** a 480 px right sheet, or a full-height bottom sheet below 768 px (`new-run-sheet.tsx:346`). The "Existing repo / New repo" pill tabs are at `:231`. Cancel is ghost (`:467`). The repo combobox trigger is an outline button (`repo-combobox.tsx:54`). Labels are 14 px (`ui/label.tsx:12`).

| Part | Change | Why | Files |
|---|---|---|---|
| Sheet | `size="sm"` (480 px); header `bg-surface-subtle py-3`, title 16/600; footer `border-t` from the primitive | Cards and panes; hard-coded sizes | `new-run-sheet.tsx:346,459,466` |
| Checklist | h3 `text-meta font-medium`; list `divide-divider`; why-line `text-meta text-foreground-secondary` | Type; text levels | `connection-checklist.tsx:69,72,89` |
| Repo mode | `Tabs variant="segmented"` | Segmented control (form choice) | `new-run-sheet.tsx:231` |
| Repo combobox | trigger in the Input look (`h-8 rounded-md border-border-strong text-meta font-normal`); "Select a repository" in `text-placeholder`; chevron `text-muted-foreground`; default branch `text-caption text-foreground-secondary` | Input | `repo-combobox.tsx:54-76,102`; `ui/command.tsx:66` |
| Fields | FieldLabel 13/500, help 12 px muted, error `text-caption text-status-failed` | Type → form labels | primitives; `schema-fields.tsx:23-30` |
| Footer | Cancel `outline`; Start run default (ink) | Secondary button | `new-run-sheet.tsx:467` |

**Widths:** 375 px is a full-height bottom sheet; from 768 px it is a 480 px side sheet. Nothing else changes between 768 and 1440 px.

**Edges:**
- Unsupported schema: ErrorState (exists).
- Disabled Start run: `disabled:opacity-50` on ink.
- A 422 lands on its field (exists).
- Dark: the sheet is `popover` `#111113`.

## 4. Templates (`/templates`: `templates/templates-view.tsx`, `template-gallery.tsx`)

**Today:** `grid gap-4 md:grid-cols-2` (`template-gallery.tsx:125`) of Cards (`rounded-xl ring`). The icon tile is `bg-muted/40` (`:65`), the footer `bg-muted/50`, and "Requires" is `text-xs` (`:76`).

| Part | Change | Why | Files |
|---|---|---|---|
| Grid | `md:grid-cols-2 xl:grid-cols-3` | Full width (two 700 px cards at 1440 px read as banners) | `template-gallery.tsx:125` |
| Card | primitive look; icon tile `size-9 rounded-lg border bg-surface-subtle`, icon `text-foreground-secondary`; title 16/600; description `text-meta text-foreground-secondary`; footer `bg-surface-subtle`; "Requires" `text-caption font-medium text-muted-foreground`; chips keep their outline edge with `text-caption font-medium` | Cards; text levels | `template-gallery.tsx:34-88` |
| Loading | skeleton `rounded-lg` | Card radius | `template-gallery.tsx:111` |

**Widths:** one column at 375 px, two at 768 px, three at 1440 px.

**Edges:**
- Long description: no clamp. Two templates exist today, so add `line-clamp-3` with a `title`.
- Empty: EmptyState with the title "No templates yet".
- GitHub return Alert: default or destructive with the new tokens (`templates-view.tsx:48-63`).

## 5. Inbox (`/inbox`: `inbox/inbox-view.tsx`, `inbox-review.tsx`)

**Today:**
- Layout: list and review side by side from 1024 px, `lg:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]` (`inbox-view.tsx:90`).
- List: `bg-card divide-y`. The selected entry is a `bg-muted` fill only (`:147-148`). Meta is muted (`:154,162`).
- Review: a pane `rounded-lg border bg-card p-4` with no header row (`inbox-review.tsx:120`). The two StatTiles are separate cards (`:140-150`). Branches and paths use `break-all` (`:205,231`).

| Part | Change | Why | Files |
|---|---|---|---|
| Grid | `lg:grid-cols-[var(--container-inbox-list)_minmax(0,1fr)]` | No hard-coded sizes | `inbox-view.tsx:90` |
| List | `rounded-lg border bg-card divide-y divide-divider`. Entry: title `text-meta font-medium`; workflow and repo `text-foreground-secondary` (repo mono 12 px); `WaitingTime` `text-status-waiting`; `ExpiresIn` `text-foreground-secondary`. Hover `bg-muted`; selected `bg-surface-subtle` with a 2 px primary bar and `aria-current` | Rows; text levels | `inbox-view.tsx:136-167` |
| Review pane | header row `border-b bg-surface-subtle px-4 py-3`: gate title 16/600, `ExpiresIn` `text-foreground-secondary`, then the workflow and IdChip `text-foreground-secondary`. Body `p-4 flex flex-col gap-4`. The prompt is `text-body text-foreground max-w-prose` | Cards and panes; content is not a caption | `inbox-review.tsx:120-136` |
| "Approving lets the run go on" | label `text-caption font-medium text-muted-foreground`; branches use `TruncatedPath` in `text-foreground-secondary` | Labels 500; paths never wrap | `inbox-review.tsx:190-215` |
| Figures | `StatStrip` of 2: Active time (with `WaitingTime tone="status"` under it) and Cost | Stat tiles | `inbox-review.tsx:140-150` |
| Changed files | `rounded-lg divide-divider`; each path in `TruncatedPath`; status label 12 px | Paths; type | `inbox-review.tsx:224-241` |
| Actions | Approve (ink, `Kbd` A); Reject `destructive` outlined (`Kbd` R); Open run ghost | Destructive action | `decision-controls.tsx:50-101`, `inbox-review.tsx:173-182` |

**Widths:**
- 375 px: the list, with the review below it, scrolled into view on select (exists).
- 768 px: the same.
- 1440 px: a 352 px list beside the review, first gate selected.

**Edges:**
- Empty: EmptyState with the title "Nothing waits for your approval" and "Show all runs" (ink).
- Expiring in under 1 h: `ExpiresIn` stays secondary. It is not status (open to change).
- A decided gate leaves the list and the next is selected (exists).
- Long gate titles truncate; a very long prompt is capped by `max-w-prose` and wraps.
- Dark: the selected entry is `#141416` with the `#fafafa` bar.

## 6. Run console (`/runs/[id]`: `runs/console/*`, `runs/graph/*`, `runs/artifacts/*`, `runs/findings/*`)

### 6.1 Header (`run-header.tsx:110-184`)
- **Today:** PageHeader with the title; StatusBadge and IdChip aside; a muted meta `<ul>` (repo `font-mono text-foreground`, branch muted, at `:143-171`); actions.
- **Change:**
  - Add a 40 px template icon tile before the title (`rounded-lg border bg-surface-subtle`, icon `size-5 text-foreground-secondary`, from `templateIcon(run.template_id)`; nothing for a run with no template).
  - The meta list becomes `text-meta text-foreground-secondary`: repo `font-mono`, branch `font-mono` with a `›` separator in `text-placeholder`, trigger, then "Started 27 min ago".
  - Actions are unchanged. The PR is the ink primary once opened.
  - The header band border sits under the band.
- **Why:** text levels; the band. The icon tile is the mockup's, in neutral colours.
- **Data:** `template_id`, `branch`, `trigger` are all available.

### 6.2 Figures (`run-tiles.tsx:50-305`)
- **Today:** five card tiles in `grid-cols-2 md:grid-cols-3 lg:grid-cols-5` (`:254`), so at 768 px a 3 + 2 grid leaves an empty cell. Output shows "—" / "No pull request"; Cost and Tokens show "—" for a run with no model calls.
- **Change:** one `StatStrip` (5 columns from 1024 px, 3 + 2 from 768 px with the second row split in 2, two-column label/value list below 768 px with Output spanning both columns).

| Tile | Value | Secondary |
|---|---|---|
| Active time | `Duration` | `WaitingTime tone="status"` |
| Cost | `Money`. A run with no model calls shows "$0.00" | "of $5.00 budget", "No budget" or "No model calls" |
| Tokens | `TokenCount`, or "None" when no model ran | in and out, or "No agents ran" |
| Steps | "7 of 7" | running and failed |
| Output | PR → "PR #7" (link) with "Opened"; else created repo; else the last-written artifact's name (mono 13 px, a button that opens its artifact sheet) with "JSON · 1.2 kB"; else "None" with "This run wrote nothing" | |

Only while the spec loads is "—" shown, in `text-placeholder`.
- **Why:** stat tiles; no empty stat tiles; mobile.
- **Data:** inventory → Data rows 1 and 2.

### 6.3 Banner (`run-banner.tsx`)
- Failed: Alert `destructive` with the new tokens; "Go to step" stays a link button.
- Waiting: Alert `variant="waiting"`, `ExpiresIn` in `text-status-waiting`, Review (outline) and "Open in Inbox" (link).
- Expired: Alert default.
- A failed step's name uses `TruncatedPath`-style truncation, not `break-all`.

### 6.4 Body (`run-console.tsx:353-421`)
- **Today:** the left pane has no border or header (`:354-418`). The right pane is a `rounded-lg border bg-card p-4` with no header row (`step-panel.tsx:243-270`). Both tab rows are grey pills.
- **Change:**
  - Both panes are `rounded-lg border bg-card overflow-hidden`.
  - **Left pane:** its tab row (Steps, Graph, Artifacts; underline, icons `size-4`) is the pane header, `bg-surface-subtle px-4` on a `border-b`. Content is `p-2` (Steps) or `p-0` (Graph, Artifacts).
  - **Right pane:** a header row `bg-surface-subtle px-4 py-3 border-b` holds the step name (mono 16/600, `truncate` with a tooltip, not `break-all`), StatusBadge, then the kind, duration and cost in `text-meta text-foreground-secondary`. The step tabs sit under it at `px-4` on their own `border-b`, and a view toggle sits at the right end of that row when the tab has one. Content is `p-4`.
- **Widths:**
  - 1440 px: two panes, 2/5 and 3/5.
  - 768–1279 px: stacked, as today.
  - Below 768 px: selecting a step opens the right pane's content in a full-height bottom `Sheet` (header = the pane header, tabs inside). The list stays in place, and closing the sheet returns focus to the row. `?step=` still drives it.

### 6.5 Step list (`step-list.tsx`)
- Row: `rounded-md`, hover `bg-muted`. Selected: `bg-surface-subtle` with `shadow-[inset_2px_0_0_var(--primary)]` (the 2 px ink bar) and `aria-current`.
- Kind icon in `text-foreground-secondary`. Name `font-mono text-meta font-medium`.
- One-liner `text-meta text-foreground-secondary`; duration and cost `text-caption text-foreground-secondary`.
- Scope headings `text-caption font-semibold text-foreground-secondary`. Live line `text-foreground-secondary`.
- **Tree lines** (asked in review): nested rows hang off their parent as in a file tree. A 1 px `border-strong` line runs down from each parent's status icon to its last child, an elbow leads into each child's icon, and the line stops at the last sibling.
- **One-liners** (`step-entries.ts:228-267`). After this, two steps never read the same unless they did the same:

| Step | Line |
|---|---|
| Tool node with a findings result | from the parsed report: "Linted 3 modules · 2 findings", "No secrets found", "Checked 41 dependencies · 1 finding". It falls back to `describeTool`. |
| Agent with an `output_schema` | "Answered with 4 findings" when the answer is a findings report, else "Answered (JSON)" plus the role's first words. Never the JSON's first line. |
| Two identical lines left in one list | the step's scope (branch or item id) is appended in mono. |

### 6.6 Output tab (`step-output.tsx`, `findings/findings-view.tsx`, `artifacts/artifact-cards.tsx`)
- Section labels ("Files written", "Artifacts written", "Checked") are 12/500 muted. Child and route names get `font-medium`. Totals and route reasons are `text-foreground-secondary`. Written-file cards: the name in `TruncatedPath` 500, facts in secondary.
- **Findings:**

| Part | Today | Target |
|---|---|---|
| Severity counts | 5 StatTiles, zeros included (`findings-view.tsx:232`) | one line: "1 High · 1 Medium · 0 Critical · 0 Low · 0 Info". Non-zero counts `text-foreground font-medium`, most severe first, then zero counts `text-placeholder`; each with its SeverityBadge icon |
| Table or cards | by viewport (`:252-257`) | the findings container is `@container`: table at `@[720px]`, cards below. At 1440 px in the 3/5 pane (about 560 px) that means cards |
| Path | `break-all` (`:124,166`) | `TruncatedPath` with `:line` |
| Rule | `break-all` (`:50,56`) | mono chip `whitespace-nowrap`, truncating with a tooltip, still a link |
| Sources | Confidence column plus "Found by 2 of 3: lint, reviewer" (`:83-87,107,119-123,160-163`) | no Confidence column or "% confidence"; one line "2 of 3 scans: lint, reviewer" in `text-caption text-muted-foreground`. Sorting by confidence stays (`findings.ts:119-124`) |
| Checked | ragged list, duplicates, `.` (`:175-198`) | a `dl` grid (`grid-cols-[auto_1fr_auto]` from 640 px, stacked below): path (`TruncatedPath`; "repo root" for `.`), tool and source ("repo config" / "platform default"), status. Deduplicated by `(path, kind, tool)` |
| Show JSON (artifact sheet) | outline button above the content (`artifact-cards.tsx:71-80`) | ghost `sm` toggle with `aria-pressed` at the right end of the sheet header row |

### 6.7 Activity tab (`work-block.tsx`, `tool-calls.tsx`, `rail.tsx`)
- Work-block header: `rounded-lg border bg-surface-subtle`, summary `text-foreground-secondary`.
- Tool rows `text-foreground-secondary`; the intent stays `foreground`. Durations `text-caption`.
- Notes `text-foreground-secondary`. Reasoning stays muted italic (tech-stack).
- Failed preview `border-status-failed-border`, preview fill `bg-surface-subtle`. The rail is at `left-2.25`.

### 6.8 Input, Usage and Events tabs
- **Input:** `dt` labels get `font-medium` (`step-input.tsx:16`).
- **Usage:** `StatStrip` of 4 (`step-usage.tsx:27`); the per-step list uses `divide-divider`, names 500 and tokens secondary.
- **Events:** a bordered table with 32 px rows (`raw-events.tsx:176`). The `#`, time and step cells are `text-foreground-secondary`; the count is `text-caption`. Filters stay `NativeSelect` at the default 32 px: they are a panel's controls, not page filters. The drawer is `Sheet size="md"`.

### 6.9 Graph → run map (`graph/run-map.tsx`, replacing `run-graph.tsx` in the tab)
- **Today:** a React Flow canvas laid out by ELK, panned and zoomed inside a `h-[min(70svh,720px)]` box (`run-graph.tsx:89`). It is hard to handle (user review).
- **Change:** the Graph tab renders a tree read left to right, as in Claude Code's agent map (DL → Components → Run map).
  - The run is a root card: workflow name, status dot, active time and cost. Each top-level step hangs off it to the right, in spec order.
  - Containers (map, parallel, loop, router) are cards whose items, branches, iterations or routes hang off them to the right. A router's routes not taken show "Skipped" (muted, dashed dot).
  - Card: status dot, name, one line (duration · tokens or cost once run; the tool or role before).
  - Each card is a `<button>`; selecting one selects its step (as the graph did, `aria-pressed`).
- **Built from** the same timeline and `specParents` the step list uses. No layout engine.
- **Widths:** the map scrolls inside its pane (x and y); cards are 240 px wide, 8 px gaps, 24 px between columns. At 375 px it shows the root's column and scrolls sideways.
- **Footer:** "6 steps · All completed" in `text-caption text-muted-foreground`.

### 6.10 Approval dock and review sheet (`approval-dock.tsx`, `gate-review-sheet.tsx`, `gate-files.tsx`)
- **Dock:** keeps `shadow-dock` (a floating bar). The title is `text-meta font-semibold`; the summary and `ExpiresIn` are `text-meta text-foreground-secondary`. Inner padding `md:px-8`, to match the page. Reject is the outlined destructive button.
- **Review sheet:** the file list's selected row uses the selected-row style. The diff file header is `bg-surface-subtle`. Paths use `TruncatedPath`. The "Edited" badge is `secondary` (now with an edge).

**Console edge cases:**
- **Live run:** the stat strip ticks without layout shift (`tabular-nums`). "Jump to latest" keeps its shadow.
- **Long node ids:** truncate with a tooltip.
- **Failed run:** the banner shows above the fold at 375 px (strip as a 2-column list, about 180 px tall).
- **No artifacts:** the Output tile reads "None · This run wrote nothing".
- **Dark mode:** pane headers `#141416` on cards `#111113`; the selected step row's bar is `#fafafa`.
- **Unknown run:** the existing not-found PageHeader plus the new EmptyState.

## 7. Settings (`app/settings/*`, `settings/*`)

**Today:**
- Nav: `SettingsNav`, a 208 px sticky column from 768 px (`app/settings/layout.tsx:13-14`) with a `bg-muted` active row (`settings-nav.tsx:29-32`). Below 768 px it is an underline tab row.
- Cards: `ConnectionCard` uses the Card primitive (`rounded-xl ring`). The badge has no edge (`connection-card.tsx:43`).

| Part | Change | Why | Files |
|---|---|---|---|
| Nav ≥ 768 px | items `text-meta font-medium text-foreground-secondary`; active `bg-background ring-1 ring-border text-foreground` (the sidebar pill); sticky `md:top-16` | Sidebar pattern | `settings-nav.tsx:20-32`, `app/settings/layout.tsx:14` |
| Nav < 768 px | moves into PageHeader's `tabs` slot (underline tabs, edge fade) | Header band | `app/settings/layout.tsx:9-15` |
| SettingsSection | description `text-foreground-secondary` | Text levels | `settings-nav.tsx:53` |
| ConnectionCard | Card primitive; header `py-3 border-b bg-surface-subtle` when it has content; icon tile `bg-surface-subtle`; badge via StatusBadge tones (with an edge); detail `text-meta text-foreground-secondary` | Cards; badges | `connection-card.tsx:17-94` |
| Integrations | repo list `divide-divider`; default branch `text-caption text-foreground-secondary`; status lines secondary; Disconnect and Remove are `destructive` outlined with the solid confirm | Destructive action | `github-connection.tsx:77,94,164,176`; `confirm-dialog.tsx:37,48` |
| Models and pricing | the table inside the card body becomes a `@container`: table at `@[720px]`, cards below. Model id: mono `text-caption font-medium`, truncated with a tooltip. "Custom" badge `outline`. Prices `text-foreground-secondary`; "—" `text-placeholder`. Edit is a ghost `sm` button. "List prices as of" `text-caption` | Content rules; text levels | `model-pricing.tsx:136-309` |
| Limits and budgets | legend `text-meta font-medium`; units `text-meta text-muted-foreground`; the save bar keeps its shadow; Discard `outline` | Type; secondary button | `run-limits.tsx:319-329,418-445` |

**Widths:**
- 375 px: tabs in the band; cards stacked; pricing as cards.
- 768 px: nav column plus content; pricing switches to the table only when its card is at least 720 px wide.
- 1440 px: pricing table with no scroll of its own (`layout.spec.ts:150-163`).

**Edges:**
- Provider not configured: a muted card with the reason (exists).
- Long model ids: truncated with a tooltip.
- Unsaved changes: the bar appears (exists).

## 8. Audit log (`/audit`: `audit/audit-view.tsx`, `audit-filters.tsx`, `audit-list.tsx`)

**Today:** the filters are a `NativeSelect size="sm"`, a mono run-id `Input` (`text-xs`) and From/To date inputs (`audit-filters.tsx:52-131`). The table is not in a card (`audit-list.tsx:75`). The Time, Actor and Details cells inherit `foreground`; the IdChip is indigo.

| Part | Change | Why | Files |
|---|---|---|---|
| Header | Refresh `outline` in actions (exists) | — | `audit-view.tsx:56-74` |
| Filters | chips plus "+ Filter": Category (list), Run (id input in a popover, mono), Date range (two date inputs in a popover; chip reads "Oct 20 – Oct 28" via `@/lib/locale`). Same URL params; the inline error shows under the popover input in `text-caption text-status-failed` | Filter chip | `audit-filters.tsx:52-142` |
| Table | bordered (primitive). Action is the row's name: `font-medium`, icon secondary. Time, Actor ("System") and Details are `text-foreground-secondary`. "—" `text-placeholder`. Run: IdChip link plus template and repo `text-caption text-foreground-secondary` | Text levels | `audit-list.tsx:21-108` |
| Cards (< 768 px) | Card primitive; meta `text-caption text-foreground-secondary`; details `text-meta` | Type | `audit-list.tsx:111-132` |

**Widths:** cards at 375 px; a table from 768 px with fixed `w-28/w-44/w-20/w-44` columns (exists); unchanged at 1440 px.

**Edges:**
- Empty: EmptyState, title "No activity yet". Filtered: "No activity matches these filters" with "Clear filters".
- Details clamp to 2 lines with a `title` (exists).
- Not live: Refresh (exists).
