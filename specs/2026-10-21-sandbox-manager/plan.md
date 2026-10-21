# Plan: Sandbox manager

The order follows the protocol-first pattern from 0.3: the interface and fake come first, then the real backend, then the tool, then wiring. The project stays green after each group.

## 1. Sandbox protocol, repo source and fake backend
- [x] Add package `packages/sandbox` (`agentic_sandbox`) to the `uv` workspace. CI picks it up through the workspace-wide lint, type and test commands.
- [x] `agentic_sandbox/protocol.py`: `ExecResult`, `Sandbox` (`workdir`, `exec`), `SandboxManager.open(run_id, repo)` (async context manager that owns cleanup). `SandboxError` lives in `errors.py`.
- [x] `agentic_sandbox/source.py`:
  - `RepoSource(url, ref=None)`, validated: an `https://` URL without credentials, or a local path. Unsafe refs are rejected.
  - `clone_shallow(source, dest, local_root=)` (`git clone --depth 1 --no-local [--branch ref]`), with a timeout. A failed clone raises a `SandboxError` free of host paths.
  - Local paths must be under `local_root`.
- [x] `agentic_sandbox/fake.py`: `FakeSandboxManager` (temp dir per run, `asyncio.create_subprocess_exec` with `cwd=workdir`, cleanup in `finally`, read-only git objects handled on Windows).
- [x] Tests:
  - Lifecycle, and cleanup on exception and on cancellation.
  - Bad sources and refs, and clone errors.
  - The clone holds the fixture files (`agentic_sandbox.testing.make_repo`).

## 2. Docker backend
- [x] Add `docker` (and `types-docker` for pyright) to `agentic-sandbox`. Add `agentic_sandbox/docker_backend.py` with `DockerSandboxManager(client, image, limits, local_root)`.
- [x] Container config:
  - `network_mode="none"`, `read_only=True`, a per-run named volume at `/workspace`, `/tmp` tmpfs, `user="1000:1000"`.
  - `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]`, `mem_limit`, `nano_cpus`, `pids_limit`, `init`.
  - Label `agentic.run_id`. The container command is `tail -f /dev/null`.
- [x] Clone on the host into a temp dir, then tar it with root ownership and modes 644/755. `put_archive` it to `/workspace` before the container starts.
- [x] Exec: `exec_run` under `timeout`, with `workdir=/workspace/repo` and demuxed, capped output.
- [x] Teardown: `open` exiting force-removes the container and volume. `sweep_orphans(client)` removes labelled leftovers and is called at worker start.
- [x] Integration tests (marker `integration`, skipped without a daemon):
  - Clone and list files.
  - The container and volume are gone after the run, including on error and after a failed clone.
  - There is no network.
  - The process is non-root and the root is read-only.
  - Commands time out.
  - The sweep removes leftovers.

## 3. `repo.list_files` tool and fake runtime tool steps
- [x] `agentic_sandbox/tools.py`: `SandboxTools(sandbox)` implementing `ToolExecutor`.
  - One definition, `repo.list_files`, with a JSON Schema for `path` and `max_depth` (1–10).
  - It normalises the path and rejects absolute and `..` paths. A `sh -c` script `cd -P`s into the path, refuses symlinks out of the repo, and runs `find -prune .git` twice (directories, then the rest).
  - It returns sorted repo-relative paths, caps them at 1,000 and adds a truncation note. A path that is not a directory returns `ToolOutput(is_error=True)`.
- [x] `agentic_runtime/fake.py`:
  - A `CallTool(name, arguments)` step and an optional `tools: ToolExecutor` on `FakeRuntime`. The step emits `tool_call`, awaits `tools.call`, then emits `tool_result`.
  - With `tools` set, unscripted nodes first call each tool their request names.
  - The `check_events` contract still holds.
- [x] Tests:
  - `SandboxTools` on both backends: listing, depth, `.git` excluded, escapes rejected (including symlinks, on Linux), truncation, bad arguments.
  - Fake runtime tool steps.
  - `ClaudeRuntime` on `MockClaude` routes `repo__list_files` to `SandboxTools`.

## 4. Worker and API wiring, compose, docs
- [x] API:
  - Alembic `0004_run_repo`: nullable `repo` JSONB on `runs`.
  - `CreateRunRequest.repo: RepoSource | None`, stored by `create_run` and returned by `get_run`.
  - A `422` when a spec node lists a `repo.*` tool and `repo` is missing.
- [x] Engine: `record_unstarted_run` logs `run_started` + `run_failed`/`run_cancelled` for a run that ended before its first node.
- [x] Worker:
  - `WorkerSettings.sandbox_backend` (`fake` by default, `docker` in compose), `sandbox_image` and `sandbox_local_root`.
  - `runtime_factory(settings)` builds one runtime per run, sharing one Claude client. `process_run` opens the sandbox when `run.repo` is set and passes `SandboxTools`.
  - A sandbox or clone failure ends the run with `run_failed` and a clear reason, with no host paths.
- [x] Tests no longer read the developer's `.env` (worker conftest fixture; the API tests pin the fake runtime).
- [x] `docker-compose.yml` and `Dockerfile`:
  - The worker mounts `/var/run/docker.sock` (group `DOCKER_GID`) and gets `SANDBOX_BACKEND=docker`, `SANDBOX_IMAGE` and `SANDBOX_LOCAL_ROOT=/samples`.
  - This repo's `.git` is mounted read-only at `/samples/agentic-dev.git` as the demo repo.
  - The image installs `git`.
- [x] Demo script `scripts/sandbox_demo.py` (stdlib only), run in the CI smoke job, which also checks that no sandbox container is left.
- [x] Docs: README "Sandbox" section, `.env.example`, CHANGELOG entry, regenerated OpenAPI spec and web client.
