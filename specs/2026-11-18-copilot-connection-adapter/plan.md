# Plan: Personal GitHub connection and Copilot adapter

## 1. The spike
- [x] Look up the SDK with `npx ctx7@latest library "GitHub Copilot SDK" "Python custom tools, usage events, permission handler, headless token auth"` then `docs`; note the current package name, version and release status.
- [x] In its own virtualenv outside the uv workspace, run `specs/2026-11-18-copilot-sdk-terms/spike/copilot_probe.py` with `COPILOT_PROBE_TOKEN` from the environment. Fix the script to the SDK's real API if names changed.
- [ ] Extend the probe to check: a custom tool is called and its result returned; built-in tools can be turned off; what the permission handler is asked for; which event carries usage (tokens, premium requests) or that none does; headless use with no signed-in user; what happens with an expired token and with a user who has no subscription; whether the token appears in any event field. (Done except an expired token and a user with no subscription: no second account yet.)
- [x] Record the results in `specs/2026-11-18-copilot-sdk-terms/findings.md` (a "Spike results" section replacing "Not run") and as decisions-log rows in `specs/tech-stack.md`. If headless use does not work, stop here and record a no-go.

## 2. Copilot adapter on a fake SDK
- [x] Add the pinned SDK to `packages/runtime`; add `packages/runtime/src/agentic_runtime/copilot.py` with `CopilotRuntime` implementing `AgentRuntime`.
- [x] Put the SDK behind a small `CopilotClientProtocol` so tests use a fake client (`copilot_fake.py`, as `fake.py` fakes the runtime).
- [x] Register the platform's MCP tools as custom tools with the same names, schemas and tool-intent argument as `claude.py` (reuse `tools.py`); turn off built-in tools; answer permission requests from the node's grants and deny and log the rest.
- [x] Map SDK events to `text_delta`, `reasoning_delta`, tool call and result events, and the normalised usage event (estimated and flagged when the SDK reports none); support cancel.
- [x] Run `contract.py`'s shared tests against `CopilotRuntime` with the fake client, beside the Claude adapter's.
- [x] Tests: what the agent receives (system prompt with "# The run", tool schemas, `TOOL_INTENT_INSTRUCTION` or `NO_TOOLS_INSTRUCTION`, `<input>` and `<request>` tags), a denied permission, cancel, and that a token string given to the fake never appears in any emitted event, log record or error text.
- Notes from building it: the adapter is `copilot.py`, the fake `copilot_fake.py`, the real connector `copilot_sdk.py` (written from the SDK's API, **not yet run against GitHub**; the live spike in group 1 still has to confirm it). The SDK sits behind `CopilotConnector`/`CopilotSession` rather than a single client protocol, so the connector holds the token and nothing else sees it. The `estimated` flag on usage is not added: Copilot has no price table, so `estimated_usd` is `None` ("no price"), and a stream with no usage report gets a zero-token `usage` event; `cost` from the SDK is not mapped until the spike shows what it means. `SdkConnector` is not exported from the package root, so importing `agentic_runtime` does not import the SDK.

## 3. The personal connection (API)
- [x] Migration: the personal connection as a `connections` row (`provider: "github_user"`, one per person, labelled by login) and `runs.copilot_connection_id`.
- [x] `packages/github`: the user-token flow on `GitHubPlatform` (authorize URL, code exchange, refresh where the kind has it, `GET /user` for the login) with a fake for tests and the e2e stack; random `state` in Redis for 10 minutes, as 1.5 and 7.1.
- [x] Routes: `POST /workspaces/{id}/connections/github-user/authorize`, `GET /github-user/callback`, `GET /workspaces/{id}/github-user` (logins and status, never tokens), `DELETE …/{connection_id}`; token refresh under a row lock; "Needs attention" on a refused token.
- [x] `POST /runs` accepts a `copilot_connection_id`, checks it belongs to the workspace and is usable, refuses a run with no starter (`422`), and records it; the worker builds `CopilotRuntime` from that connection's token only (never any other connection's).
- [x] A fixed failure code per refusal: `copilot_not_connected`, `copilot_needs_attention`, `copilot_unavailable` and `copilot_not_configured` in the worker before any agent runs; mid-run, the adapter maps a refused token (401) to `copilot_needs_attention`, a refused seat (403) to `copilot_no_subscription` and a rate limit (429) to `copilot_rate_limited`, from the status the SDK carries or names in its text (the spike showed `Failed to validate SDK token (401)`), and the worker marks that person's connection "needs attention" (`unauthorized`) when it sees the first code. The 403 wording is unverified: no account without a seat was available.
- [x] Audit actions for connect, remove, refresh failure and a run's use of a connection; a redaction test over events, logs and the audit log.
- [x] Tests: state single-use, encrypted storage, refresh race, revoked token, picking another workspace's connection refused, a trigger-started run refused for Copilot.
- Notes from building it:
  - **A table of its own.** A personal connection is `github_user_connections`, not a `connections` row: that table is unique per (workspace, provider) and has a per-provider check, and a workspace needs one connection per person. The same envelope encrypts it (`provider` in the AAD is `github_user`), a replaced master key drops it with the other secrets, and it is audited with the existing `connection.*` actions.
  - **The provider is a per-run choice for now.** The spec's node `provider` is still `Literal["claude"]` and the worker opens one runtime per run, so a run with `copilot_connection_id` runs every agent on Copilot, and node-level choice stays 8.3.
  - **Routes** are `POST /workspaces/{id}/connections/github-user/authorize`, `GET /github-user/callback`, `GET /workspaces/{id}/github-user` and `DELETE /workspaces/{id}/github-user/{connection_id}`; `POST /runs` takes `copilot_connection_id` (`422 copilot_connection_not_found`, `409 copilot_needs_attention`, `422 copilot_not_for_triggers`); `GET /runs` and `GET /runs/{id}` return `copilot_login`. A rerun keeps the connection, a follow-up a webhook starts does not.
  - **Fake stack.** With `AGENTIC_RUNTIME=fake` a Copilot run still reads its token (so a missing or broken connection fails as it would for real), then runs the stack's fake agents; `AGENTIC_GITHUB=fake` also fakes the user OAuth app.
  - API tests run from `packages/api` (the repo's `.env` sets `GITHUB_APP_ID` without a key file, which breaks `create_app` when run from the repo root).

## 4. Settings and the start sheet (web)
- [ ] A "GitHub (personal, for Copilot)" `ConnectionCard` on Settings › Integrations (Connect, login, Needs attention, Remove in a dialog), with the three states from `@/components/states`.
- [ ] The New run sheet's provider choice: Copilot is live when a usable personal connection exists and names the login; the 5.8 picker's static disabled row is replaced; the run console shows which login a Copilot run used and whether its cost is estimated.
- [ ] Component and API-client tests; the existing axe and layout e2e stay green at 375, 768 and 1440 px in light and dark.

## 5. A real run, read step by step
- [ ] With a real subscription, run a one-node Copilot agent on a real repo (`AGENTIC_RUNTIME=copilot`) and read it in the console's Activity tab: instructions, input, tools and what they read, the permission requests, the usage shown. Fix what it shows.
- [ ] Add an entry to `specs/lessons.md` for anything tests did not catch, with the rule and what enforces it.

## 6. Specs and docs
- [x] `specs/tech-stack.md`: the Copilot adapter contract, "GitHub personal connection (API contract)", the audit actions, the decisions-log rows from the spike.
- [x] `specs/roadmap.md`: 8.2's row links this plan; update "Next up" only if the priority changed.
- [ ] `docs/integrations/connecting-platforms.md`, `docs/security/security-model.md`, `.env.example`, `CHANGELOG.md` under `## [Unreleased]`.
