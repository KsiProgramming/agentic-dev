# Roadmap

High-level implementation order, in very small phases. Each phase is a thin vertical slice that can be demonstrated on its own. A phase is done when its "Done when" check passes. Phases are ordered, but within a milestone a later phase may start once its dependencies are done. Milestones are listed in the order we work them, which is not always their number: a milestone added later gets the next free number, so no phase is ever renumbered.

Status: `—` not started, `✅ Done (#PR)` merged. The PR that implements a phase marks it done in this file; CI marks it automatically on the PR branch and checks it (see `scripts/check_roadmap.py`, or the `complete-phase` skill to do it locally).

Strategy: **walking skeleton first**, then grow outward. The milestones follow the stakeholder plan: fixed flows first, then parallel, then dynamic, then the Architect. Milestone 2 sets the product UI foundation (design system, app shell, run history, run console) that every later screen builds on. Milestone 11 (UI v2) reworks those screens once the engine has grown, before the canvas adds many more.

Milestones 12 to 20, and phases 7.7, 7.8, 9.11 and 10.6, were promoted from [`ideas.md`](ideas.md) on 2026-11-10. They are listed in the order we work them: Milestone 12 (Nothing is lost) right after Milestone 6, then the v1 milestones (Jira and SDD, then verification before the second provider and the Architect), then what grows the product after them. Ideas that need a mission change stay in `ideas.md`, parked with the AI software factory vision: earned autonomy (it would auto-approve writes, against principle 3), and the deploy shepherd, production feedback loops and ticket-to-production (they reach production, beyond v1's reviewable PR). No phase adds users, sign-in and roles yet (an idea in `ideas.md`); until one does, the phases that name a person (14.1, 15.2, 20.1, 20.3) work with the workspace as the actor. A phase that changes what agents receive is done only once a real run with Claude has been read step by step in the console ([`lessons.md`](lessons.md), rule 1), whether or not its row says so.

**Next up: Milestone 6 (Dynamic orchestration and composites), at 6.7, then Milestone 12 (Nothing is lost), then Milestone 7.** The `plan-feature` skill plans the first unplanned phase of the first milestone named here before any other. Milestones 4, 5 and 11 are done. Change this line, in its own PR with a changelog entry, when the priority changes.

---

## Milestone 0: Walking skeleton

| # | Phase | Done when | Status |
|---|---|---|---|
| 0.1 | Repo scaffold: `uv` workspace, FastAPI app, Next.js app, docker compose (Postgres, Redis), CI with lint + tests | `docker compose up` serves a health endpoint and an empty web page; CI is green | ✅ Done ([#1](https://github.com/KsiProgramming/agentic-dev/pull/1)) |
| 0.2 | Workflow spec v0 as Pydantic models (`agent`, `sequence` only), exported JSON Schema | A sample spec validates and an invalid one is rejected in tests | ✅ Done ([#3](https://github.com/KsiProgramming/agentic-dev/pull/3)) |
| 0.3 | `AgentRuntime` interface + fake runtime | Engine tests can run an agent node with no network | ✅ Done ([#4](https://github.com/KsiProgramming/agentic-dev/pull/4)) |
| 0.4 | Compile spec → LangGraph graph for `sequence` of `agent` nodes | A 2-node sequence runs end to end on the fake runtime | ✅ Done ([#5](https://github.com/KsiProgramming/agentic-dev/pull/5)) |
| 0.5 | Append-only `run_events` table; engine writes events | A run produces ordered events in Postgres | ✅ Done ([#6](https://github.com/KsiProgramming/agentic-dev/pull/6)) |
| 0.6 | `POST /runs` + `GET /runs/{id}/events` (SSE) | `curl` streams events of a live run | ✅ Done ([#7](https://github.com/KsiProgramming/agentic-dev/pull/7)) |
| 0.7 | Claude adapter (API key from env for now) | A one-node run on Claude returns text and a usage event | ✅ Done ([#8](https://github.com/KsiProgramming/agentic-dev/pull/8)) |
| 0.8 | Minimal monitor page: list events of a run | Browser shows events within 1 s | ✅ Done ([#9](https://github.com/KsiProgramming/agentic-dev/pull/9)) |

## Milestone 1: Real repo, one fixed flow (Docs, AC-1)

| # | Phase | Done when | Status |
|---|---|---|---|
| 1.1 | Sandbox manager: container per run with a local repo clone | An agent can list files in a cloned repo inside the container | ✅ Done ([#10](https://github.com/KsiProgramming/agentic-dev/pull/10)) |
| 1.2 | `repo` MCP server (read only) wired into the agent runtime | An agent answers a question about the repo using the tools | ✅ Done ([#11](https://github.com/KsiProgramming/agentic-dev/pull/11)) |
| 1.3 | Durable execution with the Postgres checkpointer | Killing a worker mid-run and restarting it resumes after the last completed node (AC-8) | ✅ Done ([#12](https://github.com/KsiProgramming/agentic-dev/pull/12)) |
| 1.4 | Workspaces + connections; encrypted secrets (local KMS) | A Claude key is stored encrypted and used by a run; it never appears in logs | ✅ Done ([#13](https://github.com/KsiProgramming/agentic-dev/pull/13)) |
| 1.5 | GitHub App install + `GET /repos` | User sees repos the app is installed on | ✅ Done ([#14](https://github.com/KsiProgramming/agentic-dev/pull/14)) |
| 1.6 | `tool` primitive + `repo` write tools + worktree/branch per writer | An agent commits a file to `agent/<run>/<node>` | ✅ Done ([#15](https://github.com/KsiProgramming/agentic-dev/pull/15)) |
| 1.7 | `gate` primitive (LangGraph interrupt) + `POST /runs/{id}/approvals` | A run pauses at a gate and resumes on approval | ✅ Done ([#16](https://github.com/KsiProgramming/agentic-dev/pull/16)) |
| 1.8 | `github.openPR` tool behind a gate | A run opens a PR after approval | ✅ Done ([#17](https://github.com/KsiProgramming/agentic-dev/pull/17)) |
| 1.9 | `loop` primitive + CEL expressions | A reviewer loop stops on its condition or at max iterations | ✅ Done ([#18](https://github.com/KsiProgramming/agentic-dev/pull/18)) |
| 1.10 | `map` + `reduce` (concat/agent) primitives | Map over 3 modules with max concurrency, then reduce | ✅ Done ([#19](https://github.com/KsiProgramming/agentic-dev/pull/19)) |
| 1.11 | "Generate docs" template | AC-1: connect GitHub, pick a repo, docs run opens a PR | ✅ Done ([#20](https://github.com/KsiProgramming/agentic-dev/pull/20)) |
| 1.12 | Create new repo (behind a gate) + scaffold commit | Docs run works on a newly created repo | ✅ Done ([#119](https://github.com/KsiProgramming/agentic-dev/pull/119)) |

## Milestone 2: Product UI foundation

Milestone 1 proved the engine end to end, but the UI is a debug view. Every later milestone (cost, canvas, Architect) adds screens, so the design system, app shell and run console come first. The rules are in [tech-stack.md → UI design system](tech-stack.md#ui-design-system). This milestone does not depend on 1.12. Its second round, UI v2, is [Milestone 11](#milestone-11-product-ui-v2).

| # | Phase | Done when | Status |
|---|---|---|---|
| 2.1 | Design system: Tailwind v4 tokens (light + dark), shadcn/ui primitives, Inter + JetBrains Mono, lucide icons, status badge, empty/loading/error states | Every existing screen uses only shared components and tokens (no raw palette colours); axe finds no serious issues | ✅ Done ([#22](https://github.com/KsiProgramming/agentic-dev/pull/22)) |
| 2.2 | App shell: sidebar (Runs, Templates, Settings) + top bar (workspace, theme toggle), drawer under 1024 px, page header with breadcrumbs and actions | Every page renders in the shell at 375, 768 and 1440 px with no horizontal scroll (Playwright screenshots in CI) | ✅ Done ([#23](https://github.com/KsiProgramming/agentic-dev/pull/23)) |
| 2.3 | Run summaries API: `GET /runs` (newest first, cursor pagination, filter by status/template/repo) and `GET /runs/{id}` (status, workflow, repo, input, timings, PR URL, failure reason, waiting gate, `rerun_of`) | The API lists past runs with status taken from the event log | ✅ Done ([#24](https://github.com/KsiProgramming/agentic-dev/pull/24)) |
| 2.4 | Runs page (new home): list of runs with status, workflow, repo, started, duration and PR link; table on desktop, cards on mobile; filters; live status; "Needs approval" first | User finds any past run and sees whether it succeeded, failed or is waiting | ✅ Done ([#25](https://github.com/KsiProgramming/agentic-dev/pull/25)) |
| 2.5 | Run console v2: header (status, repo, workflow, duration, actions), node timeline grouped by node and map item, streamed text merged into one growing message per agent turn, tool calls as collapsible cards with formatted JSON, raw event log in a "Raw events" tab | A docs run shows one message block per agent turn, not one row per chunk | ✅ Done ([#27](https://github.com/KsiProgramming/agentic-dev/pull/27)) |
| 2.6 | Start, approve and rerun: **start screen** (template gallery cards, a "New run" sheet with a repo combobox and form validation) and **settings** as connection cards with clear connected/missing states; **approval dock**, a sticky bottom bar whenever a gate is waiting, with title, summary, "Review details" sheet, Approve and Reject (with comment), and a waiting badge in the runs list and the page title; **rerun**, `POST /runs/{id}/rerun` starts a new run with the same workflow, input and repo and links `rerun_of`, with a Rerun button on failed, cancelled and completed runs | A user connects Claude and GitHub and starts a docs run without reading any help text; its gate is visible and approved without scrolling at every viewport, desktop and mobile; a failed run is rerun from the console or the runs list, and the new run links back to the original | ✅ Done ([#28](https://github.com/KsiProgramming/agentic-dev/pull/28)) |

## Milestone 3: Policies, cost and monitor

| # | Phase | Done when | Status |
|---|---|---|---|
| 3.1 | Usage normalisation → cost per node/run | Run console shows tokens and estimated USD per node and per run; the runs list shows cost per run | ✅ Done ([#111](https://github.com/KsiProgramming/agentic-dev/pull/111)) |
| 3.2 | Policy limits: agents alive/spawned, depth, iterations, wall time | Exceeding a limit stops the run cleanly with a reason | ✅ Done ([#112](https://github.com/KsiProgramming/agentic-dev/pull/112)) |
| 3.3 | **Optional budget**: if set, hard stop at 100%; if unset, no cap | AC-7 for budgeted runs; an unbudgeted run continues and still reports cost | ✅ Done ([#113](https://github.com/KsiProgramming/agentic-dev/pull/113)) |
| 3.4 | Validation endpoint `POST /workflows/{id}/validate` (schema, ports, cycles, policy) | Invalid specs return actionable errors | ✅ Done ([#114](https://github.com/KsiProgramming/agentic-dev/pull/114)) |
| 3.5 | Graph tab in the run console: read-only graph (React Flow) with status colours; selecting a node opens the node detail from 2.5 | Clicking a node in the graph shows what the agent did | ✅ Done ([#115](https://github.com/KsiProgramming/agentic-dev/pull/115)) |
| 3.6 | Editable artifacts in the approval dock (2.6): diff view, edit before approving | Gate is approved from the UI with edits | ✅ Done ([#116](https://github.com/KsiProgramming/agentic-dev/pull/116)) |
| 3.7 | Audit log view for admins | Every run and approval is listed per workspace | ✅ Done ([#117](https://github.com/KsiProgramming/agentic-dev/pull/117)) |

## Milestone 4: Parallel and Audit

| # | Phase | Done when | Status |
|---|---|---|---|
| 4.1 | `parallel` primitive with join policies (all/any/quorum) | Three branches run concurrently and join correctly | ✅ Done ([#120](https://github.com/KsiProgramming/agentic-dev/pull/120)) |
| 4.2 | Typed ports: input/output JSON Schemas validated at each edge | A wrong-shaped output fails at the edge with a clear error | ✅ Done ([#138](https://github.com/KsiProgramming/agentic-dev/pull/138)) |
| 4.3 | Shared run context: named artifacts in the run workspace | Nodes exchange `findings.json` through artifacts | ✅ Done ([#139](https://github.com/KsiProgramming/agentic-dev/pull/139)) |
| 4.4 | Deterministic tool nodes: linter, dependency scanner, secret scanner | Tool outputs feed specialist agents | ✅ Done ([#140](https://github.com/KsiProgramming/agentic-dev/pull/140)) |
| 4.5 | `reduce` strategies: dedupe, vote | Duplicate findings are merged with severity and confidence | ✅ Done ([#141](https://github.com/KsiProgramming/agentic-dev/pull/141)) |
| 4.6 | `router` primitive (CEL rule + classifier agent) and the "Audit codebase" template (read-only, report only) | An audit run branches on a condition and produces findings.json + a readable report | ✅ Done ([#142](https://github.com/KsiProgramming/agentic-dev/pull/142)) |
| 4.8 | .NET analyzers in the sandbox: `scan.lint` lints C#/.NET modules with the Roslyn analyzers (a `dotnet build` with SARIF logs, the repo's `.editorconfig` and analyzer packages), the .NET SDK in the sandbox image, NuGet restore through a NuGet-only egress proxy (a slice of 10.2). [Plan](2026-11-05-dotnet-analyzers-sandbox/requirements.md) | An audit of a .NET repo reports analyzer findings instead of "no supported linter for dotnet" | ✅ Done ([#156](https://github.com/KsiProgramming/agentic-dev/pull/156)) |

4.6 merges the former 4.7 ("Audit codebase" template) into the `router` phase: the template is the router's first real use, and its report path is the branch that proves it. The number 4.7 is retired and not reused. 4.8 was added after a 4.6 test audit of a .NET repo, whose modules were all skipped by `scan.lint` (4.4 left .NET, Go, Rust and Java out). Its spike chose `dotnet build` over `dotnet format analyzers` (tech-stack decisions log), and its restore pulls a NuGet-only slice of 10.2's egress allowlist forward.

## Milestone 11: Product UI v2

Listed here, after Milestone 4, because it was worked before Milestone 4 finished.

A review of the screens shipped in Milestones 2 and 3 found that they work but read as unfinished. Waiting time is counted as run time, stale approvals pile up above real work, test runs mix with real ones, the run console shows agent output as one long wall of text and raw JSON in table cells, and settings is one long page. UI v2 fixes the information design first and the look second. Its rules are in [tech-stack.md → UI v2](tech-stack.md#ui-v2-milestone-11). Each phase moves its part into the main design-system rules when it ships. 11.1 comes first; 11.2 and 11.3 change the API and can run beside it; the screens (11.4–11.8) build on all three. Everything it builds on (Milestones 2 and 3) is done. 11.9 was added after 11.8: the screens worked but still read as faded (two text levels, every surface white, badges with no edge), so it applies one design language, [`design-language.md`](design-language.md), to all of them.

| # | Phase | Done when | Status |
|---|---|---|---|
| 11.1 | UI v2 foundations: brand accent decided; type scale and density tokens; shared display components (`RelativeTime`, `Duration`, `Money`, `TokenCount`, `IdChip`, `StatTile`); dates in the workspace's locale and time zone; pages use the full content width (no centred `max-w-*` column); a lint rule that rejects raw palette classes and hard-coded colours; the new components added to the rules in `CLAUDE.md` | Every page renders times, durations, costs and ids through the shared components; `pnpm lint` fails on `bg-red-100` or `#4f46e5` in a component; layout screenshots at 375, 768 and 1440 px pass | ✅ Done ([#129](https://github.com/KsiProgramming/agentic-dev/pull/129)) |
| 11.2 | Active and waiting time: the engine records how long a run waited at gates; `GET /runs` and `GET /runs/{id}` return `active_ms` and `waiting_ms`; every duration shown is active time, with waiting time as its own "waiting 12 h" chip and wall-clock time in the tooltip | A run that waits 1 h at a gate and works for 2 min shows "2m 00s · waited 1 h" in the runs list and the console header | ✅ Done ([#130](https://github.com/KsiProgramming/agentic-dev/pull/130)) |
| 11.3 | Approval expiry: a gate has a time to live (workspace default 72 h, overridable per gate in the spec); at expiry the run is cancelled with the reason "Approval expired" and shown as "Expired"; existing stale waiting runs are expired once by a migration | A gate past its time to live cancels its run cleanly, drops out of every waiting count and shows "Expired" with the reason | ✅ Done ([#131](https://github.com/KsiProgramming/agentic-dev/pull/131)) |
| 11.4 | Runs list v2: saved views as tabs with counts (All, Running, Needs approval, Failed) instead of a pinned "Needs approval" section; a Run column with the workflow, short id and trigger; branch under the repo; rows grouped by date; e2e and demo runs kept out of the default workspace | Real runs are the first rows on the page whatever is waiting; a waiting run is one click away; no test run appears in the default workspace | ✅ Done ([#133](https://github.com/KsiProgramming/agentic-dev/pull/133)) |
| 11.5 | Inbox: `/inbox` lists the gates waiting on the user with time left before expiry; selecting one opens its review (summary or diff, Approve, Reject, keyboard `A` / `R`) beside the list; the sidebar's waiting count moves from Runs to Inbox | A gate is approved from the Inbox without opening the run console; the console's approval dock keeps working | ✅ Done ([#134](https://github.com/KsiProgramming/agentic-dev/pull/134)) |
| 11.6 | Run console v3: a header with labelled stat tiles (active time, cost against budget, tokens, steps, output) and a banner for a failure or a waiting gate; a two-pane body with the step list (List or Graph) on the left and the selected step on the right (Output, Activity, Input, Usage, Events); long agent output capped with "Show full"; files a step wrote as cards; raw events as one-line rows that open the payload in a drawer | From the runs list, one click shows an agent's output; a failed run names its failing step and reason without scrolling; no JSON is shown inside a table cell | ✅ Done ([#135](https://github.com/KsiProgramming/agentic-dev/pull/135)) |
| 11.7 | Shell and settings v2: a command palette (`⌘K`: jump to a run by id or PR, New run, toggle theme), the theme in a user menu; settings split into sub-pages (Integrations, Models and pricing, Limits and budgets) with a secondary nav; the pricing table fits without horizontal scroll; the limits form saves from a sticky bar that appears when it changes | Every settings sub-page fits at 1440 px with no horizontal scroll and stacks at 375 px; `⌘K` opens a run from its id | ✅ Done ([#136](https://github.com/KsiProgramming/agentic-dev/pull/136)) |
| 11.8 | Agent activity, read like a chat with Claude: each agent turn is a collapsible **work block** (its tool calls, short notes and, when the provider streams it, reasoning) followed by the agent's answer, which always stays visible; while live the block's header says what the agent is doing with a running timer, once done a summary ("Listed 3 folders, read 11 files · 15 tool calls · 8s"); the platform's tools take an optional `description` the agent fills with why it makes the call, shown as the step's title | A finished docs run reads as one line of work and one visible answer per agent turn; opening the work shows why each call was made; a live run shows the current step and an elapsed time that ticks | ✅ Done ([#137](https://github.com/KsiProgramming/agentic-dev/pull/137)) |
| 11.9 | Design language v2: the look in [`design-language.md`](design-language.md) on every screen: an ink primary; three text levels (`foreground`, `foreground-secondary`, `muted-foreground`) plus `placeholder`; tinted surfaces (`surface-sunken` sidebar, `surface-subtle` headers); edges on badges and selected rows; underline tabs; stat tiles as one strip; tables in bordered cards; 13 px UI text with 500 weight on names, labels and buttons; filter chips; and the content rules (findings as cards by container width, paths truncated from the left, no empty stat tiles, quiet zeros, one fact per finding, distinct step one-liners). [Plan](2026-10-28-design-language-v2/requirements.md) | Every screen matches `design-language.md`: `globals.css` holds its tokens in light and dark; no tab is a grey pill and no badge lacks its edge; stat tiles are one strip; metadata uses `foreground-secondary`; `pnpm lint` rejects `text-[13px]`; axe passes at 375, 768 and 1440 px in light and dark; a report-only run's Output tile names the artifact it wrote | ✅ Done ([#144](https://github.com/KsiProgramming/agentic-dev/pull/144)) |

## Milestone 5: Builder canvas and versioning

| # | Phase | Done when | Status |
|---|---|---|---|
| 5.1 | Graph operations model (`addNode`, `removeNode`, `connect`, `disconnect`, `setParam`) + `PATCH /workflows/{id}` creates a version | Applying ops produces a new immutable version | ✅ Done ([#146](https://github.com/KsiProgramming/agentic-dev/pull/146)) |
| 5.2 | Canvas renders a spec; edits emit graph operations | Editing on canvas round-trips to the stored spec | ✅ Done ([#147](https://github.com/KsiProgramming/agentic-dev/pull/147)) |
| 5.3 | Node manifests + palette generated from them | A new primitive appears in the palette with no frontend change | ✅ Done ([#148](https://github.com/KsiProgramming/agentic-dev/pull/148)) |
| 5.4 | Side panel from parameter JSON Schema | Role, instructions, provider, tools, budget (optional) are editable | ✅ Done ([#149](https://github.com/KsiProgramming/agentic-dev/pull/149)) |
| 5.5 | Container nodes (map, parallel, loop) drawn with children inside | Nested flow is editable visually | ✅ Done ([#150](https://github.com/KsiProgramming/agentic-dev/pull/150)) |
| 5.6 | Live validation on canvas (incompatible ports blocked, errors on nodes) | Invalid connections cannot be made | ✅ Done ([#151](https://github.com/KsiProgramming/agentic-dev/pull/151)) |
| 5.7 | Versions: history, visual diff, restore, run any version | User restores and runs an older version | ✅ Done ([#152](https://github.com/KsiProgramming/agentic-dev/pull/152)) |
| 5.8 | Start screen v2: provider picker and "Blank canvas" added to the 2.6 start screen | A user starts a canvas workflow without touching JSON | ✅ Done ([#153](https://github.com/KsiProgramming/agentic-dev/pull/153)) |
| 5.9 | Flow layout: the canvas and the run map drawn left to right from the spec tree (fork and join lanes, routes as labelled edges, loops as back edges, SVG edges, no layout library), the vertical tree kept below 768 px. [Plan](2026-11-09-flow-layout/requirements.md) | A workflow reads left to right on the canvas and the run map: a parallel, map or orchestrator forks into lanes and joins, a router's routes are labelled edges and a loop has a back edge; below 768 px the vertical tree stays | ✅ Done ([#165](https://github.com/KsiProgramming/agentic-dev/pull/165)) |

5.9 was added after 6.5, when a team workflow (an orchestrator, a synthesizer, a reviewer and a router) read oddly as a card tree: it replaces 11.9's card tree with a flow read left to right, and is worked after 6.5.

## Milestone 6: Dynamic orchestration and composites

| # | Phase | Done when | Status |
|---|---|---|---|
| 6.1 | `orchestrator` primitive: hub plan schema, spawn workers via `Send`, max workers/depth. [Plan](2026-11-09-orchestrator-primitive/requirements.md) | A hub plans N subtasks and the engine spawns N workers | ✅ Done ([#157](https://github.com/KsiProgramming/agentic-dev/pull/157)) |
| 6.2 | Replan policy (on-failure): settle the round, the hub replans the remaining work from every task's outcome, at most `max_rounds` times. [Plan](2026-11-09-replan-policy/requirements.md) | A failed worker triggers a replan within limits | ✅ Done ([#159](https://github.com/KsiProgramming/agentic-dev/pull/159)) |
| 6.3 | Integration branch merging worker branches before the final PR: an orchestrator's completed task branches merged in plan order into `agent/<run>/<orchestrator>`, a conflict failing its task (and so replanned). [Plan](2026-11-09-integration-branch-merge/requirements.md) | Parallel writers produce one PR | ✅ Done ([#161](https://github.com/KsiProgramming/agentic-dev/pull/161)) |
| 6.4 | Monitor shows dynamic children live: an orchestrator's tasks in the step list, its Output and the run map, with progress and cost, and its worker drawn and edited on the canvas. [Plan](2026-11-09-dynamic-children-monitor/requirements.md) | Spawned workers appear with progress and cost | ✅ Done ([#162](https://github.com/KsiProgramming/agentic-dev/pull/162)) |
| 6.5 | `subflow` primitive: a stored workflow called by id and version, resolved when the run is created and run inside it. [Plan](2026-11-09-subflow-primitive/requirements.md) | One workflow calls another by id + version | ✅ Done ([#163](https://github.com/KsiProgramming/agentic-dev/pull/163)) |
| 6.6 | `wrap` / `extract` operations; composite nodes (draft → published): a composite is a stored workflow with a published version, called by a pinned `subflow`. [Plan](2026-11-10-composite-nodes/requirements.md) | AC-3: composite saved in one workflow is reused in another, updated by version | ✅ Done ([#167](https://github.com/KsiProgramming/agentic-dev/pull/167)) |
| 6.7 | Audit "fix selected findings" step with orchestrator: a selection gate on `findings.json`, an orchestrator that fixes the chosen findings on one integration branch, a gate on the diff and one PR. [Plan](2026-11-10-audit-fix-findings/requirements.md) | Selected findings become fix PRs | ✅ Done ([#170](https://github.com/KsiProgramming/agentic-dev/pull/170)) |
| 6.8 | AC-2 end-to-end: canvas flow with parallel, orchestrator, loop, gate; the flow shipped as the "Plan, build and review" template, and a check that a run matches its graph. [Plan](2026-11-10-ac2-canvas-end-to-end/requirements.md) | Run matches the drawn graph | — |
| 6.9 | Orchestrator in a loop: a loop's body may hold an orchestrator; each iteration plans afresh with the last iteration's output (a review) as data and builds on the same integration branch. [Plan](2026-11-09-orchestrator-review-loop/requirements.md) | A reviewer's rejection inside a loop makes the orchestrator plan again on top of the merged work, and an approval goes on to one PR | ✅ Done ([#166](https://github.com/KsiProgramming/agentic-dev/pull/166)) |

6.9 was added after 6.5, from a team workflow (a lead, two engineers, a synthesizer and a reviewer) whose review had to send the work back to the lead; it lifts 6.1's "no orchestrator in a loop" rule.

## Milestone 12: Nothing is lost

Listed here, after Milestone 6, because it is worked before Milestone 7.

Principle 9 says nothing is lost, and AC-8 holds for the graph but not yet for the code. A run whose id leaves the queue before a worker claims it stays "Queued" for good. The code agents write lives only in the run's sandbox until the gated `github.openPR` pushes it, so a failed or cancelled run, a worker crash or a swept sandbox loses it, and a rerun starts from scratch. Promoted from the ideas "Recover runs lost between the queue and the worker", "Keep agents' code when a run fails or its worker crashes" and "Rerun from a node, with the code as it was there". 12.2 starts with a test that kills a worker after a writer's commit, to confirm the crash gap before closing it. Pushing work-in-progress branches to GitHub (the idea's third option) stays out: a push is irreversible (principle 3).

| # | Phase | Done when | Status |
|---|---|---|---|
| 12.1 | Recover runs lost before a worker claims them: Postgres is the queue's source of truth; on start and on a timer, a sweep enqueues again the runs `queued` with no lease for longer than a threshold; a run whose spec this worker cannot load fails with a `failure_reason` instead of crashing the worker; the console shows "Queued for N min" with a hint past the threshold | A run whose id was popped from Redis by a worker killed before it claimed the run still starts within the threshold; a run with a spec the worker cannot parse fails with a clear reason and the worker keeps serving other runs | — |
| 12.2 | Writers' commits saved outside the sandbox: each writer's branch and each integration branch saved as a `git bundle` in Postgres when its step completes, and restored when an attempt resumes, a run is rerun from a step (12.4) or its sandbox is missing | A worker killed after a writer's commit resumes with that commit on its branch; deleting a running run's sandbox volume loses no completed step's commit | — |
| 12.3 | A failed, cancelled or expired run keeps its code: its sandbox is kept for a time to live (a workspace default, as for approval expiry), then swept; the console says until when, and shows each writer's changes from its saved bundle | A failed run's console shows what its writers changed and until when its sandbox is kept; once swept, the console says so and the changes are still shown | — |
| 12.4 | Rerun from a step: "Rerun from here" on a step starts a new run from that step's checkpoint, with the code restored from the saved bundles and, optionally, that step's parameters edited; the new run links the run and the step it came from, and the steps before it are neither run nor charged again | A run that failed at its last step is rerun from that step with changed instructions; the earlier steps do not run again, and the new run's branches hold the code they held at that step | — |

## Milestone 7: Jira and Spec-Driven Development

| # | Phase | Done when | Status |
|---|---|---|---|
| 7.1 | Atlassian OAuth 3LO per workspace, project scoping | Jira connection stored encrypted | — |
| 7.2 | `jira` MCP server: read issue, comment, transition | Agent reads an issue and posts a comment | — |
| 7.3 | Jira webhook trigger on configured status/label | Moving an issue starts a run | — |
| 7.4 | Per-project field mapping (acceptance criteria, components) | Spec-writer receives mapped fields | — |
| 7.5 | SDD template: spec → gate → plan/tasks → orchestrator implement → review loop → gate → PR → Jira update (Spec Kit compatible) | AC-5 | — |
| 7.6 | GitHub webhooks: PR review comments feed a new loop iteration; `@platform fix this` | Review comment resumes the run | — |
| 7.7 | Spec from a Markdown file: a run's input may be an uploaded `.md` file or a path in the repo (`docs/spec.md`), kept as a run artifact (4.3) and given to agents as data (principle 5); the SDD template runs from it without Jira | An SDD run started from an uploaded spec file, with no Jira connection, opens a PR that implements it | — |
| 7.8 | Spec and prototype at one gate: the spec step writes, in 7.5's Spec Kit layout, a product spec (`spec.md`: problem, users, success measures, scope, acceptance criteria in a testable "When … the system shall …" form, each with an id) and a technical plan (`plan.md`: design, files touched, risks, test plan), and for UI work a throwaway prototype on a sandbox branch that is never pushed; the gate shows the three, the approver comments on any of them and the agent revises | An SDD run's spec gate shows the spec, the plan and the prototype's diff; a comment sends the spec back, and the revised spec is approved and drives the build | — |

7.7 and 7.8 were promoted from `ideas.md` on 2026-11-10: "Upload a Markdown file instead of writing definitions by hand" (its run-input part; the Architect's part is 9.11 and the definitions' part 15.5) and "Spec and prototype together". 7.8's criterion ids are what 13.4 checks. Triage on intake is 18.3.

## Milestone 13: Verification and guardrails

A gate today shows a diff and asks a person to judge it. Whether the build and tests pass, whether the agent edited the tests that judge it, and whether a run is going round in circles are left to the approver, or to CI after the PR is open. This milestone makes the platform bring evidence before a person looks, protect what judges an agent, and stop a run that goes wrong (principles 2 and 3). Promoted from the ideas "Later agents can read what earlier writers changed", "Verification gates", "Protect the grader", "Independent review through several lenses", "Circuit breakers and hard caps", "Dry run for every write", "Lethal trifecta check" and "Long-running agents with progress artifacts". Worked after Milestone 7: 13.4 checks 7.8's acceptance criteria, and 13.8 covers Jira's writes. 13.2 pulls the package-registry slice of 10.2's egress allowlist forward, as 4.8 did for NuGet. Mutation scores and "passes k times in a row" stay in `ideas.md` until coverage and fail-to-pass are in use.

| # | Phase | Done when | Status |
|---|---|---|---|
| 13.1 | Later steps read the writers' work: `repo.diff {node}` (the files a writer changed and its diff against its base) and `repo.read_file {path, node}` (a file as a writer left it) for the read-only agents after it; a node's input names the writers that ran before it; a diff is cut at the artifact cap | A reviewer after a test writer and a refactoring writer, in a sequence with no orchestrator, reads both diffs and reviews them, in a real run read step by step in the console | — |
| 13.2 | Package egress for build and test jobs: job containers (4.8) restore npm and PyPI packages through the egress proxy, each registry allowlisted on its own and every refused host logged; the build and tests after the restore run with no network | A Node and a Python repo restore their packages in a job and build with no network after it; a request to any other host is refused and logged | — |
| 13.3 | Evidence pack at the gate: deterministic tool nodes build the change and run the test suite in job containers, beside the analyzers (4.4, 4.8); the gate shows each check in a stat strip beside the diff, and a failing check sends the work back to the writer's loop instead of to a person | A writer whose change breaks a test is sent back with no person involved; a passing change reaches the gate with its build, tests and analyzers shown | — |
| 13.4 | Coverage and fail-to-pass: coverage of the changed lines joins the evidence pack, with its threshold in the workflow spec; each acceptance criterion of the spec (7.8) is linked to tests that fail on the base and pass on the change | An SDD run's gate shows coverage of the changed lines and lists each criterion with a test that failed before and passes after; a criterion with no such test sends the work back | — |
| 13.5 | Protect the grader: the workflow declares protected paths (tests approved in an earlier step, `.github/workflows/`, analyzer config, the evidence thresholds); the repo write tools refuse them for writer nodes, so a change there needs its own node and gate; in a test-first flow the approved tests are frozen for the implementer, who still reads them; every attempt is an event, counted per run and shown at the gate | An implementer told to make the tests pass cannot change them; its attempt is shown at the gate and counted on the run | — |
| 13.6 | Independent review: a `review` composite (6.6) whose reviewers start fresh, with read-only tools and only the spec, the diff and the evidence pack, never the writer's conversation; lenses (correctness, security, performance, …) run in parallel and a `reduce` dedupe merges their findings; findings above a severity go back to the writer's loop, the rest reach the gate as comments beside the diff; a lens may run on another provider once Milestone 8 adds one | A review with three lenses sends a high-severity finding back to the writer, and its other findings reach the gate as comments on the lines they name | — |
| 13.7 | Circuit breakers: the engine watches a run's events and pauses it, with the reason in the console banner, on the same tool call or the same error N times, a step costing far more than its node's average, a write outside the node's declared paths, or a file changed back and forth across turns; a person resumes or cancels it after reading why; a cap refuses, it does not warn; thresholds per workspace, overridable per workflow | Each of the four breakers pauses a test run with its own reason; an agent that repeats the same failing call is paused and goes on once a person resumes it | — |
| 13.8 | Dry run for every write: each write tool has a `plan` mode that returns what it would do, without doing it, in a shape the gate shows ("comment on PROJ-12", "transition to Done", "push 3 commits to …"); approving runs the same call for real, and a result that differs from the plan is flagged | A Jira comment and transition are approved from their plan at the gate, and the event log shows the plan and the result side by side | — |
| 13.9 | Lethal trifecta check: each tool's manifest declares whether it reads private data, reads untrusted input, or can send data out; validation and the canvas (5.6) flag a node or a flow that holds all three unless the outward step is behind a gate | A flow whose agent reads untrusted issues, reads a private repo and can post outward fails validation naming the three tools, and validates once the post is gated | — |
| 13.10 | Long-running build: a pattern for work too large for one context; an initializer writes `features.json` (each requirement with `passes: false`), `init.sh` and `progress.md`; each loop iteration a fresh agent reads them and the git log, runs the smoke test, implements one failing feature and commits; only the verification node may set `passes: true` (13.5); the console shows features passing over time, not one step per iteration | A ten-feature build runs until every feature passes or its budget is spent; the coding agent cannot mark a feature as passing; the console shows progress by feature | — |

## Milestone 8: Second provider

| # | Phase | Done when | Status |
|---|---|---|---|
| 8.1 | Verify Copilot SDK terms for hosted multi-tenant use | Go/no-go recorded in tech-stack decisions log | — |
| 8.2 | Copilot adapter + MCP tools registered as custom tools | A one-node run on Copilot works | — |
| 8.3 | Provider selection per workspace / workflow / node; capability-gap validation | AC-6: same workflow runs on Claude and Copilot unchanged | — |

## Milestone 9: Flow Architect

| # | Phase | Done when | Status |
|---|---|---|---|
| 9.1 | RepoProfile builder (cheap profiler pass), cached per commit SHA | Profile reused across runs at the same SHA | — |
| 9.2 | Architect tools: `list_primitives`, `list_custom_nodes`, `get_repo_profile`, `validate` | Architect can introspect building blocks | — |
| 9.3 | `propose_ops` with structured output (graph-ops schema) + repair loop (max 3) | Draft validates or returns errors after 3 rounds | — |
| 9.4 | `POST /architect/drafts`: Assisted mode, rationale per node | AC-4 (first half): goal → validating draft | — |
| 9.5 | Architect chat docked to canvas; proposed ops shown as diff (accept all/some/reject) | AC-4 (second half) | — |
| 9.6 | `estimate` + `search_templates` / `search_runs` (retrieval) | Draft shows cost/time estimate and is based on the closest template | — |
| 9.7 | Manual and Autonomous modes (Autonomous allowed for write flows; write gates always enforced) | Autonomous run starts immediately and still stops at write gates | — |
| 9.8 | Runtime adaptation at checkpoints (param tweaks auto, structural changes need approval) | Proposal cards appear in the monitor | — |
| 9.9 | Learn: store final graph, edits, outcome; promote to template | Highly rated flows are offered as templates | — |
| 9.10 | Evaluation set + metrics in CI | First-time-valid rate, edit distance, success rate tracked | — |
| 9.11 | Architect drafts from a Markdown file: the user uploads a `.md` file, or picks one in the repo, as the goal; the file is data, never instructions (principle 5), and each node's rationale cites the section it serves | An uploaded feature spec gives a draft that validates, and each node's rationale names the part of the file it comes from | — |

9.11 was promoted on 2026-11-10 from the Architect's part of the idea "Upload a Markdown file instead of writing definitions by hand".

## Milestone 14: Provenance and understanding

Listed here, after Milestone 9, because it is worked after the v1 outcomes.

Once a PR is merged, the link from the code to the run that wrote it lives only in our database; an approver cannot see why a hunk was written without leaving the review; and nobody measures how much of an agent's change people rewrote. This milestone keeps the story of a change with the change (principle 6, "Traceable delivery"). Promoted from the ideas "Commit trailers that link a change back to its run", "Show why each change was made beside the diff at the gate", "Measure how much of a change people edited before approving", "Ask a run why" and "Keep a run's record in the repo itself (opt-in)". "Read Entire checkpoints when profiling a repo" stays in `ideas.md` until Entire's format settles.

| # | Phase | Done when | Status |
|---|---|---|---|
| 14.1 | Commit trailers: every commit the platform makes (a writer's, an approver's edits, an integration merge) carries `Agentic-Run`, `Agentic-Workflow: <id>@v<version>` and `Agentic-Node`, and the PR body lists them, so a squash merge keeps them; no name or email is published unless the workspace opts in | `git log --format='%(trailers)'` on a platform PR's commits names the run, workflow version and node, and `⌘K` opens the run from its trailer id | — |
| 14.2 | Why beside the diff: each hunk in the gate's review links to the agent turn and tool call that last wrote it, with that turn's note shown beside it as text (rule 11); every turn that touched the hunk is listed | An approver opens the turn behind any hunk from the review without leaving it | — |
| 14.3 | Edit share: when a gate is approved, the lines the agent wrote, the lines a person changed and the lines kept are counted per file; the console shows the share edited on the run (`Percent` in its stat strip) and per workflow over time | A gate approved with edits shows the share people edited on the run and in its workflow's history | — |
| 14.4 | Ask a run why: a chat panel in the run console; a read-only agent with tools over the run's record (its steps, turns, outputs, diffs and events, with secrets redacted) answers and links each answer to the turns it used; its cost is the workspace's, not the run's | "Why did the writer change this file?" is answered with links to the turns the answer used | — |
| 14.5 | Run record in the repo (opt-in per workspace or workflow): a short JSON record and a readable summary of the run written to an orphan branch (`agentic/runs/v1`) that shares no history with the code; the push is listed as its own item at the PR's gate, never implied by approving the PR; no secrets, and prompts only if opted in; trailers point into it | An opted-in run's gate lists the record's push apart from the PR; once approved, the record is on the orphan branch, readable by someone with no access to the platform | — |

## Milestone 15: Context and reuse

Know-how such as "how we write ADRs" is pasted into node instructions again and again; a team's own tools cannot be called by its agents; a good flow cannot be offered to the rest of the team, although the mission names "publishing templates" as the tech lead's entry point; and agents do not read the rule files a repo already keeps for agents. Promoted from the ideas "Repo rules and context as versioned code", "Publish a stored workflow as a template", "Skills usable in flows and agents", "User-authored tools, published for flows and agents" and the definitions' part of "Upload a Markdown file". 15.2 comes before the template library (Milestone 16), so its templates are stored workflows, not Python code; 9.9 promotes flows into the same storage, so whichever of 9.9 and 15.2 is planned first builds it. 15.1 records in tech-stack where principle 5 draws the line for a repo's rule files.

| # | Phase | Done when | Status |
|---|---|---|---|
| 15.1 | Repo rule files as context: agents read the repo's `AGENTS.md` (then `CLAUDE.md`, `.github/copilot-instructions.md`), at the root and in the folders they work in, size-capped, and quoted as coming from the repo; they are the repo's conventions: they may shape how an agent writes code and which commands it runs in the repo, never its task, its tools, its gates or what it sends out of the sandbox, and an untrusted repo's file cannot do more than that; workspace rules come first; the console shows which files a turn loaded | An agent in a repo whose `AGENTS.md` names its package manager uses it, and the turn's Activity names the file it loaded | — |
| 15.2 | Templates as published workflows: "Publish as template" on a stored version, with a name, description, icon, the connections it requires (worked out from the spec) and the parameters a user fills in when starting it, bound to the spec by path as `setParam` does; stored per workspace, draft → published as in 6.6, and shown in the gallery beside the built-in ones | A tech lead publishes a workflow as a template, a teammate starts it from the gallery filling in its parameters, and a newer published version replaces it there | — |
| 15.3 | Skills: a published, versioned package (instructions as a `SKILL.md`, reference files, scripts and the tools it needs) in a workspace registry, imported from a `SKILL.md`; attached to an `agent` node and loaded when its task matches; copied into the sandbox; listed to the Architect beside its 9.2 tools | A skill attached to an agent node changes what the agent produces, and pinning a newer version of the skill changes it again | — |
| 15.4 | User-authored tools: a name, description, input and output JSON Schemas, and an endpoint the team hosts (HTTP or an MCP server); its credentials stored like a connection and never shown to agents; tested from its form, then published by version; granted to an `agent` node or used as a `tool` node; a tool that writes says so and runs behind a gate, and every tool declares its trifecta legs (13.9); implementations in a container come with plugin nodes (10.1) | A team's HTTP tool is published, called by an agent and as a `tool` node in the same flow, and its credentials appear in no event | — |
| 15.5 | Definitions from Markdown: a template's, skill's or tool's definition drafted by an agent from an uploaded or repo `.md` file, shown as an editable draft that must validate before it is published; nothing is published straight from the file | A README describing an internal API becomes a tool draft with its schemas, edited and published from the form | — |

## Milestone 17: Evals

Listed here, before Milestone 16, because every template of the library ships with its golden cases.

A change to a template's prompts, a new model or a new tool can make results worse, and nobody would know until users complain. Templates have no quality bar, and 9.10 measures the Architect's drafts, not runs. This milestone makes the platform test itself. Promoted from the ideas "Evals for workflows and templates" and "Digital twins of external services for safe testing". Its hourly canary needs scheduled triggers (18.1) and starts with them.

| # | Phase | Done when | Status |
|---|---|---|---|
| 17.1 | Golden cases and a runner, built on 9.10's evaluation set and CI job: per workflow, real repos at fixed commits, each with a task and the expected result (tests that must pass, findings that must be found, files that must not change); a case stops at its first write gate until the twins (17.6) exist; a fast set for every change and a full set nightly; an output score from deterministic checks | Generate docs and Audit have golden cases; the fast set runs locally with one command and reports a score per case | — |
| 17.2 | Trajectory score and a judge: a score from the events log (steps, wasted tool calls, cost, time, gates) and an LLM judge that scores the output against a rubric, on another provider than the one judged when there is one | A case's report shows its output and trajectory scores, with the judge's reasons | — |
| 17.3 | Quality gate on publishing: a workflow, template or composite version cannot be published if it scores below its previous published version on its cases; sealed cases are kept outside the sandbox the agents see | A prompt change that lowers a template's score is refused at publish, naming the cases that got worse | — |
| 17.4 | Evals page: score per workflow and version over time, and cost per passing case | The Evals page shows a template's score and cost per passing case across its versions | — |
| 17.5 | Model replay: before a workspace moves to another model or provider, the replay suite runs its cases on both and shows the difference | A model change shows both models' scores side by side before it is saved | — |
| 17.6 | Twins of external services: recorded or simulated GitHub and Jira used by evals, the e2e tests and a "rehearsal" run that touches only the twins, so a team sees what a new workflow would do to its tracker and repo | A Jira-triggered SDD case runs in evals with no real Jira, and a rehearsal run lists what it would have done | — |

## Milestone 16: Template library

The start screen offers three templates, and SDD comes in 7.5. `ideas.md` keeps a catalogue of about 150 more by area (software engineering, DevOps, cloud, infrastructure, security, frontend, data, AI and ML, documentation, planning, compliance, performance), each marked as needing only the repo or a new integration. They are built in waves by what they need: repo only first, then sandbox tooling, then integrations, then platform features. A template is a flow of existing primitives, so the work is its prompts, tool grants, checks and a validation run. Every template is a published workflow (15.2), has golden cases (17.1), follows the rules for writing workflows in `lessons.md`, and ships after a real run read step by step. Further templates are picked from the catalogue and added here, one template or one sandbox tool per phase; the templates that need cloud access follow 19.3.

| # | Phase | Done when | Status |
|---|---|---|---|
| 16.1 | Fix an issue: the issue comes from Jira (7.2) or as the run's input (GitHub issues are read from 18.2); reproduce it as a failing test, fix it, pass the evidence pack (13.3), gate, PR | On a real repo, an issue with a known bug becomes a PR whose new test failed before the fix and passes after, and its golden cases pass | — |
| 16.2 | Dependency upgrade: plan → gate → implement → build and test loop → PR, for a new major version of a library or framework (.NET 8 → 10, React 18 → 19) | A real repo is moved up one major version with its build and tests green | — |
| 16.3 | Security audit (OWASP): injection, authentication, secrets and unsafe deserialisation reviewed in parallel → a report with one fact per finding | A repo with a planted injection and a hard-coded secret gets a report naming both, each as its own finding | — |
| 16.4 | Vulnerable dependency fix: the advisories from `npm audit`, `pip-audit` or `dotnet list package --vulnerable` fixed by upgrades, in a build and test loop → PR | A repo with a known vulnerable dependency gets a PR that upgrades it with its tests green | — |
| 16.5 | Add a CI pipeline: a GitHub Actions workflow (build, test, lint) for the repo's stack, checked by `actionlint` in the sandbox → PR | A repo with no CI gets a workflow that `actionlint` accepts and that runs green on GitHub | — |
| 16.6 | IaC tools in the sandbox: `terraform`, `tflint` and `kubeconform` in the image, pinned and checked like the scanners (4.4); provider downloads through the egress proxy, as NuGet in 4.8 | `terraform validate` and `tflint` run on a repo's Terraform in a job, and a request to any host outside the allowlist is refused | — |
| 16.7 | Generate IaC for an existing app: Terraform or Bicep for what the app needs (database, storage, app service), in a validate loop → PR | A real app gets IaC that passes `terraform validate` and `tflint` | — |
| 16.8 | A headless browser in the sandbox: Playwright and axe in the image, run in a job against the app the repo serves | A job serves a repo's web app, runs axe on its main pages and returns the violations and screenshots | — |
| 16.9 | Accessibility audit and fix: the template fixes the app until axe passes on its main pages; the gate shows before and after screenshots | A web app with known axe violations gets a PR after which axe reports none of them, with screenshots at the gate | — |

## Milestone 18: Continuous work

Runs start only by hand or from a Jira or GitHub webhook, and a run ends when it opens its PR. Nothing keeps a repo healthy over time, nothing creates an issue, and when CI fails or main moves on, a person picks the PR up. Promoted from the ideas "Repo healer: continuous maintenance agent", "Triage agent: the tracker as the control plane" and "PR shepherd", with the scheduled trigger, the GitHub issue tools and the CI tools they need. Every write still goes through a gate (principle 3).

| # | Phase | Done when | Status |
|---|---|---|---|
| 18.1 | Scheduled triggers: a workflow runs on a cron schedule per repo, in the workspace's time zone; a start is skipped while the previous run is still going; schedules are listed in settings and their runs marked as scheduled; the evals' hourly canary (17) runs on one | A workflow scheduled daily starts on time, and its next start is skipped while a run is still going | — |
| 18.2 | GitHub issue tools: `github.readIssue` and `github.searchIssues` (read), and `github.createIssue`, `github.commentIssue` and `github.labelIssue` behind a gate that approves a batch at once; a new issue is checked against the open issues and PRs, so a duplicate is not created | A run proposes three issues, the one already open is skipped, and the other two are created after one approval | — |
| 18.3 | Triage on intake: a label on a GitHub issue starts a run, as 7.3 does for Jira; a read-only triage workflow on each new Jira or GitHub issue finds duplicates, asks for missing details, estimates size and proposes a label (`ready-to-implement`, `ready-to-spec`, `needs-info`, `wait`), written behind one gate for the batch; a label starts the matching flow; the labels people change afterwards are counted | A new issue is labelled after the gate and its label starts an SDD run; the share of triage labels people changed is recorded | — |
| 18.4 | Repo healer: a scheduled template that finds outdated packages, advisories, deprecated syntax and lint debt, ranks them, and opens issues for what needs a person and fix PRs for safe fixes; a cap on open PRs and a budget per run; no duplicates across runs; what Dependabot or Renovate already handles is left to them | Two scheduled runs a day apart on a real repo open no duplicate issue or PR and never more PRs than the cap | — |
| 18.5 | CI as tools and events: `github.checkRuns` and `github.jobLog` read a PR's checks and a failed job's log (cut to its failing part), and a check-run webhook tells a waiting run that CI finished | A run waiting on its PR's CI wakes when the checks finish and reads the failing job's log | — |
| 18.6 | PR shepherd: after its PR is opened, a run stays in a light "shepherding" state: it watches CI (18.5), fixes a failure from the job's log, applies review comments (7.6) and rebases when main moves; each push goes through a gate with its evidence pack; it ends when the PR can be merged, or after a time to live; merging stays human | A PR whose CI fails is fixed and pushed after approval, and the run reports that the PR can be merged | — |

## Milestone 19: Several repos and read-only cloud

A run works on exactly one repo, and it can reach only the repo, GitHub and Jira. A team cannot draw "one agent studies the API repo, another the web repo, a third combines their findings", and the templates that review what is deployed cannot read it. Promoted from the ideas "Workflows that work on several repos" and "Read-only cloud access per workspace". Cloud writes (delete, resize, apply) stay out.

| # | Phase | Done when | Status |
|---|---|---|---|
| 19.1 | Named repos per run: a workflow declares the repo roles it needs, a run names them (`repos: {api: …, web: …}`) and a node picks one (`repo: "api"`), the first when it names none; the sandbox clones each into its own folder and the repo and scan tools act on the node's repo; the run sheet asks for each repo, the side panel picks a node's, and the console shows which repo a step worked on | "One agent studies the API repo, another the web repo, a `reduce` combines them" runs, and each agent read only its own repo | — |
| 19.2 | Writers across repos: each writer's branch, gate and PR target its own repo, and a run's PRs link to each other | A change across two repos opens two linked PRs, each approved at its own gate | — |
| 19.3 | Read-only Azure access: a workspace connects a subscription read-only (a service principal or workload identity), stored encrypted like the other connections; an MCP server lists resources, cost by resource and Terraform state, with sensitive values in the state redacted before an agent reads it; agents never see the credentials, and cloud costs are kept apart from the run's model cost | An agent lists a resource group's resources and their cost this month, and the credentials appear in no event | — |
| 19.4 | Read-only AWS access, as 19.3 | An agent lists an account's resources and their cost this month, and the credentials appear in no event | — |

## Milestone 20: Operating at scale

When a team runs dozens of flows, each with orchestrated workers, nobody can see what all the agents are doing at once, steer one that goes the wrong way, or say in one place what a workspace may use. Promoted from the ideas "Steer a running agent", "Mission control", "Governance control plane", "Model routing and cost per accepted change" and "Factory metrics" (its numbers, not the factory: earned autonomy stays parked, and a limit on the gates waiting per approver waits for users and sign-in).

| # | Phase | Done when | Status |
|---|---|---|---|
| 20.1 | Steer a running agent: a message sent to a running agent node from the console; the agent loop reads it between tool calls and adds it as a turn from a person (data, principle 5), named once sign-in exists; messages are events, kept in the audit log and across a worker restart; at a gate, "Reply with feedback" sends the step back with the message | A message sent during a step changes what the agent does next, and shows in its Activity and the audit log | — |
| 20.2 | Mission control: one live board of every running run and its workers by stage (building, verifying, waiting, …), with what each agent is doing, its cost so far and its time at the current step; pause, cancel or message one from the board | With ten live runs, a stuck worker is spotted and sent a message from the board | — |
| 20.3 | Governance: a settings section for the providers and models, tools and MCP servers, and repos a workspace may use, and whether flows holding the lethal trifecta (13.9) are refused outright; policies are versioned, a run records the version it ran under, and a change is an audit event | A disallowed model or tool fails validation naming the policy, and a run shows the policy version it ran under | — |
| 20.4 | Data rules and retention: a policy names what may go to which provider (no repo content to a given one) and how long runs, events, sandboxes and saved bundles (12.2) are kept, then removed | A node whose provider a data rule forbids fails validation naming the rule, and a run older than the retention is removed with an audit event | — |
| 20.5 | Model routing and cost per accepted change: `model: auto` on a node picks a small, medium or large model from the step's kind and its eval results (17), falls back to the larger one on failure, and records the model chosen for each step; cost is reported per accepted change (runs that ended in a merged PR, with the failed attempts before them) | A workflow with `model: auto` records a model per step and costs less on its golden cases with the same score; its cost per accepted change is shown | — |
| 20.6 | Workspace metrics: flow (work in progress per stage, time in each stage, the review backlog and its age), quality (share approved without edits from 14.3, reverts, evidence failures, protected-path attempts, breakers tripped) and cost per accepted change, per workflow | The metrics page shows these numbers for a workspace and for each of its workflows | — |

## Milestone 10: Extensibility and hardening

| # | Phase | Done when | Status |
|---|---|---|---|
| 10.1 | Plugin nodes: manifest + container endpoint, own sandbox (tools behind an HTTP endpoint the team hosts are 15.4) | A linter plugin runs as a node | — |
| 10.2 | Production sandbox isolation (gVisor/Firecracker) + egress allowlist | Egress outside the allowlist is blocked | — |
| 10.3 | OpenTelemetry traces end to end | One trace spans API → nodes → tools | — |
| 10.4 | Performance: canvas with 200 nodes, monitor < 1 s, Architect draft < 60 s | Targets met in load tests | — |
| 10.5 | SaaS deployment: multi-tenant, cloud KMS, managed Postgres | Production environment live | — |
| 10.6 | A vendor's agent as a node: an `external_agent` node starts a vendor's coding agent headless in the isolated sandbox (10.2) (Claude Code first, then Codex CLI or Copilot CLI) with the node's task and the repo; its model key stays outside the sandbox, added by the egress proxy on the way to the provider, so the agent never sees it; its tool calls, output and cost are mapped to our events; our gates, breakers (13.7) and evidence pack (13.3) apply, and protected paths (13.5) are checked on its diff before the gate, since its own tools write directly | A flow runs one step on Claude Code headless and the next on an `agent` node; the console shows both steps' tool calls and cost, and a change to a protected path sends the step back | — |

10.1 was narrowed and 10.6 promoted from the idea "Any vendor's agent as a node" on 2026-11-10. 10.6 needs 10.2's isolation and egress, which is why it is not in Milestone 8; the golden cases (17.1) compare a vendor's agent with ours.

---

## Acceptance criteria map

| AC | Phase |
|---|---|
| AC-1 Docs run opens PR | 1.11 |
| AC-2 Canvas flow matches run | 6.8 |
| AC-3 Composite reuse by version | 6.6 |
| AC-4 Architect draft + chat diff | 9.4–9.5 |
| AC-5 Jira SDD | 7.5 |
| AC-6 Claude and Copilot | 8.3 |
| AC-7 Clean stop on limits | 3.2–3.3 |
| AC-8 Restart keeps completed nodes | 1.3 |
