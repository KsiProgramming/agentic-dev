# Plan: Shared run context: named artifacts in the run workspace

## 1. Spec fields and validation
- [ ] `spec/models.py`:
  - `ArtifactName` (pattern and extension).
  - `writes` on `AgentNode`, `ToolNode` and `ReduceNode`, and `reads` (max 8, unique) on `AgentNode` and `ToolNode`, with descriptions.
  - `ARTIFACT_TOOLS = {"artifacts.list", "artifacts.read"}`, in `PLATFORM_TOOLS` and allowed in loops, maps and parallels.
  - `artifact_unknown` and `artifact_conflict` in `IssueCode`.
- [ ] `artifact_issues(root)`, wired into `structure_issues`:
  - Walk in run order, tracking the names written so far.
  - Parallel branches each see what was written before the parallel. After it, they see the union of what the branches wrote.
  - A loop body is checked once with what was written before it.
  - A map body may not write.
- [ ] `port_edges`: a node with one read gets the last earlier writer of that name as its producer, so `port_mismatch` and the runtime `from_node_id` follow artifacts.
- [ ] Fixtures:
  - Valid: `valid/artifacts-findings.json`.
  - Invalid: `artifact-read-before-write`, `artifact-write-in-map`, `artifact-branch-conflict`, `artifact-bad-name`.
- [ ] Unit tests in `test_validate.py` and `test_spec.py`: run-order cases (sequence, gate, loop, parallel union, sibling branch), each code's `path` and `node_id`, and port_mismatch through an artifact.
- [ ] Re-export `schemas/workflow-spec.v0.json`.

## 2. Engine: store, write, read
- [ ] New `agentic_engine/artifacts.py`:
  - `ArtifactRef`, `Artifact` (ref + content + `output_schema`), `ArtifactStore` protocol (`put`, `get`, `latest`) and `InMemoryArtifactStore`.
  - `MAX_ARTIFACT_BYTES` (1 MB) and `MAX_RUN_ARTIFACT_BYTES` (8 MB).
  - `media_type(name)`.
  - `artifact_content(node, result) -> str | ArtifactError`.
  - `reader_input(refs, store) -> str`.
- [ ] `graph/state.py`: `artifacts: Annotated[dict[str, ArtifactRef], merge_results-like]` in `RunState` and `RunUpdate`, `initial_state`, and `.get(..., {})` for old checkpoints.
- [ ] `graph/compile.py`:
  - `compile_workflow(..., artifacts: ArtifactStore | None)`, kept on `_Limits`.
  - `_run_step` takes the state's refs:
    - Before the input port check, build the reader's input and fail on a missing name.
    - After the output check, write and emit `artifact_written` (before `NODE_END`).
    - Return the new ref.
  - `_update` adds `artifacts`. Map items and parallel branches carry refs up in their updates.
  - The reduce writes through the same path.
  - `node_started` carries `reads`.
- [ ] `expr.py`: an `artifacts` variable in `CONDITION_VARIABLES` and `LIST_VARIABLES`. `_loop_check` and `_map_items` load the latest contents.
- [ ] `events.py`: `ARTIFACT_WRITTEN`, documented. Update the module docstrings (compile, state).
- [ ] `graph/run.py`: `run_workflow` and `resume_workflow` take the store and default to in-memory.
- [ ] `packages/engine/tests/test_artifacts_runtime.py` (fake runtime):
  - Write then read across an unrelated step and a gate resume.
  - Versioning in a loop, and CEL `artifacts[...]` in `until`.
  - Several reads as an object.
  - A missing read after an `any` join fails the reader with no agent start.
  - `.json` output that is not JSON fails the writer.
  - The size caps.
  - Typed writer to typed reader, passing and failing.
  - A reduce writes.
  - An untyped, artifact-free spec is unchanged (existing tests stay green).

## 3. Store and API
- [ ] `agentic_store`:
  - The `RunArtifact` model and Alembic `0023_run_artifacts`.
  - `PostgresArtifactStore(sessions, run_id)` (`put` takes the next version in one statement; `get`; `latest`).
  - `list_run_artifacts` and `get_run_artifact` for the API.
  - Tests in `test_artifacts.py`, plus the migration test.
- [ ] Worker `_workflow`: pass a `PostgresArtifactStore` for the run.
- [ ] API `runs/routes.py` and `models.py`:
  - `GET /runs/{id}/artifacts`, `GET /runs/{id}/artifacts/{name}` (`?version=`) and `.../download` (attachment, media type, `X-Content-Type-Options: nosniff`).
  - Tests in `test_artifacts_api.py`: list, versions, `404`s, download headers.
- [ ] Re-export OpenAPI and `web/src/api/schema.d.ts`. Add `artifact_written` to `web/src/runs/types.ts`.

## 4. Agent tools and sandbox mirror
- [ ] `agentic_tools/artifacts/server.py`:
  - `build_artifacts_server(store, mirror_dir)` with `artifacts.list` and `artifacts.read` through `strict_tool`. The content is returned as data, capped at 256 KB with `truncated`.
  - `open_artifact_tools(...)` returns an `McpToolExecutor`.
  - Tests in `test_artifacts_server.py`.
  - Keep the `PLATFORM_TOOLS` sync test green.
- [ ] `agentic_sandbox`:
  - `artifacts_dir` and `put_artifact(name, data)` on the `Sandbox` protocol, the Docker backend (root-owned `/workspace/artifacts`, `0644` files, name re-checked against `ArtifactName`) and `FakeSandbox`.
  - Tests in `test_docker_sandbox.py` and `test_fake_sandbox.py`: the sandbox user can read but not write.
- [ ] Worker:
  - `MirroredArtifactStore(store, sandbox)`: put, then copy. A mirror failure is logged and does not fail the node; the store is the source of truth.
  - On a fresh (non-reused) sandbox, copy `latest()` in before the run continues.
  - Add the artifacts executor to `RunTools` for every run, with or without a repo.
  - Tests in `test_worker.py`: tools granted, mirror after write, re-mirror after a restart.

## 5. Gate review
- [ ] `gate.py` and runner: `gate_waiting` adds `run_artifacts` from the state's refs.
- [ ] `agentic_store.pending_gate` and `GET /runs/{id}/gate` return it.
- [ ] Engine and API tests: a gate after a writer lists the artifact, and an empty list without one.

## 6. Run console and Inbox
- [ ] `web/src/runs/artifacts/`:
  - `use-run-artifacts.ts` (TanStack Query, invalidated on `artifact_written`).
  - `artifact-card.tsx` (name in mono, kind from the media type, size, `v2`).
  - `artifact-sheet.tsx`: side sheet from 768 px, bottom sheet below. JSON in `JsonView`, Markdown through the existing sanitised renderer, text as plain text, capped with "Show full", and a Download link to the API.
  - `artifacts-view.tsx`: the run's list (name, writer step link to `?step=`, versions, size, `RelativeTime`), using `LoadingState`, `EmptyState` ("No artifacts yet." / "This run wrote no artifacts.") and `ErrorState`.
- [ ] Console:
  - `?view=artifacts` beside Steps and Graph.
  - Output tab: "Artifacts written" cards, from the step's `artifact_written` events.
  - Input tab: "Artifacts read", from `node_started.reads`, plus the `reads` list in the node spec.
  - `step-entries` carries both.
- [ ] Inbox review and review sheet: a "Run artifacts" section of cards from `run_artifacts`, opening the same sheet.
- [ ] Vitest:
  - Card and sheet per media type (no HTML rendered from Markdown).
  - The artifacts view's three states.
  - The step view's written and read sections.
  - The Inbox review section.
- [ ] Playwright:
  - An `ARTIFACTS` helper in `e2e/runs.ts`, and a test in `console.spec.ts` that runs the fixture on the fake runtime with a JSON input.
  - The scanner's Output shows `findings.json v1`, the sheet shows it in `JsonView`, and the reporter's Input shows it as read.
  - The Artifacts view lists `findings.json` and `report.md`, and Download returns the file.
  - The gate in the Inbox lists `findings.json`.
  - Add the console's Artifacts view and the sheet to `a11y.spec.ts` and `layout.spec.ts` at 375 and 1440 px.

## 7. Docs and specs
- [ ] `specs/tech-stack.md`:
  - "Run artifacts (API contract)": fields, names, run-order rule, write and read semantics, caps, events, table, endpoints.
  - The two codes in Workflow validation.
  - `artifacts` in Tool layer.
  - `artifacts_dir` in Sandbox.
  - `run_artifacts` in Gate review.
  - The Artifacts view, step sections and sheet in Run console, plus the Inbox section.
  - CEL `artifacts` in Expressions.
  - Decisions log rows (storage, declarative writes, reader input, formats).
- [ ] README "Run artifacts" section with the example spec. `CHANGELOG.md` entry under `## [Unreleased]`.
- [ ] Roadmap: the status is left to CI (open-pr). The "Next up" line goes in its own PR (see Open questions).
