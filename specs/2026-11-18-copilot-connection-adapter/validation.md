# Validation: Personal GitHub connection and Copilot adapter

## Done when (from roadmap)
> A one-node run on Copilot works on the starter's own account, and its token appears in no event

## Automated checks
- [ ] `CopilotRuntime` passes the shared `AgentRuntime` contract tests on a fake SDK client, as the Claude adapter does.
- [ ] A test asserts what a Copilot agent receives: system prompt with "# The run", tool schemas and the tool-intent instruction (or the no-tools one), `<input>` and `<request>` as data.
- [ ] A token given to the fake client appears in no event, log record, error text, tool result, run artifact or audit entry (redaction test over all of them).
- [ ] A permission request for an ungranted tool is denied and logged; `approve_all` is never used by default.
- [ ] Connection API tests: single-use `state`, encrypted storage, refresh under lock, revoked token marks "Needs attention", another workspace's connection refused, a run with no starter refused for Copilot, a run uses only its own recorded connection.
- [ ] A usage event is emitted for a Copilot turn, flagged `estimated` when the SDK reports none.
- [ ] Web: component tests for the card, the provider choice and the console's login and estimate display; `cd web && pnpm lint && pnpm typecheck && pnpm test`; `pnpm test:e2e` (axe, layout) stays green.
- [ ] Backend: lint, type check and tests of the touched packages, run locally (CI minutes are limited). Never run `packages/sandbox/tests` whole.

## Manual / demo checks
- [ ] The spike's results are in `findings.md` and the decisions log, with the SDK version.
- [ ] With a real Copilot subscription: connect a personal GitHub account in Settings, start a one-node run on Copilot from the New run sheet, and see it use that login. Read the run step by step in the console's Activity tab (lessons.md rule 1): instructions, input, tools and what they read, permission requests, usage.
- [ ] Search the run's events (Raw events tab and `GET /runs/{id}/events`) and the worker's logs for the token: no match.
- [ ] Revoke the token on GitHub, start another run: the run fails with a fixed code and the card shows "Needs attention".
- [ ] A Jira-triggered run offers no Copilot and stays on Claude.
- [ ] Look at Settings and the New run sheet at 375 and 1440 px, light and dark.

## Merge criteria
- [ ] All checks above pass (CI green, or the local runs recorded if CI minutes are out).
- [ ] The real Copilot run was read step by step, and any mistake it showed has a `lessons.md` entry.
- [ ] Specs updated in the same PR (tech-stack, roadmap link, decisions log) and `CHANGELOG.md` has an entry under `## [Unreleased]`.
- [ ] No token or secret in logs, events, fixtures or the spike script; the owner's decision on findings condition 1 is recorded.
