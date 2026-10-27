Agentic Dev Platform: Product & Technical Spec
Oct 21, 2026 · @Said LABANI
1. Overview and goals
The platform runs AI agent workflows on a codebase: generate docs, audit code, and implement features spec-first from Jira. Its defining choice is that orchestration is open. A workflow is a graph the user draws, a planner agent drafts, or both build together. No fixed list of patterns is baked into the product.
Problem. Today each job (docs, audit, feature work) needs a different mix of sequential steps, parallel workers and review loops. Single-agent tools run one loop; workflow builders are not code-aware. Teams need both, on their own repos and with the model access they already pay for.
Goals
• G1. Run docs generation, codebase audit and spec-driven development (SDD) on an existing repo or a newly created one.
• G2. Let users design any orchestration from composable primitives, and save new node types and templates.
• G3. Provide a Flow Architect agent that reads the task and repo context and proposes a workflow graph the user can edit.
• G4. Let users bring their model access: a Claude API key or their GitHub Copilot subscription.
• G5. Deliver every code change as a branch and pull request, traceable to the Jira issue that started it.
Non-goals for v1
• An IDE plugin or inline code completion.
• Merging to protected branches without a human approval.
• GitLab, Bitbucket, Linear and Azure DevOps (adapters come later).
• Self-hosted local models.
2. Users and use cases
Three personas share one product: a developer who wants a result, a tech lead who shapes how the team's agents work, and a platform admin who sets limits.
Persona
Wants
Typical entry point
Developer
Docs, an audit report or a PR, with little setup
Pick a template or describe the goal in chat
Tech lead
Workflows that match the team's process, reused across repos
Edit a drafted flow on the canvas, publish it as a template
Platform admin
Control of cost, tools, secrets and data access
Workspace policies and audit log
User stories
• US-1. As a developer, I select one of my GitHub repos or create a new one, then run a workflow on it.
• US-2. As a developer, I describe a goal in plain words ("document the payments module and flag security risks"), and the Flow Architect proposes a workflow I can run as is or edit.
• US-3. As a tech lead, I draw a workflow from primitives, with parallel workers, a hub that delegates, review loops and approval gates.
• US-4. As a tech lead, I save a sub-flow as a reusable custom node (for example "security review") and use it in other workflows.
• US-5. As a developer, I move a Jira issue to a chosen status, and an SDD workflow starts: spec, my approval, implementation, PR, Jira update.
• US-6. As a developer, I choose per workspace or per node whether agents run on my Claude API key or my GitHub Copilot subscription.
• US-7. As anyone, I watch a run live, see what each agent did and what it cost, and approve or edit at gates.
• US-8. As an admin, I cap spend, parallelism and tool access, and every run is logged.
3. System architecture
One versioned workflow spec sits at the centre. The canvas, the chat and the Flow Architect change it; the engine executes it; the monitor shows what happened.
Dashed boxes are external services. The Flow Architect also receives runtime checkpoints from the engine (section 5.3, step 8).
Component
Responsibility
Frontend
Builder canvas, Architect chat, run monitor; palette rendered from node manifests
Spec store
Versioned workflows, graph-operation history, node manifests, templates
Flow Architect
Agent that turns goal and context into graph operations
Orchestration engine
Validation, policy enforcement, scheduling, dynamic worker spawning, durable state (Temporal or LangGraph)
Agent runtime
One interface, Claude and Copilot adapters
Tool layer
MCP servers for repo, tests, GitHub, Jira and plugin nodes
Sandbox manager
Container per run, git worktree per writer, egress allowlist
Event log
Append-only run events feeding the monitor, cost view and audit
4. Open orchestration model
Orchestration is not a closed list of patterns. The engine knows a small set of primitives, and every pattern (hub and spoke, map-reduce, pipeline, debate, review loop) is a graph built from them. Users and the Flow Architect extend the set with custom nodes, so new patterns need no engine release.
4.1 Three layers of extensibility
1. Primitives (shipped with the engine, versioned): the minimum the executor must understand.
2. Composite nodes (user-defined, no code): a saved sub-flow with typed inputs and outputs. It appears in the palette like a primitive. Example: "Security review" = router + 3 specialist agents + reduce.
3. Plugin nodes (user-defined, with code): a manifest plus a container or HTTP endpoint for steps no agent should do, such as running a linter, calling an internal API or computing a metric.
4.2 Primitives
Primitive
Purpose
Key parameters
agent
One agent loop with a role and tools
role, instructions, tools, provider, model, output schema, budget
tool
One deterministic call, no LLM
tool id, arguments
sequence
Run children in order
children
parallel
Run fixed branches at once
branches, join policy (all, any, quorum)
map
Run a sub-flow per item of a list known at that point
items expression, sub-flow, max concurrency, isolation
reduce
Merge many results into one
strategy (agent, concat, dedupe, vote), schema
orchestrator
A hub plans subtasks at runtime; the engine spawns workers
hub agent, plan schema, worker sub-flow or worker library, max workers, max depth, replan policy
router
Choose a branch by rule or by an agent
condition or classifier agent, branches
loop
Repeat until a condition holds
body, until expression, max iterations
gate
Wait for a human decision or edit
approvers, artifact to show, timeout, on-timeout action
subflow
Call another workflow by id and version
workflow ref, input mapping
4.3 Contracts that keep an open set safe
• Typed ports. Every node declares input and output JSON Schemas. The canvas only connects compatible ports, and the engine validates data at each edge.
• Shared run context. Nodes read and write named artifacts (spec.md, findings.json, branch:feature-x) in a run workspace, not hidden memory.
• Expressions. Conditions and mappings use one sandboxed expression language (CEL or JSONata), never arbitrary code.
• Node manifest. Custom nodes ship a manifest: id, version, ports, parameters schema, required tools and permissions, and a UI hint (icon, color, form layout). The palette and side panel render from the manifest, so the frontend needs no change per node.
4.4 Graph operations: one way to change a flow
The canvas, the chat and the Flow Architect all change a workflow through the same operations, applied to the versioned spec. This gives undo, diffs, review and an audit trail for free.
Operation
Example
addNode
add agent "perf-reviewer" inside audit-spokes
removeNode
remove gate "approve-spec"
connect / disconnect
connect build.out to review.in
setParam
set map.maxConcurrency to 6
wrap
wrap nodes A and B into a new parallel
extract
turn a selection into a composite node
4.5 Workflow spec (excerpt)
{
  "id": "audit-and-fix",
  "version": 4,
  "inputs": { "repo": "repoRef", "focus": "string?" },
  "nodes": [
    { "id": "profile", "type": "agent", "role": "repo-profiler", "output": "RepoProfile" },
    { "id": "spokes", "type": "parallel", "join": "all",
      "branches": ["composite:security-review@2", "perf", "deps", "tests"] },
    { "id": "merge", "type": "reduce", "strategy": "agent", "schema": "Findings" },
    { "id": "approve", "type": "gate", "show": "findings.md" },
    { "id": "fix", "type": "orchestrator", "hub": { "role": "tech-lead" },
      "worker": { "type": "agent", "role": "implementer", "isolation": "worktree" },
      "maxWorkers": 4, "maxDepth": 1, "replan": "on-failure" }
  ],
  "edges": [["profile","spokes"],["spokes","merge"],["merge","approve"],["approve","fix"]],
  "policy": { "budgetUsd": 25, "maxAgents": 12, "writeRequiresGate": true }
}
5. Flow Architect agent
The Flow Architect is an agent whose output is a workflow, not code. It reads the goal, the repo and the available building blocks, then proposes a graph as graph operations with a reason for each node. The user can run it, edit it, or ask for changes in chat. During a run it can propose changes to the graph, within policy.
5.1 Three modes
Mode
Who designs
When the flow runs
Default for
Manual
User on the canvas; Architect only validates and suggests
User presses Run
Tech leads building templates
Assisted
Architect drafts; user edits on canvas or in chat
After user approves the draft
Most runs (default)
Autonomous
Architect drafts and starts the run
Immediately, gates still apply to writes
Repeated jobs with a proven template
5.2 Inputs
• Goal: free text, a template name, or a Jira issue.
• RepoProfile: languages, size in files and lines, module graph, test framework, CI config, build commands, hot spots by churn. Built by a cheap profiler pass, cached per commit SHA.
• Building blocks: primitives and the manifests of every custom node the workspace can use.
• Constraints: workspace policy, budget, providers and tools the user connected.
• Memory: workspace templates and past runs with their outcomes (success, cost, user edits).
5.3 Design pipeline
1. Understand. Classify the intent (document, audit, implement, migrate, other) and extract constraints. If a choice changes the flow a lot and the context does not settle it, ask at most 3 questions.
2. Profile. Load or build the RepoProfile.
3. Retrieve. Find the closest templates and past successful runs by intent and repo profile.
4. Compose. Adapt the closest template, or build from primitives using the heuristics in 5.4. Output is a list of graph operations, never free-form JSON.
5. Validate. Schema, port types, cycles, tool permissions, policy limits. Failures go back to step 4 (max 3 repair rounds).
6. Estimate. Expected agent count, token use, cost and wall time, from the profile and from past runs of similar flows.
7. Present. Show the graph on the canvas with a one-line rationale per node and the estimate. The user edits; the Architect repairs anything the edit broke.
8. Adapt at runtime. At checkpoints (a node fails, a hub's plan differs from the estimate, a reviewer rejects twice), the Architect may propose operations. Parameter tweaks inside policy apply automatically; structural changes need approval except in Autonomous mode.
9. Learn. Store the final graph, user edits and outcome. Highly rated flows can be promoted to workspace templates.
5.4 Pattern heuristics
The Architect is guided by these rules in its instructions, and they are overridable per workspace.
Signal in goal or repo
Pattern it chooses
Small, local change (few files, one module)
Single agent plus a test loop. Avoid orchestration overhead.
Work splits into units known up front (modules, packages, files)
map over the units, then reduce
Same input needs several kinds of expertise
parallel specialists, then reduce (hub and spoke with fixed spokes)
Subtasks are unknown until the work is analysed
orchestrator with a planning hub (dynamic decomposition)
Repo is too large for one context window
map summariser over modules first, then the main flow on the summaries
Quality has a machine check (tests, lint, schema)
loop until the check passes, max N iterations
Quality is a judgement
reviewer agent in a loop, or a vote across 2–3 reviewers
Action is hard to undo (push, merge, create repo, change Jira)
gate before it
5.5 How it is built
The Architect is an agent node with a fixed tool set: list_primitives, list_custom_nodes, get_repo_profile, search_templates, search_runs, propose_ops, validate, estimate, dry_run. Its final answer must match the graph-operations schema (structured output). It runs as a workflow itself, so its own steps are visible in the run monitor.
Limits. It cannot exceed workspace policy, grant itself tools, or publish custom nodes. New composite nodes it invents are saved as drafts for a human to publish.
Quality bar. Maintain an evaluation set of goal and repo pairs. Track: share of drafts that validate first time, user edit distance before Run, run success rate, and cost versus the best known template.
6. Built-in workflow templates
Three templates ship on day one. They are ordinary workflows built from the primitives in section 4, so users can open, change or copy them, and the Flow Architect uses them as starting points.
6.1 Generate docs
1. agent repo-profiler builds the RepoProfile and a module list.
2. map over modules (max 6 at once): a writer agent documents each module's purpose, public API, data flow and a Mermaid diagram.
3. reduce assembles an index, architecture overview and cross-links.
4. loop (max 2): a reviewer checks claims against the code and flags anything not supported.
5. gate, then tool opens a PR adding /docs, or publishes to a docs site.
Output: Markdown docs in the repo, plus a coverage report listing undocumented modules.
6.2 Audit codebase
1. agent repo-profiler.
2. parallel specialists, each with read-only tools: security, performance, dependencies and licences, test coverage, architecture and maintainability. Deterministic tool nodes run alongside (dependency scanner, linter, secret scanner) and feed the agents.
3. reduce with an agent: deduplicate, score severity and confidence, link each finding to file and line.
4. gate: the user picks findings to fix.
5. Optional orchestrator: a hub groups selected findings into fix tasks; workers fix them in separate worktrees; each fix runs tests.
Output: findings.json, a readable report, and optional fix PRs.
6.3 Spec-driven development from Jira
Stages follow the spec, plan, tasks, implement sequence used by GitHub Spec Kit, so specs stay compatible with that toolkit.
1. Trigger: Jira issue moved to a chosen status, or started by hand.
2. agent spec-writer reads the issue, linked issues and relevant code; writes spec.md (requirements, acceptance criteria, open questions).
3. gate: user approves or edits the spec. Open questions can be posted back to Jira as a comment.
4. agent planner writes plan.md (approach, files, risks) and tasks.json with dependencies.
5. orchestrator: the hub schedules tasks by dependency; workers implement in worktrees; each task loops on tests.
6. loop reviewer checks the combined diff against the spec's acceptance criteria.
7. gate, then tool opens the PR, comments on the Jira issue with spec, plan and PR links, and moves the issue status.
7. Repositories, GitHub and Jira
All repo access goes through a GitHub App the user installs on chosen repos; Jira connects through Atlassian OAuth. No personal access tokens are stored.
7.1 Repositories
• Select existing. List repos the app is installed on; pick branch (default: the default branch).
• Create new. Name, visibility, owner (user or org), optional starter template. The platform creates it through the GitHub API, commits a scaffold, then the workflow runs on it. Creating a repo is behind a gate unless the user started the action themselves.
• Checkout. Each run gets a fresh sandbox with a shallow clone. Each parallel writer gets its own git worktree and branch (agent/<run-id>/<node-id>).
• Output. Changes always land as branches and PRs. Integration branches merge worker branches before the final PR. Direct pushes to protected branches are never allowed.
7.2 GitHub events
• Webhooks: PR comments ("@platform fix this"), check-run results, issue labels can start or resume workflows.
• PR review comments on an agent's PR are fed back to the run as a new loop iteration.
7.3 Jira
• OAuth 2.0 (3LO) per workspace, scoped to selected projects.
• Triggers: issue moved to a configured status (for example "Ready for AI"), label added, or manual start from the platform.
• Write-backs: comment with spec, plan and PR links; status transitions at configured stages; optional sub-tasks created from tasks.json.
• Field mapping (acceptance criteria field, story points, components) is set per project.
7.4 Integrations as tools
GitHub, Jira and the repo sandbox are exposed to agents as MCP servers with fine-grained tools (repo.read, repo.write, tests.run, jira.comment, github.openPR). New integrations (GitLab, Linear, Confluence) are added as MCP servers and become available to nodes through their manifests.
8. Model providers
Every agent node runs through one AgentRuntime interface with two adapters at launch: Claude via the user's API key, and GitHub Copilot via the user's subscription. The provider is chosen per workspace, overridable per workflow and per node.

Claude API key
GitHub Copilot
Runtime
Claude Agent SDK, or own tool loop on the Messages API
GitHub Copilot SDK (generally available since June 2026)
Auth
User pastes key; stored encrypted with a KMS key per workspace
GitHub OAuth or the platform's GitHub App
Billing
User's Anthropic account
User's Copilot plan; prompts count against premium requests
Tools
Platform MCP servers
Same MCP servers, registered as custom tools
Hooks
Pre/post tool use in the platform's loop
SDK hooks for pre/post tool use and permission requests
Interface (sketch)
interface AgentRuntime {
  start(session: {
    role: string; instructions: string; model?: string;
    tools: ToolRef[]; outputSchema?: JSONSchema; budget: Budget;
    workspace: SandboxRef;
  }): AsyncIterable<AgentEvent>; // text, tool_call, tool_result, usage, done, error
  cancel(sessionId: string): Promise<void>;
}
Rules
• Tools live in the platform, not in a provider, so a workflow behaves the same on either runtime.
• Each adapter maps usage to one usage event (tokens, premium requests, estimated USD) for budgets and the cost view.
• If a node needs a capability a provider lacks (for example a given structured output mode), validation flags it before the run.
• The Flow Architect can assign a stronger model to hubs and reviewers and a cheaper one to map workers, within the user's providers.
9. Frontend
The frontend has three views on one object, the workflow spec: a canvas to design it, a chat to talk to the Flow Architect about it, and a monitor to watch it run. All three emit and render the same graph operations (section 4.4), so they stay in sync.
9.1 Start screen
• Repo picker (existing or "create new") and provider picker.
• Three ways in: a template card, a goal typed in plain words (goes to the Architect), or a blank canvas.
9.2 Builder canvas
• React Flow (xyflow) canvas. The canvas state is the spec; there is no separate UI model.
• Palette generated from primitives plus node manifests, grouped: Agents, Control flow, Tools, My nodes, Workspace nodes.
• Containers for map, parallel, orchestrator and loop: children are drawn inside. An orchestrator shows its hub at the top and a worker template below.
• Side panel rendered from the node's parameter schema: role, instructions, provider and model, tools, budget, output schema.
• Live validation: incompatible ports cannot connect; errors show on the node; a cost and time estimate updates as the graph changes.
• Composite nodes: select nodes, choose "Make reusable node", name its inputs and outputs, publish to workspace.
• Versions: every save is a version with a visual diff; any version can be restored or run.
9.3 Architect chat
• Docked beside the canvas. The user writes "add a performance reviewer before the PR" or "why 6 workers?".
• The Architect replies with a short answer and a set of proposed operations shown as a highlighted diff on the canvas: green for added nodes, red for removed. Accept all, accept some, or reject.
• Each node shows its rationale on hover, so the user sees why the Architect chose it.
9.4 Run monitor
• The same graph, read-only, colored by status: queued, running, waiting for approval, done, failed.
• Dynamic children appear live when a hub plans subtasks or a map fans out; each shows progress and cost.
• Clicking a node opens its transcript, tool calls, diffs, artifacts and token use.
• Gates appear as approval cards with the artifact to review (spec, findings, diff), editable before approving.
• Runtime change proposals from the Architect appear as cards with the same diff view as the chat.
• Live updates through server-sent events from the run's event log.
9.5 Stack
Next.js and TypeScript, React Flow for canvas and monitor, a JSON-Schema form library for side panels, Monaco for viewing diffs and editing instructions, TanStack Query plus SSE for data.
10. Guardrails, security and non-functional requirements
An open orchestration model is only safe if limits are enforced by the engine, not by the graph. Every limit below is checked at validation time and again at runtime.
10.1 Policy limits (per workspace, overridable per workflow within the workspace cap)
Limit
Default
Budget per run
25 USD, hard stop at 100%
Agents alive at once
8
Agents spawned per run
40
Orchestrator nesting depth
2
Loop iterations
5
Run wall time
2 hours
Gate required before
push, PR, repo creation, Jira status change
The defaults are starting values to tune with real usage.
10.2 Security
• Sandboxes: one container or microVM per run, no host access, network egress limited to an allowlist (package registries, GitHub, the model provider).
• Least privilege: tools are granted per node; audit agents get read-only tools.
• Secrets: API keys and OAuth tokens encrypted with KMS, never exposed to agents or logs; agents call tools that hold the credentials.
• Prompt injection: repo content, Jira text and web pages are treated as data. Write actions require a gate or a policy allowing them.
• Custom code: plugin nodes run in their own sandbox with declared permissions only.
10.3 Reliability and observability
• Durable execution: a run survives worker restarts and resumes from the last completed node.
• Retries with backoff for tool and model errors; idempotent tool calls where possible.
• Append-only event log per run; OpenTelemetry traces across nodes; cost and token metrics per node, run, user and workspace.
10.4 Performance targets
• Canvas usable with 200 nodes.
• Run monitor shows an event within 1 second of it happening.
• Flow Architect returns a first draft within 60 seconds for a repo already profiled.
11. Data model and API surface
Ten core entities cover the product; workflows and node types are versioned and immutable once published.
Entity
Key fields
Notes
Workspace
id, name, policy, default provider
Tenant boundary
Connection
id, workspace, kind (github, jira, claude, copilot), encrypted credentials ref
One per integration account
Repo
id, connection, owner/name, default branch, profile ref
Profile cached per commit SHA
NodeType
id, version, kind (primitive, composite, plugin), manifest, status (draft, published)
Manifest drives palette and side panel
Workflow
id, version, spec (JSON), author (user or architect), parent version
Spec as in 4.5
Template
workflow ref, tags, intents, rating
Searchable by the Architect
Run
id, workflow version, inputs, status, budget used, mode, trigger

NodeRun
id, run, node id, parent node run, status, provider, usage, artifacts
Tree for dynamic children
RunEvent
run, sequence, type, payload, timestamp
Append-only; source for the monitor
Approval
run, node run, approver, decision, edits
Gates and runtime change proposals
API (REST + SSE)
Method and path
Purpose
GET /repos, POST /repos
List connected repos; create a new repo
GET /node-types, POST /node-types
Palette; publish a composite or plugin node
POST /workflows, PATCH /workflows/{id}
Create; apply graph operations (creates a new version)
POST /workflows/{id}/validate
Validate and estimate cost
POST /architect/drafts
Goal + repo + constraints in, proposed operations + rationale out
POST /architect/drafts/{id}/messages
Chat turn; returns proposed operations
POST /runs
Start a run of a workflow version
GET /runs/{id}/events
SSE stream of run events
POST /runs/{id}/approvals
Approve, reject or edit at a gate
POST /runs/{id}/cancel
Cancel a run
POST /webhooks/github, POST /webhooks/jira
Inbound triggers
12. Delivery, acceptance criteria and open questions
Delivery runs in four phases. Each one ships a usable template, and the open orchestration model grows one layer at a time: fixed flows first, then parallel, then dynamic, then the Architect.
A phase closes when its listed acceptance criteria pass; phase lengths are not set yet.
12.1 Acceptance criteria (proposed)
[ ] AC-1 (US-1). A user connects GitHub, selects a repo or creates one, and completes a docs run that opens a PR.
[ ] AC-2 (US-3). A user builds a flow with parallel, orchestrator, loop and gate on the canvas, and the run matches the drawn graph.
[ ] AC-3 (US-4). A composite node saved in one workflow can be used in another and is updated by version.
[ ] AC-4 (US-2). From a plain-language goal, the Architect returns a draft that validates; the user edits it in chat; changes show as a diff before applying.
[ ] AC-5 (US-5). Moving a Jira issue to the trigger status starts SDD; the issue receives spec, plan and PR links.
[ ] AC-6 (US-6). The same workflow runs on a Claude key and on Copilot with no change to the spec.
[ ] AC-7 (US-8). A run that hits its budget or agent limit stops cleanly, with the reason in the monitor.
[ ] AC-8. A worker restart mid-run does not lose completed nodes.
12.2 Open questions
[ ] Engine: Temporal (durable, language-agnostic) or LangGraph (Python-native, agent-oriented)?
[ ] Hosting: SaaS only, or also self-hosted for enterprises?
[ ] Pricing: who pays for sandbox compute when users bring their own model access?
[ ] Is Autonomous mode allowed for workflows that write code in v1, or only for read-only flows?
[ ] Check the Copilot SDK terms for use inside a hosted multi-tenant service before committing to that adapter.
Sources
• GitHub Copilot SDK is now generally available, GitHub changelog, June 2026
• GitHub Spec Kit

Also we need to put budget an optional option, when not set the flow goes on.
---

# Development

## Run locally
Requires Docker. Postgres and Redis stay inside the compose network; only the API and web app are published.

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000/health (liveness), http://localhost:8000/health/ready (Postgres + Redis), http://localhost:8000/docs
- Web: http://localhost:3000

## Tests and checks
Python (uv workspace, Python 3.12):

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest                  # integration tests need Docker (Testcontainers)
uv run pytest -m "not integration"
```

On Docker Desktop for Windows, set `TESTCONTAINERS_RYUK_DISABLED=true` if Testcontainers reports "Port mapping ... 8080 is not available".

Web (Node 24, pnpm):

```bash
cd web
pnpm install
pnpm lint && pnpm format:check && pnpm typecheck && pnpm test
pnpm exec playwright install chromium
E2E_BASE_URL=http://localhost:3000 pnpm test:e2e   # against a running app
```

## API client
The web client's types are generated from the API's OpenAPI spec. After changing an endpoint:

```bash
uv run python scripts/export_openapi.py
cd web && pnpm gen:api
```

CI fails if `web/openapi.json` or `web/src/api/schema.d.ts` is out of date.

## Workflow spec
A workflow is a JSON document validated by the Pydantic models in `agentic_engine.spec` (`parse_spec(data)` raises `pydantic.ValidationError` on a bad spec). v0 has eight node types:
- `agent`: one agent turn (`role`, `instructions`, optional `provider`, `model` and `tools`);
- `tool`: one call of a platform tool with fixed arguments and no model, e.g. `{"type": "tool", "id": "list", "tool": "repo.list_files", "args": {"path": "."}}`;
- `gate`: a pause until a human approves or rejects (`title`, optional `prompt`); see [Gates](#gates);
- `sequence`: its `steps`, in order;
- `loop`: its `body`, again and again until a CEL condition (`until`) is true, at most `max_iterations` times; see [Loops](#loops);
- `map`: its `body` once per item of a CEL list (`over`), at most `max_concurrency` at a time; see [Map and reduce](#map-and-reduce);
- `reduce`: the outputs of an earlier map (`from`), combined by `concat` or by an `agent`; see [Map and reduce](#map-and-reduce);
- `parallel`: its `branches` at the same time, joined when `all`, `any` or a `quorum` of them completed; see [Parallel](#parallel).

Node ids are unique slugs (`^[a-z][a-z0-9_-]{0,62}$`) and unknown keys are rejected.

- JSON Schema: [schemas/workflow-spec.v0.json](schemas/workflow-spec.v0.json)
- Examples: [packages/engine/tests/fixtures/specs/valid/](packages/engine/tests/fixtures/specs/valid/)

The schema is generated from the models. After changing them:

```bash
uv run python scripts/export_workflow_schema.py
```

CI fails if `schemas/workflow-spec.v0.json` is out of date.

## Agent runtime
`agentic_runtime` defines the provider-neutral `AgentRuntime` interface: `start(AgentRequest)` returns an `AgentRun`, which you iterate once for `AgentEvent`s and can `cancel()` at any time. Events are `text_delta`, `message`, `tool_call`, `tool_result`, `usage`, and exactly one terminal event (`completed`, `failed` or `cancelled`). The contract is documented in `agentic_runtime/protocol.py` and checked by `check_events`.

Tests use `FakeRuntime` (`agentic_runtime.fake`), which replays a script per node id and echoes the input for unscripted nodes. `Delay` steps let tests cancel mid-run:

```python
runtime = FakeRuntime({"reviewer": [ToolCall(call_id="c1", name="repo.read_file"),
                                    ToolResult(call_id="c1", output="..."),
                                    Message(text="LGTM"), Usage(input_tokens=5, output_tokens=1)]})
result = await run_agent_node(node, runtime, input="draft")  # agentic_engine.agent
```

The runtime and engine test suites block all non-loopback network access (`agentic_runtime.testing.block_network`); tests marked `integration` are exempt.

### Claude adapter
`ClaudeRuntime` (`agentic_runtime.claude`) runs requests on the Anthropic Messages API with our own loop:

- `role` and `instructions` form the system prompt. `input` goes in the user turn inside an `<input>` block marked as data.
- Each API call streams `text_delta` events, then emits one `usage` event (input tokens include cache tokens). A finished turn adds `message` (the final turn's text) and `completed`.
- When Claude asks for tools, each one becomes a `tool_call`, runs through the `ToolExecutor` given to the runtime, and becomes a `tool_result` that is sent back. Then the loop calls the API again, up to `max_turns` (default 50, `CLAUDE_MAX_TURNS`). Platform tool names such as `repo.read_file` are sent to the API as `repo__read_file`. A request that names tools the executor cannot offer fails before any API call. No real tools exist until phase 1.2.
- Each API call may write up to `max_tokens` (default 32,000, `CLAUDE_MAX_TOKENS`). Writers send whole files as tool input, so the cap must fit several pages.
- API errors become `failed`. Rate limits, overloaded and 5xx responses, timeouts and connection errors are marked `retryable`. Hitting `max_tokens`, a refusal, or running out of turns fails without `retryable`.

Tests use `agentic_runtime.testing.MockClaude`, a real `AsyncAnthropic` on an in-memory transport that replays scripted SSE replies (`text_reply`, `tool_use_reply`, `error_reply`) and records request bodies. `collect_and_check(runtime, request)` runs a request and checks the stream against the contract for any adapter.

## Engine
`agentic_engine.graph` compiles a workflow spec to a LangGraph graph and runs it. `agent`, `tool` and `gate` nodes become graph nodes named by their spec node id, a `sequence` chains its steps, a `loop` adds an entry node, its body and a check node with an edge back (see [Loops](#loops)), and a `map` adds an entry node, a worker that LangGraph's `Send` starts once per item, and a join node (see [Map and reduce](#map-and-reduce)), and a `parallel` adds an entry node, a worker that `Send` starts once per branch, and a join node (see [Parallel](#parallel)). The first node gets the run input; each later node gets the previous node's output text as its `input` (data, never instructions). A node that ends `failed` or `cancelled` stops the run. `result.order` lists every node run, so a node in a loop appears once per iteration, and `result.usage` adds up every run.

A `tool` node calls the `ToolExecutor` passed as `run_workflow(..., tools=)` (the worker passes the same per-run tools its agents get). It writes one `tool_call` and one `tool_result` event, and its output text becomes the next node's input. An error result, an exception or a run without tools fails the node.

```python
result = await run_workflow(spec, FakeRuntime(), input="Write the overview.")
result.status, result.order, result.text, result.usage, result.stopped_at
```

With a `checkpointer` (any LangGraph saver built with `checkpoint_serde()`), `run_workflow` saves the graph state after each node in the thread named by the run id, and `resume_workflow` carries a cut-off run on from there: nodes that completed are not run again, and the node that was cut off runs again from its start. See [Durable runs](#durable-runs).

A `gate` node pauses the run: `run_workflow` returns status `waiting` with `waiting_at` the gate, and `resume_workflow(..., decision=GateDecision(...))` continues it. See [Gates](#gates).

LangGraph ships no type information, so `typings/langgraph/` holds minimal stubs for the parts the engine uses; extend them when you use more of its API.

## Run event log
Every run writes one ordered stream of events (`agentic_engine.events.RunEvent`): `run_started`, then for each node `node_started`, the node's agent events and `node_completed` / `node_failed` / `node_cancelled`, then `run_completed` / `run_failed` / `run_cancelled`. `seq` numbers the events 1, 2, … per run. Agent events keep their `AgentEvent` type, and their `payload` is the serialised event (`event.agent_event()` parses it back).

The engine has no database code. It hands events to an `EventSink` passed to `run_workflow`. Tests use `InMemoryEventSink`. `agentic_store.PostgresEventSink` writes each event to the append-only `run_events` table in its own transaction, keeps the run's status in `runs` (`queued` → `running` → final status, with `waiting` while paused at a gate), and sends `pg_notify('run_events', '<run_id>:<seq>')` with each insert. The run's row must exist first:

```python
sessions = async_sessionmaker(create_async_engine(database_url), expire_on_commit=False)
run_id = await create_run(sessions, spec, "go")  # status "queued"
await run_workflow(spec, runtime, "go", run_id=run_id, sink=PostgresEventSink(sessions))
events = await list_run_events(sessions, run_id)  # ordered by seq
```

The `agentic_store` package holds the SQLAlchemy models. The Alembic revisions in `packages/api/alembic/` migrate them, and the migration test runs `alembic check` so the two cannot drift.

## Runs API
`POST /runs` takes an inline workflow spec and an input, stores a `queued` run and puts its id on the Redis queue (`runs:queue`). The worker (`python -m agentic_worker`) takes it, runs it and writes its events to Postgres. `GET /runs/{id}/events` streams them as Server-Sent Events: stored events first, then new ones as they are written, ending after `run_completed` / `run_failed` / `run_cancelled`. Each frame's `id` is the event's `seq`, `event` its type and `data` the `RunEvent` JSON. To resume, send `Last-Event-ID: <seq>` (browsers do this on reconnect) or `?after=<seq>`.

With the stack running (`docker compose up`):

```bash
curl -s -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d "{\"workflow\": $(cat packages/engine/tests/fixtures/specs/valid/two-step-sequence.json), \"input\": \"Write the overview\"}"
# {"run_id":"<id>","status":"queued","events_url":"http://localhost:8000/runs/<id>/events"}
curl -N localhost:8000/runs/<id>/events
```

By default the worker runs every node on the fake runtime, which echoes its input word by word. `FAKE_STEP_DELAY_S` (0.5 s in compose) paces its events so the stream is visibly live.

### Run on Claude
Start the stack with `AGENTIC_RUNTIME=claude`, store your Claude API key, then run a one-node workflow. To store the key, open http://localhost:3000/settings and paste it, or use `curl` as below:

```bash
AGENTIC_RUNTIME=claude docker compose up -d --build
curl -s -X PUT localhost:8000/workspaces/00000000-0000-0000-0000-000000000001/connections/claude   -H 'content-type: application/json' -d '{"api_key": "<your key>"}'
# {"id":"<id>","provider":"claude","key_hint":"<last 4>",...}
curl -s -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d "{\"workflow\": $(cat packages/engine/tests/fixtures/specs/valid/single-agent.json), \"input\": \"Agentic Dev lets teams design, run and trust AI agent workflows on their own repositories.\"}"
# {"run_id":"<id>","status":"queued","events_url":"http://localhost:8000/runs/<id>/events"}
curl -N localhost:8000/runs/<id>/events
```

The stream shows `run_started`, `node_started`, a series of `text_delta` frames as Claude writes, one `usage` with the token counts, the `message` with the full text, `completed`, `node_completed` and `run_completed`. `CLAUDE_MODEL` (default `claude-sonnet-5-5`) picks the model; a node's `model` overrides it. The worker exits at startup if `AGENTIC_RUNTIME=claude` is set without `MASTER_KEY_FILE`. A run whose workspace has no stored key ends with `run_failed` ("workspace has no Claude connection"). The key is no longer read from the environment.

## Secrets
Provider keys are stored per workspace, encrypted (phase 1.4, package `agentic_secrets`):
- **Envelope encryption.** A master key (`MASTER_KEY_FILE`, 32 bytes) wraps one random data key per workspace (`workspaces.wrapped_dek`, `key_id`). Each secret is encrypted under its workspace's data key with AES-256-GCM (`connections.secret_ciphertext`). The associated data names the workspace, connection and provider, so a ciphertext copied to another row does not decrypt. A cloud KMS later replaces the local key file behind the same `KeyProvider` interface.
- **Workspaces.** There is one workspace for now, `Default` (`00000000-0000-0000-0000-000000000001`, created by Alembic `0007_workspaces_connections`). Every run belongs to a workspace (`POST /runs` takes an optional `workspace_id`).
- **Write only.** `PUT /workspaces/{id}/connections/claude` stores or replaces the key. `GET /workspaces/{id}/connections` and the Settings page show only its last 4 characters. `DELETE` removes it. Validation errors on these routes never echo the input. Without `MASTER_KEY_FILE` the API answers `503` to a `PUT`.
- **Per run.** The worker decrypts the run's key when the run starts. It builds that run's own Anthropic client and closes it when the run ends. Nothing else ever sees the key: no prompt, tool or event.
- **Never logged.** While a key is held, it is registered for redaction. The log handlers of the API and the worker, and the run event payloads, replace it with `[REDACTED]`. `test_no_secret_leak.py` proves this with a canary key that the mock API echoes back.
- **The master key in compose.** The one-shot `keygen` service writes it to the `secrets` volume if it is missing, and the API and worker mount the volume read only. Deleting that volume makes stored keys unreadable: store them again (the workspace then gets a new data key). Outside compose, run `uv run python -m agentic_secrets generate-key .secrets/master.key` and set `MASTER_KEY_FILE` for both processes.

## GitHub App
A workspace reaches GitHub through the platform's GitHub App (phase 1.5, package `agentic_github` on `githubkit`). The App's id, slug and private key belong to the platform; a workspace stores only its installation (a `github` connection with no secret, Alembic `0008_github_connections`). No personal access token is stored.

Create a dev App once, at <https://github.com/settings/apps/new> (or under an organisation):
1. **Name** it anything; its URL slug (`github.com/apps/<slug>`) is `GITHUB_APP_SLUG`. **Homepage URL**: `http://localhost:3000`.
2. **Setup URL**: `http://localhost:8000/github/setup` (the API), and tick **Redirect on update**. Leave "Request user authorization (OAuth) during installation" off.
3. **Webhook**: untick **Active** (webhooks come in phase 7.6).
4. **Repository permissions**: Metadata read only is enough to list repos. Contents and Pull requests read and write are needed to clone private repos and to open pull requests (`github.openPR`, see "Pull requests"). Administration read and write is needed to create repos (`github.createRepo`, see "New repos").
5. Create it, note its **App ID** (`GITHUB_APP_ID`), then **Generate a private key** and save the downloaded file as `.secrets/github-app.pem` (gitignored).
6. Set `GITHUB_APP_ID` and `GITHUB_APP_SLUG` in `.env`, run `docker compose up --build api`, open <http://localhost:3000/settings> and click **Install GitHub App**. GitHub asks which repos to grant, then sends you back to Settings, which lists them.

How it works:
- `POST /workspaces/{id}/connections/github/install` returns the install URL with a random `state` kept in Redis for 10 minutes. `GET /github/setup` consumes the state (single use), checks with the App's JWT that the installation is ours, stores it and redirects to `/settings?github=connected` (or `?github=error&reason=state|installation|pending|github|not_configured`).
- `GET /workspaces/{id}/repos` lists the repos live with an installation token, which githubkit caches until shortly before it expires. It answers `409` with `code` `no_connection` or `installation_gone` (the App was uninstalled: install it again), `502` if GitHub fails, and `503` if the App is not configured.
- `DELETE /workspaces/{id}/connections/github` unlinks the workspace; the App stays installed on GitHub.
- The private key is read when the API starts (a configured App with a missing key stops the API) and is redacted from its logs. Errors from GitHub carry only a status code, never a token.

Each API process holds one Postgres `LISTEN` connection that wakes the streams of a run when it gets a new event. A wake-up only means "read again": streams re-read `run_events` after their last `seq`, so a lost notification never loses an event.

## Durable runs
A run survives its worker (AC-8). After each node, the graph state is checkpointed in Postgres with the LangGraph Postgres checkpointer (`langgraph-checkpoint-postgres`, tables from Alembic revision `0006_checkpoints`), in the thread named by the run id. When a worker dies, another worker resumes the run after its last completed node:
- **Leases.** A worker claims a run before running it (`runs.worker_id`, `lease_expires_at`, `attempt`) and renews the lease every 10 s while the run goes on. The Redis queue only announces new runs; Postgres decides who runs what (`agentic_store.lease`).
- **Reclaim.** Before each queue poll, a worker looks for a `queued` or `running` run whose lease has expired (`LEASE_TTL_S`, 30 s). It claims it (`FOR UPDATE SKIP LOCKED`, so two workers never take the same run) and resumes it.
- **Events.** The resumed attempt writes `run_resumed` (payload `attempt`, `completed_nodes`), then the usual node and run events. `seq` carries on from the last stored event. Events of the lost attempt stay in the log, including those of the node that was cut off, which runs again from its start (its tokens are spent twice).
- **Stopping a worker is a drain.** On SIGTERM the worker cancels its run without ending it (no `run_cancelled`) and expires its lease, so the next worker resumes it at once.
- **Crash loops.** A run claimed more than `MAX_ATTEMPTS` times (3) ends with `run_failed` ("gave up after N attempts"). A gate decision starts the count again.

The worker's checkpointer talks to Postgres through psycopg, whose async driver cannot use Windows' default Proactor event loop. `python -m agentic_worker` therefore runs on a selector loop on Windows, and the worker and API tests give the worker an in-memory saver.

Demo (the phase 1.3 "Done when"): kill the worker in the middle of a three-node run, then start it again.

```bash
FAKE_STEP_DELAY_S=2 docker compose up -d --build
curl -s -X POST localhost:8000/runs -H 'content-type: application/json'   -d "{\"workflow\": $(cat packages/engine/tests/fixtures/specs/valid/three-step-sequence.json), \"input\": \"hello\"}"
curl -N localhost:8000/runs/<id>/events      # or open http://localhost:3000/runs/<id>
# once `node_completed step-1` and `node_started step-2` are shown:
docker compose kill worker                   # SIGKILL: the run stays `running`, no end event
docker compose up -d worker                  # within LEASE_TTL_S the run is resumed
curl -s localhost:8000/runs/<id>/events
```

The stream shows `run_resumed` with `"attempt": 2, "completed_nodes": ["step-1"]`, then `node_started step-2`, `step-3` and `run_completed`. `step-1` has exactly one `node_completed`, and `seq` runs from 1 with no gaps. With `docker compose stop worker` in place of `kill`, the run is resumed as soon as a worker is back.

## Gates
A `gate` node pauses a run until a human decides; it is how irreversible steps (push and PR now, see "Pull requests"; repo creation later) are put behind an approval. Its input, the previous node's output, is shown to the approver and passed on unchanged:

```json
{ "type": "gate", "id": "gate", "title": "Approve the notes", "prompt": "Check the summary first." }
```

- **Pause.** The gate is a LangGraph `interrupt()`, so the paused state lives in the run's checkpoint (a spec with a gate needs a checkpointer). The run writes `node_started` and `gate_waiting` (payload `title`, `prompt`, `artifact`) for the gate and becomes `waiting`. The worker releases it and takes other runs; a waiting run is never reclaimed. Its sandbox is kept (`SandboxManager.keep`), so what writers committed before the gate is still there afterwards, and the worker's startup sweep spares it.
- **Decide.** `POST /runs/{id}/approvals` with `{"node_id", "decision": "approve" | "reject", "comment"?}` records the decision in the `approvals` table (one per gate and run) and queues the run again. It returns `202`, `404` for an unknown run, `409` if the run is not waiting at that gate or the gate was already decided, and `422` for any other decision.
- **Continue.** A worker claims the run, opens its kept sandbox (`open(..., reuse=True)`; a fresh one if it is gone) and resumes it with the decision (`resume_workflow(..., decision=)`). The stream carries on with `run_resumed`, then `gate_decided` (`decision`, `comment`, `decided_by`). Approve completes the gate and the next node runs; reject cancels the gate and the run ends `run_cancelled` with `stopped_at` the gate. A decision gives the run a fresh `MAX_ATTEMPTS` budget.

Demo (the phase 1.7 "Done when"), with the stack running:

```bash
curl -s -X POST localhost:8000/runs -H 'content-type: application/json'   -d "{\"workflow\": $(cat packages/engine/tests/fixtures/specs/valid/gate-approval.json), \"input\": \"go\", \"repo\": {\"url\": \"/samples/agentic-dev.git\"}}"
curl -N localhost:8000/runs/<id>/events      # stops after gate_waiting; the run is "waiting"
curl -s -X POST localhost:8000/runs/<id>/approvals -H 'content-type: application/json'   -d '{"node_id": "gate", "decision": "approve"}'
# the stream goes on: run_resumed, gate_decided, node_completed gate, the `list` node, run_completed
```

## Pull requests
A run publishes a writer's branch with the `github.openPR` tool (phase 1.8). It pushes the branch `agent/<run>/<from_node>` to the run's repo on GitHub and opens a pull request from it. A push and a pull request can't be undone, so a human approves them first:

```json
{ "type": "tool", "id": "publish", "tool": "github.openPR",
  "args": { "from_node": "writer", "title": "Add NOTES.md", "body": "…", "base": "main" } }
```

- **The gate rule.** The spec is refused (`422` at `POST /runs`, `agentic_engine.spec.publish_gate_errors`) unless all of these hold:
  - `github.openPR` is called by a tool node. An agent may not list it.
  - Its `from_node` names a writer that runs earlier.
  - A `gate` runs between that writer and the publishing node, so the approver sees what the writer produced.
- **What the run needs.** The `repo` must be on GitHub (`https://github.com/<owner>/<name>`), or the request gets `422`. The workspace must be linked to the GitHub App (see "GitHub App"), or it gets `409`. The App needs **Contents** and **Pull requests** set to read and write.
- **Arguments.**
  - `from_node`: the writer whose branch to publish.
  - `title`: the PR title.
  - `body`: optional.
  - `base`: optional. It defaults to the run's `ref`, or else the branch the run cloned.
- **How it works.** The `github` MCP server (`agentic_tools.github`) runs in the worker, next to `repo`:
  1. It takes the writer's commits out of the sandbox as a git bundle of `<clone HEAD>..<branch>` (`agentic_sandbox.export_branch`).
  2. In a temp repo on the worker, it fetches that base commit from GitHub, then the bundle.
  3. It pushes the branch with a fresh installation token. The push may only create the branch: a branch of that name with other commits is never overwritten. Pushing the same commit again is a no-op.
  4. It opens the pull request (`agentic_github.GithubApp.open_pull_request`). If one is already open from that branch, that PR is returned.
- **Credentials.** The token reaches git as an HTTP header through its environment (`GIT_CONFIG_*`), never through argv, a remote URL or a config file. It is redacted from logs while it is held. The sandbox keeps no network and never sees it.
- **Events.** The node writes `tool_call`, `tool_result` (the PR as JSON), then `pr_opened` (`url`, `number`, `head`, `base`, `commit`), then `node_completed`. A refused push or PR fails the node with GitHub's or git's reason.
- **Private repos.** A run whose repo is on GitHub, in a workspace linked to the App, is cloned with an installation token, given the same way. Without one, the clone is anonymous, which works for public repos only.

Demo (the phase 1.8 "Done when"). It needs a dev GitHub App with those permissions, installed on a test repo:

```bash
docker compose up -d --build     # with GITHUB_APP_ID, GITHUB_APP_SLUG and .secrets/github-app.pem set
# connect GitHub at http://localhost:3000/settings, then:
curl -s -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d "{\"workflow\": $(cat packages/engine/tests/fixtures/specs/valid/open-pr.json), \"repo\": {\"url\": \"https://github.com/<owner>/<test-repo>\"}}"
curl -N localhost:8000/runs/<id>/events      # stops after gate_waiting; nothing is pushed yet
curl -s -X POST localhost:8000/runs/<id>/approvals -H 'content-type: application/json' -d '{"node_id": "gate", "decision": "approve"}'
# the stream goes on: gate_decided, tool_call github.openPR, pr_opened with the PR's URL, run_completed
```

Rejecting instead ends the run `cancelled` with no branch or PR on GitHub. Without the gate, `POST /runs` answers `422` and names the publishing node.

## Loops
A `loop` node runs its `body` again and again until its `until` condition is true or it has run `max_iterations` times (phase 1.9). The typical use is a writer and a reviewer going back and forth ([review-loop.json](packages/engine/tests/fixtures/specs/valid/review-loop.json)):

```json
{
  "type": "loop", "id": "revise", "max_iterations": 3,
  "until": "last.contains(\"APPROVED\")",
  "body": { "type": "sequence", "id": "round", "steps": [ { "type": "agent", "id": "draft", "...": "..." }, { "type": "agent", "id": "review", "...": "..." } ] }
}
```

- **Input and output.** Iteration 1 gets the loop's input. Each later iteration gets the previous iteration's output (in the example, the review), and the loop's output is the output of its last iteration.
- **Conditions** are [CEL](https://cel.dev), run with `cel-python` (`agentic_engine.expr`). After each iteration, `until` can read `last` (string: the body's output), `iteration` (int: iterations completed, from 1) and `results` (map: node id → `{status, text, data}`, each node's latest result). For example: `last.contains("APPROVED")`, `last.matches("(?i)approved")`, `results.review.data.score >= 8`, `iteration >= 2 && results.lint.status == "completed"`. Only CEL's standard functions and macros are available, and no platform code can be called. `matches` uses RE2, which runs in linear time. A condition is limited to 1,000 characters, and it is checked when the spec is validated: a syntax error, an unknown variable or an unknown function (for example `lowerAscii`, which `cel-python` lacks) is rejected with its column.
- **Stopping.** The loop stops when `until` is true (`stop_reason: "condition"`) or after `max_iterations` (`"max_iterations"`). Either way it completes and the run goes on. `max_iterations` is required and at most 5 (the policy default; phase 3.2 makes it configurable). If a body node fails, the run stops there. If `until` cannot be evaluated (for example `results.missing.text`), the loop fails with the CEL error.
- **Not inside a loop, yet:** gates, writers, publishers and other loops. Approvals and writer branches are keyed by node id, which would repeat in every iteration. The spec is rejected, and the error names the node and its path.
- **Events.** `node_started` for the loop, then for each iteration `loop_iteration_started` (`iteration`), the body's usual events and `loop_condition_evaluated` (`iteration`, `result`), and finally `node_completed` (`stop_reason`, `iterations`) or `node_failed` (`error`).
- **Durability.** The iteration count is checkpointed, so a run cut off in iteration 2 resumes in iteration 2. The LangGraph step limit is computed from the spec (`recursion_limit`), so a run can never take more steps than its loops allow.

## Map and reduce
A `map` node runs its `body` once per item of a list, several items at a time, and a `reduce` node combines the items' outputs (phase 1.10). [map-modules.json](packages/engine/tests/fixtures/specs/valid/map-modules.json) describes three modules two at a time, then joins the descriptions:

```json
{ "type": "sequence", "id": "main", "steps": [
  { "type": "map", "id": "describe", "max_concurrency": 2,
    "over": "[\"packages/api\", \"packages/engine\", \"web\"]",
    "body": { "type": "agent", "id": "module-writer", "...": "..." } },
  { "type": "reduce", "id": "join", "from": "describe", "strategy": "concat", "separator": "\n\n---\n\n" }
] }
```

- **Items.** `over` is a CEL expression (see [Loops](#loops) for the sandbox) that must evaluate to a list. It can read `last` (string: the map's input) and `results` (map: node id → `{status, text, data}`), so a map can go over a tool's structured output, e.g. `results.list_modules.data.modules`, or over a literal list. It is checked when the spec is validated and evaluated when the map starts. Each item is its body's input: a string as is, any other value as JSON.
- **Concurrency.** `max_concurrency` is required, from 1 to 8 (the policy limit on agents alive). The map's items start together, and a semaphore lets at most `max_concurrency` of them run at once. A map has at most 40 items (the policy limit on agents spawned); with more, or if `over` fails or is not a list, the map fails before any item runs. Phase 3.2 makes both limits configurable.
- **Body.** Only `agent`, `tool` and `sequence` nodes. A sequence runs in order for each item, each step on the previous step's output. Gates, writers, publishers, loops, maps and reduces cannot be inside a map yet: approvals and writer branches are keyed by node id, which would repeat for every item, and parallel writers need the integration branch of phase 6.3. A map cannot be inside a loop either.
- **Output.** The map's result keeps the item order, whatever order the items finish in: its text is the outputs joined by a blank line, and its `data` is `{"items": [...], "outputs": [...]}`. Nodes inside the body are not in `result.results` or `result.order`, since their ids repeat, but their usage counts. A map with no items completes with empty output. If an item's body does not complete, the other items in flight finish, then the map fails (`item <index> <node> failed: <error>`) and the run stops there.
- **Reduce.** `{"type": "reduce", "id", "from": "<map id>", "strategy": ...}` must come after the map it names. `concat` joins the outputs with `separator` (default a blank line) and calls no model. `agent` takes `"agent": {"role", "instructions", "provider"?, "model"?}` and runs one agent turn whose input is the JSON array `[{"item": ..., "output": ...}]`, in item order (data, never instructions). [map-reduce-agent.json](packages/engine/tests/fixtures/specs/valid/map-reduce-agent.json) has a two-step body and an agent reduce.
- **Events.** `node_started` for the map (`items`), then per item `map_item_started` (`index`, `item`), the body's usual events, each with `item` (the index) in its payload, and `map_item_completed` (`index`, `status`, `error`), and finally `node_completed` (`items`) or the map's failure (`error`). Items that run at once interleave their events; `seq` still orders them all. A reduce writes the events of an agent node.
- **Durability.** LangGraph checkpoints each finished item, so a run cut off mid-map runs again only the items that had not finished. The map adds three LangGraph steps whatever its item count.

## Parallel
A `parallel` node runs different branches at the same time on the same input and joins them by a policy (phase 4.1). [parallel-three-reviewers.json](packages/engine/tests/fixtures/specs/valid/parallel-three-reviewers.json) has three specialists review the same input, then a lead merges their reviews:

```json
{ "type": "sequence", "id": "main", "steps": [
  { "type": "parallel", "id": "review", "join": "all", "branches": [
    { "type": "agent", "id": "security", "role": "Security reviewer", "instructions": "..." },
    { "type": "agent", "id": "dependencies", "role": "Dependency reviewer", "instructions": "..." },
    { "type": "agent", "id": "style", "role": "Style reviewer", "instructions": "..." } ] },
  { "type": "agent", "id": "summary", "role": "Lead reviewer", "instructions": "..." } ] }
```

- **Branches.** From 2 to 8, each one `agent`, `tool` or `sequence` node, whose id names the branch. Every branch gets the parallel's input; a sequence runs its steps in order. Gates, writers, publishers, loops, maps, reduces and other parallels cannot be inside a branch yet (`not_allowed_in_parallel`), and a parallel cannot be inside a loop or a map. The run's agents-alive limit caps the branches (a `policy_limit` issue), and a parallel counts as one level of nesting.
- **Join.** `all` completes once every branch completed, `any` once one did, and `quorum` (with `"quorum": k`, from 1 to the number of branches) once `k` did. The join is decided as soon as the outcome is known: `all` fails on the first branch that does not complete, `any` only once every branch failed, and `quorum` once `k` can no longer be reached. The branches still running then end `node_cancelled`, so no more tokens are spent on them.
- **Output.** The completed branches' outputs, in branch order whatever order they finish in, joined by a blank line. `data` is `{"outputs": {<branch id>: text}, "completed": [...], "failed": [...], "cancelled": [...]}`. Nodes inside the branches are in `result.results`, so a later CEL condition can read `results.security.text`, but not in `result.order`: a branch can fail while its parallel completes. A parallel that fails (`join any: 0 of 3 branches completed, 1 needed; branch 'a' a failed: model refused`) stops the run.
- **Limits.** Every agent in every branch counts against agents spawned when the parallel starts, so one that would pass the limit fails before any branch runs. The run's agents-alive slots and budget apply to branch agents as to any other; a budget stop ends the run, not just the branch.
- **Events.** `node_started` for the parallel (`branches`, `join`, `quorum`), then per branch `parallel_branch_started` (`index`, `branch_id`), the branch's usual events, each with `branch` (the index) in its payload, and `parallel_branch_completed` (`index`, `branch_id`, `status`, `error`), and finally `node_completed` or `node_failed` with the `completed`, `failed` and `cancelled` branch ids.
- **Durability.** LangGraph checkpoints each finished branch, so a run cut off mid-parallel runs again only the branches that had not finished. Early cancelling only sees the branches of the current attempt; the join itself decides from the checkpointed outcomes, so it is right either way.
- **Console.** The timeline nests each branch under the parallel, like map items, with "Cancelled" on the branches the join left behind. The Graph tab draws the parallel as a box with its branches side by side, its header saying how far it got ("2 of 3 branches · any · 1 cancelled").

## Generate docs
The "Generate docs" template documents each module of a repo and opens a pull request after you approve (phase 1.11, AC-1). A template is a named builder of an ordinary workflow spec (`agentic_engine.templates`): the API builds the spec from the template's options and runs it like any other.

- **Starting it.** In the browser, open `http://localhost:3000/templates`, pick a repo in the **Generate docs** card and click **Generate docs**. Over HTTP, `GET /templates` lists the templates with a JSON Schema of their options, and `POST /runs` takes `"template": {"id": "generate-docs", "parameters": {...}}` instead of `"workflow"` (give one of the two). Unknown templates and bad options get `422` with the option's path (`parameters.output_dir: ...`).
- **Options.**
  - `output_dir`: where the docs go, relative to the repo root. Default `docs`. No `.`, `..`, absolute paths or `.git`.
  - `include`: glob patterns over module paths (`packages/*`); only matching modules are documented. Default: all.
  - `extra_instructions`: preferences for every agent of the run, up to 2,000 characters. They are added to the agents' instructions in a marked `<user-preferences>` block.
- **The flow** (`build_docs_spec`):
  1. `list_modules`: the `repo.list_modules` tool (no model) finds the modules: each directory down to three levels with a manifest (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `pom.xml`, `*.csproj`), else the top-level directories, else the whole repo. Dependencies, build output, `docs` and hidden directories are skipped, and at most 40 are listed.
  2. `document`: a map over them, 4 at a time. Each item is a read-only agent that explores its module and returns one Markdown page starting with `<!-- module: PATH -->`.
  3. `combine`: a `concat` reduce that joins the pages with a separator line.
  4. `writer`: one agent that writes each page to `<output_dir>/<path with / as ->.md`, writes `<output_dir>/README.md` (overview and index) and commits once on `agent/<run>/writer`. A map body cannot write, so a single writer gives one branch and one PR.
  5. `approve`: a gate. It is always there and no option removes it.
  6. `publish`: `github.openPR` from the writer's branch.
- **What it needs.** A repo on GitHub, a workspace linked to the GitHub App (see "GitHub App") and, for real docs, a Claude key (see "Run on Claude"). On the fake runtime the module agents echo their item, which is enough to see the flow.
- **Approving.** The run page shows the gate with **Approve** and **Reject** buttons and the writer's commit summary. Approving opens the PR, and the page links to it. Rejecting ends the run `cancelled` with nothing pushed.

Demo (the phase 1.11 "Done when", AC-1). It needs a dev GitHub App installed on a test repo (see "Pull requests") and a Claude key:

```bash
docker compose up -d --build     # with GITHUB_APP_ID, GITHUB_APP_SLUG, .secrets/github-app.pem and AGENTIC_RUNTIME=claude
# http://localhost:3000/settings: save the Claude key, install the GitHub App
# http://localhost:3000/templates: pick the test repo, Generate docs, wait for the gate, Approve
# the run page links to the pull request with docs/README.md and one page per module
```

Or with `curl`:

```bash
curl -s localhost:8000/templates
curl -s -X POST localhost:8000/runs -H 'content-type: application/json'   -d '{"template": {"id": "generate-docs", "parameters": {"include": ["packages/*"]}}, "repo": {"url": "https://github.com/<owner>/<test-repo>"}}'
```

## New repos
A run can work on a repo it creates (phase 1.12): the "New run" sheet has an **Existing repo** / **New repo** switch, and `POST /runs` takes `new_repo` instead of `repo`.

- **Where.** The repo is created in the organisation the workspace's GitHub App is installed on, through `POST /orgs/{org}/repos` with an installation token. GitHub does not take installation tokens for repos on a personal account, so a personal-account installation cannot create repos (that needs user sign-in). `GET /workspaces/{id}/repos/new-repo-options` says whether a workspace can (`can_create`, `owner`, else `reason`: `no_connection`, `installation_gone`, `personal_account`).
- **The request.** `new_repo`: `name` (letters, digits, `.`, `-`, `_`; up to 100), `private` (default `true`), `description`, `gitignore` (`Python`, `Node`, `Go`, `Rust`, `Java`, `VisualStudio`) and `license` (`mit`, `apache-2.0`). A name already taken is refused with `409` `repo_exists` before anything is asked. The run's `repo` is the new repo's URL from the start.
- **The flow.** The API puts two steps before the workflow's own (`wrap_with_create_repo`):
  1. `approve_repo`: a gate naming the repo and what its first commit holds. Creating a repo is irreversible, so the spec rules require a gate before `github.createRepo`, as a step of the root sequence before anything uses the repo (`create_not_tool_node`, `create_without_gate`, `create_not_first`).
  2. `create_repo`: `github.createRepo` creates the repo with one scaffold commit made by GitHub (`auto_init`: a README, plus the `.gitignore` and license asked for) and logs `repo_created`. The audit log gets `repo.created`.
  3. The attempt then stops, and the worker starts the next one at once: it clones the new repo and the workflow runs on it as on any repo. The attempts before had no sandbox.
- **Retries and rerun.** A worker that dies after GitHub created the repo resumes and takes the repo over, but only one created after the run was. A run that created its repo is not rerun (`409` `repo_exists`): start a run on the repo instead. Rejecting at `approve_repo` creates nothing.
- **Fake GitHub.** With `AGENTIC_GITHUB=fake`, created repos are bare repos in the `fixtures` volume, seen by the worker (`SANDBOX_LOCAL_ROOT`) and the API (`FAKE_GITHUB_ROOT`).

Demo (the phase 1.12 "Done when"). It needs a dev GitHub App with Administration read and write, installed on a test organisation, and a Claude key:

```bash
docker compose up -d --build     # with GITHUB_APP_ID, GITHUB_APP_SLUG, .secrets/github-app.pem and AGENTIC_RUNTIME=claude
# http://localhost:3000/templates: Generate docs, New repo, name it, Start run
# approve "Create the repo <org>/<name>?", then the docs gate: the run page links to the pull request
```

## Sandbox
A run can name a repo: `POST /runs` takes an optional `"repo": {"url": ..., "ref": ...}`. The worker then gives the run a sandbox that holds a shallow clone of that repo for its whole duration, and its agents and tool nodes get the repo tools, which run in there. A spec whose nodes (agent or tool) use `repo.*` tools is rejected with `422` if the run has no `repo`.

| Tool | What it does | Limits |
|---|---|---|
| `repo.list_files(path=".", max_depth=3)` | Files and directories under `path`, relative to the repo root; directories end with `/`. | 1,000 entries |
| `repo.read_file(path, start_line=1, end_line=None)` | A text file's lines, each prefixed with its number and a tab. Directories and binary files (a NUL byte in the first 8 KiB) are refused. | 2,000 lines or 256 KiB; the note says where to continue |
| `repo.search(pattern, path=".", regex=False, case_sensitive=True, max_results=100)` | `path:line: text` for each matching line in text files. The pattern is a fixed string unless `regex` (extended regex). | 500 matches at most; lines cut at 300 characters |
| `repo.list_modules(include=None)` | The repo's modules as structured content, `{"modules": [{"path", "kind"}], "truncated"}`, so a map can go over `results.<node>.data.modules`. A module is a directory (down to three levels) with a manifest; without any, the top-level directories (see "Generate docs"). `include` filters by glob. | 40 modules |
| `repo.write_file(path, content)` | Writers only. Creates or overwrites a UTF-8 text file on the node's branch, creating parent directories. Refuses anything under `.git`, directories, and writing through a symlink. | 1 MiB per file |
| `repo.commit(message)` | Writers only. Commits every change on the node's branch; returns `<short-sha> on agent/<run>/<node>: <files>`. Nothing to commit is an error. | 5,000-character message; 50 files listed |

Every tool skips `.git`, refuses absolute paths and paths that leave the repo (including through symlinks), and passes its arguments to the sandbox as data, never as shell code. Errors come back as error results that name no host path.

**Writers.** A node whose spec names `repo.write_file` or `repo.commit` (in an agent's `tools`, or as a tool node's `tool`) is a writer. On its first call it gets its own git worktree, `/workspace/worktrees/<node>`, on a new branch `agent/<run-id>/<node-id>` made from the clone's `HEAD`, and all its `repo.*` calls go there: it reads its own writes, and the shared checkout and other nodes never see them. Other nodes calling a write tool get an "unknown tool" error. Commits are by `agentic-dev agent <agent@agentic-dev.invalid>`, and git runs with hooks, fsmonitor and signing off and no system or user config, so nothing in the repo can make it run code. The sandbox has no network, so nothing leaves it unless a `github.openPR` node publishes the branch after a gate (see "Pull requests"). Otherwise the branch goes when the sandbox does. A resumed run gets a fresh sandbox, so its writer runs again on a fresh worktree. A run paused at a gate is the exception: it keeps its sandbox.

The tools are served by the `repo` MCP server (`agentic_tools.repo`), built with the official MCP Python SDK. The worker builds one read-only server per run, bound to that run's checkout, and one writable server per writer, bound to its worktree, and connects to them in memory (no process or port). `open_repo_tools` returns a `RepoTools` executor that routes each call by the node id the runtime passes to `ToolExecutor.call`, and offers the tools to the agent runtime as `repo.<tool>`. The MCP clients close before the sandbox is removed.

How it works (`agentic_sandbox`):
- **Repo source.** `url` is an `https://` URL without credentials, or a local path under `SANDBOX_LOCAL_ROOT` (unset by default, so only `https://` is allowed). `ref` is a branch or tag. Other transports, `ext::`, scp-like URLs and option-like values are rejected.
- **Clone.** The worker runs `git clone --depth 1` itself, with only the https and file protocols enabled and without the user's or system's git config. For a GitHub repo in a workspace linked to the App, it sends an installation token as an HTTP header through git's environment. It then copies the clone into the sandbox, so the sandbox needs no network and never sees credentials.
- **Docker backend** (`SANDBOX_BACKEND=docker`, the compose default). There is one container (`SANDBOX_IMAGE`, default `agentic-dev/sandbox:dev`: alpine plus git, built by compose from `packages/sandbox/Dockerfile`, or by hand with `docker build -t agentic-dev/sandbox:dev packages/sandbox`) and one volume per run, both labelled `agentic.run_id`. The container:
  - has no network and a read-only root filesystem;
  - drops all capabilities and sets `no-new-privileges`;
  - runs as uid 1000, with memory, CPU and PID limits;
  - holds the checkout root-owned, so it can be read but not changed; its `.git`, `/workspace/worktrees` (writers' worktrees) and `/workspace/.incoming` (file contents on their way in via `Sandbox.put_file`, and branch bundles on their way out via `Sandbox.take_file`) belong to uid 1000.
- **Lifecycle.** The container and volume are removed when the run ends, whether it completes, fails or is cancelled. A worker removes leftovers at startup, except those of runs other workers hold a lease on. A resumed run gets a fresh sandbox: opening it first removes the one its earlier attempt left. A clone that fails ends the run with `run_failed` and a message that names no host path.
- **Fake backend** (`SANDBOX_BACKEND=fake`, the default outside compose). It uses a temp directory on the worker host and isolates nothing, so use it only for tests and trusted repos.

In compose, the worker mounts the host's Docker socket to start sandbox containers. That gives it control of the host's Docker, which is acceptable for local development; production isolation comes in phase 10.2. On Linux, set `DOCKER_GID` in `.env` to the socket's group (`stat -c %g /var/run/docker.sock`); Docker Desktop needs nothing. Compose also mounts this project's own git history read-only at `/samples/agentic-dev.git` as a demo repo.

Demos (the phase 1.1, 1.2 and 1.6 "Done when", all run by CI against the compose stack):

```bash
docker compose up -d --build
python scripts/sandbox_demo.py          # or the same request with curl:
curl -s -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d "{\"workflow\": $(cat packages/engine/tests/fixtures/specs/valid/list-repo-files.json), \"repo\": {\"url\": \"/samples/agentic-dev.git\"}}"
curl -N localhost:8000/runs/<id>/events

# Phase 1.2: one agent asks which packages make up this uv workspace
python scripts/sandbox_demo.py --spec packages/engine/tests/fixtures/specs/valid/ask-repo.json

# Phase 1.6: a writer commits NOTES.md on agent/<run>/writer, then a tool node lists the checkout
python scripts/sandbox_demo.py --spec packages/engine/tests/fixtures/specs/valid/write-file.json \
  --expect "wrote NOTES.md (" --expect "/writer: NOTES.md"
```

On the fake runtime, the agent calls each tool its node names, with the example arguments from the tool's input schema (`list_files` on the root, `read_file` on `pyproject.toml`, `search` for `[project]`). For `ask-repo.json` the stream shows:
1. `tool_call` / `tool_result` for `repo.list_files`, listing this repo (`packages/`, …);
2. `tool_call` / `tool_result` for `repo.read_file`, with the numbered root `pyproject.toml` and its `members = ["packages/*"]`;
3. `tool_call` / `tool_result` for `repo.search`, with one `packages/<name>/pyproject.toml:1: [project]` hit per package;
4. `message` and `run_completed`.

For `write-file.json` the writer node `writer` reads `pyproject.toml`, then `repo.write_file` answers `wrote NOTES.md (<n> bytes)` and `repo.commit` answers `<sha> on agent/<run-id>/writer: NOTES.md`. The tool node `list` then runs `repo.list_files` on the shared checkout, with no model, and NOTES.md is not in it.

While a run is going, `docker ps --filter label=agentic.run_id` shows its container; afterwards it shows none. With `AGENTIC_RUNTIME=claude`, Claude decides which tools to call and answers from what it finds. On `ask-repo.json` it reads each package's `pyproject.toml` and returns a table of the packages and what each is for.

## UI shell
Every page renders inside one app shell (phase 2.2, `web/src/components/shell/`), set up in the root layout:

- **Sidebar:** the product name, the workspace name (from `GET /workspaces`) and the main sections: **Runs** (`/runs`, the home page, which `/` redirects to), **Templates** (`/templates`) and **Settings** (`/settings`). It is full from 1280 px, an icon rail with tooltips from 1024 to 1279 px, and a drawer opened from the top bar's menu button below 1024 px.
- **Top bar:** breadcrumbs built from the path (`Runs › 1a2b3c4d` on a run, from `breadcrumbsFor` in `nav.ts`) and the theme menu (Light, Dark, System).
- **A new page:**
  - Add `web/src/app/<section>/.../page.tsx` under one of the sections. A new section is a new entry in `NAV_ITEMS`.
  - Start the page with `PageHeader` (`title`, `description`, `actions`). It is the page's only `h1`, and its actions stack under the title below 768 px.
  - Set `metadata.title` and the layout adds ` · Agentic Dev`.
  - Content wider than the screen scrolls in its own box (for example `Table` with `scrollLabel`), never the page.
- **Checks:** `web/e2e/layout.spec.ts` opens every page at 375, 768, 1024 and 1440 px (Playwright projects `mobile-375` … `desktop-1440`). It fails on horizontal page scroll, checks the nav is reachable, and saves a full-page screenshot to `web/test-results/screenshots/<project>/`. CI uploads these as the `layout-screenshots` artifact. `a11y.spec.ts` runs axe at 375 and 1440 px and checks the skip link, the drawer's focus trap and the theme menu from the keyboard. `pnpm test:e2e --project=mobile-375` runs one width.

## Monitor
Open `http://localhost:3000/templates` to start the "Generate docs" template (see above), or type an input and click **Start sample run**. The page starts a one-agent workflow (`web/src/runs/sample-spec.ts`) and opens `/runs/<id>`, which lists the run's events as they arrive: `seq`, time, type, node and a one-line summary of the payload, shown as plain text. The status badge goes from `connecting` to `live`, then to `completed`, `failed` or `cancelled`. A run started with `curl` (see above) can be opened the same way at `http://localhost:3000/runs/<id>`, and reloading a finished run shows its full list. While the run waits at a gate, the page shows the gate's title, prompt and input with **Approve** and **Reject** buttons (`POST /runs/{id}/approvals`). Once a `pr_opened` event arrives, it links to the pull request (only `https://github.com/<owner>/<repo>/pull/<n>` URLs are linked).

The browser calls the API directly (`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`) and reads `GET /runs/{id}/events` with `EventSource`, so the API must allow the web app's origin: `CORS_ORIGINS` is a JSON list, and compose sets it to `["http://localhost:${WEB_PORT}"]`. The `RunEvent` type the page uses is generated from the OpenAPI spec like the rest of the client. The Playwright test `web/e2e/monitor.spec.ts` checks the roadmap target: every live event shows up in the browser less than 1 s after it was stored.

## Changelog
Every pull request records its changes under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) before merge. The `CHANGELOG.md updated` CI check fails otherwise, on every PR.

## Roadmap status
A PR that implements a roadmap phase (it touches a `specs/<date>-<slug>/` folder whose `requirements.md` names the phase) must set that phase's Status in [specs/roadmap.md](specs/roadmap.md) to `✅ Done ([#<pr>](<pr-url>))`. On PRs from this repository the `Roadmap phase marked done` CI job does this for you: it commits the Status change to the PR branch, then checks it. PRs from forks only get the check. To do it locally before pushing, use the `complete-phase` Claude Code skill (`python scripts/check_roadmap.py origin/main HEAD --mark-done <pr-url>`). Label planning-only PRs `skip-roadmap`.

## Merging to main
`main` takes changes only through pull requests, merged with **Squash and merge** (the PR title and body become the commit). A PR merges once every job of `ci.yml` and `pr-checks.yml` has run and passed on a branch up to date with `main`, and nobody bypasses that. The `open-pr` Claude Code skill walks through it: changelog entry, labels, phase issue, push, watch the checks; a person merges.

These rules live in GitHub settings, applied by `python scripts/setup_repo_rules.py` (repo admin, after `gh auth login`; `--dry-run` prints them). Run it again after adding or renaming a CI job; `scripts/test_setup_repo_rules.py` fails until its list of required checks matches the workflows.

## Roadmap board
`python scripts/sync_roadmap_board.py` mirrors [specs/roadmap.md](specs/roadmap.md) on GitHub: one milestone per roadmap milestone, one `roadmap-phase` issue per phase (closed when the phase is `✅ Done`), `type:`, `area:` and `milestone:<n>` labels, and the "agentic-dev roadmap" Projects board with every phase issue on it. It needs `gh auth refresh -s project`; `--dry-run` writes nothing. The roadmap is the source of truth: running it again updates titles, milestones, states and the board's Status (Todo, Done; cards moved to In Progress stay there). On `main`, `roadmap-board.yml` runs it whenever the roadmap changes, if the `ROADMAP_BOARD_TOKEN` secret (a token with the `repo` and `project` scopes) is set.
