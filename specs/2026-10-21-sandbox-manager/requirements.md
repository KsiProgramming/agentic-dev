# Sandbox manager: container per run with a local repo clone

Roadmap phase: 1.1
Branch: plan/1.1-sandbox-manager

## Context
Milestone 0 runs agents with no access to code. Milestone 1 works on real repos, and every repo action has to happen in a sandbox (tech stack, "Sandbox": one container per run, no host access, egress limited). This phase adds that sandbox. It gives each run a container that holds a clone of a repo, and one tool that lets an agent list the files in it.

It depends on 0.3 (`ToolExecutor` in `agentic_runtime.tools`), 0.6 (the worker and `POST /runs`) and 0.7 (the Claude tool loop that routes tool calls to a `ToolExecutor`). All are done. It unblocks:
- 1.2: the `repo` MCP server runs its tools against the sandbox added here, and `repo.list_files` moves into it.
- 1.3: durable execution has to re-attach to a run's sandbox or recreate it.
- 1.6: write tools, and one worktree and branch per writer, build on the clone.
- 9.2: gVisor/Firecracker and an egress allowlist replace the local Docker backend behind the same interface.

Principles that apply:
- **Open, but safe by construction (2).** The container has no host mounts and no network. The tool can only see paths inside the clone.
- **Tools live in the platform (4).** `repo.list_files` is a platform tool behind `ToolExecutor`, the same for every provider.
- **Repo content is data (5).** File names come back as `tool_result` data and are never merged into instructions.
- **Transparency (6).** Sandbox create and destroy are logged, and tool calls appear as `tool_call`/`tool_result` run events.
- **Small, verifiable steps (7).** There is no MCP, no write tools, no worktrees and no GitHub yet.

## Scope
### In scope
- New `uv` workspace package `agentic_sandbox` with:
  - A `Sandbox` protocol: `exec(argv) -> ExecResult` (exit code, stdout, stderr, truncated flag) and `close()`. It also exposes `workdir`, where the repo lives inside the sandbox (`/workspace/repo`).
  - A `SandboxManager` protocol: `async with manager.open(run_id, repo) as sandbox:`. It creates the sandbox, clones the repo into it, and always destroys it on exit (success, failure or cancellation).
  - `FakeSandboxManager`: a temp directory per run and local `subprocess` exec. It is used by unit tests and by the worker when Docker is disabled.
  - `DockerSandboxManager`: uses the `docker` Python SDK, with blocking calls wrapped in `asyncio.to_thread`.
- Repo source: `RepoSource` holds a local path or a git URL (`file://`, `https://`). The worker runs a shallow clone (`git clone --depth 1`, optional `ref`) into a host temp dir. The clone is then copied into the container (`put_archive`), so the container needs no network and no git credentials.
- The container is hardened: a pinned small image (`alpine:3.20` with `findutils`), network disabled, no volumes or bind mounts, non-root user, read-only root FS with a writable `/workspace` tmpfs, `cap_drop=ALL`, `no-new-privileges`, and memory, CPU and PID limits. It is labelled `agentic.run_id=<id>` so leftovers can be found.
- `SandboxTools(sandbox)` implements `ToolExecutor` with one tool, `repo.list_files(path=".", max_depth=3)`. It runs `find` inside the sandbox, relative to the repo root. It rejects absolute paths and paths that leave the repo root (`..`). It skips `.git` and caps output at 1,000 entries, then marks the output as truncated.
- `FakeRuntime` can run scripted tool steps against a `ToolExecutor`: a `CallTool(name, args)` step emits `tool_call`, calls the executor and emits `tool_result`. The compose demo needs no API key because of this.
- Worker:
  - For a run with a `repo`, it opens a sandbox, builds a runtime with that run's `SandboxTools`, runs the workflow and closes the sandbox.
  - Runs without a `repo` behave as they do today.
  - New settings: `SANDBOX_BACKEND=docker|fake` and `SANDBOX_IMAGE`.
  - In compose, the worker mounts the Docker socket.
- API: `CreateRunRequest` gets an optional `repo: {url, ref?}`, stored with the run (Alembic migration `0004`). A run that asks for `repo.*` tools without a repo fails validation with `422`.
- Sandbox lifecycle is logged (created, cloned, destroyed, with duration). There are no new run event types yet.

### Out of scope
- `repo` MCP server, `read_file`, `search` and other read tools: 1.2.
- Re-attaching to a sandbox after a worker restart: 1.3. For now a crashed worker's container is removed by a startup sweep on the `agentic.run_id` label.
- Private repos, credentials and GitHub App tokens: 1.4/1.5.
- Write tools, worktrees and branches per writer: 1.6.
- Egress allowlist (network is simply off here) and gVisor/Firecracker: 9.2.
- Sandbox events shown in the monitor: 2.5.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Docker client | `docker` (docker-py) behind `asyncio.to_thread` | Widely used and stable. The tech stack does not fix a library. aiodocker and shelling out to the CLI were considered and rejected. |
| Abstraction | `Sandbox`/`SandboxManager` protocols with fake and Docker backends | This matches the `AgentRuntime` + fake pattern from 0.3. Tests are fast and need no Docker. 9.2 can swap the backend. |
| Where the clone happens | On the worker, then copied into the container | The container keeps network off and never sees credentials. Egress rules wait for 9.2. |
| Tool name | `repo.list_files` | This matches the dotted platform naming used by the Claude adapter, so 1.2 moves the tool into the MCP server without renaming it. |
| Tools per run | The worker builds the runtime per run, with that run's `SandboxTools` | `ClaudeRuntime` already takes a `ToolExecutor` in its constructor, so the `AgentRuntime` protocol does not change. |
| Sandbox lifetime | One per run, opened before the first node and destroyed after the terminal event | This is what the tech stack specifies. 1.3 revisits it for resume. |
| Image | Pinned `alpine:3.20` plus `findutils`, configurable with `SANDBOX_IMAGE` | Small and fast to pull. Later phases add a purpose-built image. |

## Open questions
- None blocking. The sandbox image will need git, language toolchains and so on for 1.6/3.4. That choice is deferred to those phases.
