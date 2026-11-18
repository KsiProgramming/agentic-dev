# Verify Copilot SDK terms for hosted multi-tenant use

Roadmap phase: 8.1
Branch: plan/8.1-copilot-sdk-terms

## Context

Milestone 8 adds a second model provider. The mission promises "a Claude API key or a GitHub Copilot subscription, chosen per workspace", and `mission.md` lists as an open question: "Copilot SDK terms for use inside a hosted multi-tenant service. We must check these before committing to that adapter." 8.1 answers it before 8.2 (the adapter) and 8.3 (provider selection, AC-6) spend effort on it.

This is a research and decision phase. It ships a verdict, evidence and a short spike, not product code.

- Depends on: nothing. Milestones 4 to 7, 11 and 12 are done.
- Unblocks: 8.2 and 8.3. A no-go changes them (see "Fallback" below). It also bears on 13.6, whose lenses "may run on another provider once Milestone 8 adds one", and on 17.2 and 17.5.
- Mission: principle 4 (tools live in the platform, so a workflow behaves the same on Claude and Copilot), the v1 decision "open source, self-hosted first" (each team uses its own GitHub App and model keys) and "bring your own model access".
- Tech stack: the agent runtime table names "GitHub Copilot SDK (Python binding)" with "GitHub OAuth / platform GitHub App" auth. Both are assumptions this phase checks.

## Scope

### In scope
- **Licence and terms.** Read the Copilot SDK's licence and the GitHub terms that apply to it (Copilot product terms, any pre-release terms, acceptable use, premium-request billing). Quote each clause that matters, with a link and the date read. Answer: may a service call the SDK on behalf of its users' own Copilot entitlements, and may it do so for several customers?
- **Both deployment modes, judged apart.** (a) **Self-hosted**, the v1 decision: one team runs the platform with its own GitHub App and subscriptions. (b) **Hosted multi-tenant**, roadmap 10.5: one operator serves many workspaces. Each gets its own verdict, so v1 can proceed even if (b) is a no-go.
- **Two GitHub connections (owner requirement).** The platform keeps its connection to the company's GitHub (the GitHub App: repos, branches, PRs, webhooks, 1.5) exactly as it is. A Copilot subscription belongs to a person, so a user who wants to use Copilot also connects their own GitHub account, a second and optional connection used only for Copilot. A user who never connects one still uses Claude. Copilot never runs on the company's GitHub App or a shared account. The findings must say whether the SDK and the terms allow this (a user OAuth token, such as a device or web flow, held by the platform and used only for that person's runs), and whether running a person's entitlement from a worker on a shared server is permitted at all. This is separate from the GitHub App used for repos and PRs (1.5), which stays as it is.
- **Auth and technical feasibility.** Which credentials the SDK accepts (a user's OAuth token, a GitHub App installation token, neither), whether it runs headless in a worker with no interactive login, whether it takes custom tools (needed for 8.2 to register our MCP tools), how usage and premium requests are reported (needed for the normalised usage event), and the Python binding's maturity (preview or GA, release cadence).
- **A throwaway spike.** A script outside the product packages that starts one headless SDK session with a test credential, makes one call with a custom tool, and prints the usage it gets back. Its result is evidence for the findings, not code the adapter builds on.
- **The verdict.** `go`, `conditional go` (with the conditions) or `no-go`, per deployment mode, in the tech-stack decisions log. The mission's open question is closed or reworded to what remains open.

### Out of scope
- The Copilot adapter, MCP tool registration and any `packages/` code: 8.2.
- Provider selection per workspace, workflow or node, and the capability-gap validation: 8.3.
- Removing the disabled "GitHub Copilot" row of the provider picker (5.8): 8.2.
- Building the per-user connection, sign-in, users and roles. 8.1 only decides whether it is allowed and possible, and records what it needs. The roadmap has no users phase yet, so the verdict must say which phase has to add one before 8.2 can ship (see open questions).
- Pricing, and who pays for sandbox compute (the mission's other open question).
- Legal advice. The findings are an engineering reading of public terms. A person confirms it before merge (see validation).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Output | `findings.md` in this folder (clauses quoted, linked, dated) plus one decisions-log row per deployment mode in `tech-stack.md` | The log holds the verdict (the roadmap's "Done when"); the file holds the evidence a reviewer needs to check it. |
| Deployment modes | Judged separately | v1 is self-hosted (mission, "v1 decisions"); the multi-tenant question is only open for 10.5. One verdict for both would block v1 on a later goal. |
| Whose account | Two connections: the company's GitHub App for repos and PRs (unchanged), plus an optional personal GitHub account (user OAuth) used only for Copilot. Copilot never uses the App or a shared token | Copilot entitlements are per person (owner requirement). It also keeps usage and premium requests billed to the right person. |
| Spike | Included, kept in `findings.md` as a short log and a script under this folder, never under `packages/` | It proves feasibility the terms cannot (headless auth, custom tools, usage fields). It needs a Copilot subscription. Without one, the spike is recorded as "not run" and the verdict is at most `conditional go`. |
| Secrets | The spike's token comes from the environment, is never written to a file, and never appears in the findings or logs | Principle 6 and the repo's secret rules. |
| Spec library docs | The SDK's current API is read with the `ctx7` CLI first, as the user's rules require, not from memory | Its API is newer than training data. |
| Fallback if no-go | Findings name the options (another provider, or a Claude-only v1) and the roadmap changes for 8.2 and 8.3 are written in the same PR | CLAUDE.md: nothing is decided only in a chat; a changed order or dropped phase goes into `roadmap.md`. |

## Open questions
- **Working assumption (owner confirmed the two-connection model, 2026-11-18):** no users phase first. The personal GitHub connection is stored inside the workspace and the person who starts a run picks whose Copilot connection it uses. The findings confirm or overturn this.
- **Conflicts with current specs.** `tech-stack.md` says Copilot auth is "GitHub OAuth / platform GitHub App", and the mission says the provider is "chosen per workspace". Both assume a workspace-level connection. Per-person auth means a run must know whose Copilot it uses, but the roadmap says "no phase adds users, sign-in and roles yet" and the workspace is the actor. The verdict has to say how to resolve this: a users phase before 8.2, or a per-user Copilot connection stored inside the workspace with the starter of a run chosen at start. Whichever it is, the mission, tech-stack and roadmap change in the same PR.
- Which person's Copilot does a run use when it is started by a webhook (Jira 7.3, GitHub 7.6) or a schedule (18.1)? These have no person. The findings should say whether they are Claude-only or need a named owner.
- Does the owner have a Copilot subscription and a test credential for the spike? If not, the spike is "not run" and the verdict is capped as above.
- Who signs off on the terms reading before merge (the project owner, or counsel)?
