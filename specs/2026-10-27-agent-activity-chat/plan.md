# Plan: Agent activity, read like a chat with Claude

The backend comes first, then the web. After each group the app still works and every test suite is green.

## 1. Tool intent (`description`)
- [x] `packages/tools/src/agentic_tools/strict.py`:
  - when `fn` has no `description` parameter, `strict_tool` adds an optional `description: str | None` (max 80 characters, with a field description that asks for the intent) to the strict arg model and to `tool.parameters`;
  - it wraps the call so the field is dropped before `fn` runs;
  - a tool that declares its own `description` (`github.createRepo`) is left as it is.
- [x] The example calls in `build_repo_server` / `build_github_server` include a `description`, so FakeRuntime calls carry intents.
- [x] `packages/engine/src/agentic_engine/agent.py` `to_request`: an agent with tools gets one platform line after its instructions ("When you call a tool, fill its `description` with why you make the call, in under 10 words."). The check in `graph/compile.py:865` (reduce agent) goes through the same path.
- [x] Tests:
  - `packages/tools/tests`: the schema has `description` on each read/write/github tool except `createRepo`; a call with it succeeds and the function never sees it; an unknown argument is still rejected; a `description` over 80 characters is rejected;
  - the worker test that keeps `PLATFORM_TOOLS` in sync still passes;
  - an engine test checks the instruction line.

## 2. Reasoning events
- [x] `packages/runtime/src/agentic_runtime/events.py`: `ReasoningDelta` (`type: "reasoning_delta"`, `text`), added to `AgentEvent` and exported from `__init__.py`. `contract.py` needs no change, but a test covers reasoning between calls.
- [x] `claude.py`:
  - pass `thinking={"type": "adaptive", "display": "summarized"}` to `messages.stream` for the models that think by default (`thinking_config`), and nothing for any other;
  - yield `ReasoningDelta` for each `thinking` stream event with text;
  - keep appending `final.content` unchanged.
  - Check the stream event name for thinking text in the installed `anthropic` SDK before writing it.
- [x] `graph/deltas.py`: `DeltaBuffer` buffers `ReasoningDelta` like `TextDelta`. Pending text of the other kind is flushed when the kind changes, so the order is kept.
- [x] `fake.py`: scripts may hold `ReasoningDelta`. An unscripted node reasons (`FAKE_REASONING`) before its tool calls, and waits `call_delay_s` before each one (the worker passes twice `FAKE_STEP_DELAY_S`), so e2e sees a live block.
- [x] Tests:
  - `test_claude_runtime.py` with a mock SSE stream holding `thinking_delta` (`agentic_runtime/testing.py` helpers): `ReasoningDelta` events come out in order, and the request sends `thinking`;
  - `test_events.py` round-trips the new event;
  - a `DeltaBuffer` test for mixed text and reasoning;
  - `test_run_events.py` logs `reasoning_delta`.

## 3. Fixture and web types
- [x] `scripts/record_console_fixture.py`: the agents reason, call tools with intents, write a note between calls, and answer. Re-record `web/src/runs/fixtures/docs-run.json`.
- [x] `web/src/runs/types.ts`: add `reasoning_delta` to `EVENT_TYPES`.
- [x] `summarize.ts`: a one-line summary for `reasoning_delta`.
- [x] `timeline.ts` `foldDeltas`: fold reasoning chunks like text chunks.
- [x] Regenerate the OpenAPI client only if the event schema export changes.

## 4. Timeline model of work blocks (no visible change)
- [x] `web/src/runs/timeline.ts`:
  - a `ReasoningTurn` (`text`, `startedAt`), merged from `reasoning_delta` the way text is;
  - `ToolTurn` gets `intent` (the `description` argument as a trimmed string, else `null`).
- [x] `web/src/runs/console/work-blocks.ts` (new): `agentTurns(step)` returns `[{work: WorkRow[], answer: MessageTurn | null}]`, where a `WorkRow` is a tool, a folded tool group, a note or a reasoning row. It also provides:
  - `workSummary(rows)`: the summary line, the tool-call count and the duration;
  - `currentTitle(rows)`: the intent, else the `doing` line, else "Thinking";
  - `hasFailure(rows)`;
  - `mapTotals(step)`: items, tool calls and duration across a map's items.
- [x] Folding rule: consecutive reads, listings and searches **without an intent** fold into one row. A call with an intent stands alone, and so do writes, commits, PRs and failures.
- [x] `activity.ts` `currentActivity`: use the intent when present.
- [x] Vitest: `work-blocks.test.ts` on the re-recorded fixture and on small hand-made steps:
  - no tools;
  - only reasoning;
  - a failed call;
  - a live step;
  - intents mixed with folded reads;
  - a map.

## 5. Work block UI
- [x] `web/src/runs/console/work-block.tsx` (new):
  - a header `<button aria-expanded>` with the live variant (spinner, `currentTitle`, a ticking `Duration` with `aria-hidden`) and the finished variant (chevron, summary, "N tool calls · Ns");
  - a body built with `rail.tsx` from tool, note and reasoning rows. Intents and reasoning render as text only. Notes render as sanitised Markdown (`AgentMessage` in a quiet variant).
  - It is open while live, closed when finished, and open when it holds a failure. New rows are followed by the page's own `useFollowScroll`: the block is not a scroll box of its own, so no second follow rule was needed.
- [x] `tool-calls.tsx` `ToolCallRow`: the intent as the title, with the `describeTool` line as the second part. With no intent it looks as today.
- [x] `step-view.tsx` `TurnsRail` → it renders `agentTurns(step)` as a `WorkBlock` and then `AgentMessage` for each turn. The empty state stays.
- [x] `step-output.tsx`:
  - the Output tab of an agent step shows the finished work block (closed) above the answer;
  - a map's children list gets the `mapTotals` line.
- [x] A ticking clock: the existing `useNow(1000)` (`@/runs/use-now`), shown with `Duration`.
- [x] Vitest (`step-view.test.tsx`, `run-console.test.tsx`):
  - one block and one answer per turn on the fixture;
  - the closed summary and its accessible name;
  - a failed call opens its block;
  - intent shown as text (a `<b>` in an intent stays literal);
  - the reasoning row is collapsed with only its first line shown;
  - the live header shows the current intent and the timer moves (fake timers);
  - the map totals line.

## 6. e2e, checks and specs
- [x] `web/e2e/console.spec.ts`:
  - a finished docs run shows, per agent step, one work-block header and its visible answer; expanding shows tool rows titled with their intents;
  - a live (slow FakeRuntime) run shows the live header with an intent, and the timer text changes between two reads.
- [x] `a11y.spec.ts` covers an open and a closed work block. `layout.spec.ts` covers the Activity tab at 375, 768 and 1440 px (long intents wrap, no horizontal page scroll).
- [x] `monitor.spec.ts` and `journey.spec.ts` are updated where they read the old rail.
- [x] tech-stack: move "Agent activity (11.8)" from UI v2 into Run console → "Agent activity". Add the `createRepo` exception and the reasoning event to the tool and event notes, and a decisions-log row "Reasoning display (11.8)". Trim the UI v2 intro sentence.
- [x] `CHANGELOG.md` entry under `[Unreleased]`. `CLAUDE.md` is unchanged unless a rule moves.
- [ ] Manual run on a real Claude key (see validation).
