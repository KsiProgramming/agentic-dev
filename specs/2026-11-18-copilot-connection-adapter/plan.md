# Plan: Personal GitHub connection and Copilot adapter

## 1. The spike
- [ ] Look up the SDK with `npx ctx7@latest library "GitHub Copilot SDK" "Python custom tools, usage events, permission handler, headless token auth"` then `docs`; note the current package name, version and release status.
- [ ] In its own virtualenv outside the uv workspace, run `specs/2026-11-18-copilot-sdk-terms/spike/copilot_probe.py` with `COPILOT_PROBE_TOKEN` from the environment. Fix the script to the SDK's real API if names changed.
- [ ] Extend the probe to check: a custom tool is called and its result returned; built-in tools can be turned off; what the permission handler is asked for; which event carries usage (tokens, premium requests) or that none does; headless use with no signed-in user; what happens with an expired token and with a user who has no subscription; whether the token appears in any event field.
- [ ] Record the results in `specs/2026-11-18-copilot-sdk-terms/findings.md` (a "Spike results" section replacing "Not run") and as decisions-log rows in `specs/tech-stack.md`. If headless use does not work, stop here and record a no-go.

## 2. Copilot adapter on a fake SDK
- [ ] Add the pinned SDK to `packages/runtime`; add `packages/runtime/src/agentic_runtime/copilot.py` with `CopilotRuntime` implementing `AgentRuntime`.
- [ ] Put the SDK behind a small `CopilotClientProtocol` so tests use a fake client (`copilot_fake.py`, as `fake.py` fakes the runtime).
- [ ] Register the platform's MCP tools as custom tools with the same names, schemas and tool-intent argument as `claude.py` (reuse `tools.py`); turn off built-in tools; answer permission requests from the node's grants and deny and log the rest.
- [ ] Map SDK events to `text_delta`, `reasoning_delta`, tool call and result events, and the normalised usage event (estimated and flagged when the SDK reports none); support cancel.
- [ ] Run `contract.py`'s shared tests against `CopilotRuntime` with the fake client, beside the Claude adapter's.
- [ ] Tests: what the agent receives (system prompt with "# The run", tool schemas, `TOOL_INTENT_INSTRUCTION` or `NO_TOOLS_INSTRUCTION`, `<input>` and `<request>` tags), a denied permission, cancel, and that a token string given to the fake never appears in any emitted event, log record or error text.

## 3. The personal connection (API)
- [ ] Migration: the personal connection as a `connections` row (`provider: "github_user"`, one per person, labelled by login) and `runs.copilot_connection_id`.
- [ ] `packages/github`: the user-token flow on `GitHubPlatform` (authorize URL, code exchange, refresh where the kind has it, `GET /user` for the login) with a fake for tests and the e2e stack; random `state` in Redis for 10 minutes, as 1.5 and 7.1.
- [ ] Routes: `POST /workspaces/{id}/connections/github-user/authorize`, `GET /github-user/callback`, `GET /workspaces/{id}/github-user` (logins and status, never tokens), `DELETE …/{connection_id}`; token refresh under a row lock; "Needs attention" on a refused token.
- [ ] `POST /runs` accepts a `copilot_connection_id`, checks it belongs to the workspace and is usable, refuses a run with no starter (`422`), and records it; the worker builds `CopilotRuntime` from that connection's token only (never any other connection's).
- [ ] A fixed failure code per refusal (`copilot_not_connected`, `needs_attention`, `no_subscription`, `rate_limited`, `copilot_unavailable`) so a run fails with a reason, not a trace.
- [ ] Audit actions for connect, remove, refresh failure and a run's use of a connection; a redaction test over events, logs and the audit log.
- [ ] Tests: state single-use, encrypted storage, refresh race, revoked token, picking another workspace's connection refused, a trigger-started run refused for Copilot.

## 4. Settings and the start sheet (web)
- [ ] A "GitHub (personal, for Copilot)" `ConnectionCard` on Settings › Integrations (Connect, login, Needs attention, Remove in a dialog), with the three states from `@/components/states`.
- [ ] The New run sheet's provider choice: Copilot is live when a usable personal connection exists and names the login; the 5.8 picker's static disabled row is replaced; the run console shows which login a Copilot run used and whether its cost is estimated.
- [ ] Component and API-client tests; the existing axe and layout e2e stay green at 375, 768 and 1440 px in light and dark.

## 5. A real run, read step by step
- [ ] With a real subscription, run a one-node Copilot agent on a real repo (`AGENTIC_RUNTIME=copilot`) and read it in the console's Activity tab: instructions, input, tools and what they read, the permission requests, the usage shown. Fix what it shows.
- [ ] Add an entry to `specs/lessons.md` for anything tests did not catch, with the rule and what enforces it.

## 6. Specs and docs
- [ ] `specs/tech-stack.md`: the Copilot adapter contract, "GitHub personal connection (API contract)", the audit actions, the decisions-log rows from the spike.
- [ ] `specs/roadmap.md`: 8.2's row links this plan; update "Next up" only if the priority changed.
- [ ] `docs/integrations/connecting-platforms.md`, `docs/security/security-model.md`, `.env.example`, `CHANGELOG.md` under `## [Unreleased]`.
