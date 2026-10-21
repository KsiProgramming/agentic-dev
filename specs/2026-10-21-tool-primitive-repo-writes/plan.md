# Plan: `tool` primitive + `repo` write tools + worktree/branch per writer

Order: tools first. Build the image, then the sandbox worktree API, then the write tools, then routing by node, then the `tool` node, and finally the worker wiring and the demo. After each group the project builds, and the 1.1/1.2 demos still pass.

## 1. Sandbox image with git
- [x] `packages/sandbox/Dockerfile`: `FROM alpine:3.20` (pinned digest) plus `apk add --no-cache git`, with the same non-root sandbox user and UID as today. It also reads no system or user git config (`GIT_CONFIG_NOSYSTEM`, `GIT_CONFIG_GLOBAL=/dev/null`). A `.dockerignore` keeps the build context to the Dockerfile.
- [x] `docker-compose.yml`: add a build-only `sandbox-image` service (`command: ["true"]`, no network) that the worker depends on (`service_completed_successfully`). Set the worker's `SANDBOX_IMAGE` to it. The tag is `agentic-dev/sandbox:dev`, not `agentic-sandbox:local`, to match compose's `agentic-dev/python:dev`.
- [x] `agentic_sandbox.docker_backend.DEFAULT_IMAGE` and the worker settings default become `agentic-dev/sandbox:dev`. A missing local image fails with the `docker build` command that makes it. `.env.example` is updated.
- [x] CI (`.github/workflows/ci.yml`): build the image before `pytest`. The compose job builds it through the `sandbox-image` service. Docker tests also build it if it is missing (`agentic_sandbox.testing.ensure_sandbox_image`).
- [x] Check: the existing Docker tool suites pass on the new image.

## 2. Clone layout and worktrees in the sandbox
- [x] `docker_backend._workspace_tar` (was `_tar`): the base checkout stays root-owned and read only. `repo/.git` becomes owned by the sandbox user and writable by it. Add an empty `worktrees/` and `.incoming/` owned by the sandbox user.
- [x] `Sandbox` protocol:
  - `exec(argv, *, timeout_s, cwd=None)`. `cwd` must be the checkout or a directory under `worktrees_dir`, else `ValueError`.
  - `worktrees_dir`, a new property.
  - `put_file(data) -> str` (no `name`: the file gets a random one) writes into `.incoming/` and returns the in-sandbox path. It is capped at `MAX_PUT_FILE_BYTES` (1 MiB).
  - Implement both for the Docker backend (`put_archive` of a one-file tar, owned by the sandbox UID) and for `FakeSandbox`.
- [x] `agentic_sandbox.worktree`:
  - `add_worktree(sandbox, run_id, node_id) -> Worktree` runs `git worktree add -b agent/<run>/<node> /workspace/worktrees/<node> HEAD`. It passes `GIT_SAFETY` (hooks, fsmonitor and signing off), `safe.directory` for the root-owned checkout, and `AGENT_IDENTITY`. It is idempotent per node.
  - `Worktree` is a `Sandbox` view whose `workdir` is the worktree. `Worktree.of(...)` gives its path and branch without creating it.
- [x] `FakeSandboxManager` mirrors the layout in its temp dir, using host git with no system or user config.
- [x] Tests (`packages/sandbox/tests/test_worktree.py`, fake and `integration`):
  - a worktree on the right branch, from `HEAD`, made under the agent identity;
  - re-adding it reuses it;
  - a commit works in the shallow clone;
  - two nodes get separate worktrees;
  - the base checkout is still unwritable (Docker);
  - `cwd` is confined;
  - `put_file` stages files and enforces its cap.

  The open question was answered without the fallback (see requirements).

## 3. Write tools on the `repo` server
- [x] `build_repo_server(sandbox, *, writable=False, limits=...)`. There is no `root` parameter: a writer's server is built on its `Worktree`, so the read tools see the worktree unchanged. The write tools are registered only when `writable` is true.
- [x] `write_file(path, content)`:
  - Check `repo_relative`, and refuse `.` and any `.git` path component (any case).
  - Cap the content at 1 MiB (UTF-8 bytes).
  - `put_file`, then a script that confines the deepest existing parent and then the parent itself to the root, runs `mkdir -p`, refuses a directory or a symlink as the target, and runs `mv`. The staged file is removed when the write is refused.
  - Return `wrote <path> (<n> bytes)`.
- [x] `commit(message)`:
  - Run `git add -A`.
  - Fail on an empty diff ("nothing to commit"), and refuse a blank message.
  - Run `git -c user.name=… -c user.email=agent@agentic-dev.invalid <GIT_SAFETY> commit --no-verify -m "$1"`. The message is passed as a positional argument, never interpolated.
  - Return `<short-sha> on agent/<run>/<node>: <paths>`, listing at most 50 paths.
- [x] Add `examples` to both schemas: `{"path": "NOTES.md", "content": "…"}` and `{"message": "Add NOTES.md"}`.
- [x] Tests in `packages/tools/tests/test_write_file.py` and `test_commit.py`, with fake and `integration` variants:
  - Writes and overwrites work, parent directories are created, and bytes are exact (CRLF kept).
  - `..`, absolute, drive and symlink escapes are refused. The symlinks are made inside the worktree, so the Docker variant runs on any host; the fake one is skipped on Windows.
  - `.git/config`, `src/.GIT/...` and `.git` are refused.
  - The size cap is enforced.
  - A commit lands on the branch with the platform identity as author and committer.
  - An empty commit and a blank message are errors.
  - A message of `$(touch pwned)` (and backticks, `;`) is stored literally.
  - A planted `pre-commit`/`commit-msg`/`post-commit` hook does not run, and neither does a repo `core.hooksPath`. A manual control run showed the hook does run without the tool's options.
  - Errors name no host path, and a read-only server has no write tools.

## 4. Route tool calls by node
- [x] `agentic_runtime.tools.ToolExecutor.call(name, arguments, *, node_id: str | None = None)`. Update `ClaudeRuntime`, `FakeRuntime` and the test doubles to pass `request.node_id` (`ScriptedToolExecutor.node_ids` records them).
- [x] `agentic_tools.repo.RepoTools`, opened through `open_repo_tools(sandbox, *, run_id, writers)` (`agentic_tools/repo/routing.py`):
  - It keeps a base `McpToolExecutor`.
  - Each writer's writable server and MCP client are opened up front, bound to its `Worktree.of(...)`. On the writer's first call, `add_worktree` runs. Clients are opened up front because anyio requires a client to close in the task that opened it, and tool calls can come from other tasks.
  - Its `definitions()` are the base set plus the write tools when the run has writers.
  - A write tool called by a non-writer returns an "unknown tool" error output.
  - A worktree that cannot be made becomes an error output.
  - It closes every MCP client before the sandbox.
- [x] `McpToolExecutor` ignores `node_id`.
- [x] Tests (`packages/tools/tests/test_repo_tools.py`):
  - a writer reads its own write;
  - a reader never sees a writer's file;
  - a non-writer can't write;
  - one worktree per writer;
  - writers need a run id;
  - clean close after failure or cancellation;
  - Claude (mocked) writes and commits through the router.

## 5. `tool` primitive
- [x] `agentic_engine.spec.models`: `ToolNode(type="tool", id, tool: NonEmptyStr, args: dict[str, JsonValue] = {})`, added to `Node`. `iter_nodes` needed no change (a tool node is a leaf). Update the docstring and the exported JSON Schema.
- [x] `agentic_engine.spec`: add `node_tools(node)` and `writer_node_ids(root, write_tools)`.
- [x] Compiler:
  - `step_nodes` replaces `agent_nodes`.
  - A `tool` node runs `agentic_engine.tool.run_tool_node`, which calls the run's `ToolExecutor` with `node_id`.
  - It emits `node_started`, `tool_call`, `tool_result`, then `node_completed` or `node_failed` (on `is_error` or an exception).
  - It writes `last_text` and `results[id]` as an `AgentNodeResult` with `usage=None`.
- [x] Thread the executor into `run_workflow`/`resume_workflow` (`tools=`, the same object the runtime factory gets). A run with a `tool` node and no tools fails the node with a clear error.
- [x] API: the `repo.*`-needs-a-repo check walks every node through `node_tools`. The OpenAPI spec and the generated web client are regenerated.
- [x] Fixtures: `valid/tool-node.json`; `invalid/tool-node-missing-tool.json`.
- [x] Tests (`packages/engine/tests/test_tool_node.py`, `test_spec.py`, `test_compile.py`, API `test_runs.py`):
  - the spec accepts and rejects;
  - the schema has `ToolNode`;
  - writers are derived;
  - run order and events on the fake runtime with a stub executor, and the output becomes the next input;
  - an error result fails the run at that node;
  - a raising tool fails the node without details;
  - resume skips a completed tool node;
  - `422` without a repo.

## 6. Worker wiring, demo and docs
- [x] Worker: compute `writers` from the run's spec and pass the `run_id` and `writers` to `open_repo_tools`. Hand the same executor to both the runtime factory and the engine.
- [x] Fixture `valid/write-file.json`:
  - The agent `writer` has `repo.read_file`, `repo.write_file` and `repo.commit`.
  - It is followed by the tool node `list` (`repo.list_files`).
- [x] `test_worker.py::test_done_when_an_agent_commits_a_file_to_its_branch` (Docker), and the same test on the fake sandbox:
  - Run `write-file.json` with the unscripted fake runtime.
  - Before teardown, inspect the sandbox (`RecordingSandboxes(inspect=BranchLog())`). It shows one branch, `agent/<run>/writer`, with one commit by the platform identity touching only NOTES.md.
  - The test waits for the sandbox to close before stopping the worker.
- [x] CI compose job: add a "Repo write demo (phase 1.6)" step that runs `scripts/sandbox_demo.py --spec …/write-file.json` and expects `wrote NOTES.md (` and `/writer: NOTES.md` in the tool results.
- [x] README: document the tool node, the write tools, the limits, the branch naming, the writer grant rule, the sandbox image and layout, and that there is no push yet. The CHANGELOG is updated.
- [x] Update the "phase 1.6" mentions in docstrings and comments (`docker_backend`, worker module, `repo/server.py`, the Docker sandbox test).

### Found and fixed along the way
- Every git command that writes a ref (here `git worktree add`) stalled about 5 s per ref write. With no identity configured, git looks up the host's full name in DNS, which times out with no network. `add_worktree` now passes `AGENT_IDENTITY`, and a test checks the reflog identity.
- A Docker sandbox's removal could be skipped when its run was cancelled during teardown, for example by a stopping worker: `to_thread` work that had not started yet was dropped. The removal is now shielded.
