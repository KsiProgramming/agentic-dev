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
A workflow is a JSON document validated by the Pydantic models in `agentic_engine.spec` (`parse_spec(data)` raises `pydantic.ValidationError` on a bad spec). v0 has two node types, `agent` and `sequence`. Node ids are unique slugs (`^[a-z][a-z0-9_-]{0,62}$`) and unknown keys are rejected.

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
- When Claude asks for tools, each one becomes a `tool_call`, runs through the `ToolExecutor` given to the runtime, and becomes a `tool_result` that is sent back. Then the loop calls the API again, up to `max_turns` (default 10). Platform tool names such as `repo.read_file` are sent to the API as `repo__read_file`. A request that names tools the executor cannot offer fails before any API call. No real tools exist until phase 1.2.
- API errors become `failed`. Rate limits, overloaded and 5xx responses, timeouts and connection errors are marked `retryable`. Hitting `max_tokens`, a refusal, or running out of turns fails without `retryable`.

Tests use `agentic_runtime.testing.MockClaude`, a real `AsyncAnthropic` on an in-memory transport that replays scripted SSE replies (`text_reply`, `tool_use_reply`, `error_reply`) and records request bodies. `collect_and_check(runtime, request)` runs a request and checks the stream against the contract for any adapter.

## Engine
`agentic_engine.graph` compiles a workflow spec to a LangGraph graph and runs it. In v0, nested `sequence`s are flattened depth first into one chain of `agent` nodes, each named by its spec node id. The first node gets the run input; each later node gets the previous node's output text as its `input` (data, never instructions). A node that ends `failed` or `cancelled` stops the run.

```python
result = await run_workflow(spec, FakeRuntime(), input="Write the overview.")
result.status, result.order, result.text, result.usage, result.stopped_at
```

With a `checkpointer` (any LangGraph saver built with `checkpoint_serde()`), `run_workflow` saves the graph state after each node in the thread named by the run id, and `resume_workflow` carries a cut-off run on from there: nodes that completed are not run again, and the node that was cut off runs again from its start. See [Durable runs](#durable-runs).

LangGraph ships no type information, so `typings/langgraph/` holds minimal stubs for the parts the engine uses; extend them when you use more of its API.

## Run event log
Every run writes one ordered stream of events (`agentic_engine.events.RunEvent`): `run_started`, then for each node `node_started`, the node's agent events and `node_completed` / `node_failed` / `node_cancelled`, then `run_completed` / `run_failed` / `run_cancelled`. `seq` numbers the events 1, 2, … per run. Agent events keep their `AgentEvent` type, and their `payload` is the serialised event (`event.agent_event()` parses it back).

The engine has no database code. It hands events to an `EventSink` passed to `run_workflow`. Tests use `InMemoryEventSink`. `agentic_store.PostgresEventSink` writes each event to the append-only `run_events` table in its own transaction, keeps the run's status in `runs` (`queued` → `running` → final status), and sends `pg_notify('run_events', '<run_id>:<seq>')` with each insert. The run's row must exist first:

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
Set `AGENTIC_RUNTIME=claude` and `ANTHROPIC_API_KEY` in your shell or `.env` (see `.env.example`), then start the stack and run a one-node workflow:

```bash
AGENTIC_RUNTIME=claude ANTHROPIC_API_KEY=<your key> docker compose up -d --build
curl -s -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d "{\"workflow\": $(cat packages/engine/tests/fixtures/specs/valid/single-agent.json), \"input\": \"Agentic Dev lets teams design, run and trust AI agent workflows on their own repositories.\"}"
# {"run_id":"<id>","status":"queued","events_url":"http://localhost:8000/runs/<id>/events"}
curl -N localhost:8000/runs/<id>/events
```

The stream shows `run_started`, `node_started`, a series of `text_delta` frames as Claude writes, one `usage` with the token counts, the `message` with the full text, `completed`, `node_completed` and `run_completed`. `CLAUDE_MODEL` (default `claude-sonnet-5-5`) picks the model; a node's `model` overrides it. The worker exits at startup if `AGENTIC_RUNTIME=claude` is set without a key. For now the key is read from the environment; encrypted per-workspace keys come in phase 1.4.

Each API process holds one Postgres `LISTEN` connection that wakes the streams of a run when it gets a new event. A wake-up only means "read again": streams re-read `run_events` after their last `seq`, so a lost notification never loses an event.

## Durable runs
A run survives its worker (AC-8). After each node, the graph state is checkpointed in Postgres with the LangGraph Postgres checkpointer (`langgraph-checkpoint-postgres`, tables from Alembic revision `0006_checkpoints`), in the thread named by the run id. When a worker dies, another worker resumes the run after its last completed node:
- **Leases.** A worker claims a run before running it (`runs.worker_id`, `lease_expires_at`, `attempt`) and renews the lease every 10 s while the run goes on. The Redis queue only announces new runs; Postgres decides who runs what (`agentic_store.lease`).
- **Reclaim.** Before each queue poll, a worker looks for a `queued` or `running` run whose lease has expired (`LEASE_TTL_S`, 30 s). It claims it (`FOR UPDATE SKIP LOCKED`, so two workers never take the same run) and resumes it.
- **Events.** The resumed attempt writes `run_resumed` (payload `attempt`, `completed_nodes`), then the usual node and run events. `seq` carries on from the last stored event. Events of the lost attempt stay in the log, including those of the node that was cut off, which runs again from its start (its tokens are spent twice).
- **Stopping a worker is a drain.** On SIGTERM the worker cancels its run without ending it (no `run_cancelled`) and expires its lease, so the next worker resumes it at once.
- **Crash loops.** A run claimed more than `MAX_ATTEMPTS` times (3) ends with `run_failed` ("gave up after N attempts").

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

## Sandbox
A run can name a repo: `POST /runs` takes an optional `"repo": {"url": ..., "ref": ...}`. The worker then gives the run a sandbox that holds a shallow clone of that repo for its whole duration, and its agents get the read-only repo tools, which run in there. A spec whose nodes use `repo.*` tools is rejected with `422` if the run has no `repo`.

| Tool | What it does | Limits |
|---|---|---|
| `repo.list_files(path=".", max_depth=3)` | Files and directories under `path`, relative to the repo root; directories end with `/`. | 1,000 entries |
| `repo.read_file(path, start_line=1, end_line=None)` | A text file's lines, each prefixed with its number and a tab. Directories and binary files (a NUL byte in the first 8 KiB) are refused. | 2,000 lines or 256 KiB; the note says where to continue |
| `repo.search(pattern, path=".", regex=False, case_sensitive=True, max_results=100)` | `path:line: text` for each matching line in text files. The pattern is a fixed string unless `regex` (extended regex). | 500 matches at most; lines cut at 300 characters |

Every tool skips `.git`, refuses absolute paths and paths that leave the repo (including through symlinks), and passes its arguments to the sandbox as data, never as shell code. Errors come back as error results that name no host path.

The tools are served by the `repo` MCP server (`agentic_tools.repo`), built with the official MCP Python SDK. The worker builds one server per run, bound to that run's sandbox, and connects to it in memory (no process or port). `McpToolExecutor` (`agentic_tools.mcp_bridge`) offers the server's tools to the agent runtime as `repo.<tool>`, the same `ToolExecutor` the Claude and fake runtimes already use. The MCP client closes before the sandbox is removed.

How it works (`agentic_sandbox`):
- **Repo source.** `url` is an `https://` URL without credentials, or a local path under `SANDBOX_LOCAL_ROOT` (unset by default, so only `https://` is allowed). `ref` is a branch or tag. Other transports, `ext::`, scp-like URLs and option-like values are rejected.
- **Clone.** The worker runs `git clone --depth 1` itself, with only the https and file protocols enabled and without the user's or system's git config. It then copies the clone into the sandbox, so the sandbox needs no network and never sees credentials.
- **Docker backend** (`SANDBOX_BACKEND=docker`, the compose default). There is one container (`SANDBOX_IMAGE`, default `alpine:3.20`) and one volume per run, both labelled `agentic.run_id`. The container:
  - has no network and a read-only root filesystem;
  - drops all capabilities and sets `no-new-privileges`;
  - runs as uid 1000, with memory, CPU and PID limits;
  - holds the clone root-owned, so agents can read it but not change it yet (write tools come in phase 1.6).
- **Lifecycle.** The container and volume are removed when the run ends, whether it completes, fails or is cancelled. A worker removes leftovers at startup, except those of runs other workers hold a lease on. A resumed run gets a fresh sandbox: opening it first removes the one its earlier attempt left. A clone that fails ends the run with `run_failed` and a message that names no host path.
- **Fake backend** (`SANDBOX_BACKEND=fake`, the default outside compose). It uses a temp directory on the worker host and isolates nothing, so use it only for tests and trusted repos.

In compose, the worker mounts the host's Docker socket to start sandbox containers. That gives it control of the host's Docker, which is acceptable for local development; production isolation comes in phase 9.2. On Linux, set `DOCKER_GID` in `.env` to the socket's group (`stat -c %g /var/run/docker.sock`); Docker Desktop needs nothing. Compose also mounts this project's own git history read-only at `/samples/agentic-dev.git` as a demo repo.

Demos (the phase 1.1 and 1.2 "Done when", both run by CI against the compose stack):

```bash
docker compose up -d --build
python scripts/sandbox_demo.py          # or the same request with curl:
curl -s -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d "{\"workflow\": $(cat packages/engine/tests/fixtures/specs/valid/list-repo-files.json), \"repo\": {\"url\": \"/samples/agentic-dev.git\"}}"
curl -N localhost:8000/runs/<id>/events

# Phase 1.2: one agent asks which packages make up this uv workspace
python scripts/sandbox_demo.py --spec packages/engine/tests/fixtures/specs/valid/ask-repo.json
```

On the fake runtime, the agent calls each tool its node names, with the example arguments from the tool's input schema (`list_files` on the root, `read_file` on `pyproject.toml`, `search` for `[project]`). For `ask-repo.json` the stream shows:
1. `tool_call` / `tool_result` for `repo.list_files`, listing this repo (`packages/`, …);
2. `tool_call` / `tool_result` for `repo.read_file`, with the numbered root `pyproject.toml` and its `members = ["packages/*"]`;
3. `tool_call` / `tool_result` for `repo.search`, with one `packages/<name>/pyproject.toml:1: [project]` hit per package;
4. `message` and `run_completed`.

While a run is going, `docker ps --filter label=agentic.run_id` shows its container; afterwards it shows none. With `AGENTIC_RUNTIME=claude`, Claude decides which tools to call and answers from what it finds. On `ask-repo.json` it reads each package's `pyproject.toml` and returns a table of the packages and what each is for.

## Monitor
Open `http://localhost:3000`, type an input and click **Start sample run**. The page starts a one-agent workflow (`web/src/runs/sample-spec.ts`) and opens `/runs/<id>`, which lists the run's events as they arrive: `seq`, time, type, node and a one-line summary of the payload, shown as plain text. The status badge goes from `connecting` to `live`, then to `completed`, `failed` or `cancelled`. A run started with `curl` (see above) can be opened the same way at `http://localhost:3000/runs/<id>`, and reloading a finished run shows its full list.

The browser calls the API directly (`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`) and reads `GET /runs/{id}/events` with `EventSource`, so the API must allow the web app's origin: `CORS_ORIGINS` is a JSON list, and compose sets it to `["http://localhost:${WEB_PORT}"]`. The `RunEvent` type the page uses is generated from the OpenAPI spec like the rest of the client. The Playwright test `web/e2e/monitor.spec.ts` checks the roadmap target: every live event shows up in the browser less than 1 s after it was stored.

## Changelog
Every pull request records its changes under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) before merge. The `Changelog` CI check fails otherwise; label the PR `skip-changelog` only when it has no notable change.

## Roadmap status
A PR that implements a roadmap phase (it touches a `specs/<date>-<slug>/` folder whose `requirements.md` names the phase) must set that phase's Status in [specs/roadmap.md](specs/roadmap.md) to `✅ Done ([#<pr>](<pr-url>))`. On PRs from this repository the `Roadmap phase marked done` CI job does this for you: it commits the Status change to the PR branch, then checks it. PRs from forks only get the check. To do it locally before pushing, use the `complete-phase` Claude Code skill (`python scripts/check_roadmap.py origin/main HEAD --mark-done <pr-url>`). Label planning-only PRs `skip-roadmap`.
