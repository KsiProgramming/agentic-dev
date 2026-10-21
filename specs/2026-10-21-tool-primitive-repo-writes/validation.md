# Validation: `tool` primitive + `repo` write tools + worktree/branch per writer

## Done when (from roadmap)
> An agent commits a file to `agent/<run>/<node>`

To check this, run `write-file.json` with `POST /runs` on a repo. It streams `tool_call`/`tool_result` events for `repo.write_file` and then `repo.commit`, and the commit's result names `agent/<run-id>/writer`. In the run's sandbox, `git log agent/<run-id>/writer` shows that commit by `agentic-dev agent`, on top of the clone's `HEAD`, touching only the written file. The `tool` node that follows (`repo.list_files`) runs with no model and completes. The agent is the unscripted fake runtime, so no API key is needed.

The proof is in two places:
- `packages/worker/tests/test_worker.py::test_done_when_an_agent_commits_a_file_to_its_branch`, on a real Docker sandbox.
- The CI compose job's "Repo write demo (phase 1.6)" step.

## Automated checks
- [ ] Sandbox (`packages/sandbox/tests`), with fake and `integration` (Docker) variants:
  - `add_worktree` creates `/workspace/worktrees/<node>` on `agent/<run>/<node>` from `HEAD`, from a shallow clone.
  - Calling it twice for one node is a no-op.
  - Two nodes get separate worktrees.
  - The base checkout is still unwritable by the sandbox user.
  - `put_file` lands in `.incoming/` only.
  - `exec(cwd=)` outside `/workspace` is refused.
- [ ] `packages/tools/tests/test_write_file.py`:
  - A file is created and then overwritten, with its parent directories.
  - `..`, absolute, drive/UNC and symlink escapes are refused (symlinks on Linux in CI).
  - `.git/...` paths are refused.
  - Content over 1 MiB is refused.
  - A directory target is refused.
  - Errors name no host path.
  - The tool is absent from a non-writable server.
- [ ] `packages/tools/tests/test_commit.py`:
  - A commit lands on the node's branch with the platform identity.
  - The result has the short SHA, the branch and the paths.
  - Nothing to commit is an error.
  - The message `$(touch /tmp/pwned)` is stored literally and creates no file.
  - A planted `.git/hooks/pre-commit` and a repo-level `core.hooksPath` do not run.
- [ ] `RepoTools` routing tests:
  - A writer reads its own write, and a reader doesn't see it.
  - A non-writer calling `repo.write_file` gets an error output.
  - Each writer gets exactly one worktree.
  - Every MCP client closes before the sandbox, on success, failure and cancellation.
- [ ] Runtime: `ClaudeRuntime` (stubbed client) and `FakeRuntime` pass `node_id` to `ToolExecutor.call`. The unscripted fake runtime uses the write tools' `examples`.
- [ ] Engine:
  - The spec tests accept `tool-node.json` and `write-file.json` and reject `tool-node-missing-tool.json`.
  - The exported JSON Schema has `tool`.
  - The compiled `tool` node emits `node_started → tool_call → tool_result → node_completed`, and its output feeds the next node.
  - An `is_error` result gives `node_failed` and `run_failed`, with `stopped_at` set.
  - Resume does not re-run a completed `tool` node.
- [ ] API: `POST /runs` with a `tool` node naming `repo.*` and no `repo` returns `422`.
- [ ] Worker: the Done-when Docker test passes; the 1.2 Done-when test (`ask-repo.json`) still passes on the new image.
- [ ] `ruff`, `pyright` strict, and the full `pytest` suite are green (the same skips as before only).

## Manual / demo checks
- [ ] `docker compose up --build` builds `agentic-sandbox:local`.
- [ ] `python scripts/sandbox_demo.py --spec packages/engine/tests/fixtures/specs/valid/write-file.json` streams:
  1. `run_started`, then `node_started` for `writer`.
  2. `tool_call`/`tool_result` for `repo.read_file`.
  3. `tool_call` for `repo.write_file`, then `wrote NOTES.md (<n> bytes)`.
  4. `tool_call` for `repo.commit`, then `<sha> on agent/<run-id>/writer: NOTES.md`.
  5. `node_completed`.
  6. `node_started` for `list`, then a `tool_result` from `repo.list_files`, then `node_completed`.
  7. `run_completed`.
- [ ] The 1.1 and 1.2 demos (`sandbox_demo.py` with no `--spec`, and with `ask-repo.json`) still behave as before.
- [ ] `docker ps -a --filter label=agentic.run_id` and `docker volume ls --filter label=agentic.run_id` are empty after the run.
- [ ] The sandbox container still has `NetworkMode=none`, `ReadonlyRootfs=true` and `CapDrop=[ALL]` (`docker inspect` during a run).

## Merge criteria
- [ ] All checks above pass in CI, including the image build and the compose job with the 1.1, 1.2 and 1.6 demo steps.
- [ ] The README is updated: write tools, limits, branch naming, writer grants, the sandbox image, and no push yet.
- [ ] `specs/roadmap.md` 1.6 is marked done by the implementing PR (`complete-phase`).
- [ ] No push and no network from the sandbox. No secrets, file contents beyond existing event logging, or host paths in logs or tool errors.
