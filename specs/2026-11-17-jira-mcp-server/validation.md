# Validation: `jira` MCP server: read issue, comment, transition

## Done when (from roadmap)
> Agent reads an issue and posts a comment

Made checkable: in a run of `jira-issue-answer` with Claude on a real Jira Cloud site, the agent reads the issue with `jira.getIssue`, the gate shows the comment it wrote, and on approval `jira.comment` posts it to that issue. The comment is visible in Jira, ending with the line that links the run.

## Automated checks
- [ ] `packages/jira`: ADF ⇄ Markdown round trips and hostile input (HTML stays text, deep nesting capped); client URLs and fields for issue, search, comments and transitions; error mapping to the fixed kinds; one `Retry-After` retry then `rate_limited`; no token or response body in any error.
- [ ] `packages/tools` (fake platform): each tool's result shape and caps; `project_not_allowed` for an off-list key, a moved issue and a disabled site; `jql` with `OR project = X` returns nothing from X and `ORDER BY` in `jql` is refused; `site_required` with two enabled sites; `needs_attention` / `jira_not_connected`; the comment footer; the server registers exactly `JIRA_READ_TOOLS | JIRA_WRITE_TOOLS`; no token in any tool result or event (extends `test_jira_tokens_appear_nowhere`).
- [ ] `packages/engine` validation: `jira_write_not_tool_node`, `jira_write_without_gate`, `jira_write_not_shown`, `issue_from` without `input` or with another value; `jira-issue-answer` validates.
- [ ] `packages/engine` **what the agent receives** (lessons rule 1): the analyst's request carries `jira.getIssue`, `jira.search` and the repo read tools and no write tool; its tool calls go out as its node id; the issue arrives only as a tool result; the tool node gets `issue` from the request and `body` from `comment.md`, and never sees `issue_from` or `body_from`.
- [ ] `packages/api`: `POST /runs` → `409 jira_not_connected` (not connected, needs attention); `GET /templates` lists `jira` in `requires`.
- [ ] Worker / e2e stack (fake runtime, `AGENTIC_JIRA=fake`): a `jira-issue-answer` run pauses at the gate with `comment.md`; on approval the fake records one comment on the seeded issue; on rejection none.
- [ ] Web: Vitest for `workflowRequires` and the Jira checklist item; `pnpm lint && pnpm typecheck && pnpm test`; `pnpm test:e2e` (axe and layout specs on the gallery and the run sheet) green.
- [ ] `uv run ruff check`, `uv run pyright` (or the repo's type check), and the full Python test suite green. Never run `packages/sandbox/tests` whole against the dev stack.

## Manual / demo checks
- [ ] Real run (lessons rule 1): with a Jira Cloud test site connected (7.1) and one project picked, start "Answer a Jira issue" with `AGENTIC_RUNTIME=claude` on a real repo and an issue key in that project. In the console's Activity, read each step: the analyst called `jira.getIssue` (and read the repo), its answer is the comment and nothing else, and the gate shows `comment.md`. Approve, then open the issue in Jira: the comment is there, formatted, with the run link. Record the run id and what was read in this file.
- [ ] Same run with an issue key from a project that is not picked: the analyst's `jira.getIssue` returns `project_not_allowed`, and nothing is posted.
- [ ] A spec with `jira.comment` and no gate fails validation in the canvas with `jira_write_without_gate` on the node.
- [ ] Gallery at 375 and 1440 px, light and dark: the "Answer a Jira issue" card shows the Jira chip missing, then connected after connecting; the run sheet's checklist connects Jira and returns to the sheet.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] The real run has been read step by step, and its result is recorded here; any lesson it taught is in `lessons.md`.
- [ ] `specs/tech-stack.md` updated (Jira tools contract, validation codes, template, UI, decisions log); docs and `CHANGELOG.md` updated in the same PR.
- [ ] No token, authorization header or Jira response body in logs, events or audit entries.
