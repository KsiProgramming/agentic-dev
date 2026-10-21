# `repo` MCP server (read only) wired into the agent runtime

Roadmap phase: 1.2
Branch: plan/1.2-repo-mcp-server

## Context
Phase 1.1 gave each run a sandbox container with a clone of its repo, plus one tool (`repo.list_files`) written directly against `ToolExecutor` in `agentic_sandbox.tools`. Listing files is not enough to answer questions about code. This phase adds the reading and searching tools, and serves them from a platform-owned MCP server, as the tech stack's "Tool layer" section requires.

It depends on:
- 1.1: the `Sandbox` protocol, where tools run, and the worker's per-run sandbox.
- 0.3/0.7: `ToolExecutor`, and the Claude and fake runtimes that route tool calls to it.

All of these are done. It unblocks:
- 1.6: the write tools are added to the same server, and per-node tool grants decide who gets them.
- 3.4: deterministic tool nodes reuse the bridge.
- 7.2: the Copilot adapter registers the same MCP tools as custom tools.

Principles that apply:
- **Tools live in the platform (4).** The `repo` server belongs to the platform and is built with the official MCP Python SDK (tech stack). Adapters see it only through `ToolExecutor`, so a workflow behaves the same on any provider.
- **Repo content is data (5).** File contents and search hits come back as `tool_result` data. Claude already gets them as `tool_result` blocks, never as instructions.
- **Open, but safe by construction (2).** Every tool runs inside the sandbox: no network, read-only clone, and paths confined to the repo root, including through symlinks. Output sizes are capped.
- **Small, verifiable steps (7).** The server runs in-process with an in-memory transport. It is read only. There is no new process, port or image.

## Scope
### In scope
- A new `uv` workspace package `agentic_tools` (the `tools` package named in the tech stack) with:
  - `agentic_tools.repo`: `build_repo_server(sandbox)`. It builds an MCP server named `repo` with the SDK's high-level server API, whose tools run commands in that sandbox through `Sandbox.exec`. It has three tools:
    - `list_files(path=".", max_depth=3)`: moved from `agentic_sandbox.tools`. The behaviour stays the same: `.git` skipped, 1,000-entry cap, symlink escape refused.
    - `read_file(path, start_line=1, end_line=None)`: returns numbered lines. It refuses directories, missing files, paths outside the repo (`..`, absolute, drive, or a symlink out of the repo) and binary files (a NUL byte in the first 8 KiB). It caps output at 2,000 lines or 256 KiB, whichever comes first, and says so when it truncates.
    - `search(pattern, path=".", regex=False, case_sensitive=True, max_results=100)`: runs grep inside the sandbox. It returns `path:line: text` hits with each line truncated to 300 characters. It skips `.git` and binary files and caps the number of hits (hard limit 500), noting truncation. The pattern is passed as an argument, never interpolated into the shell.
  - `agentic_tools.mcp_bridge.McpToolExecutor`: implements `ToolExecutor` over an MCP `Client`.
    - It lists the server's tools once on open and exposes them as `<server>.<tool>` (`repo.list_files`), with the MCP input schema as `input_schema`.
    - On `call`, it strips the prefix, calls the tool and joins its text content. An MCP `isError` result becomes `ToolOutput(is_error=True)`.
  - `open_repo_tools(sandbox)`: an async context manager that builds the server, opens `Client(server)` in memory and yields an `McpToolExecutor`.
- `agentic_sandbox.tools.SandboxTools` is removed. `repo_relative()` and the path-confinement shell snippet move to `agentic_tools.repo`, and their tests move with them.
- Worker: for a run with a `repo`, it opens the sandbox and then `open_repo_tools(sandbox)`, and passes that executor to the runtime factory. The MCP client closes before the sandbox. Runs without a repo behave as they do today.
- Fake runtime: for a node with no script, it calls each requested tool with the first item of the tool's input schema `examples`, or `{}` if there is none. Each repo tool declares one example. This lets the compose demo call `read_file` and `search` with no API key.
- A new spec fixture, `ask-repo.json`. One agent gets `repo.list_files`, `repo.read_file` and `repo.search` and the question "Which Python packages make up this uv workspace, and what is each for?"
- `scripts/sandbox_demo.py` gains a `--spec` option. The README section on repo tools is updated for the three tools.

### Out of scope
- Write tools, worktrees and per-node tool grants from node manifests: 1.6. For now a node gets the tools its spec names, as today.
- Git history tools (`git_log`, `git_show`): they need git in the sandbox image, which is deferred to 1.6.
- Running the server out of process (stdio/HTTP) or inside the container: later, behind the same bridge, if isolation or Copilot (7.2) needs it.
- Other MCP servers (`tests`, `github`, `jira`): 1.8, 3.4 and 6.2.
- Live Claude verification in CI: not added. The Claude path is covered by the adapter's existing routing tests, and the scripted demo proves the tools end to end.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Tool set | `list_files`, `read_file`, `search` (core read set) | This is the smallest set that lets an agent actually answer a question about code: find the file, read it, search for symbols. Git tools wait for an image with git. |
| Server placement | In-process FastMCP with an in-memory `Client(server)` (MCP SDK v2) | This is real MCP: the protocol layer lists, validates and calls the tools, with no new process, port or image. The SDK documents the in-memory client as an embedding API. The transport can change later without touching adapters. |
| Library | Official MCP Python SDK (`mcp>=2.3`) | It is fixed by the tech stack. |
| One server per run | `build_repo_server(sandbox)` is called per run | Tools are bound to that run's sandbox, so one run can never reach another run's repo. |
| Naming | MCP tool `list_files` on server `repo`; platform name `repo.list_files` | This keeps the 1.1 name that specs and the API's `repo.*` validation already use. The Claude adapter still maps dots to `__`. |
| Bridge | `McpToolExecutor` implements the existing `ToolExecutor` | `AgentRuntime`, `ClaudeRuntime` and `FakeRuntime` need no interface change, so this phase stays small. |
| Package | New `agentic_tools`; repo tools leave `agentic_sandbox` | This follows the package split in the tech stack (api, engine, runtime, tools). The sandbox package goes back to being only about containers. |
| Fake tool arguments | First `examples` entry of the input schema, else `{}` | The no-key compose demo can read and search without a script format in the spec. The examples also guide real models. |
| "Done when" proof | Scripted fake agent in compose and on Docker in the worker test | The user chose no live-Claude check. The proof is that a run's events show the three tools returning the facts (package names and their `pyproject.toml` contents) that answer the question. |

## Open questions
- ~~Busybox `grep` in `alpine:3.20` may not support every flag (`-I`, `--exclude-dir`).~~ Resolved in group 2: it supports neither. `search` runs `find … -exec grep -Hn -E` (pruning `.git`) and drops files that fail a NUL-byte check. Fixed strings are escaped into an extended regex instead of using `-F`, because Git for Windows' grep 3.0 aborts on `-F -i`.
- The `read_file` example (`pyproject.toml`) only makes sense for Python repos. In the fake demo, another repo just gets an error result. This should be revisited when templates bring their own scripted demos.
