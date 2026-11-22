# Personal GitHub connection and Copilot adapter

Roadmap phase: 8.2
Branch: plan/8.2-copilot-connection-adapter

## Context

First build phase of Milestone 8 (Second provider), named by the roadmap's "Next up" line. 8.1 (merged as #248) settled the terms: Copilot is a **conditional go for self-hosted use**, per person, and a **no-go for a hosted multi-tenant service** until GitHub confirms in writing ([findings](../2026-11-18-copilot-sdk-terms/findings.md)). It did not run its spike (no subscription was available), so three things are unknown and this phase must find them first: whether the SDK's custom tools carry the platform's MCP tools, whether it reports usage (tokens or premium requests), and whether it runs headless on a stored token.

The phase depends on done work only: the `AgentRuntime` interface and the Claude adapter (0.3, 0.7), encrypted connections (1.4), the GitHub package and its OAuth-style `state` handling (1.5), Settings › Integrations (11.7) and the Jira connection as the latest pattern for an OAuth grant with refresh and "Needs attention" (7.1). It unblocks 8.3 (provider selection per workspace, workflow and node; AC-6).

Principles: **3. Humans approve irreversible actions** (the platform's gates and tool grants stay the safety layer; the SDK's own permission prompts are answered by the platform, not by the model), **4. Tools live in the platform** (every tool is an MCP tool of ours, registered with the SDK as a custom tool, so a workflow behaves the same on both providers), **5. Content is data** (nothing from the SDK's events is rendered as HTML), **6. Transparency** (connect, remove, refresh failures and the use of a token by a run are audit entries; the token is in no event). Tech stack: "Agent runtime" (the Copilot row: a user token, one SDK client or session token per user, never the company App) and the 8.1 decisions-log rows (triggered runs use Claude only; hosted multi-tenant does not offer Copilot).

This phase changes what agents receive on a second provider, so [`lessons.md`](../lessons.md) rule 1 applies: it is done only once a real Copilot run has been read step by step in the console.

## Scope

### In scope
- **The spike, first.** Run [`copilot_probe.py`](../2026-11-18-copilot-sdk-terms/spike/copilot_probe.py) with a real subscription and a user token, check the SDK's current names (and the `microsoft-copilot-sdk` rename 8.1 noticed), and record in `findings.md` and tech-stack what it showed: custom tools, usage fields, headless use, the permission handler, the pinned version. The adapter is built to what the spike found, not to the documentation.
- **A personal GitHub connection.** A user OAuth token per person, from a GitHub OAuth flow (`gho_`) or GitHub App user-token flow (`ghu_`), stored encrypted in the workspace under the envelope of 1.4, labelled by the GitHub login, with its expiry and refresh when the token kind has them. Never the company App's installation token, never a classic `ghp_` token, no pooled or shared account (findings, conditions 2 and 3). Several personal connections may exist in one workspace, one per person.
- **Picking whose Copilot a run uses.** The person who starts a run picks one of the personal connections; a run records which (`runs.copilot_connection_id`) and uses only that token. A run with no starter (a Jira or GitHub trigger, a schedule) cannot be given Copilot and stays on Claude (decisions log, 8.1).
- **The Copilot adapter.** `CopilotRuntime` behind `AgentRuntime` in `packages/runtime`: one SDK client or session token per run, the platform's MCP tools registered as custom tools with the same names, schemas and tool-intent argument as on Claude, the SDK's permission requests answered by the platform's grants (never `approve_all` by default), streamed text and reasoning as `text_delta` and `reasoning_delta`, cancel, and the normalised usage event.
- **Usage.** The usage event is filled from what the SDK reports. If the spike finds no usage field, the event is estimated, says so (`estimated: true`), and the console and `Money` show it as an estimate; premium requests are counted when the SDK reports them.
- **Token hygiene.** The token is passed to the SDK per run and never placed in an event, a log line, an error message, a tool result, the sandbox's environment or a run artifact; a redaction test proves it.
- **Needs attention.** A token the SDK or GitHub refuses (expired, revoked, no Copilot subscription, premium requests rejected for the wrong billing entity) marks that person's connection "Needs attention" with the reason and fails the run with a fixed code, not a stack trace.
- **Settings and the start sheet.** A "GitHub (personal, for Copilot)" `ConnectionCard` on Settings › Integrations (Connect, the login, Needs attention, Remove in a dialog); a provider choice on the New run sheet that offers Copilot only when the starter has a usable personal connection, naming the login it will use; the 5.8 provider picker's disabled Copilot row becomes live. Audit entries for connect, remove and failure.
- Specs and docs: tech-stack (the Copilot adapter contract, the personal connection's API contract, the audit actions, decisions-log rows for what the spike found), `docs/integrations/connecting-platforms.md` (registering the OAuth app or reusing the GitHub App's user-token flow), `docs/security/security-model.md`, `.env.example`, `CHANGELOG.md`.

### Out of scope
- **Provider selection per workspace, workflow and node, capability-gap validation and "same workflow runs unchanged on both" (AC-6):** 8.3. Here the provider stays the node-level field that exists (5.4); a run's Copilot connection is picked at start.
- **Runs with no starter on Copilot:** not until a phase names an owner for a trigger (decisions log).
- **A hosted multi-tenant Copilot offer (10.5):** stays no-go until GitHub answers in writing.
- **BYOK (bring your own key) for the SDK, organisation server-to-server billing, and `ghs_` installation tokens:** not what the owner asked for.
- **Users, sign-in and roles:** the workspace is the actor (roadmap note); a personal connection is labelled by GitHub login, and "the person who starts a run" picks among the workspace's personal connections until users exist.
- **A new Playwright spec for connect and pick** (not chosen in the interview). The existing axe and layout e2e must stay green.
- **Copilot-specific pricing tables and premium-request budgets beyond showing what the SDK reports:** a later phase if the spike shows premium requests are metered per run.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Order | Spike first, then adapter on a fake SDK, then the connection, then the UI | Chosen in the interview. The spike decides what the adapter can promise (tools, usage), and the adapter on a fake needs no subscription to test. |
| Spike result recorded | In `findings.md` and the tech-stack decisions log, before the adapter's code | 8.1 left tools, usage and headless use unproven; a later reader must see what was checked, with the SDK version. |
| Token kind | The user OAuth token (`gho_` or `ghu_`); fine-grained `github_pat_` accepted only if the spike shows it works; never `ghp_` or `ghs_` | 8.1 findings, S1 and S2. The company App's token is not addressed by the docs and the owner ruled it out. |
| Where the token lives | One encrypted JSON secret on a `connections` row per person (`provider: "github_user"`), no key hint | Same envelope as 1.4 and 7.1; a hint would not identify a rotating token. |
| Who may use a connection | Any run starter in the workspace, until users exist; the run records which connection it used | Matches the roadmap note that the workspace is the actor. The record keeps "never pooled" checkable in the audit log. |
| SDK permission requests | Answered by the platform from the node's tool grants; anything not granted is denied and logged | Principle 3: `approve_all` would let the SDK's own tools (shell, file writes) bypass the platform's gates. The spike confirms what the SDK asks for. |
| Tools | The platform's MCP tools registered as custom tools; the SDK's built-in tools turned off if it allows | Principle 4: the same tools on both providers. Built-in file and shell tools would write outside the platform's worktrees and gates. |
| Usage | What the SDK reports; otherwise estimated and flagged | Findings: no usage event was found in the documentation. An honest estimate beats a missing cost (principle 8: numbers are truthful). |
| Package | Pinned SDK version in `packages/runtime`'s dependencies | Findings, condition 4: pin, and re-read the sources if the package or licence changes. |

## Open questions
- Does the SDK run headless with a stored token, with no interactive sign-in? The spike answers it; if not, the adapter cannot be built as planned and the phase stops at the spike with a recorded no-go.
- Which package is current, `github-copilot-sdk` or `microsoft-copilot-sdk`, and do its terms differ? Checked in the spike; the answer goes into the decisions log.
- Is the user token obtained by a GitHub OAuth app or by the existing GitHub App's user-to-server flow? Decided after the spike, by which one the SDK accepts and what scopes it needs; the other is recorded as rejected.
- Does `findings.md`'s condition 1 (the owner's confirmation of the terms reading) hold? It is a person's decision; the phase records it and does not assume it.
