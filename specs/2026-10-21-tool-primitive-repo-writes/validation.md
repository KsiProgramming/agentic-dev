# Validation: `tool` primitive + `repo` write tools + worktree/branch per writer

## Done when (from roadmap)
> An agent commits a file to `agent/<run>/<node>`

To check this, run `write-file.json` with `POST /runs` on a repo. It streams `tool_call`/`tool_result` events for `repo.write_file` and then `repo.commit`, and the commit's result names `agent/<run-id>/writer`. In the run's sandbox, `git log agent/<run-id>/writer` shows that commit by `agentic-dev agent`, on top of the clone's `HEAD`, touching only the written file. The `tool` node that follows (`repo.list_files`) runs with no model and completes. The agent is the unscripted fake runtime, so no API key is needed.

The proof is in two places:
- `packages/worker/tests/test_worker.py::test_done_when_an_agent_commits_a_file_to_its_branch`, on a real Docker sandbox. It passes locally. `test_a_writer_commits_a_file_to_its_branch` is the same check on the fake sandbox.
- The CI compose job's "Repo write demo (phase 1.6)" step.

## Automated checks
- [x] Sandbox (`packages/sandbox/tests/test_worktree.py`), with fake and `integration` (Docker) variants:
  - `add_worktree` creates `<worktrees_dir>/<node>` on `agent/<run>/<node>` from `HEAD`, from a shallow clone, under the agent identity.
  - Calling it twice for one node is a no-op.
  - Two nodes get separate worktrees.
  - The base checkout is still unwritable by the sandbox user.
  - `put_file` lands in `.incoming/` only, is owned by uid 1000, and enforces its cap.
  - `exec(cwd=)` outside the checkout or a worktree is refused.
- [x] `packages/tools/tests/test_write_file.py`:
  - A file is created and then overwritten, with its parent directories, byte for byte.
  - `..`, absolute, drive and symlink escapes are refused. The symlink cases run in Docker on any host and on the fake sandbox off Windows.
  - `.git/...` paths are refused.
  - Content over the cap is refused.
  - A directory target, and a file in the way, are refused.
  - Errors name no host path, and refused writes leave nothing staged.
  - The tool is absent from a non-writable server.
- [x] `packages/tools/tests/test_commit.py`:
  - A commit lands on the node's branch with the platform identity.
  - The result has the short SHA, the branch and the paths.
  - Nothing to commit is an error, and so is a blank message.
  - The message `$(touch pwned)` is stored literally and creates no file.
  - A planted `.git/hooks/pre-commit` and a repo-level `core.hooksPath` do not run. A manual control showed the planted hook does run under a plain `git commit`.
- [x] `RepoTools` routing tests (`packages/tools/tests/test_repo_tools.py`):
  - A writer reads its own write, and a reader doesn't see it.
  - A non-writer calling `repo.write_file` gets an error output.
  - Each writer gets exactly one worktree.
  - Every MCP client closes before the sandbox, on success, failure and cancellation.
- [x] Runtime: `ClaudeRuntime` (stubbed client) and `FakeRuntime` pass `node_id` to `ToolExecutor.call`. The unscripted fake runtime uses the write tools' `examples` (the worker tests rely on it).
- [x] Engine:
  - The spec tests accept `tool-node.json` and `write-file.json` and reject `tool-node-missing-tool.json`.
  - The exported JSON Schema has `tool`.
  - The compiled `tool` node emits `node_started → tool_call → tool_result → node_completed`, and its output feeds the next node.
  - An `is_error` result gives `node_failed` and `run_failed`, with `stopped_at` set.
  - Resume does not re-run a completed `tool` node.
- [x] API: `POST /runs` with a `tool` node naming `repo.*` and no `repo` returns `422`.
- [x] Worker: the Done-when Docker test passes, and the 1.1 and 1.2 Done-when tests still pass on the new image.
- [x] `ruff`, `pyright` strict, and the full `pytest` suite are green: 532 passed, 9 skipped locally on Windows. The skips are the host-symlink cases and the Docker-only permission test on the fake backend.

## Manual / demo checks
These run in the CI compose job. They were not run locally, because the local compose stack is in use on the Claude runtime and rebuilding it would retag its shared images. The Docker worker tests cover the same path from the worker down.
- [ ] `docker compose up --build` builds `agentic-dev/sandbox:dev`.
- [ ] `python scripts/sandbox_demo.py --spec packages/engine/tests/fixtures/specs/valid/write-file.json --expect "wrote NOTES.md (" --expect "/writer: NOTES.md"` streams:
  1. `run_started`, then `node_started` for `writer`.
  2. `tool_call`/`tool_result` for `repo.read_file`.
  3. `tool_call` for `repo.write_file`, then `wrote NOTES.md (<n> bytes)`.
  4. `tool_call` for `repo.commit`, then `<sha> on agent/<run-id>/writer: NOTES.md`.
  5. `node_completed`.
  6. `node_started` for `list`, then a `tool_result` from `repo.list_files`, then `node_completed`.
  7. `run_completed`.
- [ ] The 1.1 and 1.2 demos (`sandbox_demo.py` with no `--spec`, and with `ask-repo.json`) still behave as before.
- [x] No labelled container or volume is left after a sandbox closes. Checked with a probe on the Docker backend; CI checks `docker ps` after each demo.
- [x] The sandbox container still has `NetworkMode=none`, `ReadonlyRootfs=true`, `CapDrop=[ALL]`, `no-new-privileges` and user `1000:1000` on `agentic-dev/sandbox:dev` (`docker inspect` of a live sandbox).

## Merge criteria
- [ ] All checks above pass in CI, including the image build and the compose job with the 1.1, 1.2 and 1.6 demo steps.
- [x] The README is updated: tool node, write tools, limits, branch naming, writer grants, the sandbox image and layout, and no push yet. The CHANGELOG is updated.
- [ ] `specs/roadmap.md` 1.6 is marked done by the implementing PR (`complete-phase`).
- [x] No push and no network from the sandbox. No secrets, file contents beyond existing event logging, or host paths in logs or tool errors.
