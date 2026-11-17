# Plan: Spec from a Markdown file

Contract first, then engine, API and web, then a real run. Each group leaves the repo working.

## 1. Contract in the specs
- [ ] `specs/tech-stack.md`: `WorkflowInput.kind: "spec_file"`; the `POST /runs` `spec_file` body, its caps and its `422` codes; `runs.spec_file`; the seed artifact `spec-input.md`; `RunContext.spec` (`<spec-file>`, `SPEC_FILE_CAP`); `{spec}` for `repo.commitArtifacts`; a "Build from a spec file template" section beside "Build from a Jira issue template" (and drop "a spec from a Markdown file (7.7)" from its "Not yet")
- [ ] Decisions-log rows: two templates from one builder; file as a seed run artifact; repo path read at `POST /runs`
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`

## 2. Spec model and validation (engine)
- [ ] `agentic_engine/spec/models.py`: `kind` gains `"spec_file"`; JSON Schema export and the web's generated types updated
- [ ] Validation: `spec-input.md` counts as written before the first step when `input.kind == "spec_file"`; a node writing it is `artifact_conflict`; `{spec}` accepted in `repo.commitArtifacts.dir` (a run with no spec file fails the step at run time, as `{issue}` does)
- [ ] Engine tests for the three rules; `schemas/fixtures` updated if the port-check fixtures need it

## 3. Engine: seed artifact, run context, `{spec}`
- [ ] The run's start writes `spec-input.md` v1 through the `ArtifactStore` by the writer `$input` and logs `artifact_written` (`source: "input"`) before the first step; a resume or a rerun from a step finds it and writes nothing
- [ ] `agentic_engine/agent.py`: `SpecFile` model (`source`, `name`, `path`, `text`) and `RunContext.spec`, with `_spec_text()` (tags, data wording, cap and the "full file is `spec-input.md`" note); the Claude adapter needs no change beyond `RunContext.text()`
- [ ] `agentic_engine/commit.py`: `{spec}` slug (first `# ` heading, else file stem; reuse the `{issue}` slug helper)
- [ ] Tests: run-context text with and without a cut; slug cases; seed artifact written once across a resume

## 4. Template `sdd-spec-file`
- [ ] `agentic_engine/templates/sdd.py`: `build_sdd_spec(params, source="jira" | "file")`; the file flavour drops the `jira` tools, `clarify`, `jira_update` and `move`, adds `reads: ["spec-input.md"]` to `spec_writer`, uses `specs/{spec}`, the file wording in `spec_writer`, `approve_spec`, `synthesizer` and `publish`; `move_to` refused for it
- [ ] Register the template (`sdd-spec-file`, "Build from a spec file", requires Claude + GitHub) and add its default spec as `packages/engine/tests/fixtures/specs/valid/sdd-spec-file.json`
- [ ] **What agents receive** test (lessons rule 1): on the fake runtime, the spec writer's request holds `<spec-file>` and reads `spec-input.md`; the planner, tasker, lead and reviewer each have the spec in their run context; no agent has a `jira` tool; every agent's instructions start with what its input is
- [ ] `sdd` unchanged: its existing tests stay green with no edits

## 5. API and worker
- [ ] Alembic migration: `runs.spec_file` (JSONB, nullable)
- [ ] `POST /runs`: parse `spec_file`, check the caps, read a repo path through the GitHub App contents API at the ref (fake GitHub in tests), store `runs.spec_file` (with the text) in the run's transaction, for the worker to give the engine; the refusals of requirements.md
- [ ] Rerun (`POST /runs/{id}/rerun` and from a step): copy the stored artifact and `runs.spec_file`, never read the repo again
- [ ] Worker: build `RunContext.spec` from the stored artifact; `GET /runs/{id}` returns `spec_file` (without the content) so the console can show the source
- [ ] **AC test** `test_done_when_a_spec_file_run_opens_a_pr` (worker, fakes): an uploaded spec, no Jira connection in the workspace, fake GitHub; approve both gates through the API; the run opens a PR whose diff holds `specs/<slug>/spec.md`, `plan.md` and `tasks.md`

## 6. Web
- [ ] New run sheet (`web/src/runs/new-run/`): for `kind: "spec_file"`, "Upload" / "From the repo" choice, a `.md` file picker with the size check, a mono path field; server refusals on the field
- [ ] Console step Input → Run context: the spec file as sanitised Markdown with its source (`TruncatedPath` or file name), next to the existing issue and review briefs
- [ ] Start screen: the new template's card (requirements: Claude, GitHub)
- [ ] `pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`; look at 375 and 1440 px, light and dark

## 7. Docs and a real run
- [ ] `docs/`: the "Build from a spec file" template (what it does, upload vs repo path, what lands in the PR)
- [ ] Real run with Claude (`AGENTIC_RUNTIME=claude`) on a small real repo with an uploaded spec and no Jira connection; read each step's Input and Activity in the console; fix what it shows and add a `lessons.md` entry if a mistake reaches the run
