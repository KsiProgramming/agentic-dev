# Run console v3

Roadmap phase: 11.6
Branch: plan/11.6-run-console-v3

## Context
The run console (2.5, plus the Graph tab from 3.5) works, but it reads as a debug view. A finished run opens on a long timeline where the agent's answer is buried among its tool calls. A failure is an alert you have to scroll to inside the Timeline tab. Raw events puts JSON payloads in table cells. Mission principle 8 ("runs are readable as a story… the raw event log is one click away, not the default view"; "what needs the user… is never below the fold") and the UI v2 success measure "one click from the runs list shows what an agent produced" drive this phase. tech-stack → UI design system → UI v2 → "Run console (11.6)" already fixes its shape, and this plan follows it.

It builds on 11.1 (display components, `StatTile`, `JsonView`), 11.2 (`active_ms` / `waiting_ms`), 11.3 (expired runs), 11.4 (`trigger`, `branch`) and 11.5 (the shared gate decision, `/inbox?run=`). All of these are done. It unblocks 11.8, which fills the step's Output and Activity tabs with work blocks.

Everything the new console shows is already in the run's events and in `GET /runs/{id}`: spec, input, usage, budget, trigger, branch, PR URL and failure reason. This phase changes `web/` only, with no API change.

## Scope
### In scope
- **Header** (`PageHeader`): the workflow name, `StatusBadge` and `IdChip`. Under them: `repoLabel` › branch (mono), who started the run (`trigger`: "Manual", "API", "Rerun of <id8>") and when (`RelativeTime`, with the wall clock in its tooltip). Actions on the right:
  - the pull request as the primary action once it is opened;
  - Rerun (ended runs) or Cancel (live runs);
  - a "⋯" menu with Copy link and Download events (the received events as `run-<id8>-events.json`, built in the browser).
- **Stat tiles** (`StatTile`) under the header:
  - Active time (`Duration`, with `WaitingTime` under it);
  - Cost (`Money`, "of $x" when there is a budget);
  - Tokens (`TokenCount`, with in, out and cache in the tooltip);
  - Steps (done of total, from the spec's nodes and their statuses);
  - Output (the PR number, linked, and "Opened"; else the created repo; else "—").

  Two columns at 375 px, five in a row from 1024 px.
- **Banner** under the tiles, at most one at a time:
  - failed: the failing step (the deepest failed step; when no step failed, the run's `failure_reason` alone), its reason, and "Go to step", which selects that step;
  - waiting: the gate title, `ExpiresIn`, "Review" (focuses the dock) and "Open in Inbox" (`/inbox?run=<id>`);
  - expired: the neutral "Approval expired" alert that sits above the timeline today.
- **Body: two panes from 1280 px, stacked below that.**
  - Left: the step list, which can be switched to the Graph (`?view=graph`).
    - Each row shows a status icon, a type icon, the name (the node id, or the map item's name), one line on what the step did, `Duration` and `Money`. The line is the first line of the agent's last message, the tool's `describeTool` line, or the gate's decision.
    - Map items, parallel branches and loop iterations nest under their node.
    - Selecting a graph node selects its step: the instance that needs attention first, as `focusStep` picks it. The node detail sheet is removed.
  - Right: the selected step, with the tabs Output (default), Activity, Input, Usage and Events (`?step=<key>&tab=<tab>`).
  - Which step is selected, in this order of preference:
    1. the step named in the URL;
    2. while the run is live, the running step (followed as the run moves, until the user picks one);
    3. the waiting gate;
    4. the failing step;
    5. the last agent step with a final message.

    So a finished run opens on its agent's answer.
- **Step tabs:**
  - Output:
    - an agent's final message as sanitised Markdown, capped at about 480 px with "Show full output" / "Show less";
    - a tool node's result (`OutputView`);
    - a gate's decision, comment and edits;
    - for a map, loop or parallel, its items, iterations or branches with their status, each of which selects its step.

    Files the step wrote (`repo.write_file` calls, last write per path) show as cards with the path in mono and a kind from the extension. A card opens the written content as text in a side sheet.
  - Activity: the step's tool calls and notes, shown as the timeline shows them today. 11.8 turns them into work blocks.
  - Input: what the step was given, read from the spec and the run:
    - an agent's role, instructions, model and tools;
    - a tool node's tool and arguments;
    - a map item's value;
    - the run's input, for the first step.

    JSON is shown in `JsonView`, never in a table.
  - Usage: the step's input, output and cache tokens and its cost. A container shows its total and one line per item.
  - Events: the raw events below, filtered to the step's node. The filter can be cleared to show every step.
- **Raw events:** one 32 px row per event, or per folded run of `text_delta` events. A row shows the event number, the time from the run's start, the type, the step and a one-line summary (`summarizePayload`, on one line, truncated). The row is a button that opens the payload in a side drawer (`JsonView`; a folded row lists its chunks). No table cell holds JSON.
- **Kept as they are:** the approval dock, `A` / `R`, the live activity line (moved to the end of the step list), "Jump to latest", the `aria-live` status, the tab title while waiting, Cancel and Rerun.
- **URLs:** the old `?tab=graph` opens `?view=graph`, and `?tab=raw` opens the Events tab.
- **Specs, in the same PR:**
  - tech-stack: the UI v2 "Run console (11.6)" part moves into the main "Run console" section, which rewrites its Header, Timeline, Raw events and Graph tab rules, and gets a decisions-log row;
  - `CHANGELOG.md`;
  - `CLAUDE.md`, only if a rule changes.

### Out of scope
- Work blocks, tool intents and reasoning rows in Output and Activity: 11.8.
- A PR's live state (merged, closed) from GitHub. The tile says "Opened" until there is a PR API.
- Reading a written file from the branch. The card shows what the agent wrote.
- Resuming a failed run from its failing step. Rerun stays a new run.
- Command palette actions on the console: 11.7.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Data | Web only: the timeline from the events plus `GET /runs/{id}`; Input from the stored spec and the run's input | Every value is already there. No event changes shape (the log is append-only), and the API contract stays as it is. |
| Default step | The URL, else the running step (live), the waiting gate, the failing step, the last agent answer | Meets "one click from the runs list shows an agent's output", and a live run shows the step that is moving. |
| Selection and tabs in the URL | `?step=`, `?tab=`, `?view=` | A reload or a shared link keeps the place, the back button works, and old `?tab=` links still open. |
| Step key | The node id with its scope: `docs[2]/writer` for a map item, `review#2/writer` for a loop iteration, `checks:lint/scan` for a branch | Unique across items and iterations, readable in a link, and stable while the run grows. |
| Raw events | 32 px rows that open a `JsonView` drawer; the Events view is per step, with "All steps" | No JSON in a cell (Done when). The drawer reuses `JsonView`, and one table serves both a step and the whole run. |
| Graph | In the left pane, where a click selects a step; the node detail sheet goes | One step panel for both views, so the graph and the list never show a step in two different ways. |
| Written files | From `repo.write_file` arguments, last write per path, opened in a sheet as plain text | The content is already in the event log. Agent content is data (principle 5), so it is never rendered as HTML. |
| Steps total | The spec's nodes without sequences; done means completed, from `nodeStatuses` | The graph already counts this way, so the tile and the graph agree. |

## Open questions
- None
