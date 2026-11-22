# Plan: Later steps read the writers' work

The work goes bottom-up, and each layer is test-first. After each group the project still builds and its tests pass.

## 1. Sandbox: read a branch without a worktree

- [ ] `agentic_sandbox` (beside `review.py`): add `branch_diff(sandbox, branch, *, path=None, max_bytes)`. Against the checkout's `HEAD`, it returns each file's status (`--name-status -M`), its added and removed lines (`--numstat`, with binary files marked) and the unified diff (`--no-ext-diff -M`), cut at `max_bytes` with `truncated` set. A missing branch raises `BranchNotFoundError`.
- [ ] Add the reads at a ref: `show_file`, which returns a line range and the total line count with the binary check, and `list_tree` and `grep_tree`, which take a depth or a pattern, a path and the result caps. They keep the checkout scripts' confinement (`repo_relative`), binary checks and caps, and every git call runs with `GIT_SAFETY` and `safe.directory`.
- [ ] Write tests on a real git repo. Run the new test files one by one: never run `packages/sandbox/tests` as a whole, because its sweep removes the dev stack's sandboxes.

## 2. Repo tools: `repo.diff` and `node`

- [ ] Add `ReadableWriters` to `agentic_runtime.tools`, next to `ToolExecutor`, so that both the engine and the tools can import it. `set(writers)` takes the writers that completed, each with its id and kind; `branch(node_id)` returns the branch, or raises a fixed refusal: not a writer of the run, has not run before this step, or has no commits.
- [ ] In `agentic_tools.repo.server`, add the `diff` tool (`node`, `path?`) and give `read_file`, `list_files` and `search` an optional `node`. With `node`, these read through the step-1 helpers at the writer's ref, using the same output format and notes as today. Then update the `strict_tool` examples and the module docstring.
- [ ] Pass the run's `ReadableWriters` through `build_repo_server` and `open_repo_tools`, so the read-only server and every writer's server resolve `node` the same way. A writer that names itself goes to its own worktree, as it does without `node`.
- [ ] Write the routing tests. Refusals return their fixed text. `node` set to an orchestrator reads its integration branch. A writer reads an earlier writer and still writes its own branch. Reads through the 6.9 reroute behave as before. Uncommitted worktree changes are not shown.

## 3. Engine: who ran before, and what each step is told

- [ ] Write the test first, following lessons rule 1, in `packages/engine/tests/test_writers_work.py`. It runs `review-two-writers.json` on the fake runtime, with scripted tool calls, and asserts what each agent receives:
  - `test_writer` is told about no writer.
  - `refactorer` is told about `test_writer`.
  - `reviewer` has `repo.diff` among its tools, and its context names both writers.
  - `node_started.writers` matches each case, and the reviewer's `repo.diff` calls reach the tools as `reviewer`.
- [ ] In `spec/models.py`, add `repo.diff` to `READ_TOOLS`. Add the `no_writer_before` issue code with its check, in which a loop body's writers count for the whole body. Then regenerate the JSON Schema, the manifests and `schemas/`.
- [ ] In `graph/compile.py`, add `writers_before(state)`. It returns the writer nodes that completed, followed by the orchestrators whose integration branch merged a task, in run order. The engine sets it on `ReadableWriters` before every step: top-level steps, map items, parallel branches, orchestrator tasks and hub turns. It also adds `writers` to `node_started`.
- [ ] In `agent.py`, add `work_before_text(...)`. It writes the "# Work before you" section after `RunContext.text()` for agents that have repo read tools, and names what their reads see without `node`: the checkout, their own branch, or the team's merged work.
- [ ] Add a resume test: a run cut off after `refactorer` resumes, and `reviewer` gets the same writers and the same context.
- [ ] In the worker, create one `ReadableWriters` per attempt and hand it to `open_repo_tools` and to the engine.

## 4. Web: the Input tab and a diff in Activity

- [ ] Before writing any code, add the tokens `--diff-added`, `--diff-added-muted`, `--diff-removed` and `--diff-removed-muted` to `design-language.md` and to `tech-stack.md` → "UI design system". Then add them to `web/src/app/globals.css`, in light and dark.
- [ ] In `@/runs/timeline`, read `node_started.writers`. In `step-input.tsx`, add a "Work before this step" list: the node id in the mono font and its kind, "writer" or "team's merged work".
- [ ] Add a `UnifiedDiff` component in `@/runs/console` for `repo.diff` results in `tool-calls.tsx`. It parses the tool's text into a file list and hunks, puts file headers on `surface-subtle`, keeps the `+` and `−` gutter, scrolls in its own box and is capped with "Show full", reusing `long-output`. An error result falls back to plain text.
- [ ] Add one-liners in `tool-describe.ts`: "Read the changes of test_writer", and "Read `src/a.py` as test_writer left it".
- [ ] Write tests for the Input list, the diff parsing and rendering, and the one-liners.

## 5. Fixture, real run, specs

- [ ] Add `packages/engine/tests/fixtures/specs/valid/review-two-writers.json`. Every agent's instructions say what its input is and what its tools read (the lessons' rules for workflows). The reviewer answers a typed `verdict` and `feedback`.
- [ ] Do the real run on Copilot: store the fixture as a workflow, start it by hand on a real repo with the Copilot provider, and read every step in Activity (see `validation.md`). If the run finds something the tests missed, add a `lessons.md` entry in this PR.
- [ ] In `tech-stack.md`, document `repo.diff` and `node` in the Tool layer, the "# Work before you" section under Agent runtime → "What an agent is told", `node_started.writers`, and decisions-log rows for git-ref reads, `ReadableWriters` and the diff tokens.
- [ ] Add a `CHANGELOG.md` entry under `## [Unreleased]`.
