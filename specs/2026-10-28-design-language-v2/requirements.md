# Design language v2

Roadmap phase: 11.9
Branch: ui-redesign

Reference files: [inventory.md](inventory.md) (the evidence, as tables), [screens.md](screens.md) (each screen before and after). The target look is [`specs/design-language.md`](../design-language.md) ("DL" below). It wins over the mockups in [`mockups/`](mockups/) everywhere.

## Context

UI v2 (11.1–11.8) fixed the information design, but the screens still read as faded. Contrast is not the cause: today's `--muted-foreground` is `#62626c`, 6.0:1 on white (`web/src/app/globals.css:100`). The cause is a flat hierarchy, as the code shows:

| Symptom | Evidence |
|---|---|
| Two text levels only | `text-muted-foreground` appears 165 times in `web/src` (66 of them in the console, findings and artifacts files). Metadata is either muted (Inbox meta at `inbox/inbox-view.tsx:154`, branch at `runs/runs-list.tsx:186`) or full `foreground` (Started, Duration and Cost at `runs/runs-list.tsx:139-174`). No middle level exists (inventory → Tokens). |
| Every surface is white | No `surface-*` token. The sidebar has no fill (`components/shell/app-shell.tsx:70`). Table headers have no fill (`components/ui/table.tsx:32`). Only one of 5 tables sits in a bordered card (`settings/model-pricing.tsx:136`). |
| Badges have no edge | `components/ui/badge.tsx:7` sets `border-transparent`, and `StatusBadge` (`components/status-badge.tsx:74`) and `ConnectionBadge` (`settings/connection-card.tsx:43`) inherit it. |
| Thin, 14 px text | `body` is `text-sm` (`globals.css:174`). Button, Input, Label, Card, Alert, Sheet and Tabs all default to `text-sm` (14 px), against DL's 13 px. Stat-tile labels are weight 400 (`components/display/stat-tile.tsx:22`). |
| Tabs are grey pills | `components/ui/tabs.tsx:22,35` and the hand-rolled `runs/run-views.tsx:25-39`. DL: "No grey segmented pill for tabs". |
| Primary does not anchor | Indigo `--primary` (`globals.css:95`) is also used for links and decoration in 12 places (inventory → Tokens → `text-primary` consumers). |
| Stat tiles float | Each `StatTile` is its own card (`stat-tile.tsx:20`), in 4 grids. Findings show one 24 px tile per severity, zeros included (`runs/findings/findings-view.tsx:232`). |

This phase applies DL to every screen. It depends on nothing open: Milestone 11's other phases and 4.6 are done. It comes before 4.8 and before Milestone 5, so the canvas is built on the new look ("Next up" moves to 11.9).

Drivers: mission principle 8 (calm, enterprise-grade UI; colour for status), principle 10 (the specs govern the work); tech-stack → UI design system.

## Scope

### In scope
- **Tokens** (`web/src/app/globals.css`, light and dark): the new values and 11 new tokens from DL (inventory → Tokens). They are `foreground-secondary`, `placeholder`, `surface-sunken`, `surface-subtle`, `border-strong`, `divider`, and `status-{queued,running,waiting,succeeded,failed,cancelled}-border`. Plus a `text-kbd` scale step, a `--spacing-row-header` (36 px), sheet widths as tokens, body `text-meta` with Inter `cv11`/`ss01` and `tabular-nums`.
- **Ink primary:** `--primary` and `--ring` become `#18181b` (dark: `#fafafa`). Links become `text-foreground` with an underline on hover.
- **Primitives** (`web/src/components/ui`): Button (sizes, outlined and solid destructive, link variant), Badge, Card, Tabs (underline by default, plus `variant="segmented"`), Table (bordered container, 36 px `surface-subtle` header, `divider` rows, `muted` hover), Input, Textarea, NativeSelect, InputGroup, Label, Field, Alert (status tokens, a `waiting` variant), Sheet (header and footer borders, size prop), Dialog, AlertDialog, DropdownMenu, Popover and Command. Per-primitive targets are in inventory → Components.
- **Shared components:** StatusBadge (edge), IdChip (border, 12 px), StatTile plus a new `StatStrip`, EmptyState (new look; `message` is now its title, plus an optional `description`, so its 17 call sites keep their prop), ErrorState, PageHeader (header band, `tabs` slot), JsonView, Kbd, and a new `FilterChip` / `AddFilter` pair. Also a new `TruncatedPath` (truncates from the left, tooltip), `ApproveButton`/`RejectButton`, AgentMessage, FieldMessage, ArtifactCards.
- **Shell:** sidebar on `surface-sunken` with the white active pill; 48 px top bar; 32 px page padding from 768 px; sticky offsets moved to the new bar height; drawer badge on the type scale; `app/not-found.tsx` and `app/error.tsx` built from the states.
- **Screens:** Runs list, New run sheet, Templates, Inbox, run console (header, stat strip, banner, both panes, every tab, work blocks, findings, artifacts, raw events, graph, dock, review sheet), Settings (nav, the three sub-pages) and Audit log. Each is in screens.md.
- **Content rules** from DL, all from data the API already returns (inventory → Data):
  - findings tables become cards by container width;
  - paths truncate from the left;
  - no empty stat tiles: "$0.00 · no model calls"; the Output tile shows the last artifact written;
  - quiet zero counts;
  - one fact per finding ("2 of 4 scans", no confidence %);
  - a deduplicated "Checked" grid with "repo root";
  - distinct step one-liners for tool and JSON-answering steps;
  - "Show JSON" in the tab row.
- **Checks:** `no-raw-colors` also rejects arbitrary text sizes; axe also runs at 768 px; layout screenshots also in dark at 375 px.
- **Specs:** `design-language.md` becomes a constitution file (mission principle 10; tech-stack → Look points to it), the decisions-log rows, the `CLAUDE.md` pointer and a `CHANGELOG.md` entry, all in the implementing PR.

### Out of scope
- New information or screens: no column, filter or action is added or removed, except the filter chips, which replace the selects with the same filters.
- API changes. The investigation found that none is required (inventory → Data). The optional additions are listed below as follow-ups.
- An icon-only sidebar at desktop widths (the mockup's rail): the labelled sidebar stays.
- The mockups' indigo, pill tabs and tinted stat cards (DL wins).
- Per-step waiting time for a loop or map that holds a gate (today it counts in the container's duration, `runs/console/step-list.tsx:93-97`). Follow-up.
- Monaco's diff colours and React Flow internals beyond the tokens already mapped in `globals.css:204-218`.

### Follow-ups (need an API change, not in this phase)
| Item | Change | Where |
|---|---|---|
| Output of a run in the runs list | `RunSummary.output_artifact: str \| null`, the last `artifact_written`, as `pr_url` is set | `packages/store/src/agentic_store/sink.py:96`, `summaries.py:30-183`, `packages/api/src/agentic_api/runs/routes.py:141-166`, `models.py:302`, plus a migration |
| A "primary output" a template names | `WorkflowSpec.output: ArtifactName \| None` (the audit would name `report.md`) | `packages/engine/src/agentic_engine/spec/models.py:1473` |
| Severity counts in the runs list | `RunSummary.findings_counts`, set by the artifact store | `packages/store/src/agentic_store/artifacts.py` |
| Explicit "no model calls" in the list | `RunUsage.model_calls: int` (counted from `usage` events) | `sink.py:181`, `models.py:271-286` |

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where it lives | One phase, 11.9, in Milestone 11 | Asked by the user. The work is a single coherent restyle; plan.md splits it into PR-sized groups that each leave the app working. |
| Primary colour | Ink `#18181b` (dark `#fafafa`) for primary buttons, the selected tab underline, the selected row bar and focus. Supersedes the 11.1 row "Brand accent: Indigo stays" | Asked by the user. With colour kept for status, indigo was the only hue left that is not a status. It read as decoration on links and ids (12 places) and weakened "colour means status". Ink focus is 17.7:1 on white, against 4.6:1 for today's ring. |
| Authority of DL | `specs/design-language.md` becomes the fourth constitution file; tech-stack → Look points to it; the mockups are layout reference only | Asked by the user ("design-language.md always"). |
| API additions | Allowed if small, but none needed: every content rule is met from existing data | inventory → Data. Keeps the phase visual and its risk low. |
| DL edit: `--placeholder` | `#71717a` → `#6e6e77` (`oklch(0.541 0.014 285.9)`) | `#71717a` is 4.4:1 on `muted` (filter chips, kbd, inline code), breaking DL's own "at least 4.5:1 on every surface". `#6e6e77` is 5.1:1 on white and 4.6:1 on `muted`. |
| DL edit: `--surface-sunken` oklch | `oklch(0.976 0 0)` → `oklch(0.976 0.001 286.4)` | The old oklch value renders `#f7f7f7`, not the stated `#f7f7f8`. |
| DL edit: lint reference | "2.7 lint rule" → "11.1 lint rule" | The rule shipped in 11.1 (tech-stack decisions log, "Colour lint (11.1)"). There is no phase 2.7. |
| DL edit: mono under a name | 11.5 px → 12 px | Fractional sizes are off the type scale (CLAUDE.md rule 6). 0.5 px does not justify a token. |
| DL edit: kbd size | A `text-kbd` step, 11/16 px | DL asks for 11 px. Today `decision-controls.tsx:43` uses `text-[11px]`, which the new size lint would reject. |
| DL edit: form labels | 13/20 px weight 500 `foreground` above inputs; 12 px labels stay for tiles and headers | DL had only the 12 px label. `Label` is 14 px today (`ui/label.tsx:12`), and 12 px field labels under 13 px inputs read upside-down. |
| DL edit: card surface | Cards and panes use `card`: white in light, `#111113` in dark | DL said `background` but defines a dark `--card`. Today's dark console pane is already `bg-card` (`step-panel.tsx:243`). Light is unchanged. |
| DL edit: segmented control | Also allowed for a two-way choice inside a form | The New run sheet's "Existing repo / New repo" (`new-run-sheet.tsx:231`) is not a view of the same data, but underline tabs inside a 480 px form would look like page navigation. |
| DL edit: floating bars | The approval dock, the limits save bar and "Jump to latest" keep a shadow | They float over scrolling content (`approval-dock.tsx:53`, `run-limits.tsx:321`, `run-console.tsx:454`). Without a shadow, the dock's edge disappears over a white pane. |
| DL edit: page header band | Full-width bottom `border` under the title row; page tabs sit on it | One of the user's picks. It gives every page the same top edge and gives the runs tabs a home. |
| DL edit: rows | `muted` hover on clickable rows; a selected row is `surface-subtle` with a 2 px `primary` bar on the left | One of the user's picks. Today the selected step and Inbox entry are a fill only (`step-list.tsx:66`, `inbox-view.tsx:147`), which DL's "edges on selected states" rules out. |
| DL edit: EmptyState | A 40 px icon tile, a 16/600 title, an optional 13 px line, one primary action, no dashed box | One of the user's picks. Today it is a dashed box with grey text (`components/states.tsx:25-30`); DL keeps dashed lines for "+ Filter". |
| DL edit: type | `body` is `text-meta` (13 px); Inter `cv11`/`ss01` and `tabular-nums` on `body` | One of the user's picks. DL says UI text is 13 px, but 14 px is inherited by every element without an explicit size (sidebar, breadcrumbs, dialogs). |
| Severity colour | Own `--severity-*` tokens (critical deep red, high orange-red, medium amber, low blue, info grey), with fill, edge and text; supersedes "Severity in the UI (4.4): a neutral badge" | Asked by the user after seeing the first screens: grey severities did not stand out. The colours are separate from the status ones, so "Colour means status only" still holds for statuses, and a Critical finding never looks like a Failed run. Each severity keeps its own icon shape. |
| Run graph | An Agent-map-style tree (left to right, compact cards, elbow lines, no pan or zoom) replaces the React Flow canvas in the Graph tab | Asked by the user: the canvas was hard to handle (pan and zoom inside a box). A tree reads like the step list and scrolls like one. ELK and React Flow are no longer needed for the tab. |
| Mobile breakpoint | Drawer below 1024 px stays; DL's mobile rules apply below 768 px | tech-stack → Layout (`app-shell.tsx:77`); the 1024–1279 px rail covers the gap. |
| Step detail below 1280 px | A full-height bottom sheet below 768 px (DL); stacked under the list from 768 to 1279 px, as today | DL covers phones only. At tablet width the stacked panel has room, and its scroll-into-view already works (`run-console.tsx:213-220`). |
| Output tile without a PR | The artifact the run wrote last (latest `created_at` in `GET /runs/{id}/artifacts`), opening its sheet | Available today with no API change. In an audit that is `report.md`, the readable result. See the open question. |
| Filters | Chips with "+ Filter", replacing the `NativeSelect size="sm"` filters on Runs and Audit | DL → Components. Same filters and URL params; only the control changes. |
| Size lint | Extend `agentic-ui/no-raw-colors` with an arbitrary-text-size check (`text-[…px\|rem]`), allowing `em` values and `text-[0px]` | Keeps rule 6 mechanical. Five current offenders (inventory → Hard-coded values) are fixed in the same PR. |

## Open questions
1. **Succeeded and waiting text contrast drops.** DL's `#15803d` and `#b45309` are 4.8:1 on their fills, where today's values are 6.8:1 and 6.9:1 (`globals.css:116-119`). They still pass AA, but the badges get lighter, which is the problem this phase fixes. Should we keep DL's values, or use `#166534` / `#92400e` (6.8:1 / 6.8:1 on their fills)? The spec assumes DL's values until answered.
2. **Output tile for a report-only run:** is "last artifact written" right (`report.md` for an audit), or should `findings.json` win when present? DL's example names `findings.json`. The spec assumes last-written.
3. **Inter features:** confirm in a browser that the `next/font/google` Inter build (`app/layout.tsx:13`) carries `cv11` and `ss01`. If it does not, drop the setting rather than self-host the font.
4. **Button `sm` (28 px):** 23 call sites use it (inventory → Components → Button), against DL's 32–34 px for buttons. The spec keeps `sm` for in-row and filter actions only and moves page-level actions to `default`. Confirm, or make every button 32 px.
