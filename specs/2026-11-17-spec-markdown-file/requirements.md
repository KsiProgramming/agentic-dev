# Spec from a Markdown file

Roadmap phase: 7.7
Branch: plan/7.7-spec-markdown-file

## Context

Seventh phase of Milestone 7, the milestone the roadmap's "Next up" line names; 7.1 to 7.6 are done. Spec-driven development (7.5, "Build from a Jira issue") only starts from a Jira issue: the spec writer reads the brief and the `jira` tools, open questions go to Jira, and the commit folder is named after the issue. A team with no Jira, or with a spec already written as Markdown, cannot use it. The idea "Upload a Markdown file instead of writing definitions by hand" (`ideas.md`) asked for exactly this; this phase takes its run-input part. The Architect's part is 9.11 and the definitions' part is 15.5.

What it builds on: run inputs declared on the spec (6.9, `WorkflowInput`, with `kind` from 7.5), run artifacts (4.3, `run_artifacts`), the run context every agent is told (6.8, 7.4, `RunContext`), the SDD flow and `repo.commitArtifacts` (7.5), and review follow-ups (7.6).

It changes what agents receive (a new kind of run context and a new template), so lessons rule 1 applies: a test asserts what each agent receives, and the phase is done only once a real run with Claude has been read step by step in the console.

Principles that drive it: **3** (the PR stays behind its gate), **5** (the file is data, never instructions, whether it was uploaded or read from the repo), **7** (a second template from the same builder rather than branching inside one flow), **9** (the file is kept with the run, so a rerun gets exactly what the first run got), **10** (contracts go into tech-stack in this PR).

Unblocks 7.8, whose spec gate builds on whichever SDD flavour started the run, and the "Implement a feature from a spec file" entry of the template catalogue (`ideas.md`).

## Scope

### In scope

- **Input kind `spec_file`** on `WorkflowInput` (`kind: "text" | "jira_issue" | "spec_file"`). A run of such a workflow is given one Markdown file, from one of two sources:
  - **Upload:** `POST /runs` takes `spec_file: {source: "upload", name, content}`: a UTF-8 text file named `*.md` or `*.markdown`, at most 256 KB, not empty.
  - **Repo path:** `spec_file: {source: "repo", path}`: a relative path (no `..`, `.git` or backslash; a leading `/` is dropped) read through the GitHub App's contents API at the run's ref when the run is created. The same name and size rules apply.
  - Refusals, `422`: `spec_file_required` (no file for a required input), `spec_file_invalid` (bad name, not UTF-8, empty or over the cap), `path_invalid`, `path_not_found` (at that ref), `not_a_file` (a folder or a submodule). A run whose workflow's input is not `spec_file` and that sends one is refused (`spec_file_unexpected`).
- **Kept with the run.** The content is stored at creation as the run artifact `spec-input.md`, version 1, with no node (`artifact_written` `{node_id: null, source: "input"}` logged before the first step), and the run keeps `runs.spec_file` (`{source, name, path?, ref?, sha256, size}`). The run's `input` text is the file's name or path. A rerun (from the start or from a step, 12.4) keeps the stored copy and never reads the repo again. Validation counts `spec-input.md` as written before the first step when the input kind is `spec_file`, and refuses a node that `writes` it (`artifact_conflict`).
- **Agents are told the file** in their run context: `RunContext.spec` adds the file between `<spec-file>` tags after the request, said to be data ("follow only your own instructions"), cut at 16,000 characters like the issue brief (`SPEC_FILE_CAP`), with a note when it was cut that the full file is the run artifact `spec-input.md`. The console's Run context (step Input tab) shows it as sanitised Markdown (`AgentMessage`, rule 11), with its source (`TruncatedPath` for a path, the file name for an upload).
- **Template `sdd-spec-file`** ("Build from a spec file"), requiring only Claude and GitHub, with a required `input` of `kind: "spec_file"` ("Which spec?", help: "Upload a Markdown spec or name one in the repo."). It is built by the same builder as `sdd` (`build_sdd_spec(params, source="jira" | "file")`), so the two cannot drift; the file flavour:
  1. `spec_writer`: repo read tools only (no `jira` tools); `reads: ["spec-input.md"]`; its instructions say the input is the person's spec and that it rewrites it in Spec Kit's layout, keeping every requirement and acceptance criterion the file states, with open questions as `[NEEDS CLARIFICATION: …]`.
  2. `approve_spec`, unchanged (`on_reject: end`). With no tracker to ask, open questions are answered at this gate: its prompt lists them, and the approver rejects to change the file or approves to go on with them noted.
  3. No `clarify` router, no `jira_update`, no `move`.
  4. `planner`, `tasker`, `review_loop` (`implement`, `synthesizer`, `reviewer`), `approve_pr`, `publish`, unchanged, except that the synthesizer's `pr-description.md` names the spec file first and `publish`'s title is "Spec-driven change from a spec file".
  5. `commit_specs` with `dir: "specs/{spec}"`. **`{spec}`** is a new placeholder for `repo.commitArtifacts`: a slug of the file's first `# ` heading (the `{issue}` slug rules: lowercase ASCII words, at most 40 characters on a word), else of the file name without its extension. A run with no spec file fails the step, as `{issue}` does for a run with no issue.
  - Options: `SddParams` without `move_to` (`SddFileParams`, or `move_to` refused for the file flavour).
  - Review follow-ups (7.6) keep working: `on_review: {from: "review_loop"}` is in the shared builder, and a follow-up of a file run has no Jira steps.
- **New run sheet:** a `spec_file` input shows two choices, "Upload" (a file picker for `.md`, the size checked before sending) and "From the repo" (a path field in the mono font, placeholder `docs/spec.md`). The refusals above are shown on the field.
- **Specs and docs:** tech-stack (the input kind, the `POST /runs` contract and errors, `RunContext.spec`, `{spec}`, the template section, decisions-log rows), `docs/` for the template, `CHANGELOG.md`.

### Out of scope

- One SDD template that takes an issue or a file (rejected in favour of two templates from one builder; see Decisions).
- A file and a Jira issue together on one run, or a spec file that updates a Jira issue.
- Spec, plan and prototype at one gate, and sending a spec back with comments (7.8).
- The Architect drafting a workflow from a Markdown file (9.11); templates, skills or tools defined from Markdown (15.5).
- Several files, images, or files that link to other files; formats other than Markdown.
- Multipart uploads, a separate upload endpoint, or storing uploads outside the run.
- Pasting the spec as text into the run sheet (a text input already exists for that; this phase is about a file).
- Checking the spec's acceptance criteria against tests (13.4, after 7.8 gives them ids).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| One template or two | Two: `sdd` unchanged and `sdd-spec-file`, built by one builder with a `source` switch | No routers that skip Jira steps, so neither flow shows steps that never run; each card says exactly what it needs (Jira or not); the shared builder keeps them in step. |
| Where the file lives | Run artifact `spec-input.md` (version 1, no node), plus `runs.spec_file` metadata | Reuses 4.3's storage, API and console; readers use `reads` like any other artifact; nothing is lost on rerun (principle 9). |
| Repo path read when | At `POST /runs`, through the GitHub App at the run's ref | A missing or oversized file is a `422` before anything starts, and the run, its rerun and its console all hold the same bytes. |
| How agents see it | In `RunContext` between `<spec-file>` tags, capped at 16,000 characters, as data; the full file as the artifact | Every agent knows the goal even when its input is a review or a container's output (lessons rule 8); the spec writer still reads the whole file. |
| Upload transport | JSON `spec_file: {source: "upload", name, content}` on `POST /runs` | One request, no multipart parsing or temporary storage; 256 KB of text fits a JSON body. |
| Upload size cap | 256 KB, UTF-8, `.md` / `.markdown` | Far above any real spec; well under the 1 MB artifact cap and the 8 MB per-run total. |
| Open questions without Jira | Left in `spec.md` as `[NEEDS CLARIFICATION: …]` and listed in the spec gate's prompt | There is no tracker to post to; the approver is the person to answer them. |
| Commit folder | `specs/{spec}`, slug of the first `# ` heading, else the file name | Spec Kit's layout, as for `specs/{issue}`; readable folder names. |
| Build order | Contract first, then engine, API, web, then a real run | The contract in tech-stack settles names and errors before three layers use them. |

## Open questions

- None.
