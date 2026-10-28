# Shared run context: named artifacts in the run workspace

Roadmap phase: 4.3
Branch: plan/4.3-shared-run-artifacts

## Context
Today a node receives only the previous node's output (`RunState.last_text`). The audit flow of Milestone 4 needs more than that:
- A scanner's `findings.json` must reach a triage agent several steps later, past a gate or an unrelated step.
- Tool outputs must feed specialist agents (4.4).
- Reduces must merge findings (4.5).
- The audit template must end with `findings.json` and a report (4.7).

Named artifacts give a run a small shared context. A node writes its output under a name, and any later node reads it by that name, whatever ran in between.

It depends on these phases, all done:
- 4.1: parallel. A branch can write an artifact, and two branches cannot write the same one.
- 4.2: typed ports. An artifact keeps its writer's `output_schema`, so a reader's `input_schema` is checked against it, statically (`port_mismatch`) and at runtime.
- 3.4: the one validator behind `/validate` and `POST /runs`. The new issue codes go there.
- 11.5, 11.6 and 11.8: the Inbox review, the console's step panel and its "files a step wrote" cards, which the artifact cards follow.

It unblocks 4.4 (tool outputs as files in the sandbox), 4.5 (reduce strategies over `findings.json`), 4.7 (the audit's `findings.json` plus its report) and 6.x (an orchestrator's shared plan).

Principles that apply:
- **One spec, many views (1):** reads and writes are spec fields. The validator, canvas and Architect see the data flow without running anything.
- **Open, but safe by construction (2):** a read with no earlier writer, or two writers that race, is refused at validation. Size caps are enforced at runtime.
- **Repo, Jira and web content are data (5):** artifact content is agent output. It is stored and shown as data (`JsonView`, sanitised Markdown or plain text) and never run. In the sandbox it is a read-only file.
- **Transparency (6):** every write is an `artifact_written` event. Every version is kept (append-only), viewable and downloadable.
- **Nothing is lost (9):** artifacts live in Postgres, not in the sandbox. A worker restart (AC-8) or a discarded sandbox loses none.
- **Tools live in the platform (4):** agents reach artifacts through an `artifacts` MCP server, like `repo` and `github`, so Claude and Copilot behave alike.

Tech-stack choices that apply:
- **Engine and storage:** Pydantic v2 spec fields exported to JSON Schema. The engine never touches a database: a store protocol is implemented by `agentic_store`, as `EventSink` is. Postgres and Alembic for storage.
- **Tools:** MCP servers built with the official SDK, granted per node, with `strict_tool` adding the `description` intent.
- **Sandbox:** the checkout is root-owned and read-only for agents, and the sandbox has no network.
- **Console:** the run console rules (step panel tabs, cards, `JsonView`, "Show full output", no JSON in table cells), the Inbox and dock review, and the display components (`RelativeTime`, `IdChip`).

## Scope
### In scope
- **Spec**
  - `agent`, `tool` and `reduce` nodes take an optional `writes: <name>`, which writes the node's output under that name.
  - `agent` and `tool` nodes take an optional `reads: [<name>, …]`, with at most 8 unique names.
  - **Names:** `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, ending in `.json`, `.md` or `.txt`. The extension gives the media type: `application/json`, `text/markdown` or `text/plain`.
- **Validation**, in the one validator, with two new codes:
  - `artifact_unknown`: a read of a name that no node writes earlier in run order. A writer in a sibling branch of the same parallel is not earlier. A writer later in the same loop body is not earlier, since the first iteration would not have it.
  - `artifact_conflict`: a `writes` inside a map body (its id repeats per item), or two branches of one parallel writing the same name. Writers in sequence may overwrite each other, which is how a loop refines an artifact.
  - `port_mismatch` extends to artifacts: a node with exactly one read and an `input_schema` is checked against the `output_schema` of the last writer of that name before it.
  - A bad name is a `schema` issue (pattern).
- **Engine (runtime)**
  - **Write:**
    - After a node completes, and after its output port check, its output is written under its `writes` name as a new version (1, 2, … per name).
    - The content is the typed `data` as pretty JSON when present, else the text. A `.json` artifact must parse as JSON, using `ports.parse_output`, so one fenced block is allowed.
    - An artifact is at most 1 MB, and all versions of a run's artifacts add up to at most 8 MB.
    - A failure fails the node with a one-line error: ``cannot write 'findings.json': output of 'scan' is not JSON: …`` or ``…: 1.4 MB is over the 1 MB limit``.
  - **Read:**
    - Before a node with `reads` starts, its input is built from the latest version of each name: the content itself for one read, and a JSON object by name for several (JSON artifacts parsed, others as strings). The previous output is not passed.
    - A name not written by then (for example its branch failed under an `any` join) logs `node_started`, then `node_failed` (``artifact 'findings.json' was not written``). No agent starts. The input port check runs on the built input.
  - **CEL:** `until`, `over` and later `router` read `artifacts` (name → parsed JSON or text).
  - **State:** `RunState.artifacts` holds refs only (`{name, version, node_id, media_type, size, sha256}`), merged by name. Content stays in the store. Checkpoints from before 4.3 have none, which counts as empty.
  - **Store protocol:** `agentic_engine.artifacts.ArtifactStore` (`put`, `get(name, version=None)`, `latest()` and `total_bytes()` per run). `InMemoryArtifactStore` serves tests and runs without a database.
- **Events**
  - `artifact_written` `{name, version, media_type, size, sha256}` on the writer node (with `item` or `branch` tags). It is emitted before the node's `node_completed`.
  - The reader's `node_started` carries `reads: [{name, version}]`.
- **Storage:** an append-only `run_artifacts` table (`run_id`, `name`, `version`, `node_id`, `media_type`, `size`, `sha256`, `content`, `output_schema`, `created_at`, with primary key `(run_id, name, version)`) in Alembic `0023_run_artifacts`. `agentic_store.PostgresArtifactStore` implements the protocol.
- **Agent tools:** a new `artifacts` MCP server (`agentic_tools/artifacts`), read-only, granted per node like any tool:
  - `artifacts.list`: the latest version of each artifact so far, with `name`, `version`, `media_type`, `size`, `node_id` and `path` when mirrored.
  - `artifacts.read(name, version?)`: the content, capped at 256 KB with `truncated`.
  - Every run gets these tools, including runs without a repo. They are added to `PLATFORM_TOOLS` as `ARTIFACT_TOOLS` and are allowed in loops, maps and parallels.
- **Sandbox mirror:**
  - The sandbox gains a read-only `artifacts_dir` (`/workspace/artifacts`, root-owned like the checkout) and `put_artifact(name, data)`.
  - The worker wraps the store so that each write is also copied there. An attempt that opens a fresh sandbox (a worker restart) copies the latest version of each artifact in first.
  - A run without a sandbox only skips the mirror. Tool nodes of 4.4 read `/workspace/artifacts/<name>`.
- **Gate review:**
  - `gate_waiting` and `GET /runs/{id}/gate` add `run_artifacts`: the latest version of each artifact at the pause (`name`, `version`, `node_id`, `media_type`, `size`). The name avoids confusion with the existing `artifact`, which is the gate's input.
  - The Inbox review and the console's review sheet list them as read-only cards.
- **API**
  - `GET /runs/{id}/artifacts`: the latest version of each artifact, with `versions` (its count) and `created_at`.
  - `GET /runs/{id}/artifacts/{name}?version=`: the content and its metadata. `404` for an unknown run, name or version; `422` for a name that is not an artifact's.
  - `GET /runs/{id}/artifacts/{name}/download`: an attachment with the artifact's media type and `nosniff`.
  - The OpenAPI spec and `web/src/api/schema.d.ts` are re-exported.
- **Web**
  - **Output tab:** the selected step's Output tab lists "Artifacts written" as cards (name in mono, kind, size, version), like the written-files cards.
  - **Input tab:** lists "Artifacts read" with the version read.
  - **Artifact sheet:** a card opens a sheet showing JSON in `JsonView`, Markdown sanitised (no raw HTML or images) and text as plain text, capped with "Show full", plus a Download action.
  - **Artifacts view:** a third left-pane view beside Steps and Graph (`?view=artifacts`) lists the run's artifacts (name, writer step as a link, versions, size, `RelativeTime`).
  - It has empty, loading and error states. Gate review cards in the Inbox and the review sheet open the same sheet.
- **Fixtures:**
  - Valid: `artifacts-findings.json` (a typed scanner writes `findings.json`, an unrelated step runs, then a gate, then a reporter that reads `findings.json` and writes `report.md`).
  - Invalid: `artifact-read-before-write`, `artifact-write-in-map`, `artifact-branch-conflict`, `artifact-bad-name`.
- **Docs:**
  - tech-stack: a "Run artifacts (API contract)" section, the codes, the tool layer, the sandbox, gate review, run console, and decisions log rows.
  - A README section and a CHANGELOG entry.

### Out of scope
- **Writes from agent tools** (`artifacts.write`). Writes stay declarative so the validator can see them. This may return with the orchestrator (6.x).
- **Binary artifacts and other extensions** (images, SARIF, archives). These can come with 4.4 if a scanner needs them.
- **Templates that use artifacts.** The audit template is 4.7, and the docs template is unchanged.
- **Reduce strategies over artifacts** (dedupe and vote on findings), which is 4.5.
- **Editing an artifact at a gate.** Gate edits stay on repo files (3.6).
- **Artifacts kept after the run for reuse by other runs, or a retention policy.** They live as long as the run's row.
- **Workspace policy limits for artifact sizes.** These are platform constants for now. A policy field can come with 10.x hardening.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Core read/write, console, agent read tools, gate display and sandbox mirror | User choice. It covers "Done when" and what 4.4 and 4.7 need right after, so they can build on it without reopening it. |
| Where artifacts live | Engine-owned: refs in checkpointed `RunState`, content in an append-only `run_artifacts` table behind an `ArtifactStore` protocol, mirrored into the sandbox as a read-only copy | User choice. Durable across worker restarts and sandbox loss (principle 9, AC-8). The engine stays database-free. The event log stays small (metadata only). |
| How nodes use them | Declarative `writes`/`reads` in the spec, with read-only tools for on-demand reads | Validation can prove read-after-write and find races before a run spends tokens (principle 2). Agents still look things up as they need them. |
| A reader's input | The artifact replaces the previous output (one read: its content; several: an object by name) | One clear input that typed ports check, and no hidden concatenation. A node that also needs the previous output reads it as an artifact. |
| Overwrites | Sequential writers create new versions, and every version is kept. Parallel and map races are refused statically. | Loops refine an artifact. Nothing is lost, and audit shows each version. |
| Formats | `.json`, `.md` and `.txt`, UTF-8 text, 1 MB each and 8 MB per run | Enough for findings and reports. Text renders safely in the console. Caps keep Postgres and the sandbox bounded. |
| Field name at the gate | `run_artifacts` | `artifact` already means the gate's input in the gate contract. |
| Build order | Contract first: spec and validation → engine → store and API → tools and mirror → gate → console → docs | User choice, as in 4.2. The backend is testable before any UI. |

## Open questions
- **The roadmap's "Next up" line still names Milestone 11, which is done.** As noted in 4.2, it should move to Milestone 4 in its own small PR with a changelog entry.
