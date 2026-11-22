# Validation: Later steps read the writers' work

## Done when (from roadmap)

> A reviewer after a test writer and a refactoring writer, in a sequence with no orchestrator, reads both diffs and reviews them, in a real run read step by step in the console

## Automated checks

Run everything locally before pushing, because CI minutes are limited.

### Sandbox

Run the new test files by name; never run `packages/sandbox/tests` as a whole.

- [ ] `branch_diff`:
  - It lists added, modified, deleted and renamed files, each with its added and removed lines, followed by the unified diff against the base.
  - A binary file is named, not shown.
  - `path` limits the result to one file.
  - A result over 256 KB is cut, with `truncated` set.
  - A missing branch raises `BranchNotFoundError`.
- [ ] Reads at a ref:
  - `show_file` returns the line ranges asked for and cuts a long file.
  - `list_tree` respects the depth.
  - `grep_tree` returns its hits by path and line and skips binary files.
  - A path outside the repo is refused.

### Tools (`agentic_tools`)

- [ ] `repo.diff` and the reads with `node` return the writer's committed work. Uncommitted changes in its worktree do not appear.
- [ ] Each refusal returns its fixed text: an unknown node, a writer that has not run yet, a writer with no commits, and a task key.
- [ ] A writer reads an earlier writer with `node`. Without `node`, it still reads and writes its own branch.
- [ ] `node` set to an orchestrator reads its integration branch. The 6.9 reroute still sends a reviewer's plain reads to that branch.
- [ ] After a restore from saved bundles (12.2), where no worktree exists, `repo.diff` still works.

### Engine

- [ ] **What agents receive** (`test_writers_work.py`, on the fixture):
  - `test_writer` is told about no writer.
  - `refactorer` is told about `test_writer`.
  - `reviewer` has `repo.diff` and is told about both writers.
  - `node_started.writers` matches each case, and the reviewer's tool calls go out as `reviewer`.
- [ ] A run resumed after `refactorer` gives `reviewer` the same writers and the same context.
- [ ] `no_writer_before`:
  - It is raised on a node granted `repo.diff` when no writer runs before it.
  - It is not raised when a writer follows the reader in the same loop body.
  - The manifests and the JSON Schema list `repo.diff`.
- [ ] The typed-port checks are unchanged: the existing port tests and fixtures pass.

### Web

- [ ] The Input tab lists the writers from `node_started.writers`.
- [ ] Activity draws a `repo.diff` result as a diff, with its `+` and `−` markers.
- [ ] An error result shows as plain text.
- [ ] The one-liners name the writer.

### Commands

- [ ] Backend: `uv run ruff check`, `uv run ruff format --check` and `uv run pyright`. Then pytest for the engine, the tools, the worker, the targeted sandbox files and the API; run the API tests from `packages/api`.
- [ ] Web, in `web/`: `pnpm lint && pnpm typecheck && pnpm test`, then `pnpm test:e2e`, which runs the axe and layout checks. `pnpm lint` must reject a raw colour in the diff component.

## Manual / demo checks

- [ ] **Real run on Copilot.**
  - Store `review-two-writers.json` as a workflow.
  - Start it by hand on a real repo that has a function worth refactoring.
  - Use the Copilot provider (8.3) and the starter's personal connection.
- [ ] **Read it step by step in the console:**
  - `test_writer` commits its tests.
  - The `refactorer`'s Activity shows that it read those tests with `node: "test_writer"` before it committed.
  - The `reviewer`'s Input lists both writers.
  - The `reviewer`'s Activity shows a `repo.diff` call for each writer, drawn as a diff.
  - The reviewer's verdict talks about changes from both writers.
- [ ] Nothing blocks the new tools: no Copilot permission prompt stops `repo.diff` or the `node` argument.
- [ ] The Copilot token appears in no event or log line.
- [ ] Look at the console at 375 and 1440 px, in light and dark. The Input list and the diff fit with no horizontal page scroll, and a wide diff scrolls in its own box.

## Merge criteria

- [ ] All the checks above pass locally, then in CI.
- [ ] `tech-stack.md`, `design-language.md` (the diff tokens) and the `CHANGELOG.md` entry under `[Unreleased]` are in the same PR, with decisions-log rows.
- [ ] The PR description says the real run was on Copilot and stands in for the Claude run in lessons rule 1, and says what each step read.
- [ ] If the real run found something the tests missed, `lessons.md` has an entry for it in this PR.
- [ ] No token or secret appears in any event or log.
