# Validation: Design language v2

## Done when (from roadmap)
> Every screen matches `specs/design-language.md`:
> - `globals.css` holds its tokens in light and dark;
> - no tab is a grey pill and no badge lacks its edge;
> - stat tiles are one strip;
> - metadata uses `foreground-secondary`;
> - `pnpm lint` rejects `text-[13px]`;
> - axe passes at 375, 768 and 1440 px in light and dark;
> - a report-only run's Output tile names the artifact it wrote.

## Automated checks
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test` green.
- [ ] `no-raw-colors` rule tests: `text-[13px]` and `leading-[18px]` are rejected; `text-[0.85em]`, `text-[0px]` and `text-meta` are accepted. The colour cases from 11.1 still pass.
- [ ] Token check (Vitest, new `app/globals.test.ts`). Read `globals.css` and assert that:
  - every token in inventory §1–3 exists in `:root` and `.dark` with its target value;
  - every `--color-*` named there is in `@theme inline`.
- [ ] Contrast check (same file). Assert that each text token is ≥ 4.5:1 on each surface it is used on, in both themes, computed from the oklch values. The pairs are the inventory §3 matrix: `foreground`, `foreground-secondary`, `muted-foreground` and `placeholder` on `background`, `card`, `surface-subtle`, `surface-sunken` and `muted`; each `status-X` on `status-X-muted` and on `background`.
- [ ] Unit tests updated or added per inventory §7, including:
  - `StatStrip`: 5 tiles at 2 columns, the last spans;
  - `TruncatedPath`: `src/a/b/c.py:12` keeps `c.py:12`; `.` → "repo root"; tooltip has the full path;
  - `FilterChip` / `AddFilter`: add, remove, Escape, and the URL params stay the same;
  - `EmptyState`: title, description, one action;
  - `stepOutline`: "Linted 3 modules · 2 findings"; "Answered with 4 findings"; two identical lines get their scope appended;
  - findings: "2 of 3 scans: lint, reviewer", no "% confidence", Checked deduplicated with "repo root", the severity line with zeros in `text-placeholder`;
  - Output tile: PR, created repo, last artifact (button opens the sheet), "None · This run wrote nothing"; Cost "$0.00 · No model calls" for an ended run with zero tokens and `cost_complete`.
- [ ] `rg "bg-muted p-1|data-\[state=active\]:shadow" web/src` finds only the `segmented` variant in `ui/tabs.tsx`.
- [ ] `rg "border-transparent" web/src/components/ui/badge.tsx` finds nothing.
- [ ] `rg "text-xs|text-sm\b|text-base\b" web/src --glob '!**/*.test.*' --glob '!components/ui/**'` finds nothing. Inside `components/ui`, only `text-base` on inputs below `md` (iOS zoom).
- [ ] `rg "break-all" web/src --glob '!**/*.test.*'` finds nothing for paths, ids or branches (agent text keeps `break-words`).
- [ ] `pnpm test:e2e` green:
  - `a11y.spec.ts` in `mobile-375`, `tablet-768` and `desktop-1440`, light and dark, no serious or critical axe issues;
  - `layout.spec.ts` at 375/768/1024/1440 with no horizontal page scroll, the new dark-375 screenshots, and the new `run-findings-pane-narrow` and `not-found` names;
  - every other spec unchanged in behaviour.
- [ ] CI green on the PR, including the CHANGELOG and roadmap checks.

## Manual checks (per screen against `specs/design-language.md`)

Look at each at 375 and 1440 px, in light and dark, from the `layout-screenshots` CI artifact or `pnpm dev`.

- [ ] **Shell:**
  - sidebar `#f7f7f8` (dark `#0f0f11`) with a right border;
  - the active item is a white pill with a 1 px ring;
  - top bar 48 px;
  - page gutter 32 px from 768 px, 16 px below;
  - `⌘K` field 32 px with a placeholder-coloured label;
  - `/nope` shows the not-found page in the shell.
- [ ] **Text levels:** on Runs, Inbox and the console, names and values are `#18181b`; repo, branch, started, durations and costs are `#3f3f46`; only labels, headers and counts are `#52525b`; "—" is `#6e6e77`. Muted text is at most about a third of the text.
- [ ] **Runs:**
  - view tabs are underlined in the header band;
  - counts are 400 muted;
  - filters are chips plus a dashed "+ Filter";
  - the table is in an 8 px bordered card with a 36 px `#fafafa` header and 40 px rows (32 px compact) split by `#f0f0f2`;
  - date headers are 12/600 and stick under the bar.
- [ ] **New run sheet:** the 480 px side sheet has a tinted header; Existing/New repo is segmented; inputs are 32 px with a `#d4d4d8` edge and 6 px radius; labels are 13/500; Cancel is outlined.
- [ ] **Templates:** 3 columns at 1440 px; 8 px cards with a border and no ring; 16/600 titles; secondary descriptions.
- [ ] **Inbox:** the selected entry has a 2 px ink bar; the review pane has a tinted header row; the figures are one strip with the wait in amber; branches and paths truncate from the left with a tooltip; Reject is red-outlined; the `A` and `R` keys work.
- [ ] **Console frame:**
  - template icon tile; secondary meta line;
  - one stat strip (5 cells at 1440 px, a 2-column list at 375 px with Output spanning);
  - both panes bordered, with tinted header rows and underline tabs;
  - the selected step has an ink bar;
  - below 768 px a step opens in a full-height sheet;
  - a failed run's banner shows without scrolling at 375 px.
- [ ] **Console content:**
  - findings in the 1440 px pane are cards;
  - severities are one line with quiet zeros;
  - "2 of 4 scans" and no "%";
  - the Checked list is a grid that shows "repo root";
  - "Show JSON" is at the right of the sheet header;
  - the two lint steps of an audit read differently;
  - graph nodes have no shadow, and the footer reads "N steps · …";
  - the dock keeps its shadow and Reject is red-outlined.
- [ ] **Audit codebase run** (a report-only run): the Output tile names `report.md` and opens it. Cost reads "$0.00 · No model calls" only when no agent ran.
- [ ] **Settings:** the nav pill matches the sidebar; below 768 px the sub-pages are tabs in the band; connection badges have edges; pricing is cards when its card is under 720 px and a table with no own scroll at 1440 px; the limits save bar keeps its shadow and Discard is outlined.
- [ ] **Audit log:** chip filters (category, run, date range) round-trip through the URL; the table is in a bordered card; Time, Actor and Details are secondary.
- [ ] **Dark mode:** pane headers `#141416` on `#111113` cards; badge edges visible (`#14532d` on `#052e16`, etc.); focus ring `#fafafa`.
- [ ] Open questions 1–4 in requirements.md answered and their answers written into `specs/design-language.md`.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] `specs/tech-stack.md`, `specs/design-language.md`, `specs/mission.md` (principle 10 already lists design-language.md) and `CLAUDE.md` updated in the same PR (plan group 10).
- [ ] The decisions-log row "Primary colour (11.9)" supersedes "Brand accent (11.1)".
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
- [ ] The PR attaches 1440 px light and 375 px dark screenshots of Runs, Inbox, the console (finished and failed), Settings → Models and Audit.
- [ ] No rule from `CLAUDE.md` is broken, or the break is stated in the PR and the spec is updated.
