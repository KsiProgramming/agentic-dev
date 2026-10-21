# Plan: `tool` primitive + `repo` write tools + worktree/branch per writer

Order: tools first. Build the image, then the sandbox worktree API, then the write tools, then routing by node, then the `tool` node, and finally the worker wiring and the demo. After each group the project builds, and the 1.1/1.2 demos still pass.

## 1. Sandbox image with git
- [ ] `packages/sandbox/Dockerfile`: `FROM alpine:3.20` (pinned digest) plus `apk add --no-cache git`, with the same non-root sandbox user and UID as today.
- [ ] `docker-compose.yml`: add a build-only `sandbox-image` service (`image: agentic-sandbox:local`, `command: ["true"]`) that the worker depends on (`service_completed_successfully`). Set the worker's `SANDBOX_IMAGE` to it.
- [ ] `agentic_sandbox.docker_backend.DEFAULT_IMAGE` and the worker settings default become `agentic-sandbox:local`. `.env.example` is updated.
- [ ] CI (`.github/workflows/ci.yml`): build the image before the `integration` tests and the compose job.
- [ ] Check: the existing Docker tool suites pass on the new image.

## 2. Clone layout and worktrees in the sandbox
- [ ] `docker_backend._tar`: the base checkout stays root-owned and read only. `repo/.git` becomes owned by the sandbox user and writable by it. Add an empty `worktrees/` and `.incoming/` owned by the sandbox user.
- [ ] `Sandbox` protocol:
  - `exec(argv, *, timeout_s, cwd=None)`. `cwd` must be under `/workspace`.
  - `put_file(name, data) -> str` writes into `.incoming/` and returns the in-sandbox path.
  - Implement both for the Docker backend (`put_archive` of a one-file tar, owned by the sandbox UID) and for `FakeSandbox`.
- [ ] `agentic_sandbox.worktree`: `add_worktree(sandbox, run_id, node_id) -> Worktree(path, branch)` runs `git -c core.hooksPath=/dev/null worktree add -b agent/<run>/<node> /workspace/worktrees/<node> HEAD`. It is idempotent per node.
- [ ] `FakeSandboxManager` mirrors the layout in its temp dir, using host git.
- [ ] Tests (fake and `integration`): a worktree on the right branch; two nodes get separate worktrees; the base checkout is still unwritable; a shallow clone works. If the open question fails, apply the fallback.

## 3. Write tools on the `repo` server
- [ ] `build_repo_server(sandbox, *, root=REPO_DIR, writable=False, limits=...)`. The read tools use `root` (base checkout or worktree). The write tools are registered only when `writable` is true.
- [ ] `write_file(path, content)`:
  - Check `repo_relative` plus `CONFINE` against `root`, and refuse any `.git` path component.
  - Cap the content at 1 MiB (UTF-8 bytes).
  - `put_file`, then a script that runs `mkdir -p` on the parent, refuses an existing directory or a symlink target that leaves the root, and runs `mv`.
  - Return `wrote <path> (<n> bytes)`.
- [ ] `commit(message)`:
  - Run `git add -A`.
  - Fail on an empty diff ("nothing to commit").
  - Run `git -c user.name=… -c user.email=agent@agentic-dev.invalid -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -m "$1"`. The message is passed as a positional argument, never interpolated.
  - Return `<short-sha> on agent/<run>/<node>: <paths>`.
- [ ] Add `examples` to both schemas: `{"path": "NOTES.md", "content": "…"}` and `{"message": "Add NOTES.md"}`.
- [ ] Tests in `packages/tools/tests/test_write_file.py` and `test_commit.py`, with fake and `integration` variants:
  - Writes and overwrites work, and parent directories are created.
  - `..`, absolute, drive and symlink escapes are refused (symlinks on Linux only).
  - `.git/config` and `.git/hooks/x` are refused.
  - The size cap is enforced.
  - A commit lands on the branch with the platform identity.
  - An empty commit is an error.
  - A message of `$(touch /tmp/pwned)` is stored literally.
  - A planted `.git/hooks/pre-commit` does not run.
  - Errors name no host path.

## 4. Route tool calls by node
- [ ] `agentic_runtime.tools.ToolExecutor.call(name, arguments, *, node_id: str | None = None)`. Update `ClaudeRuntime`, `FakeRuntime` and the test doubles to pass `request.node_id`.
- [ ] `agentic_tools.repo.RepoTools`, opened through `open_repo_tools(sandbox, run_id, writers: set[str])`:
  - It keeps a base `McpToolExecutor`.
  - On a writer node's first call, it runs `add_worktree` and opens a writable server for that worktree.
  - Its `definitions()` are the base set plus the write tools.
  - A write tool called by a non-writer returns an "unknown tool" error output.
  - It closes every MCP client before the sandbox.
- [ ] `McpToolExecutor` ignores `node_id`.
- [ ] Tests: a writer reads its own write; a reader never sees a writer's file; a non-writer can't write; one worktree per writer; clean close after failure or cancellation.

## 5. `tool` primitive
- [ ] `agentic_engine.spec.models`: `ToolNode(type="tool", id, tool: NonEmptyStr, args: dict[str, JsonValue] = {})`, added to `Node`. Update `iter_nodes`, the docstring and the exported JSON Schema.
- [ ] `agentic_engine.spec`: add a `writer_node_ids(spec, write_tools)` helper.
- [ ] Compiler: a `tool` node calls the run's `ToolExecutor` with `node_id`. It emits `node_started`, `tool_call`, `tool_result`, then `node_completed` or `node_failed` (on `is_error` or an exception). It writes `last_text` and `results[id]` as an `AgentNodeResult` with `usage=None`.
- [ ] Thread the executor into `run_workflow`/`resume_workflow` (the same object the runtime factory gets). A run with a `tool` node and no tools fails the node with a clear error.
- [ ] API: the existing `repo.*`-needs-a-repo check also walks `tool` nodes.
- [ ] Fixtures: `valid/tool-node.json`; `invalid/tool-node-missing-tool.json`.
- [ ] Tests: the spec accepts and rejects; the compile and run order and events on the fake runtime with a stub executor; an error result fails the run at that node; resume skips a completed tool node.

## 6. Worker wiring, demo and docs
- [ ] Worker: compute `writers` from the run's spec and pass the `run_id` and `writers` to `open_repo_tools`. Hand the same executor to both the runtime factory and the engine.
- [ ] Fixture `valid/write-file.json`:
  - The agent `writer` has `repo.read_file`, `repo.write_file` and `repo.commit`.
  - It is followed by the tool node `list` (`repo.list_files`).
- [ ] `test_worker.py::test_done_when_an_agent_commits_a_file_to_its_branch` (Docker): run `write-file.json` with the unscripted fake runtime, then exec `git log --format=%an%x09%s agent/<run>/writer` in the sandbox before teardown. It shows one commit by the platform identity.
- [ ] CI compose job: add a "Repo write demo (phase 1.6)" step that runs `scripts/sandbox_demo.py --spec …/write-file.json` and asserts that a `tool_result` matches `on agent/<uuid>/writer`.
- [ ] README: document the write tools, the limits, the branch naming, the writer grant rule, the sandbox image, and that there is no push yet.
- [ ] Update the "phase 1.6" mentions in docstrings (`docker_backend`, worker module, `repo/server.py`).
