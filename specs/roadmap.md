# Roadmap

High-level implementation order, in very small phases. Each phase is a thin vertical slice that can be demonstrated on its own. A phase is done when its "Done when" check passes. Phases are ordered, but within a milestone a later phase may start once its dependencies are done. Milestones are listed in the order we work them, which is not always their number: a milestone added later gets the next free number, so no phase is ever renumbered.

Status: `—` not started, `✅ Done (#PR)` merged. The PR that implements a phase marks it done in this file; CI marks it automatically on the PR branch and checks it (see `scripts/check_roadmap.py`, or the `complete-phase` skill to do it locally).

Strategy: **walking skeleton first**, then grow outward. The milestones follow the stakeholder plan: fixed flows first, then parallel, then dynamic, then the Architect. Milestone 2 sets the product UI foundation (design system, app shell, run history, run console) that every later screen builds on. Milestone 11 (UI v2) reworks those screens once the engine has grown, before the canvas adds many more.

**Next up: Milestone 11 (UI v2).** The `plan-feature` skill plans the first unplanned phase of this milestone before any other. Milestone 4 resumes at 4.2 after it. Change this line, in its own PR with a changelog entry, when the priority changes.

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
| 4.2 | Typed ports: input/output JSON Schemas validated at each edge | A wrong-shaped output fails at the edge with a clear error | — |
| 4.3 | Shared run context: named artifacts in the run workspace | Nodes exchange `findings.json` through artifacts | — |
| 4.4 | Deterministic tool nodes: linter, dependency scanner, secret scanner | Tool outputs feed specialist agents | — |
| 4.5 | `reduce` strategies: dedupe, vote | Duplicate findings are merged with severity and confidence | — |
| 4.6 | `router` primitive (rule + classifier agent) | A run branches on a condition | — |
| 4.7 | "Audit codebase" template (read-only, report only) | Audit run produces findings.json + readable report | — |

## Milestone 11: Product UI v2

Listed here, after Milestone 4, because it is worked next (see "Next up" above).

A review of the screens shipped in Milestones 2 and 3 found that they work but read as unfinished. Waiting time is counted as run time, stale approvals pile up above real work, test runs mix with real ones, the run console shows agent output as one long wall of text and raw JSON in table cells, and settings is one long page. UI v2 fixes the information design first and the look second. Its rules are in [tech-stack.md → UI v2](tech-stack.md#ui-v2-milestone-11). Each phase moves its part into the main design-system rules when it ships. 11.1 comes first; 11.2 and 11.3 change the API and can run beside it; the screens (11.4–11.8) build on all three. Everything it builds on (Milestones 2 and 3) is done.

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

## Milestone 5: Builder canvas and versioning

| # | Phase | Done when | Status |
|---|---|---|---|
| 5.1 | Graph operations model (`addNode`, `removeNode`, `connect`, `disconnect`, `setParam`) + `PATCH /workflows/{id}` creates a version | Applying ops produces a new immutable version | — |
| 5.2 | Canvas renders a spec; edits emit graph operations | Editing on canvas round-trips to the stored spec | — |
| 5.3 | Node manifests + palette generated from them | A new primitive appears in the palette with no frontend change | — |
| 5.4 | Side panel from parameter JSON Schema | Role, instructions, provider, tools, budget (optional) are editable | — |
| 5.5 | Container nodes (map, parallel, loop) drawn with children inside | Nested flow is editable visually | — |
| 5.6 | Live validation on canvas (incompatible ports blocked, errors on nodes) | Invalid connections cannot be made | — |
| 5.7 | Versions: history, visual diff, restore, run any version | User restores and runs an older version | — |
| 5.8 | Start screen v2: provider picker and "Blank canvas" added to the 2.6 start screen | A user starts a canvas workflow without touching JSON | — |

## Milestone 6: Dynamic orchestration and composites

| # | Phase | Done when | Status |
|---|---|---|---|
| 6.1 | `orchestrator` primitive: hub plan schema, spawn workers via `Send`, max workers/depth | A hub plans N subtasks and the engine spawns N workers | — |
| 6.2 | Replan policy (on-failure) | A failed worker triggers a replan within limits | — |
| 6.3 | Integration branch merging worker branches before the final PR | Parallel writers produce one PR | — |
| 6.4 | Monitor shows dynamic children live | Spawned workers appear with progress and cost | — |
| 6.5 | `subflow` primitive | One workflow calls another by id + version | — |
| 6.6 | `wrap` / `extract` operations; composite nodes (draft → published) | AC-3: composite saved in one workflow is reused in another, updated by version | — |
| 6.7 | Audit "fix selected findings" step with orchestrator | Selected findings become fix PRs | — |
| 6.8 | AC-2 end-to-end: canvas flow with parallel, orchestrator, loop, gate | Run matches the drawn graph | — |

## Milestone 7: Jira and Spec-Driven Development

| # | Phase | Done when | Status |
|---|---|---|---|
| 7.1 | Atlassian OAuth 3LO per workspace, project scoping | Jira connection stored encrypted | — |
| 7.2 | `jira` MCP server: read issue, comment, transition | Agent reads an issue and posts a comment | — |
| 7.3 | Jira webhook trigger on configured status/label | Moving an issue starts a run | — |
| 7.4 | Per-project field mapping (acceptance criteria, components) | Spec-writer receives mapped fields | — |
| 7.5 | SDD template: spec → gate → plan/tasks → orchestrator implement → review loop → gate → PR → Jira update (Spec Kit compatible) | AC-5 | — |
| 7.6 | GitHub webhooks: PR review comments feed a new loop iteration; `@platform fix this` | Review comment resumes the run | — |

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

## Milestone 10: Extensibility and hardening

| # | Phase | Done when | Status |
|---|---|---|---|
| 10.1 | Plugin nodes: manifest + container/HTTP endpoint, own sandbox | A linter plugin runs as a node | — |
| 10.2 | Production sandbox isolation (gVisor/Firecracker) + egress allowlist | Egress outside the allowlist is blocked | — |
| 10.3 | OpenTelemetry traces end to end | One trace spans API → nodes → tools | — |
| 10.4 | Performance: canvas with 200 nodes, monitor < 1 s, Architect draft < 60 s | Targets met in load tests | — |
| 10.5 | SaaS deployment: multi-tenant, cloud KMS, managed Postgres | Production environment live | — |

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
