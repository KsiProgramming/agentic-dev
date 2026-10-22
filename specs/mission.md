# Mission

## Why we exist

Teams need AI agents that work on their real codebases: writing docs, auditing code, and shipping features from Jira. Single-agent tools run one loop. Workflow builders don't understand code. We build a platform that does both. Orchestration is open, the platform understands code, and teams use the model access they already pay for.

## Mission statement

> Let any team design, run, and trust AI agent workflows on their own repositories. Orchestration is something they draw, discuss with an architect agent, and reuse. It is never a fixed menu. Every change lands as a reviewable pull request.

## What we deliver (v1)

- **Three day-one outcomes** on an existing or newly created GitHub repo: generated docs, a codebase audit, and spec-driven development (SDD) from Jira.
- **Open orchestration.** A small set of engine primitives (`agent`, `tool`, `sequence`, `parallel`, `map`, `reduce`, `orchestrator`, `router`, `loop`, `gate`, `subflow`). Every pattern is a graph built from them. Users extend the set with composite nodes (no code) and plugin nodes (code), and no engine release is needed.
- **Flow Architect.** An agent that turns a goal and repo context into graph operations, with a reason for each node. Users run the draft, edit it, or chat about it.
- **Bring your own model access.** A Claude API key or a GitHub Copilot subscription, chosen per workspace and overridable per workflow and per node.
- **Traceable delivery.** Every code change becomes a branch and a PR, linked back to the Jira issue that started it.

## Who we serve

| Persona | Wants | Entry point |
|---|---|---|
| Developer | Docs, an audit report or a PR with little setup | Template or plain-language goal |
| Tech lead | Workflows that match the team's process, reused across repos | Canvas editing, publishing templates and composite nodes |
| Platform admin | Control of cost, tools, secrets and data | Workspace policies, audit log |

## Principles

1. **One spec, many views.** The versioned workflow spec is the single source of truth. The canvas, the chat, the Architect and the monitor all read it or change it through the same graph operations. This gives undo, diffs and audit with no extra work.
2. **Open, but safe by construction.** The engine enforces limits, not the graph. We check them at validation time and again at runtime.
3. **Humans approve irreversible actions.** Push, PR, repo creation and Jira status changes always go through a gate. No merge to protected branches without human approval.
4. **Tools live in the platform.** Integrations are MCP servers owned by the platform, so a workflow behaves the same on Claude and on Copilot.
5. **Repo, Jira and web content are data, never instructions.** We defend against prompt injection by default.
6. **Transparency.** Every agent action, tool call, artifact and cost is visible live and kept in an append-only log.
7. **Small, verifiable steps.** We ship in thin vertical slices. Each one is usable and passes its acceptance criteria.
8. **Enterprise-grade, calm UI.** The product looks and behaves like a professional tool, not a debug page. That means one design system, a quiet neutral palette with colour kept for status, and a layout that works from a phone to a wide monitor. Every screen has a defined empty, loading and error state. What needs the user, such as a waiting approval or a failed run, is always visible and never below the fold. Runs are readable as a story (nodes, messages, tool calls), and the raw event log is one click away, not the default view.
9. **Nothing is lost.** Every run is listed in a history with its outcome, and any run can be opened later. A failed or cancelled run can be rerun in one click.

## v1 decisions

- **Hosting: SaaS only.** A multi-tenant hosted service. Self-hosting for enterprises is a later goal, not a v1 commitment.
- **Autonomous mode is allowed for code-writing workflows.** Gates are still enforced before every write action (push, PR, repo creation, Jira change). Autonomous mode skips draft approval, never write gates.
- **Budget is optional.** A workspace, workflow or run *may* set a USD budget. If set, it is a hard stop at 100%. If no budget is set, the run continues without a cost cap. The other policy limits still apply (agents alive, agents spawned, nesting depth, loop iterations, wall time). Cost is always tracked and shown, whether or not a budget is set.

## Non-goals (v1)

- IDE plugin or inline code completion.
- Merging to protected branches without human approval.
- GitLab, Bitbucket, Linear and Azure DevOps (adapters come later as MCP servers).
- Self-hosted local models.
- Self-hosted deployment of the platform.

## How we measure success

- Acceptance criteria AC-1 to AC-8 from the product spec pass.
- Flow Architect quality: share of drafts that validate on the first try, user edit distance before Run, run success rate, and cost compared with the best known template.
- Performance: canvas usable with 200 nodes, monitor events shown within 1 s, Architect first draft within 60 s for a profiled repo.
- Reliability: a worker restart mid-run loses no completed nodes.
- UI quality: every page works at 375, 768 and 1440 px with no horizontal scroll; WCAG 2.2 AA (axe finds no serious issues); a waiting gate is visible without scrolling; a user starts a docs run without help text.

## Open questions (not decided here)

- Pricing: who pays for sandbox compute when users bring their own model access?
- Copilot SDK terms for use inside a hosted multi-tenant service. We must check these before committing to that adapter.
