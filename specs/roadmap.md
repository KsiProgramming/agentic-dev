# Roadmap

High-level implementation order, in very small phases. Each phase is a thin vertical slice that can be demonstrated on its own. A phase is done when its "Done when" check passes. Phases are ordered, but within a milestone a later phase may start once its dependencies are done.

Status: `—` not started, `✅ Done (#PR)` merged. The PR that implements a phase marks it done in this file; CI marks it automatically on the PR branch and checks it (see `scripts/check_roadmap.py`, or the `complete-phase` skill to do it locally).

Strategy: **walking skeleton first**, then grow outward. The milestones follow the stakeholder plan: fixed flows first, then parallel, then dynamic, then the Architect. Milestone 2 sets the product UI foundation (design system, app shell, run history, run console) that every later screen builds on.

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
| 1.12 | Create new repo (behind a gate) + scaffold commit | Docs run works on a newly created repo | — |

## Milestone 2: Product UI foundation

Milestone 1 proved the engine end to end, but the UI is a debug view. Every later milestone (cost, canvas, Architect) adds screens, so the design system, app shell and run console come first. The rules are in [tech-stack.md → UI design system](tech-stack.md#ui-design-system). This milestone does not depend on 1.12.

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
| 3.2 | Policy limits: agents alive/spawned, depth, iterations, wall time | Exceeding a limit stops the run cleanly with a reason | — |
| 3.3 | **Optional budget**: if set, hard stop at 100%; if unset, no cap | AC-7 for budgeted runs; an unbudgeted run continues and still reports cost | — |
| 3.4 | Validation endpoint `POST /workflows/{id}/validate` (schema, ports, cycles, policy) | Invalid specs return actionable errors | — |
| 3.5 | Graph tab in the run console: read-only graph (React Flow) with status colours; selecting a node opens the node detail from 2.5 | Clicking a node in the graph shows what the agent did | — |
| 3.6 | Editable artifacts in the approval dock (2.6): diff view, edit before approving | Gate is approved from the UI with edits | — |
| 3.7 | Audit log view for admins | Every run and approval is listed per workspace | — |

## Milestone 4: Parallel and Audit

| # | Phase | Done when | Status |
|---|---|---|---|
| 4.1 | `parallel` primitive with join policies (all/any/quorum) | Three branches run concurrently and join correctly | — |
| 4.2 | Typed ports: input/output JSON Schemas validated at each edge | A wrong-shaped output fails at the edge with a clear error | — |
| 4.3 | Shared run context: named artifacts in the run workspace | Nodes exchange `findings.json` through artifacts | — |
| 4.4 | Deterministic tool nodes: linter, dependency scanner, secret scanner | Tool outputs feed specialist agents | — |
| 4.5 | `reduce` strategies: dedupe, vote | Duplicate findings are merged with severity and confidence | — |
| 4.6 | `router` primitive (rule + classifier agent) | A run branches on a condition | — |
| 4.7 | "Audit codebase" template (read-only, report only) | Audit run produces findings.json + readable report | — |

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
