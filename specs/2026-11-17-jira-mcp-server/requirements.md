# `jira` MCP server: read issue, comment, transition

Roadmap phase: 7.2
Branch: plan/7.2-jira-mcp-server

## Context

Second phase of Milestone 7. 7.1 (#237) stored a workspace's Atlassian grant, its sites and the projects picked on each, and gave one check every Jira tool must make (`agentic_store.jira_project_allowed`) and one way to get a valid token (`agentic_jira.access_token`, refreshed under a row lock). Nothing gives agents a Jira tool yet. This phase adds the platform's `jira` MCP server, which 7.3 (webhook trigger), 7.4 (field mapping) and 7.5 (the SDD template, AC-5) build on. The roadmap's "Next up" line still names Milestone 6 at 6.7; Milestones 6 and 12 are done, so Milestone 7 is next, and the line is updated in its own PR, not here.

Principles that drive it:

- **3. Humans approve irreversible actions.** Jira status changes are named in principle 3, and a comment, once posted, is read by people and integrations before anyone can delete it. Both writes are tool nodes after a gate, as `github.openPR` is. Agents only read.
- **4. Tools live in the platform.** One MCP server built on the official MCP Python SDK (tech-stack → Tool layer), so the tools behave the same on any provider; the token stays in the server.
- **5. Jira content is data.** Issue text, comments and search results come back as tool results, never put into an agent's instructions; rich text becomes Markdown text, with no HTML and no images.
- **6. Transparency.** Every call is a tool call event in the console. A posted comment says which run wrote it.

This phase changes what agents receive (new tools), so lessons.md rule 1 applies: an engine test asserts what the agent is given, and the phase is done only after a real run with Claude on a real Jira Cloud site has been read step by step in the console.

As chosen in the interview, it also pulls 7.5's UI forward: the "Jira" requirement chip on template cards and the Jira item in the run sheet's "Before you start" checklist. The template that needs them ships here too.

## Scope

### In scope

- **Reads for agents** (any `agent` node may be granted them; allowed in loops, maps, parallels and orchestrator workers):
  - `jira.getIssue {issue, site?}`: key, summary, status, type, priority, labels, components, assignee and reporter (display names), created and updated, URL, description as Markdown, and the latest 20 comments (author, created, body as Markdown). Text is capped (description 32,000 characters, each comment 4,000) with `truncated`.
  - `jira.search {jql, order_by?, site?, limit?}`: the matching issues (key, summary, status, type, assignee, updated, URL), at most 50 (default 20). The query is always limited to the picked projects: the server runs `project in (<picked keys>) AND (<jql>)`, refuses a `jql` holding `ORDER BY` (use `order_by`), and drops any result whose project is not picked.
  - `jira.listTransitions {issue, site?}`: the transitions available from the issue's current status (id, name, target status), so an agent can say which one the gated write should take.
- **Writes, gated** (tool nodes only, after a gate, like `PUBLISH_TOOLS`):
  - `jira.comment {issue | issue_from, body | body_from, site?}`: posts the comment, converted from Markdown to Atlassian Document Format (ADF), with a last line linking the run.
  - `jira.transition {issue | issue_from, to, site?}`: moves the issue through the transition named `to` (its id or name, matched without regard to case); `transition_unavailable` when the issue's current status offers none.
  - The engine resolves `issue_from: "request"` (the run's request, trimmed, must be one issue key) and `body_from` (a run artifact, as `github.openPR` does, 6.7). The tool never sees either.
- **Which site.** `site` takes a cloud id or a site's host. When it is left out, the workspace's only enabled site is used; with several enabled sites the call fails `site_required`.
- **Project scoping on every call.** Each tool checks `jira_project_allowed` for the issue's project. `getIssue`, `listTransitions` and both writes check the key's prefix before calling Jira, then the project Jira returns, since an issue keeps its old key after a move.
- **Fixed errors**, never Jira's words or a token: `jira_not_connected`, `needs_attention`, `site_required`, `site_unknown`, `project_not_allowed`, `issue_not_found`, `invalid_jql`, `transition_unavailable`, `rate_limited` (one retry honouring `Retry-After` up to 10 s first), `jira_unavailable`.
- **Engine and validation.** `JIRA_READ_TOOLS` and `JIRA_WRITE_TOOLS` in `PLATFORM_TOOLS`. New issue codes `jira_write_not_tool_node` and `jira_write_without_gate`. `jira_write_not_shown` fires when the gate before a `jira.comment` with `body_from` does not show that artifact (`artifact`), so no comment is approved unseen. `issue_from` must be `"request"` and the workflow must declare `input`.
- **A run needs a connected Jira.** `POST /runs` answers `422 jira_not_connected` when the spec names a `jira.*` tool and the workspace's connection is not `connected`. The worker checks again when it opens the tools. A run that starts with Jira connected gets the server even with no repo.
- **Client and fake.** `JiraPlatform` gains `get_issue`, `search`, `transitions`, `add_comment` and `transition`, on the REST API v3 through `https://api.atlassian.com/ex/jira/{cloud_id}` (`/rest/api/3/issue/{key}`, `/rest/api/3/search/jql`, `/rest/api/3/issue/{key}/comment`, `/rest/api/3/issue/{key}/transitions`), through `agentic_jira.call` (refresh and one `401` retry from 7.1). `FakeAtlassian` gets seeded issues, comments and a small workflow, so tests and the e2e stack stay off the network.
- **ADF ⇄ Markdown** in `agentic_jira.adf`. Reading handles paragraphs, headings, lists, code, quotes, links, mentions (display name), tables (as Markdown tables), and media as `[attachment]`. Writing handles paragraphs, headings, lists, code blocks, inline code, bold, italic and links; anything else is sent as plain text. No HTML in either direction.
- **Template `jira-issue-answer`** ("Answer a Jira issue"). It requires Claude, GitHub and Jira and has a required `input` (the issue key). An analyst reads the issue and the repo and writes `comment.md`, a gate shows it, then `jira.comment` posts it. This is the "Done when" flow, and the first template whose card shows the Jira chip.
- **UI pulled from 7.5.** `Requirement` gains `jira`. The gallery's "Requires" line shows a Jira chip, connected or missing. The New run sheet's "Before you start" checklist shows Jira, with Connect going through 7.1's authorize (`return_to` back to the sheet). `workflowRequires` adds Jira when a node names a `jira.*` tool, so a stored workflow's run sheet asks for it too.
- Specs and docs: tech-stack ("Jira tools (API contract)", Tool layer, validation codes, decisions-log rows), `lessons.md` if the real run teaches one, `docs/integrations/connecting-platforms.md` (what the tools do, the dedicated account), `docs/security/security-model.md`, CHANGELOG.

### Out of scope

- **Webhook trigger** (moving an issue starts a run): 7.3. `issue_from: "request"` is the seam it uses, since the webhook will set the run's request to the issue key.
- **Field mapping** (acceptance criteria, custom fields): 7.4. `getIssue` returns only the standard fields above.
- **The SDD template and its Jira update:** 7.5.
- **A plan mode for every write tool** (the planned write shown at the gate, checked against the result): 13.8. Here the gate shows the comment's artifact and the transition's `to` in its title and prompt.
- **Creating issues, editing fields, assigning, attachments, worklogs:** not asked for by the milestone. Each would be a new gated write.
- **Agents calling a write tool directly.** Not chosen in the interview (principle 3).
- **A Playwright spec for the Jira flow** (not chosen in the interview). The existing e2e suite, with its axe and layout checks on the gallery and the run sheet, must stay green.
- **The roadmap's "Next up" line** (its own PR).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where writes happen | `jira.comment` and `jira.transition` only as tool nodes after a gate; agents get read tools only | Chosen in the interview. Principle 3 names Jira status changes, and agent-written text reaching a tracker unseen is what 13.8 exists to stop. It is also the shape the engine already enforces for `github.openPR`. |
| Read tools | `getIssue`, `search`, `listTransitions` | Chosen in the interview ("gated writes + more reads"), so 7.5 needs no new read tool and a gated transition can be named correctly. |
| Tool names | camelCase under `jira.`, as `github.openPR` | One naming style across platform tools. |
| Search scoping | Wrap as `project in (…) AND (jql)`, no `ORDER BY` inside (`order_by` instead), then drop off-list results | Atlassian's grant covers a whole site. Wrapping keeps a user's `OR` from escaping the allowlist, and the post-filter is a second check that does not trust the first. |
| Issue checks | Key prefix before the call, the returned project after it | Fails fast with no Jira call for an obvious miss. A moved issue keeps its old key, so the returned project is the one that counts. |
| How a write knows its issue and text | Fixed `issue` or `issue_from: "request"`; fixed `body` or `body_from` (an artifact), resolved by the engine | Tool node args are fixed today. `body_from` already exists for pull requests (6.7). The request is the seam 7.3's trigger fills. No expression language in args yet. |
| What the gate shows | `jira_write_not_shown`: the gate before a comment with `body_from` must show that artifact | No comment is approved blind; a full plan mode for every write stays in 13.8. |
| Site choice | `site` optional; the only enabled site by default, `site_required` otherwise | Most workspaces have one site. Guessing among several would act on the wrong tracker. |
| Rich text | Our own small ADF ⇄ Markdown converter in `agentic_jira.adf`, no library | Agents read and write Markdown. The ADF subset we need is small, and a library would bring HTML rendering we must not use (principle 5, CLAUDE.md rule 11). |
| Comment footer | A last line linking the run ("Posted by agentic-dev run <short id>") | Jira shows the consenting account as the author (7.1). The footer tells readers a run wrote it and where to look (principle 6). It resolves 7.1's open question on authorship together with the card's existing sentence. |
| Template | Ship `jira-issue-answer` now | The UI pulled from 7.5 needs a template that requires Jira, and the "Done when" needs a real flow to run. 7.5 adds the SDD template beside it. |
| UI pulled forward | Jira chip and checklist item from 7.5 | Chosen in the interview. A template that needs Jira should say so before the run fails at `POST /runs`. |

## Open questions

- Whether `read:jira-user` (asked for in 7.1) is needed: `getIssue` shows display names, which `read:jira-work` returns. It is confirmed in the real run and dropped in 7.4 if nothing needs it.
- Whether `jira-issue-answer` stays a template once SDD (7.5) ships, or becomes an example in the docs. Decided in 7.5.
