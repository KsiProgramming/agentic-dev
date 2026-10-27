# Plan: Run console v3

After each group the console still works, and its Vitest and e2e tests are green.

## 1. Pure helpers (no visible change)
- [x] `src/runs/console/step-entries.ts`:
  - `stepEntries` (the list's rows in run order, a scope with several steps as a heading), `stepKey` by scope, `findEntry`, `stepRows`;
  - `defaultEntry(entries, live)` (running, waiting gate, failing, last agent answer) and `failingEntry`;
  - `stepOutline`: the one line on what each step did (the error, the gate decision, "2 of 3 items", the last message's first line, the `describeTool` line)
- [x] `src/runs/console/written-files.ts`: `writtenFiles(step)` from `repo.write_file` turns (last write per path, failed writes skipped, kind from the extension)
- [x] `src/runs/console/run-stats.ts`: steps done of total (from `nodeStatuses`) and `pullRequestNumber`
- [x] `src/runs/console/event-rows.ts`: a raw row's type, step, time from the start and one-line summary; `summarizePayload` no longer returns JSON (a tool call as its `describeTool` line, a JSON result as "JSON, N entries", other payloads as `key: value`)
- [x] Vitest (`step-entries.test.ts`, `summarize.test.ts`) on `fixtures/docs-run.json` and small hand-made timelines (map, loop, parallel, failed, waiting)

## 2. Header, stat tiles and banner
- [x] `run-header.tsx`: title with status and `IdChip` beside it (`PageHeader` takes an `aside`), repo › branch, trigger and start time. Actions: PR (primary), Rerun or Cancel, and "⋯" (`DropdownMenu`: Copy link, Download events)
- [x] `run-tiles.tsx`: five `StatTile`s (Active time with time waited, Cost against the budget, Tokens, Steps, Output), 2 columns, 3 from 768 px, 5 from 1024 px
- [x] `run-banner.tsx`: failed (step, reason, Go to step), waiting (title, `ExpiresIn`, Review, Open in Inbox) and expired. It replaces the alerts in the Timeline tab
- [x] `run-console.test.tsx` covers the header, tiles and banner; `headerFacts` keeps its behaviour

## 3. Two-pane body and step list
- [x] `step-list.tsx`: rows (status icon, type icon, name, outline, `Duration` or time waited, `Money` with `focusable={false}`), nesting for items, iterations and branches, `aria-current` on the selected row, and the activity line at the end
- [x] `run-console.tsx`:
  - the layout: two panes from `xl` (1280 px), stacked below;
  - the Steps | Graph switch (`?view=`);
  - the selection from `?step=`, else `defaultEntry`, following the running step until the user picks one; below 1280 px, selecting scrolls to the step;
  - the old `?tab=graph` and `?tab=raw` mapped to the new URLs
- [x] `RunGraph` takes `selected` (`aria-pressed` and a ring on the node) and its `onOpen` selects the step that needs attention first. `node-detail-sheet.tsx` removed
- [x] The waiting marker sits in the waiting gate's Output; "Jump to latest" is unchanged

## 4. Selected step panel
- [x] `step-panel.tsx`: a header (name, status, kind, duration, cost) and the tabs Output, Activity, Input, Usage and Events (`?tab=`)
- [x] `step-output.tsx`:
  - the last message as Markdown, capped at 480 px past 1,200 characters or 20 lines, with "Show full output" / "Show less";
  - a tool's result; a gate's decision and edits; a container's children, each selecting its step (`childRows`);
  - written-file cards opening a sheet with the content as plain text (mono)
- [x] The other tabs:
  - Activity: `TurnsRail`, what is left of `step-view.tsx` (the nested timeline views went with the Timeline tab);
  - Input (`step-input.tsx`): the map item, iteration, run input and spec node, `JsonView` for JSON;
  - Usage (`step-usage.tsx`): `StatTile`s with `TokenCount` and `Money`, one line per step of a container
- [x] Each tab has its empty state
- [x] Vitest: Output on a finished run, Show full, file cards and the sheet, Activity, Input, Usage

## 5. Raw events
- [x] `raw-events.tsx`:
  - 32 px rows (number, time from start, type, step, summary); the type is a button that opens the drawer (a right-hand `Sheet` with `JsonView`, or a folded row's text and chunks);
  - filters by type and step, the step set to the selected step at first, with "All steps"
- [x] Vitest: no cell holds JSON, the drawer shows the payload and the chunks, the step filter

## 6. e2e and specs
- [x] `e2e/console.spec.ts`: one click from `/runs` shows the agent's output; a failed run's banner and Go to step; no cell of the Events view holds JSON and a payload opens in the drawer; Download events
- [x] `layout.spec.ts`: a failed run's banner is in the first viewport at every width; the graph's selected step and the event drawer fit
- [x] Update `monitor.spec.ts`, `graph.spec.ts`, `gate-edits.spec.ts` and `a11y.spec.ts` (graph, selected step, event drawer) to the new layout; `expiry.spec.ts`, `journey.spec.ts` and `inbox.spec.ts` need no change
- [x] tech-stack: the "Run console" section rewritten (11.6 removed from UI v2) and a decisions-log row. A `CHANGELOG.md` entry
