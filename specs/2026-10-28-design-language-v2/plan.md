# Plan: Design language v2

Ten task groups, in order: tokens, primitives, shared components, shell, screens, then specs. Each is one commit, and can be its own PR if the phase is split. Each group ends with `cd web && pnpm lint && pnpm typecheck && pnpm test` green and the app working. Values and per-file targets are in [inventory.md](inventory.md) and [screens.md](screens.md), and are not repeated here. Before writing Next.js code, read `web/AGENTS.md` and the docs it points to.

## 1. Tokens, type base and checks
- [ ] `web/src/app/globals.css`, as listed in inventory §1–3:
  - new light and dark values;
  - the 11 new colour tokens and their `@theme` lines;
  - `--text-kbd`, `--spacing-row-header`, `--container-sheet-*`, `--container-inbox-list`;
  - `--input` → `var(--border-strong)`, `--destructive` → `var(--status-failed)`, `--secondary`/`--accent` → `var(--muted)`;
  - `body` `text-meta` with `font-feature-settings: "cv11", "ss01"` and `tabular-nums`.
- [ ] Update the comment above `:root` ("indigo for primary actions" → "ink").
- [ ] `web/eslint/no-raw-colors.mjs`: add the arbitrary text-size check (`(text|leading)-\[[\d.]+(px|rem)\]`), message "Arbitrary size: use the type scale". `em` values and `text-[0px]` are allowed. Add cases to `web/eslint/no-raw-colors.test.mjs`.
- [ ] Fix the offenders the rule now finds: `ui/button.tsx:26` (`text-[0.8rem]` → `text-meta`), `shell/app-shell.tsx:37` (dot, screens §1), `decision-controls.tsx:43` (temporarily `text-kbd`).
- [ ] `web/playwright.config.ts`: run `a11y.spec.ts` in `tablet-768` too. `e2e/layout.spec.ts`: add a dark pass at 375 px (`test.use({ colorScheme: "dark" })` for a `-dark` copy of each screenshot name).
- **Visual result:** primary buttons, focus rings and links turn ink. Body text drops to 13 px. Muted text darkens to `#52525b`. Nothing else moves.
- **Tests:** eslint rule tests; axe at 375/768/1440 in both themes passes with the new values.

## 2. Action and form primitives
- [ ] `ui/button.tsx`:
  - base `text-meta` and a 2 px focus ring with offset;
  - `outline` without `dark:input`;
  - `ghost` `text-foreground-secondary`;
  - `link` takes `h-auto px-0`; remove the 4 overrides (gate-decision.tsx:58, run-banner.tsx:44,71, run-console.tsx:149);
  - `destructive` (outlined red) and a new `destructive-solid`;
  - `sm` `rounded-md text-meta`; `icon-sm` 32 px;
  - remove `secondary`, `lg`, `icon-lg`.
- [ ] Move page-level actions to `size="default"` (open question 4). `sm` stays only in rows, filters and dense toolbars. List the call sites moved in the PR.
- [ ] `ui/input.tsx`, `textarea.tsx`, `native-select.tsx` (drop the `sm` size only after group 6 replaces the filters; until then keep it at `h-7 rounded-md`), `input-group.tsx`: the Input target.
- [ ] `ui/label.tsx`, `ui/field.tsx`: the Label, FieldDescription, FieldError and checked-label targets.
- [ ] New `ui/kbd.tsx`; use it in `decision-controls.tsx:41-47` and `command-palette.tsx:88`.
- [ ] `ui/badge.tsx`: `h-6 text-caption border`; `secondary` neutral with an edge; remove the unused variants. Drop the height overrides at `connection-card.tsx:43`, `model-pricing.tsx:257` and `template-gallery.tsx:34`.
- [ ] `ui/alert.tsx`: `destructive` on status tokens, the new `waiting` variant, description `text-foreground-secondary`. Drop the overrides at `states.tsx:68-70`, `github-connection.tsx:255` and `templates-view.tsx:59`.
- [ ] `ui/alert-dialog.tsx`: Action `destructive` → `destructive-solid` (cancel-run-button.tsx:66, confirm-dialog.tsx:48).
- **Visual result:**
  - inputs get the stronger edge and 6 px radius;
  - Reject, Disconnect and Remove read red;
  - confirm buttons are solid red;
  - badges get their outline (StatusBadge edge colour comes in group 4).
- **Tests:** `templates-view.test.tsx` and `states.test.tsx` still pass; snapshot-free.

## 3. Surface primitives
- [ ] `ui/card.tsx`: radius, border, header row, title, description, footer.
- [ ] `ui/table.tsx`:
  - bordered container with a `bordered` prop;
  - `TableHeader` on `surface-subtle`, its rows never hover;
  - `h-row-header`, `px-3`;
  - rows `border-divider hover:bg-muted`.

  Then remove the 5 redundant `className="text-meta"`, the 5 `hover:bg-transparent` and the `model-pricing.tsx:136` border wrapper.
- [ ] `ui/tabs.tsx`:
  - the `line` default, with the edge fade on overflow;
  - `variant="segmented"`;
  - export `tabsListVariants` and `tabsTriggerVariants`;
  - one content spacing (`pt-3`).

  Set `new-run-sheet.tsx:231` to segmented and drop the `pt-*` overrides.
- [ ] `ui/sheet.tsx`: header and footer borders, header fill, title and description, and the `size` prop. Replace the 6 `border-b pr-12` and 2 `border-t` overrides and the 5 width literals.
- [ ] `ui/dialog.tsx`, `dropdown-menu.tsx`, `popover.tsx`, `command.tsx`: border instead of ring, `rounded-lg`, `text-meta`, `focus:bg-muted`, `bg-divider` separators.
- **Visual result:**
  - tabs everywhere become underline tabs;
  - tables sit in bordered cards with tinted headers;
  - sheets and dialogs get header bands.
- **Tests:** `run-console.test.tsx:176,331,858` and `templates-view.test.tsx:242` (tab roles unchanged); `runs-list.test.tsx` (table names unchanged).

## 4. Shared components
- [ ] `components/status-badge.tsx`: `border-status-X-border` per tone. Export the tone map for `settings/connection-card.tsx` and use it there.
- [ ] `components/display/id-chip.tsx`: the three forms (copy, link, in-row). Drop the overrides at `audit-list.tsx:52` and `command-palette.tsx:112`.
- [ ] `components/display/stat-tile.tsx` plus new `stat-strip.tsx`: the strip, the 2-column mobile list with a spanning odd tile, and `tone` on the secondary line. Add `tone="status"` to `waiting-time.tsx`. A tile loses its own border here, so swap all 4 grids for `StatStrip` in this group (`run-tiles.tsx:254`, `inbox-review.tsx:140`, `step-usage.tsx:27`, `findings-view.tsx:232`). Their content changes come in groups 7–9.
- [ ] `components/states.tsx`:
  - EmptyState: new look; `message` → `title` plus optional `description`; update all 17 call sites with the wording in screens.md; make their actions default buttons;
  - ErrorState: Retry `outline` default size.
- [ ] `components/page-header.tsx`: the band (`-mx-4 -mt-6 px-4 pt-6 md:-mx-8 md:px-8 border-b`), the description in `text-meta text-foreground-secondary`, and the `tabs` slot.
- [ ] `components/json-view.tsx`, `runs/console/agent-message.tsx`, `forms/schema-form/schema-fields.tsx` (FieldMessage), `runs/artifacts/artifact-cards.tsx` (cards): their targets in inventory §4.
- [ ] New `components/display/truncated-path.tsx`, built with `ValueTooltip`: it keeps the file name, drops leading segments with `…/`, and renders `.` as "repo root".
- [ ] New `components/filters.tsx` (`FilterChip`, `AddFilter`), on the DropdownMenu and Popover primitives.
- [ ] Export `templateIcon` from `templates/template-gallery.tsx` (to a new `templates/icons.ts`).
- [ ] Update the `CLAUDE.md` rules 3 and 5 rows for `StatStrip`, `TruncatedPath` and the EmptyState props.
- **Visual result:**
  - stat tiles become strips;
  - empty states get the icon tile;
  - every page title sits in a bordered band.
- **Tests:** `status-badge.test.tsx:16`, `display.test.tsx` (StatStrip, TruncatedPath, IdChip forms), `states.test.tsx`, `page-header.test.tsx` (tabs slot). New tests for `filters.tsx` (add, remove, keyboard).

## 5. Shell
- [ ] `components/shell/sidebar.tsx`, `user-menu.tsx`, `app-shell.tsx`, `breadcrumbs.tsx`, `command-palette.tsx`: the targets in screens §1. That covers the sunken sidebar and white active pill, the 48 px bar, 32 px padding, the palette field and the drawer dot.
- [ ] Sticky offsets: `runs-list.tsx:198`, `app/settings/layout.tsx:14`, `inbox-view.tsx:97`, `run-console.tsx:421`.
- [ ] New `app/not-found.tsx` and `app/error.tsx`. Read the Next.js docs in `node_modules/next/dist/docs/` for both conventions first.
- **Visual result:** a tinted sidebar with a clear active item, a lower top bar and a wider gutter.
- **Tests:** `app-shell.test.tsx` (roles unchanged; drawer button label now includes the count); `layout.spec.ts:39` (rail labels), sticky checks; new `not-found` screenshot.

## 6. Runs list, New run sheet, Templates
- [ ] `runs/runs-view.tsx`, `run-views.tsx`: the tabs move into the PageHeader slot and use the shared tab variants.
- [ ] `runs/run-filters.tsx`: chips plus "+ Filter". Then remove `NativeSelect` `size="sm"`.
- [ ] `runs/runs-list.tsx`: cells, date headers, PR link, menu size, cards, and "$0.00 · No model calls" (screens §2).
- [ ] `runs/new-run/*`, `forms/schema-form/*`: screens §3.
- [ ] `templates/template-gallery.tsx`: 3 columns from 1280 px, the card treatment.
- **Visual result:** the Runs page reads in three levels; filters are chips; template cards are calmer.
- **Tests:** `runs-list.test.tsx`, `runs-view.test.tsx` (filters), `templates-view.test.tsx`; `e2e/runs-page.spec.ts` (view links are in the band, same text).

## 7. Inbox, Settings, Audit log
- [ ] `inbox/inbox-view.tsx`, `inbox-review.tsx`: screens §5 (selected row, pane header, StatStrip, TruncatedPath, Reject outlined red).
- [ ] `app/settings/layout.tsx`, `settings/*`: screens §7 (nav pill, mobile tabs in the band, ConnectionCard, pricing container query, limits).
- [ ] `audit/audit-filters.tsx`, `audit-list.tsx`: screens §8.
- **Visual result:** these three screens match DL.
- **Tests:** `inbox-view.test.tsx`, `audit-view.test.tsx`, `settings/*.test.tsx`; `e2e/inbox.spec.ts`, `audit.spec.ts`; `layout.spec.ts:130-163` (settings nav, pricing fit).

## 8. Run console: frame
- [ ] `runs/console/run-header.tsx`: the template icon tile and the secondary meta line.
- [ ] `runs/console/run-tiles.tsx`: `StatStrip`; Cost, Tokens and Output per screens §6.2 (Output reads `useRunArtifacts`, the last `created_at`, and opens `ArtifactSheet`).
- [ ] `runs/console/run-banner.tsx`: the variants.
- [ ] `runs/console/run-console.tsx`, `step-panel.tsx`: the bordered panes with header rows, the tab rows, and the below-768 px step sheet (`useMediaQuery(MD_UP)`, focus back to the row on close).
- [ ] `runs/console/step-list.tsx`, `activity-line.tsx`: the row states and text levels.
- [ ] `runs/console/step-entries.ts`: the one-liner rules in screens §6.5.
- **Visual result:** the console frame matches DL; a report-only run's Output tile names its artifact.
- **Tests:**
  - `run-console.test.tsx:215-222` (labels unchanged) plus new Output and Cost cases;
  - `step-entries.test.ts` and `step-view.test.tsx` (new lines, `aria-current`);
  - `e2e/console.spec.ts` and `layout.spec.ts:292-316` (dock and panel fit).

## 9. Run console: content
- [ ] `runs/findings/findings-view.tsx`, `findings.ts`: the severity line, container-query table and cards, TruncatedPath, the "N of M scans" line (no confidence), the Checked grid with dedup and "repo root".
- [ ] `runs/artifacts/artifact-cards.tsx`: the "Show JSON" ghost toggle in the sheet header row.
- [ ] `runs/console/step-output.tsx`, `work-block.tsx`, `tool-calls.tsx`, `rail.tsx`, `step-input.tsx`, `step-usage.tsx`, `raw-events.tsx`: screens §6.6–6.8.
- [ ] `runs/graph/graph-nodes.tsx`, `run-graph.tsx`: no node shadow, the tinted containers and the footer line.
- [ ] `runs/console/approval-dock.tsx`, `gate-review-sheet.tsx`, `gate-files.tsx`, `decision-controls.tsx`: screens §6.10.
- **Visual result:** every console tab matches DL; findings read as cards in the pane at 1440 px.
- **Tests:**
  - `findings.test.tsx` (strings and structure, see inventory §7);
  - `artifacts.test.tsx`, `run-graph.test.tsx`, `port-errors.test.tsx`, `route-choice.test.tsx`;
  - `e2e/graph.spec.ts`, `monitor.spec.ts`, `gate-edits.spec.ts`;
  - new layout screenshot `run-findings-pane-narrow` at 1440 px.

## 10. Specs and docs (in the same PR as the code; if the phase is split, each PR carries its part)
- [ ] `specs/tech-stack.md` → UI design system:
  - Look: "one accent colour (indigo)" becomes ink; Look points to `specs/design-language.md` for values;
  - Layout: 48 px bar, 32 px padding, header band;
  - Display values: `StatStrip`, `TruncatedPath`;
  - Start and settings: filter chips;
  - Run console: the Output tile, one-liners, findings sources line, mobile step sheet, graph footer;
  - "How the rules are enforced": the size check, axe at 768, dark screenshots;
  - decisions log rows: "Primary colour (11.9)" superseding "Brand accent (11.1)", "Size lint (11.9)", "Output tile (11.9)", "Step sheet below 768 px (11.9)".
- [ ] `specs/design-language.md`: drop the "Status" paragraph; resolve open questions 1–4 in it.
- [ ] `CLAUDE.md`: name `specs/design-language.md` in "Specs are the source of truth" and in the Frontend section; rule 1 lists the new tokens; rule 6 names `text-kbd`.
- [ ] `CHANGELOG.md` → `[Unreleased]` → `Changed`: "Phase 11.9 Design language v2" with one line per screen group.
- [ ] `specs/roadmap.md`: 11.9 is marked done by CI on the PR. Set "Next up" back to Milestone 4 at 4.8.
