# Plan: `jira` MCP server: read issue, comment, transition

Order chosen in the interview: client → tools → engine → worker and template → UI from 7.5 → specs and the real run. The project stays working after each group: nothing grants a `jira.*` tool until group 3 lets a spec name one.

## 1. Jira client: issues, search, comments, transitions
- [ ] `packages/jira/src/agentic_jira/models.py`: `Issue`, `IssueComment`, `IssueSummary`, `SearchPage`, `Transition` (Pydantic, display fields only).
- [ ] `agentic_jira/adf.py`: `to_markdown(adf)` (paragraph, heading, bullet and ordered lists, code block, inline marks, quote, link, mention, table, media as `[attachment]`; unknown nodes become their text) and `from_markdown(text)` (the write subset; the rest as plain text). No HTML either way.
- [ ] `platform.py` / `client.py`: `get_issue`, `search` (`/rest/api/3/search/jql`, `nextPageToken`, fixed `fields`), `transitions`, `add_comment`, `transition`, all through `agentic_jira.call` (refresh, one `401` retry). `429` gets one retry after `Retry-After` up to 10 s, then `RateLimited`. Errors map to the fixed kinds in `errors.py`, never a body.
- [ ] `fake.py`: seeded issues on two projects of the fake site, comments, a To Do → In Progress → Done workflow, and calls recorded so tests can assert what was posted.
- [ ] Tests: `packages/jira/tests/test_adf.py` (round trips, hostile input: HTML in text stays text, deep nesting capped), `test_issues.py` against an `httpx2` mock transport (URLs, fields, error mapping, `Retry-After`, no token in any error).

## 2. `jira` MCP server
- [ ] `packages/tools/src/agentic_tools/jira/server.py`: `build_jira_server(jira, access, workspace_id, run_id)` with `getIssue`, `search`, `listTransitions`, `comment`, `transition` via `strict_tool` (the `description` intent arg, unknown args refused).
- [ ] Site resolution (`site` cloud id or host → an enabled site of the grant; the only one by default; `site_required`, `site_unknown`).
- [ ] Allowlist on every call through `jira_project_allowed`: key prefix first, the returned project after; search wrapped as `project in (…) AND (jql)`, `ORDER BY` refused, results post-filtered.
- [ ] Caps and `truncated` (description 32,000, comment 4,000, 20 comments, 50 results); the run-link footer on `comment`.
- [ ] `agentic_tools/jira/__init__.py`: `open_jira_tools(...)` (in-memory `Client`, `McpToolExecutor`), `JIRA_READ_TOOL_NAMES`, `JIRA_WRITE_TOOL_NAMES`.
- [ ] Tests (`packages/tools/tests/test_jira_tools.py`, fake platform): each tool's result shape; `project_not_allowed` for an off-list key, for a moved issue and for a disabled site; a `jql` with `OR project = X` returns nothing from X; `needs_attention` and `jira_not_connected`; no token in any result or error; the server registers exactly the names in `PLATFORM_TOOLS`.

## 3. Engine: tool sets, validation, write arguments
- [ ] `spec/models.py`: `JIRA_READ_TOOLS`, `JIRA_WRITE_TOOLS` in `PLATFORM_TOOLS`. Issue codes `jira_write_not_tool_node`, `jira_write_without_gate`, `jira_write_not_shown`, plus `issue_from` checks (only `"request"`, the workflow declares `input`). Jira tools do not make a run need a repo (they are not in `REPO_TOOL_PREFIXES`).
- [ ] `graph/compile.py`: generalise `_with_body_from` to the Jira writes and resolve `issue_from: "request"` from `RunContext.request` (one key, `^[A-Z][A-Z0-9_]+-\d+$`, else the node fails `issue_invalid` before any call).
- [ ] Node manifests (5.3): the read tools listed for agents, the writes for tool nodes, so the canvas palette and side panel offer them with no frontend change; live validation (5.6) mirrors the new codes in `@/workflows`.
- [ ] Tests: validation cases for every new code; `body_from` / `issue_from` resolution; **what the agent receives** (lessons rule 1): an agent granted `jira.getIssue` gets the tool in its request, its tool call goes out with the run's node id, and the issue comes back as a tool result, never in the system prompt or the instructions.

## 4. Worker, API and the template
- [ ] Worker: open the `jira` tools when the spec names any `jira.*` tool (with or without a sandbox), with `access_token` per call from the store; refuse to start with `jira_not_connected` (a `failure_reason`) if the connection changed since `POST /runs`.
- [ ] API: `POST /runs` answers `422 jira_not_connected` for a spec that names a `jira.*` tool when the workspace's connection is not `connected`; `Requirement` gains `jira`, and `GET /templates` lists it.
- [ ] `agentic_engine/templates/jira_issue_answer.py`: required `input` ("Which Jira issue?", example `PROJ-12`). Steps: an analyst with `jira.getIssue`, `jira.listTransitions` and the repo read tools writes `comment.md`; a gate shows `comment.md`; `jira.comment` posts it with `issue_from: "request"` and `body_from: comment.md`. Instructions follow lessons.md's rules for writing workflows (what the input is, what the tools read, Markdown only).
- [ ] Tests: the template validates; the e2e stack's fake run reads the seeded issue and the fake records the comment after approval; `POST /runs` refusals.

## 5. Web: Jira as a requirement (from 7.5)
- [ ] `web/src/runs/new-run/readiness.ts`: `jira` in the requirements; `workflowRequires` adds it when a node names a `jira.*` tool.
- [ ] Template card "Requires" line: a Jira chip (connected or missing) beside Claude and GitHub.
- [ ] New run sheet "Before you start": a Jira item. Connect calls `POST …/connections/jira/authorize` with `return_to=/templates?template=<id>`; "Needs attention" links to Settings › Integrations. Start run stays disabled until Jira is connected.
- [ ] `JiraConnection` callback result on the sheet's return (`?jira=connected|error`).
- [ ] Vitest for the readiness rules and the checklist item; `pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e` green; screens checked at 375 and 1440 px in light and dark.

## 6. Specs, docs and the real run
- [ ] `specs/tech-stack.md`: "Jira tools (API contract)" (tools, args, results, errors, caps, scoping, the footer); Tool layer line; validation codes; template entry; UI design system → Start and settings (the Jira chip and checklist item); decisions-log rows from requirements.md.
- [ ] `docs/integrations/connecting-platforms.md` (what the tools can do, the dedicated account), `docs/security/security-model.md` (scoping, writes behind gates, no token in events), `CHANGELOG.md` under `[Unreleased]`.
- [ ] Real run (validation.md): `AGENTIC_RUNTIME=claude` against a real Jira Cloud test project. Read each step in the console's Activity, record the result in validation.md, and add a lessons.md entry if anything went wrong that tests missed.
