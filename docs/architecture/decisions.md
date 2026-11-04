# Architecture decisions

The choices that shape the platform, and why they were made. Each record gives the context, the decision, the alternatives considered and the consequences, in the spirit of [Architecture Decision Records](https://adr.github.io/).

This is a curated set of the decisions that matter most to someone adopting, operating or extending the platform. The **complete, binding log** (about 90 entries, one per choice, in the order they were made) is the "Decisions log" table in [`specs/tech-stack.md`](../../specs/tech-stack.md#decisions-log). New decisions are recorded there first, in the same pull request as the work.

| # | Decision | Area |
|---|---|---|
| [001](#adr-001-open-orchestration-built-from-a-small-set-of-primitives) | Open orchestration built from a small set of primitives | Product / engine |
| [002](#adr-002-langgraph-as-the-orchestration-engine-not-temporal) | LangGraph as the engine, not Temporal | Engine |
| [003](#adr-003-python-backend-typescript-frontend-contracts-in-json-schema) | Python backend, TypeScript frontend, contracts in JSON Schema | Stack |
| [004](#adr-004-postgres-leases-decide-ownership-redis-only-announces-work) | Postgres leases decide ownership; Redis only announces work | Reliability |
| [005](#adr-005-an-append-only-event-log-is-the-single-source-of-truth) | An append-only event log is the single source of truth | Data |
| [006](#adr-006-tools-are-platform-owned-mcp-servers) | Tools are platform-owned MCP servers | Integration |
| [007](#adr-007-a-sandbox-with-no-network-and-no-credentials) | A sandbox with no network and no credentials | Security |
| [008](#adr-008-a-github-app-never-personal-access-tokens) | A GitHub App, never personal access tokens | Security / integration |
| [009](#adr-009-envelope-encryption-behind-a-keyprovider-protocol) | Envelope encryption behind a `KeyProvider` protocol | Security |
| [010](#adr-010-humans-approve-every-irreversible-action-and-approvals-expire) | Humans approve every irreversible action, and approvals expire | Governance |
| [011](#adr-011-limits-are-platform-ceilings-frozen-on-each-run-the-budget-is-optional) | Limits are ceilings frozen on each run; the budget is optional | Governance |
| [012](#adr-012-cost-is-priced-once-when-it-is-logged) | Cost is priced once, when it is logged | Data |
| [013](#adr-013-graph-operations-over-the-specs-tree-and-immutable-versions) | Graph operations over the spec's tree, immutable versions | Engine / UI |
| [014](#adr-014-cel-for-every-expression) | CEL for every expression | Engine / security |
| [015](#adr-015-durations-mean-active-time) | Durations mean active time | Product / data |
| [016](#adr-016-the-canvas-is-a-card-tree-not-a-free-form-graph-editor) | The canvas is a card tree, not a free-form graph editor | UI |
| [017](#adr-017-an-owned-component-library-and-colour-reserved-for-status) | An owned component library, colour reserved for status | UI |
| [018](#adr-018-specs-govern-the-work) | Specs govern the work | Process |
| [019](#adr-019-open-source-under-apache-20-self-hosted-first) | Open source under Apache-2.0, self-hosted first | Distribution |

---

### ADR-001: Open orchestration built from a small set of primitives

**Context.** Docs generation, audits and feature work each need a different mix of sequential steps, parallel workers, review loops and approvals. Single-agent tools run one loop; workflow builders do not understand code. A fixed menu of patterns would never fit every team.

**Decision.** The engine understands a small, versioned set of primitives: `agent`, `tool`, `sequence`, `parallel`, `map`, `reduce`, `router`, `loop`, `gate`, plus `orchestrator` and `subflow` (planned). Every pattern (hub-and-spoke, map-reduce, pipeline, debate, review loop) is a graph of them. Users extend the set with composite nodes (no code) and plugin nodes (code) without an engine release.

**Alternatives.** A catalogue of named patterns: simpler UI, but every new pattern needs a release. Arbitrary code nodes: maximally flexible, but impossible to validate, cap or explain.

**Consequences.** One validator can check any workflow for type safety and policy before it runs. The palette and parameter forms are generated from node manifests, so a new primitive appears in the UI with no frontend change.

### ADR-002: LangGraph as the orchestration engine, not Temporal

**Context.** Runs must survive worker crashes (AC-8), pause for humans for days, and fan out dynamically.

**Decision.** Compile each workflow spec to a LangGraph graph. Durability comes from LangGraph's Postgres checkpointer; gates use `interrupt()`; `map`, `parallel` and the orchestrator use `Send` for dynamic fan-out.

**Alternatives.** Temporal: very strong durability and language-agnostic, but it adds a cluster to operate, and its programming model is not agent-oriented. A home-grown engine: full control, but a long road to durability.

**Consequences.** Python-native, with built-in human-in-the-loop and fan-out. The platform owns leases and recovery (ADR-004) on top of checkpoints. A node that was mid-flight at a crash runs again, so tools must tolerate a retry (for example the push accepts a branch already at the same commit).

### ADR-003: Python backend, TypeScript frontend, contracts in JSON Schema

**Context.** The agent and MCP ecosystem is strongest in Python; the product needs a modern, accessible web UI.

**Decision.** FastAPI + Pydantic v2 on the backend, Next.js + TypeScript on the frontend. They share **contracts, not code**: the workflow spec, graph operations and findings schemas are exported as JSON Schema, and the TypeScript API client is generated from FastAPI's OpenAPI document. CI fails if any generated artifact is stale.

**Consequences.** Each side uses its best ecosystem. A browser mirror of `apply_ops` and of the port check exists for instant feedback, and shared fixtures keep it identical to the engine. The server stays the single authority.

### ADR-004: Postgres leases decide ownership, Redis only announces work

**Context.** Several workers must share runs without double execution, and a dead worker's run must be resumed.

**Decision.** The API pushes only the run id to a Redis list. A worker claims a run with a conditional `UPDATE` on its `runs` row (`worker_id`, `lease_expires_at`) and renews the lease every 10 s. A run whose lease expired (judged by the **database** clock) is reclaimed with `SKIP LOCKED` and resumed from its checkpoint. `MAX_ATTEMPTS` bounds crash loops.

**Alternatives.** A Redis-based queue with acknowledgements (for example streams or a job library): it would need a second source of truth for ownership. Kubernetes jobs per run: heavy and slow to start.

**Consequences.** A run is never executed twice, and a started run survives the loss of its worker. Clock skew between workers is harmless. The queue is a hint; correctness lives in one transactional store. A known edge: a run whose announcement is lost before any worker claims it stays `queued` until rerun; automatic recovery is tracked in [`specs/ideas.md`](../../specs/ideas.md).

### ADR-005: An append-only event log is the single source of truth

**Context.** The live console, the cost view, the audit and the history must agree, and must be explainable later.

**Decision.** Every step writes typed events to `run_events` (unique `(run_id, seq)`). The `runs` row is a projection updated in the same transaction. Postgres `NOTIFY` wakes the API, which streams new events by `seq` over SSE. Text deltas are buffered 250 ms server-side.

**Consequences.** Reconnecting clients resume exactly with `Last-Event-ID`. Listing runs never scans the log. A rerun is a new run (`rerun_of`), so history is never rewritten. The log grows with usage and needs a retention policy in production.

### ADR-006: Tools are platform-owned MCP servers

**Context.** The same workflow must run on Claude and on GitHub Copilot, and credentials must never reach agents.

**Decision.** Integrations (`repo`, `scan`, `artifacts`, `github`, later `jira` and plugins) are MCP servers the platform runs, connected in memory and routed per node. Tools are granted per node through the spec; unknown arguments are refused.

**Alternatives.** Each provider's built-in tools: they differ by provider and would hold credentials in the agent's environment.

**Consequences.** Provider neutrality and least privilege by construction. Adding an integration means adding a server (see [Connecting your platforms](../integrations/connecting-platforms.md)).

### ADR-007: A sandbox with no network and no credentials

**Context.** Agents read untrusted repository content and run commands; model output is untrusted too.

**Decision.** One container per run, created by the worker: `network_mode: none`, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, non-root user, CPU, memory and PID limits, a `noexec` tmpfs. The checkout is root-owned (read-only to agents); each writer gets its own worktree and branch. Commits leave as a git bundle; the worker pushes them. Scanners are baked into the image with pinned, hash-checked releases and an offline vulnerability database.

**Alternatives.** Giving the sandbox network and a scoped token: simpler pushes, but any prompt injection could exfiltrate code or the token.

**Consequences.** A compromised agent cannot reach the network or a credential. Tools that need the network (dependency install, tests that download) are out of scope until an egress allowlist exists (phase 10.2, together with gVisor or Firecracker). In the reference compose setup the worker needs the Docker socket, which is a host-level privilege: see the [security model](../security/security-model.md).

### ADR-008: A GitHub App, never personal access tokens

**Decision.** All GitHub access goes through a GitHub App installed on chosen repositories. A workspace stores only the installation id. Short-lived installation tokens are minted on demand from the App's private key.

**Alternatives.** Personal access tokens: long-lived, tied to a person, broad scopes, and a secret to store per user.

**Consequences.** No long-lived GitHub secret per workspace; repository access is chosen by the installer; commits and PRs come from the App's bot identity. Each operator registers **their own** App, so a self-hosted deployment never depends on someone else's credentials. Installation tokens can create organisation repos but not personal ones, so "New repo" works in organisations only.

### ADR-009: Envelope encryption behind a `KeyProvider` protocol

**Decision.** Each workspace has a random 256-bit data key (DEK), wrapped by a master key held by a `KeyProvider`. Secrets are encrypted with AES-256-GCM under the DEK, with associated data that binds each ciphertext to its workspace, connection and provider. A redaction filter replaces any live secret in logs and event payloads.

**Consequences.** The master key never leaves the provider; moving from a key file (dev) to a cloud KMS is a new provider class, not a migration. A ciphertext copied to another row fails to decrypt. Losing the master key makes stored keys unrecoverable (they must be entered again), so it must be backed up apart from the database.

### ADR-010: Humans approve every irreversible action, and approvals expire

**Decision.** Push, pull request, repo creation and (later) Jira transitions always sit behind a `gate`, also in autonomous mode. The platform never merges. A gate has a time to live (72 h ceiling, shorter per gate); at expiry the run is cancelled with the reason "Approval expired". The approver can edit the change; the gate commits the edits so the PR is exactly what was approved.

**Consequences.** Agents can be given real work on real repositories without an unreviewed write. A forgotten approval never blocks counts forever. Every decision is recorded with its edits and comment.

### ADR-011: Limits are platform ceilings frozen on each run; the budget is optional

**Decision.** Platform defaults (8 agents alive, 40 spawned, depth 2, 5 loop iterations, 2 h active time, 72 h approval TTL) are also ceilings; a workspace may only lower them. A run copies its effective limits when it is created and keeps them across resumes. The USD budget is optional at workspace, workflow and run level (the most specific wins); if set it is a hard stop, and every model used must have a price.

**Consequences.** Safe by construction: a stop can always be explained by the limits the run was given. Teams can run without a cap, while cost is still tracked.

### ADR-012: Cost is priced once, when it is logged

**Decision.** The adapter prices each provider call from the workspace's price table when it writes the `usage` event. Logged costs never change. Cache reads and writes are priced apart.

**Consequences.** A budget stop is always explainable; a price change never rewrites history. Prices are dated (`PRICES_AS_OF`) and checked by hand against the provider; workspaces can override them.

### ADR-013: Graph operations over the spec's tree, and immutable versions

**Decision.** The canvas, the side panel and (later) the Flow Architect all change a workflow through the same typed operations (`addNode`, `removeNode`, `connect`, `disconnect`, `setParam`), addressed by node id over the spec's tree. `PATCH` takes a `base_version`; a stale base gets `409`. Each version stores its spec and the ops that made it; versions are append-only.

**Alternatives.** A separate nodes-and-edges form (two shapes to keep in sync); JSON Patch (array positions shift as the tree changes).

**Consequences.** Undo, diff, history, restore and audit come from one mechanism. Two editors never overwrite each other silently.

### ADR-014: CEL for every expression

**Decision.** Router conditions, `loop.until` and input mappings use the Common Expression Language (`cel-python`). No arbitrary code in a spec, ever.

**Consequences.** Expressions are side-effect free, bounded and safe to evaluate on the worker. Logic that needs code belongs in a plugin node with its own sandbox.

### ADR-015: Durations mean active time

**Decision.** Active time, waiting time (at gates) and wall-clock time are stored apart. Everything labelled "duration" is active time; waiting is shown beside it; the wall-time limit counts active time only.

**Consequences.** A run that waited a weekend for approval is not a 60-hour run. Numbers in the product are trustworthy.

### ADR-016: The canvas is a card tree, not a free-form graph editor

**Decision.** One component (`SpecTree`) draws the run map and the builder as a tree of cards (chains top to bottom, containers to the right). Every edit is a menu item that maps to one graph operation. No React Flow or layout engine.

**Alternatives.** React Flow with ELK layout (used before 11.9): pan and zoom inside a box were hard to handle, and the free-form graph did not match the spec's tree.

**Consequences.** Fully keyboard-accessible, no layout engine, fewer dependencies; the view is the spec's own structure. Drag-and-drop can come later as an extra input, never instead of the menu.

### ADR-017: An owned component library, and colour reserved for status

**Decision.** shadcn/ui (Radix) components copied into the repo, Tailwind v4 with semantic design tokens for light and dark, and one component per kind of value (times, durations, money, tokens, ids, paths). Colour means status (and severity, with its own tokens), never decoration. A lint rule rejects raw colours and arbitrary text sizes.

**Consequences.** A calm, consistent, accessible UI (WCAG 2.2 AA, checked by axe in CI) that coding agents cannot drift from. Re-theming is a token change.

### ADR-018: Specs govern the work

**Decision.** [`specs/mission.md`](../../specs/mission.md), [`roadmap.md`](../../specs/roadmap.md), [`tech-stack.md`](../../specs/tech-stack.md) and [`design-language.md`](../../specs/design-language.md) are the constitution. Every phase is planned in a dated `specs/YYYY-MM-DD-<slug>/` folder (requirements, plan, validation) before it is built, and every decision lands in the specs in the same PR as the code. CI checks the changelog and the roadmap status on every PR.

**Consequences.** People and coding agents read one place to know what to build and why. Phase numbers never change, so references stay valid.

### ADR-019: Open source under Apache-2.0, self-hosted first

**Context.** The v1 plan was a hosted SaaS only. The project is now published as open source so that teams can run it on their own infrastructure, with their own GitHub App and their own model keys.

**Decision.** License the code under Apache-2.0. Treat self-hosting as the primary distribution; a hosted multi-tenant service remains a later goal (roadmap phase 10.5).

**Alternatives.** MIT (no explicit patent grant); AGPL-3.0 (forces hosted modifications open, but many companies cannot adopt AGPL software).

**Consequences.** Companies can adopt and modify it freely, with an explicit patent grant. Every operator owns their own credentials, so no deployment depends on another's secrets. Authentication, which the hosted plan had deferred, becomes the most important gap for self-hosters (see the [security model](../security/security-model.md)).
