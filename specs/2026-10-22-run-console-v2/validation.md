# Validation: Run console v2

## Done when (from roadmap)
> A docs run shows one message block per agent turn, not one row per chunk

Made checkable: rendering the recorded docs-run fixture produces exactly one message block per agent turn (turn = text between tool calls, ending in `message`), whose text is the full paragraph(s) — the chunks joined in order. No view shows one row per chunk: the Timeline shows message blocks, and Raw events shows one folded row per run of consecutive deltas.

## Automated checks
The user chose Vitest reducer + component tests as the merge gate. Backend code added here (buffer, cancel) still gets the repo's usual pytest coverage, and the existing CI suites must stay green.

- [x] **Vitest, `buildTimeline`:** on the docs-run fixture, 8 message blocks (3 writers × 2 turns + 2 review rounds) from many more chunks. `message` replaces the merged text. `tool_call`/`tool_result` pair by `call_id` (pending, success, `is_error`). Map items nest under their map node; loop iterations are separate. Duplicate `seq` and unknown types do not change the result. Usage tokens sum per step.
- [x] **Vitest, components and console:**
  - Messages: Markdown renders; raw HTML and `<!-- -->` comments are dropped, never rendered; images dropped; links `target="_blank" rel="noreferrer"`, `javascript:` dropped; caret only while streaming.
  - Tool calls: one line per call, closed until opened, then arguments and result; failed calls marked; running calls say what they are doing; groups summarise ("Read 2 files, listed 1 folder, ran 1 search") and count failures; writes stand on their own line with a preview ("+3 more lines"); reads have no preview.
  - Rail: each step's marker carries its status label for screen readers.
  - `currentActivity`: the latest running step's action, map items named by path, parallel count, `null` once nothing runs.
  - `JsonView` collapses past depth 2 and copies.
  - Header: summary facts before any event, PR link after `pr_opened`, Cancel only while live and only after confirming, failure reason shown.
  - Raw events folds a streamed message into one row with the full text and chunk count (expandable to the chunks), filters by type and node; the tab is kept in the URL.
  - Follow-scroll: the replay neither scrolls nor shows the pill; follows once at the bottom; away from the bottom, new content shows "Jump to latest".
  - 169 web tests pass locally.
- [x] **pytest, delta buffer** (`test_deltas.py`): merge, timer flush, flush before other events, text unchanged, per map item in a real run, flush on cancel, cancel reason.
- [x] **pytest, cancel** (`test_runs.py`, `test_worker.py`): running, waiting at a gate (approval then refused), queued before any worker, unknown → 404, ended → 409, asked twice; kept sandbox discarded. 653 Python tests pass locally (all packages but `sandbox`, whose Docker tests sweep every run sandbox on the host).
- [ ] Existing CI e2e (`layout` screenshots at 375/768/1440, `a11y` axe, `monitor`, `runs-page`) pass in CI. `monitor` was updated for the folded raw rows; the suite was not run locally.
- [x] Lint and types: `ruff`, `pyright` strict, ESLint, Prettier, `tsc` clean; OpenAPI and `schema.d.ts` regenerated.

## Manual / demo checks
- [x] On the local stack (Claude runtime), a real "Generate docs" run on `KsiProgramming/GildedRoseKata`: each agent turn is one message; a module's 16 tool calls are one summary line; the writer's file writes and commit show their first lines; map items read `src/Core dotnet`; steps hang off the rail with status icons; the waiting gate says "Needs approval" with its panel.
- [x] Raw events on a two-node run: each streamed message is one folded row ("text_delta × 6", "× 27") with readable text; 45 events in all.
- [x] A fresh live run shows the activity line ("writer · Thinking…") with a spinner.
- [x] Opening a finished or waiting run lands at the top with no "Jump to latest" pill.
- [x] At 375 px: header actions stack, no horizontal page scroll.
- [ ] Scroll up during a long live run: auto-scroll stops and "Jump to latest" appears; clicking it returns to the bottom and follow resumes (covered by unit tests, not tried by hand).
- [ ] Cancel a running run from the header: confirm dialog, toast, status becomes Cancelled within a few seconds, in the console and on the Runs page (API and worker covered by pytest, not tried by hand).

## Merge criteria
- [ ] All checks above pass in CI.
- [x] No raw palette classes; only tokens and shared components (2.1 rule).
- [x] Agent messages and tool output are never rendered as HTML.
- [x] Cancel never triggers a write action (push, PR) and leaves the event log append-only.
- [x] Roadmap 2.5 is marked `✅ Done` in the implementation PR (#27).
