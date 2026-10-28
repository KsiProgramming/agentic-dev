# "Generate docs" template

Roadmap phase: 1.11
Branch: plan/1.11-generate-docs-template

## Context
Phases 1.1–1.10 built every piece a docs run needs: a sandbox with a clone (1.1), read tools (1.2), durable runs (1.3), encrypted keys (1.4), the GitHub App and repo list (1.5), write tools and a branch per writer (1.6), gates (1.7), `github.openPR` (1.8), loops (1.9) and `map`/`reduce` (1.10). This phase puts them together into the first real template and the first user-facing flow. It proves **AC-1: connect GitHub, pick a repo, docs run opens a PR**.

It also closes two open questions from earlier phases:
- 1.10: no tool returns a module list as structured data, so `map` had nothing real to fan out over.
- 1.5: no live run against a real GitHub App has been done yet.

It unblocks 1.12 (docs run on a newly created repo), 3.7 (the audit template reuses the same template mechanism) and 4.8 (the full start screen).

Principles that apply:
- **Humans approve irreversible actions (3):** the template always has a gate before `github.openPR`. The template cannot be configured without it.
- **Repo content is data (5):** module names and file contents reach agents as input, never as instructions. The user's extra instructions are the only user-written text in agent instructions, and they are clearly delimited.
- **Open, but safe by construction (2):** the template is an ordinary `WorkflowSpec`. It goes through the same validation as any other spec, and `map` keeps its caps (8 concurrent, 40 items).
- **One spec, many views (1):** a template only produces a spec. The run stores and executes that spec, so the monitor and the event log work unchanged.

Tech-stack choices that apply: FastAPI + Pydantic v2 (template parameters exported as JSON Schema), the generated OpenAPI web client used by the Next.js pages, `pytest` with the fake runtime, sandbox and GitHub.

## Scope
### In scope
- **`repo.list_modules` tool** (read only, in the `repo` MCP server):
  - Returns `structuredContent` `{"modules": [{"path", "kind"}]}` plus a readable text list.
  - A module is a directory with a known manifest (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `pom.xml`, `*.csproj`), found up to depth 3. If none is found, it falls back to the top-level source directories (excluding hidden dirs, `node_modules`, `vendor`, `dist`, `build`, `docs`).
  - Optional `include` glob list to filter modules. The result is capped at 40 (the `map` item cap), with `truncated: true` when cut.
  - The tool node's `data` carries the structured result, so `map.over` can use `results.list_modules.data.modules`.
- **Docs template** (`agentic_engine.templates.docs`):
  - `DocsParams` (Pydantic): `output_dir` (relative path, default `docs`, no `..` or absolute paths), `include` (optional glob list), `extra_instructions` (optional, at most 2,000 characters).
  - `build_docs_spec(params) -> WorkflowSpec` builds this flow:
    1. `list_modules`: tool node `repo.list_modules` with `include`.
    2. `document`: `map` over `results.list_modules.data.modules`, `max_concurrency: 4`. The body is a read-only agent (`repo.list_files`, `repo.read_file`, `repo.search`) that writes one Markdown page for its module.
    3. `combine`: `reduce` with strategy `concat`, joining the pages with a separator line.
    4. `writer`: an agent with `repo.list_files`, `repo.write_file` and `repo.commit` that writes `<output_dir>/<module>.md` and `<output_dir>/README.md` (overview and index) and commits once.
    5. `approve`: gate "Open a pull request with the generated docs?".
    6. `publish`: `github.openPR` from `writer`, with a fixed title and a body naming the output folder and the module filter.
  - A template registry: `id`, `name`, `description`, parameters JSON Schema, and the builder.
- **API:**
  - `GET /templates` lists templates (id, name, description, `parameters` JSON Schema).
  - `POST /runs` accepts either `workflow` or `template: {id, parameters}` (exactly one). The API builds and validates the spec, then stores it on the run as today. Unknown template or bad parameters return 422 with the field path.
  - The OpenAPI spec and the web client are re-exported.
- **Web:**
  - Home page: a repo picker from `GET /workspaces/{id}/repos` (asked only once `GET …/connections` shows GitHub, so an unconnected page logs no error response) and a "Generate docs" card with the three options (output folder, module filter, extra instructions). Starting it opens `/runs/{id}`. If GitHub is not connected, the card links to `/settings`.
  - Monitor page: when the latest event is a gate waiting for approval, show **Approve** and **Reject** buttons that call `POST /runs/{id}/approvals`. When `openPR` completes, show the PR link from its event.
  - The monitor's `EventSource` listens for the gate, loop, map and `pr_opened` events too. Before this phase it dropped them, because `EventSource` only delivers event names it has listeners for.
  - The sample-run form stays, below the templates.
- **Docs:** README "Generate docs" section (how to run AC-1 locally) and a CHANGELOG entry.

### Out of scope
- Creating a new repo for the docs run: 1.12.
- Cost per node and in the monitor: 2.1.
- Approval cards with editable artifacts: 2.6. This phase only adds approve/reject buttons.
- A full start screen with provider picker and blank canvas: 4.8.
- Writers inside `map` (one branch per module): needs the integration branch from 5.3. One writer after the reduce commits all pages.
- Saved user templates and template versioning: 5.7 / 9.9. Templates here are code.
- Regenerating or updating existing docs incrementally: later, if needed.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where templates live | Python builders in the engine, listed by the API | User choice. The spec is validated server-side and the web never ships a spec. Parameters export to JSON Schema like the rest of the contracts. |
| Template parameters | `output_dir`, `include`, `extra_instructions` | User choice ("configurable docs options"). Each is validated: a relative path, globs, a length cap. |
| Module discovery | Deterministic `repo.list_modules` tool with structured output | User choice. It resolves the 1.10 open question with no model cost, and the result is testable. |
| Who writes files | One writer agent after the reduce | `map` bodies cannot write (1.10). One writer means one branch and one PR. |
| Map concurrency | 4 | Half the alive-agents cap (8), leaving room for the reduce and writer agents. |
| Reduce strategy | `concat`; the writer writes the overview and index | Changed during implementation (was `agent`). An agent only sees the previous node's text, so an `agent` reduce would have to re-emit every page for the writer: double the output tokens and a risk of truncation. The writer already needs judgement to write the files, so it writes the index too. |
| PR body | Fixed at build time: output folder and module filter | Changed during implementation. Tool node args are fixed when the spec is built, and the module list is only known at runtime. |
| Gate | Always present and not a parameter | Mission principle 3: a PR is an irreversible action. |
| Run request shape | `POST /runs` takes `workflow` or `template` (exactly one) | Keeps one endpoint and one stored spec per run. The monitor and worker do not change. |
| Approval in the UI | Minimal approve/reject buttons on the monitor | User choice. AC-1 must work in the browser, and 2.6 later replaces the buttons with cards. |
| Order of work | Engine flow → API → UI | User choice. Each step is testable on fakes before the next one uses it. |

## Open questions
- **Large modules:** a module page agent may hit context limits on big modules. The agent only reads files it chooses, so this phase relies on its judgement. Revisit with cost limits in 2.2.
- **Docs folder already exists:** the writer overwrites the pages it generates and leaves other files alone. Check that this is acceptable during the manual demo.
- **Monorepos with more than 40 modules:** the list is truncated and the PR body says so. A better split (by group) is left for later.
