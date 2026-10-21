# Plan: Sandbox manager

The order follows the protocol-first pattern from 0.3: the interface and fake come first, then the real backend, then the tool, then wiring. The project stays green after each group.

## 1. Sandbox protocol, repo source and fake backend
- [ ] Add package `packages/sandbox` (`agentic_sandbox`) to the `uv` workspace and CI lint/type/test matrix.
- [ ] `agentic_sandbox/protocol.py`: `ExecResult`, `Sandbox` (`workdir`, `exec`, `close`), `SandboxManager.open(run_id, repo)` (async context manager).
- [ ] `agentic_sandbox/source.py`: `RepoSource(url, ref=None)`, validated (local path, `file://` or `https://` only). Add `clone_shallow(source, dest)` (`git clone --depth 1 [--branch ref]`) with a timeout and a clear `SandboxError` when the clone fails.
- [ ] `agentic_sandbox/fake.py`: `FakeSandboxManager` (temp dir per run, `asyncio.create_subprocess_exec` with `cwd=workdir`, cleanup in `finally`).
- [ ] Tests: lifecycle, cleanup on exception and on cancellation, a bad repo URL raises `SandboxError`, and the clone has the expected files (fixture repo made with `git init` in `tmp_path`).

## 2. Docker backend
- [ ] Add the `docker` dependency to `agentic-sandbox`. Add `agentic_sandbox/docker.py` with `DockerSandboxManager(client, image, limits)`.
- [ ] Container config:
  - `network_disabled=True`, `read_only=True`, tmpfs `/workspace`, `user="1000:1000"`, `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]`.
  - `mem_limit`, `nano_cpus`, `pids_limit`, label `agentic.run_id`. The container command is `sleep infinity`.
- [ ] Clone on the host into a temp dir, tar it, then `put_archive` to `/workspace`. Run `exec_run` with `workdir=/workspace/repo`, demuxed output, and output capped.
- [ ] `close()` force-removes the container. Add `sweep_orphans(client)` to remove containers labelled `agentic.run_id`, and call it at worker start.
- [ ] Integration tests marked `docker` (skipped if no daemon):
  - Clone and list files.
  - The container is gone after `open` exits, including on error.
  - Outbound network fails inside the container.
  - Writing outside `/workspace` fails.

## 3. `repo.list_files` tool and fake runtime tool steps
- [ ] `agentic_sandbox/tools.py`: `SandboxTools(sandbox)` implementing `ToolExecutor`.
  - One definition, `repo.list_files`, with a JSON Schema for `path` and `max_depth` (1–10).
  - Normalise and reject absolute and `..` paths. Run `find <path> -maxdepth N -not -path '*/.git*'`.
  - Return sorted relative paths, cap them at 1,000, and add a truncation note. A missing path returns `ToolOutput(is_error=True)`.
- [ ] `agentic_runtime/fake.py`: add a `CallTool(name, arguments)` step and an optional `tools: ToolExecutor` on `FakeRuntime`. The step emits `tool_call`, awaits `tools.call`, then emits `tool_result`. The `check_events` contract still holds.
- [ ] Tests:
  - `SandboxTools` on `FakeSandboxManager`: listing, depth, `.git` excluded, escape rejected, truncation.
  - A fake runtime run with a `CallTool` step yields a valid event stream.
  - A Claude runtime test, using the existing mocked client, routes `repo__list_files` to `SandboxTools`.

## 4. Worker and API wiring, compose, docs
- [ ] API:
  - Alembic `0004_run_repo`: nullable `repo` JSONB on `runs`. `CreateRunRequest.repo: RepoSource | None`, stored by `create_run` and returned by `get_run`.
  - A `422` when a spec node lists a `repo.*` tool and `repo` is missing.
- [ ] Worker:
  - `WorkerSettings.sandbox_backend` (`docker` by default in compose, `fake` by default in tests) and `sandbox_image`.
  - `process_run` opens the sandbox when `run.repo` is set and builds the runtime with `SandboxTools`. `build_runtime(settings, tools)` passes them to `ClaudeRuntime`/`FakeRuntime`.
  - A sandbox or clone failure ends the run with `run_failed` and a clear reason, with no stack trace or host paths in events.
- [ ] Fake demo script:
  - When `FAKE_SCRIPT=list_files`, the fake runtime calls `repo.list_files` and echoes the result.
  - The default stays the echo script.
- [ ] `docker-compose.yml`:
  - The worker mounts `/var/run/docker.sock` and gets `SANDBOX_BACKEND=docker` and `SANDBOX_IMAGE`.
  - Add a `samples/` fixture repo, mounted read-only into the worker at `/samples/hello-repo` for the demo.
  - The sandbox image is pulled on first use.
- [ ] Docs: a README "Sandbox" section covering what it isolates, settings, the demo `curl`, and the Claude variant (`AGENTIC_RUNTIME=claude` with an agent node that has `tools: ["repo.list_files"]`). Add a CHANGELOG entry.
