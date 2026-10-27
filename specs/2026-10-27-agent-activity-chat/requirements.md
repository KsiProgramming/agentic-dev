# Agent activity, read like a chat with Claude

Roadmap phase: 11.8
Branch: plan/11.8-agent-activity-chat

## Context
The run console (11.6) opens on an agent's answer, but its Activity tab still shows each turn as a rail of tool-call groups and streamed text. Notes the agent writes between calls look like answers. Nothing says *why* a call was made. A live step only says "Reading `src/app.ts`…" in the live line. Mission principle 8 asks that runs read "as a story (nodes, messages, tool calls)", and principle 6 asks that every agent action be visible. tech-stack → UI design system → UI v2 → "Agent activity (11.8)" already fixes the shape: one collapsible **work block** per agent turn, then its answer, which is always open. The decisions log row "Tool intent (11.8)" chooses an optional `description` argument on the platform's tools.

This is the last phase of Milestone 11. It builds on 11.6 (step panel, Output and Activity tabs, `TurnsRail`, `ToolCallGroup`, `describeTool`, the live line) and on 11.1 (`Duration`). Both are done. After it, Milestone 4 resumes at 4.2.

What the code does today:
- The Claude adapter (`agentic_runtime/claude.py`) calls the Messages API with its own tool loop. It reads only `text` stream events. It already passes `final.content`, thinking blocks included, back unchanged in the tool loop.
- The default model, `claude-sonnet-5-5`, already thinks adaptively on every call, and that thinking is billed. The API returns it empty because `display` defaults to `"omitted"`. Asking for `display: "summarized"` therefore shows reasoning at no extra cost.
- Every platform tool is built through `strict_tool` (`agentic_tools/strict.py`), which rejects unknown arguments. `github.createRepo` already has a `description` argument (the GitHub repo description).
- Events have no turn index. On the web, `tool_call` / `tool_result` already carry `startedAt` / `endedAt`. The answer is the step's final `message`. Text before it arrives as non-final `MessageTurn`s.

## Scope
### In scope
- **Tool intent (`description`):**
  - `strict_tool` adds an optional `description` argument (plain text, at most 80 characters, "why you make this call, in under 10 words") to every platform tool that does not already declare one. It strips the argument before the tool function runs. `github.createRepo` keeps its own `description` (the repo's), because it is only called by tool nodes, never by agents. The spec notes this exception.
  - The field's schema description asks for the intent, so every provider sees the request. The engine also adds one platform line to an agent's instructions when the agent has tools.
  - Each tool's example call includes a `description`, so FakeRuntime runs (e2e, the console fixture) show intents.
  - The intent is logged as part of the `tool_call` arguments. No event changes shape.
- **Reasoning:**
  - A new `ReasoningDelta` agent event (`reasoning_delta`, `{text}`) in the `AgentEvent` union. `DeltaBuffer` buffers it like `text_delta`, on its own stream, so the order of events is kept.
  - The Claude adapter sends `thinking: {type: "adaptive", display: "summarized"}` to the models that think by default (the Claude 5 family) and yields their `thinking` stream events as `ReasoningDelta`. Empty thinking yields nothing. Other models get no `thinking` setting. On Opus 4.6–4.8 and Sonnet 4.6, leaving it out means no thinking, and older models refuse `adaptive`, so asking them would change cost or break runs.
  - FakeRuntime can script `ReasoningDelta`. Unscripted, it reasons before its tool calls and can wait before each call (`call_delay_s`, set by the worker from `FAKE_STEP_DELAY_S`), so e2e can watch a live block. The web lists `reasoning_delta` in `EVENT_TYPES`, folds it in Events like `text_delta`, and summarises it in `summarizePayload`.
- **Timeline model (web):** each agent step (and each map item, branch or iteration) is split into turns of **work** (reasoning, notes, tool calls, in order) followed by an **answer** (the final message). A step with no tool calls and no reasoning is just its answer. A failed or cancelled step's work has no answer after it.
- **Work block UI**, in the step's Activity tab and above the answer in Output:
  - *Finished header:* a chevron, the summary ("Listed 3 folders, read 11 files, ran 1 search", from `summarizeTools`), and "15 tool calls · 8s" on the right. It is closed by default. A block with a failed call opens and shows the failure.
  - *Live header:* a spinner, the current step's title (the running or latest call's intent, else its `describeTool` "doing" line, else "Thinking"), and an elapsed timer that ticks (`Duration`, from the block's first event). The block is open while live and follows new rows only when the user is at its bottom.
  - *Tool row:* the intent as its title, the `describeTool` line as a quiet second part, its duration on the right, and a chevron to the arguments and result. Consecutive reads, listings and searches with no intent fold into one summary row, as today. Writes, commits, PRs and failures keep their preview.
  - *Note row:* non-final text between calls, shown in one or two quiet lines (Markdown, sanitised).
  - *Reasoning row:* the first line in muted italic. The rest shows on expand. It is never open by default.
  - Intents and reasoning are agent output, rendered as plain text, never as Markdown or HTML (mission principle 5).
- **Map header:** a map's Output (its children list) gets one summary line: "2 items · 31 tool calls · 21s".
- **Live line:** it uses the current call's intent when there is one ("writer · Reading the frontend config…").
- **Accessibility:**
  - The block header is a `<button>` with `aria-expanded`. Its accessible name reads the summary and the count ("Listed 3 folders, read 11 files, 15 tool calls, 8 seconds").
  - The ticking timer is `aria-hidden` and is not announced. The live line keeps `aria-live="polite"`.
- **Specs, in the same PR:**
  - tech-stack: the "Agent activity (11.8)" part of UI v2 moves into Run console → "Agent activity". It names the reasoning event, the `description` exception for `createRepo`, and "summarized reasoning by default", with a decisions-log row for it.
  - `CHANGELOG.md`.
  - `CLAUDE.md`, only if a rule changes (rule 11 already covers intents and reasoning as data).

### Out of scope
- A per-node or per-workspace switch for reasoning display. It is always on for Claude because it costs nothing extra. A switch can come with Settings › Models later.
- Reasoning from the Copilot adapter (Milestone 8). An adapter that receives no reasoning logs none.
- Server-side turn boundaries (a turn index in events). The web derives turns from the event order.
- `display: "updates"` (progress-note beta). Notes come from the text the agent writes between calls.
- Changing the runs list or the step list rows, beyond what the live line and outline already read.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where intent is added | `strict_tool` injects an optional `description` into each tool's argument model and schema, and strips it before calling | One place for every tool, and tool functions stay unchanged. Unknown arguments are still rejected. The schema reaches the model through `list_tools`, so any provider sees it (principle 4). |
| `createRepo` clash | Keeps its own `description` (repo description); no intent on that tool | Only tool nodes call it, with fixed arguments, so no agent ever writes its intent. Renaming would change a tool contract for no user-visible gain. |
| Asking for intent | The field's schema description, plus one platform line added by the engine to an agent's instructions when it has tools | The schema is provider-neutral, and the instruction line makes the field actually get filled. It lives in the engine, not the Claude adapter, so Copilot gets the same instruction. |
| Reasoning display | Claude adapter always requests `display: "summarized"` from the models that think by default (Claude 5 family); others are sent nothing | Those models think adaptively anyway and the thinking is billed. `"omitted"` only hides it. Showing it is free, and the rows are closed by default. On older models the same request would turn thinking on or be refused. |
| Reasoning events | `reasoning_delta` buffered like `text_delta` (250 ms), each kind flushed before any other event | It keeps the log small and the order truthful. The client merges it the way it merges text. |
| Turn grouping | Derived on the client from the event order: work until the final `message`, then the answer | No event changes shape, and older runs get work blocks too (the log is append-only). |
| Elapsed time | Live: from the block's first event to now, ticking. Finished: first event to last tool result or reasoning. | It is active time inside one step, never waiting time (CLAUDE.md rule 4), and it is shown with `Duration`. |

## Open questions
- None
