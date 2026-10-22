# Validation: Run console v2

## Done when (from roadmap)
> A docs run shows one message block per agent turn, not one row per chunk

Made checkable: rendering the recorded docs-run fixture produces exactly one message block per agent turn (turn = text between tool calls, ending in `message`), whose text is the full paragraph(s) — the chunks joined in order. No view shows one row per chunk: the Timeline shows message blocks, and Raw events shows one folded row per run of consecutive deltas.

## Automated checks
The user chose Vitest reducer + component tests as the merge gate. Backend code added here (buffer, cancel) still gets the repo's usual pytest coverage, and the existing CI suites must stay green.

- [ ] **Vitest, `buildTimeline`:** on the docs-run fixture, the number of message turns per step equals the number of agent turns, and no turn holds a single chunk when the fixture streamed several. `message` replaces the merged text. `tool_call`/`tool_result` pair by `call_id` (pending, success, `is_error`). Map items nest under their map node with their own turns; loop iterations are separate. Duplicate `seq` and unknown types do not change the result. Usage tokens sum per step.
- [ ] **Vitest, components:** a message with `<script>`/`<img onerror>` renders as text (no raw HTML). Links get `target="_blank" rel="noreferrer"`. Tool card is collapsed by default, expands with keyboard, Copy writes the JSON. `JsonView` collapses past depth 2. Header shows PR link only after `pr_opened`; Cancel only for live statuses and asks for confirmation. Raw events tab folds a streamed message into one row with the full text and chunk count (expandable to the chunks), filters by type and node, and the tab survives a reload via `?tab=raw`. "Jump to latest" appears when scrolled up and new content arrives.
- [ ] **pytest, delta buffer:** see plan group 4 (merge, timer flush, flush-before-other-events, text unchanged, per map item, flush on cancel).
- [ ] **pytest, cancel:** see plan group 5 (running, waiting, ended → 409, unknown → 404, idempotent).
- [ ] Existing CI e2e (`layout` screenshots at 375/768/1440, `a11y` axe, `monitor`, `runs-page`) pass, updated where they relied on per-event rows.
- [ ] Lint and types: `ruff`, `pyright`/`mypy` strict, ESLint, Prettier, `tsc`; the OpenAPI/schema-is-current check is green.

## Manual / demo checks
- [ ] `docker compose up`, start a "Generate docs" run on the fake runtime, open it from the Runs page: each agent turn is one growing message, tool calls are collapsed cards, map items are nested under the map node.
- [ ] Switch to Raw events: each streamed message is a single row with readable paragraph text (no row per chunk); expanding it lists the chunks; filters by type and node work; the event count is much lower than before the buffer (deltas merged per 250 ms).
- [ ] Scroll up during a live run: auto-scroll stops and "Jump to latest" appears; clicking it returns to the bottom and follow resumes.
- [ ] Cancel a running run from the header: confirm dialog, toast, status becomes Cancelled within a few seconds, both in the console and on the Runs page.
- [ ] Check the page at 375 px: header actions stack, JSON scrolls in its box, no horizontal page scroll.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] No raw palette classes; only tokens and shared components (2.1 rule).
- [ ] Agent messages and tool output are never rendered as HTML.
- [ ] Cancel never triggers a write action (push, PR) and leaves the event log append-only.
- [ ] Roadmap 2.5 is marked `✅ Done` in the implementation PR.
