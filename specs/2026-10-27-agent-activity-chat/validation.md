# Validation: Agent activity, read like a chat with Claude

## Done when (from roadmap)
> A finished docs run reads as one line of work and one visible answer per agent turn; opening the work shows why each call was made; a live run shows the current step and an elapsed time that ticks

- "One line of work and one visible answer": in a finished docs run, each agent step's Activity (and Output) shows one closed work-block header per turn, then the answer, which is open.
- "Why each call was made": an expanded block's tool rows are titled with the call's `description`. Only calls without one fall back to the `describeTool` line.
- "Ticks": on a live run, the block header shows the current call's intent (or the doing line), and its elapsed time changes from one second to the next.

## Automated checks
- [ ] Backend (`uv run pytest`, ruff, pyright strict):
  - `strict_tool` adds an optional `description` (max 80 characters) to every platform tool except `github.createRepo`; the tool function never receives it; unknown arguments are still rejected;
  - an agent with tools gets the intent line in its instructions;
  - `ReasoningDelta` round-trips in `agent_event_adapter`;
  - the Claude adapter sends `thinking: {type: "adaptive", display: "summarized"}` and turns a mocked `thinking_delta` stream into ordered `ReasoningDelta` events, with tool-loop messages unchanged;
  - `DeltaBuffer` buffers reasoning and keeps the order with text and tool events;
  - `reasoning_delta` is logged and streamed over SSE;
  - the `PLATFORM_TOOLS` sync test passes.
- [ ] Web unit (Vitest):
  - `work-blocks.test.ts`: turns split into work and answer; summary, count and duration; folding (intents stand alone); a failed call; live title; map totals;
  - `step-view.test.tsx` / `run-console.test.tsx`: one block and one answer per turn on the re-recorded `docs-run.json`; closed by default; open on failure; the header's `aria-expanded` and accessible name; intent and reasoning rendered as text; the reasoning row collapsed; the live timer moves with fake timers;
  - `summarize.test.ts` / `timeline.test.ts`: `reasoning_delta` summary and folding;
  - the existing console, dock and Inbox tests still pass.
- [ ] e2e (Playwright):
  - `console.spec.ts` checks the three Done when points above on FakeRuntime runs;
  - `a11y.spec.ts` (no serious axe issue) covers open and closed blocks;
  - `layout.spec.ts` covers the Activity tab at 375, 768 and 1440 px with no horizontal page scroll;
  - `monitor.spec.ts` and `journey.spec.ts` are green.
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`, and the backend CI jobs, are green.

## Manual / demo checks
- [ ] On the dev stack with a **real Claude key**, start a docs run on a small repo:
  - while live, the selected step's block header shows an intent the agent wrote and a ticking timer, and the live line uses the intent;
  - reasoning rows appear, collapsed, with their first line in muted italic;
  - after it finishes, each module agent reads as one closed line ("Listed …, read … · N tool calls · Ns") above its answer, and expanding shows an intent on most calls.
- [ ] Look at a work block at 375 and 1440 px, in light and dark. Use the keyboard to open and close it and to reach a tool row's arguments.
- [ ] Check that the run's cost is in line with an earlier docs run on the same repo (summarized reasoning adds no thinking tokens).

## Merge criteria
- [ ] Every check above passes in CI.
- [ ] No palette colours, hand-made `Intl` formats, `duration_ms` reads, or agent text rendered as HTML (CLAUDE.md rules 1, 3, 4 and 11).
- [ ] tech-stack ("Agent activity" moved out of UI v2, the reasoning event, the `createRepo` exception, the decisions-log row) and `CHANGELOG.md` are updated in the same PR. The roadmap row is marked done by CI.
